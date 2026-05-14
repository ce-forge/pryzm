"""Generate an interactive HTML visualization of Pryzm's codebase.

Crawls backend/ and frontend/src/, extracts file-level imports and
frontend->backend API calls, renders a Cytoscape.js graph with
Frontend / Backend / Tests zones as horizontal bands with shaded regions.

Usage:
    cd backend
    ./venv/bin/python scripts/codemap.py
    # Output: backend/scripts/_out/codemap.html
"""
from __future__ import annotations

import ast
import json
import math
import re
from pathlib import Path

# Project paths — script lives at backend/scripts/codemap.py.
PROJECT_ROOT = Path(__file__).parent.parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"
FRONTEND_ROOT = PROJECT_ROOT / "frontend" / "src"
OUT_DIR = Path(__file__).parent / "_out"
OUT_HTML = OUT_DIR / "codemap.html"

# Directories to skip during crawl.
SKIP_DIRS = {
    "venv", "__pycache__", ".pytest_cache", "_artifacts", "_out",
    "node_modules", ".next", "alembic",
}


# ---------------------------------------------------------------------------
# Backend crawl
# ---------------------------------------------------------------------------

def crawl_backend() -> dict[str, dict]:
    files: dict[str, dict] = {}
    for py in BACKEND_ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in py.parts):
            continue
        rel = str(py.relative_to(PROJECT_ROOT))
        files[rel] = _parse_python_file(py)
    return files


def _parse_python_file(path: Path) -> dict:
    source = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {"imports": [], "routes": [], "error": "syntax"}

    imports: list[str] = []
    routes: list[dict] = []
    functions: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(node.name)
            for dec in node.decorator_list:
                # Detect @router.METHOD("path") decorators.
                if (
                    isinstance(dec, ast.Call)
                    and isinstance(dec.func, ast.Attribute)
                    and isinstance(dec.func.value, ast.Name)
                    and dec.func.value.id == "router"
                ):
                    method = dec.func.attr.upper()
                    if dec.args and isinstance(dec.args[0], ast.Constant):
                        routes.append({
                            "method": method,
                            "path": dec.args[0].value,
                            "function": node.name,
                        })

    return {"imports": imports, "routes": routes, "functions": functions}


# ---------------------------------------------------------------------------
# Frontend crawl
# ---------------------------------------------------------------------------

# Match:  import ... from "..."  or  import "..."
_IMPORT_RE = re.compile(
    r"""^\s*import\s+(?:.*?\bfrom\s+)?['"]([^'"]+)['"]""",
    re.MULTILINE,
)
# Match apiFetch("...") or apiFetch(`...`) — single or double quoted, or backtick.
# We capture greedily up to the first closing quote/backtick.
_API_RE = re.compile(r"""apiFetch\(\s*[`'"]([^`'"]+)[`'"]""")


def crawl_frontend() -> dict[str, dict]:
    files: dict[str, dict] = {}
    for ts in list(FRONTEND_ROOT.rglob("*.ts")) + list(FRONTEND_ROOT.rglob("*.tsx")):
        if any(part in SKIP_DIRS for part in ts.parts):
            continue
        rel = str(ts.relative_to(PROJECT_ROOT))
        files[rel] = _parse_ts_file(ts)
    return files


def _normalize_api_path(raw: str) -> str:
    """Strip query string, normalize template params → :param."""
    path_only = raw.split("?")[0].rstrip("/") or "/"
    return re.sub(r"\$\{[^}]+\}", ":param", path_only)


def _parse_ts_file(path: Path) -> dict:
    source = path.read_text(encoding="utf-8", errors="replace")
    imports = _IMPORT_RE.findall(source)
    raw_calls = _API_RE.findall(source)
    api_calls = list(dict.fromkeys(_normalize_api_path(c) for c in raw_calls))  # dedupe, order-preserved
    return {"imports": imports, "api_calls": api_calls}


# ---------------------------------------------------------------------------
# Node categorization
# ---------------------------------------------------------------------------

