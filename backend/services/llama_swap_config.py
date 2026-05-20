"""YAML I/O and parsing for `infra/llama-swap-config.yaml`.

Round-trip mode via ruamel.yaml so comments and key order survive mutations —
devs may still edit the file by hand. Reload helper SIGHUPs llama-swap; failure
is logged-and-swallowed because the YAML is already written and the SIGHUP can
be retried manually.
"""
from __future__ import annotations

import logging
import pathlib
import re
import subprocess
import time

import ruamel.yaml

_logger = logging.getLogger("pryzm.admin")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
YAML_PATH = REPO_ROOT / "infra" / "llama-swap-config.yaml"

_yaml = ruamel.yaml.YAML()
_yaml.preserve_quotes = True

# Match the bits we care about inside the multi-line cmd string.
# `-hf <repo>` with `:quant` optional, since the `-hff <filename>` form replaces
# the colon shortcut for repos that don't expose preset metadata on the HF API.
HF_RE = re.compile(r"-hf\s+(\S+?)(?::(\S+))?(?=\s|$)")
HFF_RE = re.compile(r"-hff\s+(\S+)")
NGL_RE = re.compile(r"-ngl\s+(\d+)")
CTX_RE = re.compile(r"--ctx-size\s+(\d+)")
# Extract a quant tag from a GGUF filename for display (e.g. "Q4_K_M" from
# "model-Q4_K_M.gguf"). Used only when the cmd uses `-hff` instead of `:quant`,
# so the admin UI can still show "Q4_K_M" alongside the repo.
QUANT_FROM_FILE_RE = re.compile(
    r"-((?:IQ|Q|UD-Q|UD-IQ)\d+(?:_[A-Z]+)*|F\d+|BF\d+)\.gguf$",
    re.IGNORECASE,
)


def read_yaml() -> dict:
    with open(YAML_PATH) as f:
        return _yaml.load(f) or {}


def write_yaml(data: dict) -> None:
    with open(YAML_PATH, "w") as f:
        _yaml.dump(data, f)


def reload_llama_swap() -> None:
    """SIGHUP the llama-swap container so it re-reads the YAML. Tolerates
    failure internally — the YAML is already written and the SIGHUP can be
    retried manually."""
    start = time.perf_counter()
    try:
        subprocess.run(
            ["docker", "compose", "kill", "-s", "HUP", "llama-swap"],
            cwd=REPO_ROOT, check=True, timeout=5, capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        _logger.warning(
            "admin.llama_swap_reload_failed stderr=%s",
            e.stderr.decode(errors="replace") if e.stderr else "",
        )
        return
    duration_ms = int((time.perf_counter() - start) * 1000)
    _logger.info("admin.llama_swap_reloaded duration_ms=%d", duration_ms)


def parse_model_row(model_id: str, cfg: dict) -> dict:
    cmd = " ".join((cfg.get("cmd") or "").split())  # collapse newlines/whitespace
    hf_match = HF_RE.search(cmd)
    hff_match = HFF_RE.search(cmd)
    ngl_match = NGL_RE.search(cmd)
    ctx_match = CTX_RE.search(cmd)
    groups = cfg.get("groups") or []

    repo = hf_match.group(1) if hf_match else None
    quant = hf_match.group(2) if hf_match else None
    filename = hff_match.group(1) if hff_match else None
    # Newer entries omit `:quant` from `-hf` and use `-hff <filename>` instead
    # — derive a display quant from the filename so the UI keeps its label.
    if filename and not quant:
        m = QUANT_FROM_FILE_RE.search(filename)
        if m:
            quant = m.group(1)

    return {
        "id": model_id,
        "repo": repo,
        "quant": quant,
        "filename": filename,
        "ngl": int(ngl_match.group(1)) if ngl_match else None,
        "ctx_size": int(ctx_match.group(1)) if ctx_match else None,
        "group": groups[0] if groups else None,
        "tags": list(cfg.get("tags") or []),
    }


def build_cmd_block(
    repo: str,
    quant: str,
    filename: str | None,
    ngl: int,
    ctx_size: int,
    group: str,
) -> str:
    """Render a multi-line `cmd:` value matching the style of existing entries.
    When `filename` is provided (HF picker path), emit the explicit-filename
    form which bypasses the HF API's preset metadata lookup — some repos
    (e.g. bartowski's larger Gemma variants) don't expose it and return 404.
    Falls back to the `:quant` shortcut for manual entries without a filename.
    Chat models get k/v cache quantisation; embedding doesn't."""
    if filename:
        hf_lines = f"-hf {repo}\n-hff {filename}"
    else:
        hf_lines = f"-hf {repo}:{quant}"
    base = (
        f"/app/llama-server --port ${{PORT}}\n"
        f"{hf_lines}\n"
        f"-ngl {ngl} --ctx-size {ctx_size} --jinja --flash-attn on"
    )
    if group == "on-demand":
        base += "\n--cache-type-k q8_0 --cache-type-v q8_0"
    return base
