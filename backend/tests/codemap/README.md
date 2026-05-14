# Codebase map (dev aid)

Local-only static-analysis tool. Lives alongside the test suite as a reference
for visualizing the codebase after each phase of work — confirms files are
connecting the way they should and surfaces orphan/unexpected coupling.

Not a pytest target; just a Python script. Output goes to `_out/` (gitignored).

## Run

```bash
cd backend
./venv/bin/python tests/codemap/codemap.py
# Then open: tests/codemap/_out/codemap.html
```

Or from the project root:

```bash
xdg-open backend/tests/codemap/_out/codemap.html
```

## What it shows

Three horizontal shaded regions: Frontend, Backend, Tests. Within each region,
files are grouped into sub-shaded boxes by sub-directory (`hooks/`, `routers/`,
`services/`, etc.). Edges:

- **Solid gray** — internal module imports (within a zone).
- **Solid light-gray** — cross-zone imports (rare but possible).
- **Dashed orange** — frontend `apiFetch()` → matching backend `@router` declaration.
- **Dashed red + diamond phantom node** — frontend API call to a route that doesn't exist.
  A clean codebase has zero of these.

Click a node to dim everything else and highlight that file's neighbourhood
(imports, importers, API targets). Click empty space to clear. Pan via drag,
zoom via mouse wheel. Nodes are locked — they can't be dragged out of position.

## When to regenerate

After landing each phase, re-run the script. The new map shows whether the
refactor connected things the way you expected.
