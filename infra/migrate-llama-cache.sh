#!/usr/bin/env bash
# One-time migration of llama-swap's HuggingFace cache from the old named
# Docker volume (`pryzm_llama_models`) into the new bind-mounted host
# directory at infra/llama_models. Run this once after pulling the
# compose change that switches from the named volume to the bind mount.
#
# Safe to re-run: only copies files that aren't already at the destination.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$REPO_ROOT/infra/llama_models"
OLD_VOLUME="pryzm_llama_models"

echo "Migrating $OLD_VOLUME -> $DEST"

# Make sure the destination exists and is owned by the host user.
mkdir -p "$DEST"

# Bail early if the named volume isn't there — nothing to migrate.
if ! docker volume inspect "$OLD_VOLUME" >/dev/null 2>&1; then
  echo "Old named volume $OLD_VOLUME not present — nothing to migrate."
  exit 0
fi

# Stop llama-swap so neither side is writing during the copy.
docker compose stop llama-swap >/dev/null 2>&1 || true

# Run a throwaway container that has both the old volume and the new
# bind mount, then rsync into place. Using rsync (not cp -a) so re-runs
# are idempotent.
docker run --rm \
  -v "$OLD_VOLUME:/from:ro" \
  -v "$DEST:/to" \
  alpine sh -c "apk add --no-cache rsync >/dev/null 2>&1 && rsync -a --info=progress2 /from/ /to/"

# Fix ownership so the host user can read the files (in case the named
# volume had everything owned by root).
HOST_UID="$(id -u)"
HOST_GID="$(id -g)"
docker run --rm \
  -v "$DEST:/to" \
  alpine chown -R "$HOST_UID:$HOST_GID" /to

echo "Migration complete. Restart with: docker compose up -d llama-swap"
echo "Once verified, you can delete the old volume: docker volume rm $OLD_VOLUME"