def categorize_node(file_path: str) -> dict:
    parts = file_path.split("/")
    if file_path.startswith("frontend/"):
        # frontend/src/<group>/...
        group = parts[2] if len(parts) > 2 else "root"
        return {"zone": "frontend", "group": group}
    if file_path.startswith("backend/tests"):
        # backend/tests/<group>/... or a top-level test file
        group = parts[2] if len(parts) > 2 and "." not in parts[2] else "unit"
        return {"zone": "tests", "group": group}
    if file_path.startswith("backend/"):
        # backend/<group>/...
        group = parts[1] if len(parts) > 1 and "." not in parts[1] else "root"
        return {"zone": "backend", "group": group}
    return {"zone": "other", "group": "other"}


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_graph(
    backend_files: dict[str, dict],
    frontend_files: dict[str, dict],
) -> tuple[list, list]:
    nodes: list[dict] = []
    edges: list[dict] = []

    # --- Backend nodes ---
    for path, meta in backend_files.items():
        cat = categorize_node(path)
        routes = meta.get("routes", [])
        nodes.append({
            "data": {
                "id": path,
                "label": path.split("/")[-1],
                "path": path,
                "zone": cat["zone"],
                "group": cat["group"],
                "routes": routes,
                "functions": meta.get("functions", []),
                "kind": "route" if routes else "module",
            }
        })

    # --- Frontend nodes ---
    for path, meta in frontend_files.items():
        cat = categorize_node(path)
        api_calls = meta.get("api_calls", [])
        nodes.append({
            "data": {
                "id": path,
                "label": path.split("/")[-1],
                "path": path,
                "zone": cat["zone"],
                "group": cat["group"],
                "api_calls": api_calls,
                "kind": "api_consumer" if api_calls else "module",
            }
        })

    # --- Backend import edges ---
    # Build dotted-module → file index: "routers.chat" → "backend/routers/chat.py"
    backend_module_index: dict[str, str] = {}
    for p in backend_files:
        dotted = (
            p.replace("backend/", "")
             .replace("/", ".")
             .rsplit(".", 1)[0]   # strip .py
        )
        backend_module_index[dotted] = p

    seen_edges: set[tuple] = set()

    def _add_edge(src: str, tgt: str, **kwargs):
        key = (src, tgt, kwargs.get("kind"))
        if key not in seen_edges and src != tgt:
            seen_edges.add(key)
            edges.append({"data": {"source": src, "target": tgt, **kwargs}})

    for path, meta in backend_files.items():
        for imp in meta.get("imports", []):
            base = imp.lstrip(".")
            target = backend_module_index.get(base)
            if not target:
                parts = base.split(".")
                for i in range(len(parts), 0, -1):
                    candidate = ".".join(parts[:i])
                    if candidate in backend_module_index:
                        target = backend_module_index[candidate]
                        break
            if target:
                _add_edge(path, target, kind="import")

    # --- Frontend import edges ---
    # Build relative-path → file index: "hooks/useSession" → "frontend/src/hooks/useSession.ts"
    frontend_module_index: dict[str, str] = {}
    for p in frontend_files:
        rel = p.replace("frontend/src/", "").rsplit(".", 1)[0]
        frontend_module_index[rel] = p

    for path, meta in frontend_files.items():
        for imp in meta.get("imports", []):
            if not (
                imp.startswith("./")
                or imp.startswith("../")
                or imp.startswith("@/")
            ):
                continue

            if imp.startswith("@/"):
                normalized = imp[2:]  # strip "@/"
            else:
                importer_dir = "/".join(path.split("/")[:-1]).replace("frontend/src/", "")
                normalized = _normalize_relative(importer_dir, imp)

            target = None
            for try_key in [normalized, f"{normalized}/index"]:
                if try_key in frontend_module_index:
                    target = frontend_module_index[try_key]
                    break
            if target:
                _add_edge(path, target, kind="import")

    # --- Frontend → backend API edges ---
    # Normalize backend route paths: {param} → :param
    backend_route_index: dict[str, list[dict]] = {}
    for path, meta in backend_files.items():
        for r in meta.get("routes", []):
            normalized = re.sub(r"\{[^}]+\}", ":param", r["path"]).rstrip("/") or "/"
            backend_route_index.setdefault(normalized, []).append(
                {"file": path, "method": r["method"]}
            )

    phantom_ids: set[str] = set()

    for path, meta in frontend_files.items():
        for api_path in meta.get("api_calls", []):
            normalized_call = api_path.rstrip("/") or "/"
            target_routes = backend_route_index.get(normalized_call)

            if target_routes:
                for tr in target_routes:
                    _add_edge(
                        path,
                        tr["file"],
                        kind="api",
                        method=tr["method"],
                        api_path=api_path,
                    )
            else:
                # Phantom node for unmatched API endpoint.
                phantom_id = f"unmatched::{normalized_call}"
                if phantom_id not in phantom_ids:
                    phantom_ids.add(phantom_id)
                    nodes.append({
                        "data": {
                            "id": phantom_id,
                            "label": normalized_call,
                            "zone": "backend",
                            "group": "unmatched",
                            "kind": "phantom",
                        }
                    })
                _add_edge(path, phantom_id, kind="api_unmatched", api_path=api_path)

    return nodes, edges


