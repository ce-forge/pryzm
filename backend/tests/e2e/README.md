# E2E UI Smoke Harness

Playwright-driven smoke tests that exercise the real frontend against the real
backend in a headless Chromium browser.

## Prerequisites

One-time per dev machine:

```bash
cd backend
./venv/bin/playwright install chromium
```

The dev servers must be running:

```bash
# Terminal A
cd backend && ./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# Terminal B
cd frontend && npm run dev -- -H 0.0.0.0
```

## Run

```bash
cd backend
./venv/bin/pytest tests/e2e/ -v
```

Screenshots are written to `backend/tests/e2e/_artifacts/` (gitignored).

## Layout

- `conftest.py` — fixtures (browser, context, page, token injection, screenshot helper).
- `test_phaseN_smoke.py` — one file per merged phase, covering that phase's UI flows.
- `_artifacts/` — screenshot captures (gitignored).
