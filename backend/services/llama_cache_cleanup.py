"""Periodic reaper for the llama-swap HuggingFace cache.

The HF cache layout at infra/llama_models/hub/:

    models--<org>--<repo>/
      blobs/<sha256>            ← the actual file, named by content hash
      snapshots/<commit>/<name> ← symlinks pointing at blobs/

Two distinct kinds of waste accumulate:

1. **Orphan blobs.** Partial download (admin clicked Cancel, llama-server
   crashed, the user re-picked a different quant) leaves a blob with no
   incoming snapshot symlink — wasted bytes nothing will reuse.

2. **Unused repos.** Admin deletes a model from /admin/system — the YAML
   entry is removed, but the entire repo dir (blobs + snapshots) stays
   in the cache. Multi-GB of weights for a model llama-swap no longer
   knows about.

This task runs both passes daily. The orphan-blob pass is precise; the
unused-repo pass is gated on (a) the repo not appearing in any model's
`-hf` cmd in the live YAML, and (b) the most recent file in the repo
being quiescent (older than the safety threshold) so an in-flight
download doesn't get reaped mid-stream.

Failures are logged and swallowed; the loop keeps running.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import re
import shutil
import time

import yaml


_logger = logging.getLogger(__name__)


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_HF_CACHE = _REPO_ROOT / "infra" / "llama_models" / "hub"
_YAML_PATH = _REPO_ROOT / "infra" / "llama-swap-config.yaml"

# Daily by default. Safety margin: only reap untouched for at least
# 6 hours so an in-flight multi-GB download that's slow to write the
# snapshot symlink doesn't get its blob nuked mid-stream.
DEFAULT_INTERVAL_SECONDS = 24 * 3600
DEFAULT_QUIESCENT_SECONDS = 6 * 3600

_HF_CMD_RE = re.compile(r"-hf\s+(\S+?):")


def _active_repo_ids() -> set[str]:
    """Read the live YAML and return the set of `org/repo` ids referenced
    by any model's `-hf` cmd. Models in any group count (chat, always-on,
    inactive) — inactive still wants its cache preserved."""
    active: set[str] = set()
    try:
        with open(_YAML_PATH) as f:
            cfg = yaml.safe_load(f) or {}
    except OSError:
        return active
    for model_cfg in (cfg.get("models") or {}).values():
        cmd = model_cfg.get("cmd") or ""
        match = _HF_CMD_RE.search(cmd)
        if match:
            active.add(match.group(1))
    return active


def _repo_dir_to_id(name: str) -> str | None:
    """Turn `models--org--repo` back into `org/repo`. Returns None for
    names that don't follow the expected pattern."""
    if not name.startswith("models--"):
        return None
    rest = name[len("models--"):]
    # HF uses `--` as the org/name separator. Split once on the leftmost
    # occurrence so repo names containing dashes survive intact.
    parts = rest.split("--", 1)
    if len(parts) != 2:
        return None
    return f"{parts[0]}/{parts[1]}"


def _newest_mtime(root: pathlib.Path) -> float:
    """Walk root recursively and return the newest mtime found. 0 if empty
    or unreadable — caller treats that as 'don't reap yet'."""
    newest = 0.0
    try:
        for entry in root.rglob("*"):
            try:
                m = entry.lstat().st_mtime
                if m > newest:
                    newest = m
            except OSError:
                continue
    except OSError:
        return 0.0
    return newest


def _referenced_blobs(repo_dir: pathlib.Path) -> set[str]:
    """Return the set of blob filenames pointed to by any snapshot symlink."""
    referenced: set[str] = set()
    snapshots = repo_dir / "snapshots"
    if not snapshots.is_dir():
        return referenced
    for commit_dir in snapshots.iterdir():
        if not commit_dir.is_dir():
            continue
        for entry in commit_dir.iterdir():
            try:
                target = os.readlink(entry)
            except OSError:
                continue
            # Symlinks are relative: ../../blobs/<hash>. We only care about
            # the basename — the blob filename within blobs/.
            referenced.add(os.path.basename(target))
    return referenced


def reap_orphan_blobs(quiescent_seconds: int) -> list[tuple[pathlib.Path, int]]:
    """Single sync pass over the cache. Returns (path, freed_bytes) for each
    blob deleted. Sizes are sampled before unlink so the caller can log them."""
    deleted: list[tuple[pathlib.Path, int]] = []
    if not _HF_CACHE.is_dir():
        return deleted
    now = time.time()
    for repo_dir in _HF_CACHE.iterdir():
        if not repo_dir.is_dir() or not repo_dir.name.startswith("models--"):
            continue
        blobs_dir = repo_dir / "blobs"
        if not blobs_dir.is_dir():
            continue
        referenced = _referenced_blobs(repo_dir)
        for blob in blobs_dir.iterdir():
            if not blob.is_file():
                continue
            if blob.name in referenced:
                continue
            try:
                stat = blob.stat()
            except OSError:
                continue
            if now - stat.st_mtime < quiescent_seconds:
                continue
            size = stat.st_size
            try:
                blob.unlink()
                deleted.append((blob, size))
            except OSError as e:
                _logger.warning(
                    "llama cache cleanup: failed to delete %s: %s", blob, e,
                )
    return deleted


def reap_unused_repos(
    quiescent_seconds: int,
    active_repo_ids: set[str],
) -> list[tuple[pathlib.Path, int]]:
    """Delete entire repo dirs whose org/repo doesn't appear in any model's
    `-hf` cmd in the live YAML, and whose newest file is older than the
    safety threshold. Returns (path, freed_bytes) per dir removed."""
    deleted: list[tuple[pathlib.Path, int]] = []
    if not _HF_CACHE.is_dir():
        return deleted
    now = time.time()
    for repo_dir in _HF_CACHE.iterdir():
        if not repo_dir.is_dir() or not repo_dir.name.startswith("models--"):
            continue
        repo_id = _repo_dir_to_id(repo_dir.name)
        if repo_id is None or repo_id in active_repo_ids:
            continue
        newest = _newest_mtime(repo_dir)
        if newest == 0 or now - newest < quiescent_seconds:
            continue
        # Sum sizes before delete so we can log how much was freed.
        size = 0
        for entry in repo_dir.rglob("*"):
            try:
                if entry.is_file() and not entry.is_symlink():
                    size += entry.stat().st_size
            except OSError:
                continue
        try:
            shutil.rmtree(repo_dir)
            deleted.append((repo_dir, size))
        except OSError as e:
            _logger.warning(
                "llama cache cleanup: failed to remove %s: %s", repo_dir, e,
            )
    return deleted


async def llama_cache_cleanup_loop(
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    quiescent_seconds: int = DEFAULT_QUIESCENT_SECONDS,
) -> None:
    """Long-running coroutine. Spawn via asyncio.create_task in lifespan;
    cancel on shutdown."""
    while True:
        try:
            orphans = await asyncio.to_thread(reap_orphan_blobs, quiescent_seconds)
            active = await asyncio.to_thread(_active_repo_ids)
            unused = await asyncio.to_thread(reap_unused_repos, quiescent_seconds, active)
            orphan_bytes = sum(size for _, size in orphans)
            unused_bytes = sum(size for _, size in unused)
            if orphans or unused:
                _logger.info(
                    "llama cache cleanup: %d orphan blob(s) (%d B), "
                    "%d unused repo(s) (%d B)",
                    len(orphans), orphan_bytes, len(unused), unused_bytes,
                )
        except asyncio.CancelledError:
            return
        except Exception:
            _logger.exception("llama cache cleanup tick failed")
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