def _normalize_relative(importer_dir: str, imp: str) -> str:
    """Collapse  ../foo/bar  from  a/b  into  a/foo/bar."""
    parts = importer_dir.split("/") if importer_dir else []
    for piece in imp.split("/"):
        if piece == "..":
            if parts:
                parts.pop()
        elif piece != ".":
            parts.append(piece)
    return "/".join(parts)


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

NODE_W = 20            # node diameter
NODE_H = 20
LABEL_SPACE = 140      # room for filename label beside each node
ROW_SPACING = 30       # vertical gap between nodes in a column
COL_W = NODE_W + LABEL_SPACE + 24   # horizontal width per file column
MAX_ROWS_PER_COL = 12  # max files before adding a second column in a subgroup
SUBGROUP_PADDING_X = 18
SUBGROUP_PADDING_Y = 32   # top padding inside subgroup (room for subgroup label)
SUBGROUP_GAP_X = 22       # horizontal gap between subgroups within a zone
ZONE_PADDING_X = 28
ZONE_PADDING_Y = 36       # top padding inside zone band (room for zone label)
ZONE_GAP_Y = 50           # vertical gap between zone bands
BAND_START_Y = 80         # Y position where the first zone starts (below header)

# Preferred sub-group ordering within each zone.
GROUP_ORDER: dict[str, list[str]] = {
    "frontend": ["app", "context", "hooks", "components", "utils", "types", "data"],
    "backend": ["routers", "services", "core", "tools", "db", "utils", "root", "unmatched"],
    "tests": ["unit", "smoke", "e2e"],
}

ZONE_ORDER = ["frontend", "backend", "tests"]


# ---------------------------------------------------------------------------
# Layout computation
# ---------------------------------------------------------------------------

def _subgroup_size(num_files: int) -> tuple[int, int, int]:
    """Return (num_cols, rows_in_last_col, pixel_width, pixel_height)."""
    num_cols = max(1, math.ceil(num_files / MAX_ROWS_PER_COL))
    rows = math.ceil(num_files / num_cols) if num_cols > 0 else 1
    width = num_cols * COL_W + 2 * SUBGROUP_PADDING_X
    height = rows * ROW_SPACING + SUBGROUP_PADDING_Y + 16  # 16 = bottom pad
    return num_cols, rows, width, height


