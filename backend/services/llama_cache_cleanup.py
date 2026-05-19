"""Periodic reaper for orphaned blobs in the llama-swap HuggingFace cache.

The HF cache layout at infra/llama_models/hub/:

    models--<org>--<repo>/
      blobs/<sha256>            ← the actual file, named by content hash
      snapshots/<commit>/<name> ← symlinks pointing at blobs/

A successful download finishes with a snapshot symlink referencing the
blob. A *partial* download (admin clicked Cancel, llama-server crashed,
the user re-picked a different quant, etc.) leaves the blob on disk with
no incoming symlink — wasted multi-GB bytes that nothing will ever
reuse.

This task walks every repo dir, builds the set of referenced blobs from
the snapshot symlinks, and deletes blobs that are unreferenced AND
quiescent (mtime older than the safety threshold). The threshold guards
against deleting a blob whose snapshot symlink hasn't been created yet
because the download is still in flight.

Failures are logged and swallowed; the loop keeps running.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import time


_logger = logging.getLogger(__name__)


_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_HF_CACHE = _REPO_ROOT / "infra" / "llama_models" / "hub"

# Daily by default. Safety margin: only reap blobs untouched for at least
# 6 hours so an in-flight multi-GB download that's slow to write the
# snapshot symlink doesn't get its blob nuked mid-stream.
DEFAULT_INTERVAL_SECONDS = 24 * 3600
DEFAULT_QUIESCENT_SECONDS = 6 * 3600


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


async def llama_cache_cleanup_loop(
    interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
    quiescent_seconds: int = DEFAULT_QUIESCENT_SECONDS,
) -> None:
    """Long-running coroutine. Spawn via asyncio.create_task in lifespan;
    cancel on shutdown."""
    while True:
        try:
            deleted = await asyncio.to_thread(reap_orphan_blobs, quiescent_seconds)
            if deleted:
                total_bytes = sum(size for _, size in deleted)
                _logger.info(
                    "llama cache cleanup: reaped %d orphan blob(s), freed %d bytes",
                    len(deleted), total_bytes,
                )
        except asyncio.CancelledError:
            return
        except Exception:
            _logger.exception("llama cache cleanup tick failed")
        try:
            await asyncio.sleep(interval_seconds)
        except asyncio.CancelledError:
            return
