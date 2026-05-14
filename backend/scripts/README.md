# Pryzm dev tools

Local-only utilities. Each script is a standalone Python file with no
external state; output goes to `scripts/_out/` (gitignored).

## `codemap.py`

Generates an interactive HTML map of the codebase:
files as nodes, imports + API calls as edges, zoned Frontend / Backend / Tests.

```bash
cd backend
./venv/bin/python scripts/codemap.py
# Then open: scripts/_out/codemap.html
```

The map crawls statically — it doesn't trace runtime calls. Use it to sanity-check
the architecture, spot orphan API calls, or scan for unexpected coupling.