def compute_positions(nodes: list[dict]) -> tuple[list[dict], list[dict], dict]:
    """Assign positions to leaf nodes; return (positioned_nodes, compound_nodes, zone_bands).

    zone_bands maps zone_id -> {"y_start": int, "y_end": int}.
    compound_nodes are the zone + subgroup parent nodes (no position needed for compounds).
    """
    # Bucket leaf nodes by (zone, group).
    by_zone_group: dict[tuple[str, str], list[dict]] = {}
    for n in nodes:
        key = (n["data"]["zone"], n["data"]["group"])
        by_zone_group.setdefault(key, []).append(n)

    compound_nodes: list[dict] = []
    positioned: list[dict] = []
    zone_bands: dict[str, dict] = {}

    current_band_y = BAND_START_Y

    for zone in ZONE_ORDER:
        zone_id = f"zone_{zone}"
        known_order = GROUP_ORDER.get(zone, [])
        all_groups = sorted({g for (z, g) in by_zone_group if z == zone})
        ordered_groups = [g for g in known_order if g in all_groups] + [
            g for g in all_groups if g not in known_order
        ]

        # First pass: calculate max subgroup height for this zone row.
        # All subgroups in a zone sit side by side horizontally.
        # We need to find the tallest subgroup to know the band height.
        subgroup_data: list[dict] = []
        for group in ordered_groups:
            group_nodes = by_zone_group.get((zone, group), [])
            if not group_nodes:
                continue
            group_nodes.sort(key=lambda n: n["data"]["label"])
            num_cols, rows, sg_width, sg_height = _subgroup_size(len(group_nodes))
            subgroup_data.append({
                "group": group,
                "nodes": group_nodes,
                "num_cols": num_cols,
                "rows": rows,
                "sg_width": sg_width,
                "sg_height": sg_height,
            })

        if not subgroup_data:
            continue

        max_sg_height = max(s["sg_height"] for s in subgroup_data)
        band_inner_height = max_sg_height + ZONE_PADDING_Y + 16
        band_y_start = current_band_y
        band_y_end = current_band_y + band_inner_height
        zone_bands[zone_id] = {"y_start": band_y_start, "y_end": band_y_end}

        # Add zone compound node (no position — compound auto-sizes in Cytoscape).
        compound_nodes.append({
            "data": {
                "id": zone_id,
                "label": zone.upper(),
                "zone": zone,
                "kind": "zone_compound",
            }
        })

        # Second pass: place subgroups left-to-right.
        current_sg_x = ZONE_PADDING_X

        for s in subgroup_data:
            group = s["group"]
            group_nodes = s["nodes"]
            num_cols = s["num_cols"]
            rows = s["rows"]
            sg_width = s["sg_width"]

            sg_id = f"subgroup_{zone}_{group}"

            # Add subgroup compound node.
            compound_nodes.append({
                "data": {
                    "id": sg_id,
                    "label": group,
                    "zone": zone,
                    "group": group,
                    "kind": "subgroup_compound",
                    "parent": zone_id,
                }
            })

            # Place leaf nodes inside the subgroup.
            # Origin: top-left of subgroup content area.
            # In Cytoscape preset layout, positions are the CENTER of each node.
            # We position relative to an absolute canvas coordinate.
            # Zone starts at band_y_start; subgroup content starts after zone+subgroup padding.
            sg_origin_x = current_sg_x + SUBGROUP_PADDING_X + NODE_W / 2
            sg_origin_y = band_y_start + ZONE_PADDING_Y + SUBGROUP_PADDING_Y + NODE_H / 2

            for idx, n in enumerate(group_nodes):
                col = idx % num_cols
                row = idx // num_cols
                x = sg_origin_x + col * COL_W
                y = sg_origin_y + row * ROW_SPACING
                n["position"] = {"x": x, "y": y}
                # Assign parent to compound subgroup node.
                n["data"]["parent"] = sg_id
                positioned.append(n)

            current_sg_x += sg_width + SUBGROUP_GAP_X

        current_band_y = band_y_end + ZONE_GAP_Y

    return positioned, compound_nodes, zone_bands


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------

def render_html(nodes: list, edges: list) -> str:
    """Assign preset positions, inject compound parent nodes, return HTML."""
    # Separate phantom nodes (they have zone/group but no real path) from the rest.
    # All nodes go through compute_positions.
    positioned, compound_nodes, zone_bands = compute_positions(nodes)

    # Combine: compound parents first (Cytoscape requires parents before children
    # when using the array form — but the JS side handles it fine either way).
    all_elements = compound_nodes + positioned + edges

    elements_json = json.dumps(all_elements, indent=None)
    zone_bands_json = json.dumps(zone_bands)

    html = _HTML_TEMPLATE
    html = html.replace("__ELEMENTS_JSON__", elements_json)
    html = html.replace("__ZONE_BANDS_JSON__", zone_bands_json)
    return html


# ---------------------------------------------------------------------------
# HTML template
# ---------------------------------------------------------------------------

_HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Pryzm codebase map</title>
<style>
html, body {
  margin: 0; padding: 0; height: 100%;
  background: #0e0e10; color: #ddd;
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
#header {
  position: fixed; top: 0; left: 0; right: 0; height: 64px;
  padding: 0 24px; display: flex; align-items: center; gap: 32px;
  background: #18181b; border-bottom: 1px solid #2a2a2e; z-index: 20;
}
#header h1 { margin: 0; font-size: 16px; font-weight: 700; letter-spacing: .02em; }
.legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 11px; color: #9ca3af; }
.li { display: flex; align-items: center; gap: 5px; }
.sw { width: 11px; height: 11px; border-radius: 2px; flex-shrink: 0; }
#cy { position: absolute; top: 64px; left: 0; right: 0; bottom: 200px; }
#panel {
  position: fixed; bottom: 0; left: 0; right: 0; height: 196px;
  overflow-y: auto; padding: 10px 24px; box-sizing: border-box;
  background: rgba(15,15,17,0.97); border-top: 1px solid #2a2a2e;
  font-size: 12px; font-family: "Menlo","Consolas",monospace; line-height: 1.5;
}
#panel.hidden { display: none; }
#panel b { color: #e2e8f0; }
#panel i { color: #6b7280; }
#panel u { color: #a78bfa; text-decoration: none; font-weight: 600; }
#stats { font-size: 11px; color: #6b7280; margin-left: auto; }
</style>
<script src="https://unpkg.com/cytoscape@3.30.0/dist/cytoscape.min.js"></script>
</head>
<body>
<div id="header">
  <h1>Pryzm codebase map</h1>
  <div class="legend">
    <span class="li"><span class="sw" style="background:#3b82f6"></span>Frontend</span>
    <span class="li"><span class="sw" style="background:#22c55e"></span>Backend module</span>
    <span class="li"><span class="sw" style="background:#f97316"></span>Backend route</span>
    <span class="li"><span class="sw" style="background:#a855f7"></span>Tests</span>
    <span class="li"><span class="sw" style="background:#ef4444"></span>Phantom (unmatched API)</span>
    <span class="li"><span class="sw" style="background:#444;border:1px solid #888"></span>Import (solid)</span>
    <span class="li"><span class="sw" style="background:transparent;border:2px dashed #f97316"></span>API call (dashed)</span>
    <span class="li"><span class="sw" style="background:transparent;border:2px dashed #ef4444"></span>Unmatched API</span>
  </div>
  <div id="stats"></div>
</div>
<div id="cy"></div>
<div id="panel" class="hidden"></div>

<script>
const elements = __ELEMENTS_JSON__;
const zoneBands = __ZONE_BANDS_JSON__;

function nodeColor(d) {
  if (d.kind === "phantom")    return "#ef4444";
  if (d.kind === "route")      return "#f97316";
  if (d.zone === "frontend")   return "#3b82f6";
  if (d.zone === "tests")      return "#a855f7";
  return "#22c55e";
}

function nodeBorderColor(d) {
  if (d.kind === "phantom")        return "#b91c1c";
  if (d.kind === "api_consumer")   return "#93c5fd";
  return "#27272a";
}

const cy = cytoscape({
  container: document.getElementById("cy"),
  elements,
  layout: { name: "preset" },

  // Lock nodes — no dragging.
  autoungrabify: true,
  userZoomingEnabled: true,
  userPanningEnabled: true,
  boxSelectionEnabled: false,

  style: [
    // ---- Zone compound nodes ----
    {
      selector: 'node[kind = "zone_compound"]',
      style: {
        "background-opacity": 0.08,
        "background-color": ele => {
          const z = ele.data("zone");
          return z === "frontend" ? "#3b82f6" : z === "backend" ? "#22c55e" : "#a855f7";
        },
        "border-width": 1.5,
        "border-color": ele => {
          const z = ele.data("zone");
          return z === "frontend" ? "#3b82f6" : z === "backend" ? "#22c55e" : "#a855f7";
        },
        "border-opacity": 0.35,
        "label": "data(label)",
        "color": ele => {
          const z = ele.data("zone");
          return z === "frontend" ? "#60a5fa" : z === "backend" ? "#4ade80" : "#c084fc";
        },
        "font-size": "14px",
        "font-weight": "700",
        "text-valign": "top",
        "text-halign": "center",
        "text-margin-y": -6,
        "padding": "36px",
        "shape": "roundrectangle",
      }
    },
    // ---- Subgroup compound nodes ----
    {
      selector: 'node[kind = "subgroup_compound"]',
      style: {
        "background-opacity": 0.12,
        "background-color": ele => {
          const z = ele.data("zone");
          return z === "frontend" ? "#3b82f6" : z === "backend" ? "#22c55e" : "#a855f7";
        },
        "border-width": 1,
        "border-color": ele => {
          const z = ele.data("zone");
          return z === "frontend" ? "#3b82f6" : z === "backend" ? "#22c55e" : "#a855f7";
        },
        "border-opacity": 0.25,
        "label": "data(label)",
        "color": "#9ca3af",
        "font-size": "10px",
        "font-weight": "600",
        "text-valign": "top",
        "text-halign": "center",
        "text-margin-y": -2,
        "padding": "18px",
        "shape": "roundrectangle",
      }
    },
    // ---- Leaf file nodes ----
    {
      selector: "node[kind != 'zone_compound'][kind != 'subgroup_compound']",
      style: {
        "background-color": ele => nodeColor(ele.data()),
        "label": "data(label)",
        "color": "#cbd5e1",
        "font-size": "9px",
        "text-valign": "center",
        "text-halign": "right",
        "text-margin-x": 6,
        "width": 16,
        "height": 16,
        "border-width": 1.5,
        "border-color": ele => nodeBorderColor(ele.data()),
        "shape": ele => ele.data("kind") === "phantom" ? "diamond" : "ellipse",
      }
    },
    // ---- Edges ----
    {
      selector: "edge",
      style: {
        "width": 1,
        "line-color": "#5a5a5e",
        "target-arrow-color": "#5a5a5e",
        "target-arrow-shape": "triangle",
        "arrow-scale": 0.7,
        "curve-style": "bezier",
        "opacity": 0.5,
      }
    },
    {
      selector: 'edge[kind = "import"]',
      style: {
        "line-color": "#5a5a5e",
        "target-arrow-color": "#5a5a5e",
        "opacity": 0.5,
      }
    },
    {
      selector: 'edge[kind = "api"]',
      style: {
        "line-color": "#f97316",
        "target-arrow-color": "#f97316",
        "line-style": "dashed",
        "line-dash-pattern": [6, 4],
        "width": 1.5,
        "opacity": 0.9,
      }
    },
    {
      selector: 'edge[kind = "api_unmatched"]',
      style: {
        "line-color": "#ef4444",
        "target-arrow-color": "#ef4444",
        "line-style": "dashed",
        "line-dash-pattern": [4, 3],
        "width": 1.5,
        "opacity": 0.85,
      }
    },
    // Cross-zone import edges get a lighter, distinct color.
    {
      selector: 'edge[kind = "import"].cross-zone',
      style: {
        "line-color": "#9ca3af",
        "target-arrow-color": "#9ca3af",
        "opacity": 0.55,
      }
    },
    { selector: "node:selected",    style: { "border-color": "#fff", "border-width": 2.5 } },
    { selector: "node.highlighted", style: { "opacity": 1, "border-color": "#fef08a", "border-width": 2.5 } },
    { selector: "edge.highlighted", style: { "opacity": 1, "width": 2.5 } },
    { selector: "node.dimmed",      style: { "opacity": 0.12 } },
    { selector: "edge.dimmed",      style: { "opacity": 0.05 } },
  ],
  zoom: 0.55,
  minZoom: 0.05,
  maxZoom: 4,
});

// Tag cross-zone import edges after graph is built.
cy.edges('[kind = "import"]').forEach(e => {
  if (e.source().data("zone") !== e.target().data("zone")) {
    e.addClass("cross-zone");
  }
});

// Stats (exclude compound parents from the file count).
const leafNodes = cy.nodes().filter(n =>
  n.data("kind") !== "zone_compound" && n.data("kind") !== "subgroup_compound"
);
const fileNodes  = leafNodes.filter(n => n.data("kind") !== "phantom");
const phantomCount = leafNodes.filter(n => n.data("kind") === "phantom").length;
const edgeCount  = cy.edges().length;
document.getElementById("stats").textContent =
  `${fileNodes.length} files · ${edgeCount} edges · ${phantomCount} phantom`;

cy.fit(undefined, 60);

// ---- Info panel on node tap ------------------------------------------------
const panel = document.getElementById("panel");

cy.on("tap", "node", evt => {
  const d = evt.target.data();
  // Skip compound parent taps — just show generic info.
  if (d.kind === "zone_compound" || d.kind === "subgroup_compound") {
    panel.innerHTML = `<b>${d.label}</b>  <i>compound region</i>`;
    panel.classList.remove("hidden");
    return;
  }

  const lines = [
    `<b>${d.label}</b>  <i>${d.path || d.id}</i>  <span style="color:#6b7280">zone: ${d.zone} / ${d.group}</span>`,
  ];
  if (d.routes && d.routes.length) {
    lines.push("<u>routes</u>");
    for (const r of d.routes)
      lines.push(`&nbsp;&nbsp;${r.method} <span style="color:#fbbf24">${r.path}</span> → <span style="color:#86efac">${r.function}()</span>`);
  }
  if (d.api_calls && d.api_calls.length) {
    lines.push("<u>api calls</u>");
    for (const c of d.api_calls)
      lines.push(`&nbsp;&nbsp;<span style="color:#fbbf24">${c}</span>`);
  }
  if (d.functions && d.functions.length && (!d.routes || !d.routes.length)) {
    lines.push("<u>functions</u>");
    lines.push(`&nbsp;&nbsp;${d.functions.slice(0, 12).join("&nbsp;&nbsp;")}${d.functions.length > 12 ? " …" : ""}`);
  }
  panel.innerHTML = lines.join("<br>");
  panel.classList.remove("hidden");

  // Dim all leaves + edges (NOT compound parents — they're the shaded zone/subgroup
  // backgrounds and should stay at their normal look), then highlight neighbourhood.
  const dimmable = cy.elements().filter(el => !el.isParent());
  dimmable.addClass("dimmed").removeClass("highlighted");
  evt.target.removeClass("dimmed").addClass("highlighted");
  const hood = evt.target.connectedEdges();
  hood.removeClass("dimmed").addClass("highlighted");
  hood.connectedNodes().removeClass("dimmed").addClass("highlighted");
});

cy.on("tap", evt => {
  if (evt.target === cy) {
    panel.classList.add("hidden");
    cy.elements().removeClass("dimmed").removeClass("highlighted");
  }
});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Crawling backend…")
    backend_files = crawl_backend()
    print(f"  {len(backend_files)} Python files")

    print("Crawling frontend…")
    frontend_files = crawl_frontend()
    print(f"  {len(frontend_files)} TypeScript/TSX files")

    print("Building graph…")
    nodes, edges = build_graph(backend_files, frontend_files)

    phantoms = sum(1 for n in nodes if n["data"].get("kind") == "phantom")
    api_edges = sum(1 for e in edges if e["data"].get("kind") in ("api", "api_unmatched"))
    import_edges = sum(1 for e in edges if e["data"].get("kind") == "import")
    print(f"  {len(nodes)} leaf nodes ({phantoms} phantom), {len(edges)} edges")
    print(f"  import edges: {import_edges}  |  API-call edges: {api_edges}")

    html = render_html(nodes, edges)
    OUT_HTML.write_text(html, encoding="utf-8")
    size_kb = OUT_HTML.stat().st_size // 1024

    # Count compound nodes added by render_html by parsing elements out of html.
    # Quick way: regenerate to get counts.
    positioned, compound_nodes, _ = compute_positions(nodes)
    total_nodes = len(positioned) + len(compound_nodes)
    print(f"\nWrote {OUT_HTML}  ({size_kb} KB)")
    print(f"  total nodes in graph: {total_nodes} ({len(compound_nodes)} compound parents + {len(positioned)} leaf nodes)")
    print(f"Open:  file://{OUT_HTML.resolve()}")


if __name__ == "__main__":
    main()
