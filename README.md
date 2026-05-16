# Pryzm

A locally-hosted AI copilot for IT management. Agentic LLM loop with hybrid RAG over uploaded docs, web search via self-hosted SearxNG, per-workspace tooling, and pre-built network-diagnostic tools (ping, port-check, DNS, traceroute, SSL inspection, public IP).

Everything runs on-host. The chat model, embeddings, vision captioning, and search index all live in containers on the same machine — no cloud LLM, no external API keys.

## Stack

| Layer | Tech |
|---|---|
| **Backend** | FastAPI (Python 3.12), SQLAlchemy + Alembic |
| **Frontend** | Next.js 16 / React 19 / Tailwind 4 |
| **Database** | PostgreSQL 15 + pgvector (vector + tsvector hybrid retrieval via RRF) |
| **Cache / pub-sub** | Redis (upload status broker, memory-condense locks) |
| **LLM serving** | [llama-swap](https://github.com/mostlygeek/llama-swap) wrapping llama.cpp; OpenAI-compatible API |
| **Models (defaults)** | Gemma-4 E2B (small chat), Gemma-4 E4B (large chat, escalation target), Qwen2-VL-2B (vision captioning, on-demand), `nomic-embed-text-v1.5` (embeddings) |
| **Web search** | Self-hosted SearxNG container, JSON API |

## Architecture in one paragraph

The user sends a message. A heuristic router picks the small (E2B) or large (E4B) chat model based on prompt length / code fences / complex verbs / history depth / attachments. The agentic loop in `core/ai_engine.py` calls the model, runs any tools it asks for, feeds results back, and loops up to 8 times before returning. Attached files trigger auto-RAG scoped to that document; free-form questions trigger workspace-wide hybrid retrieval. Per-turn "modes" (e.g. the globe-icon `web_search` toggle) can force-include tools or override the router for a single turn.

## Quick start

You need: Docker (with NVIDIA Container Toolkit for GPU access), Python 3.12, Node 20+, and ~16 GB VRAM for the default Gemma-4 lineup. First boot downloads ~10 GB of model weights from HuggingFace via `bartowski/*-GGUF` quants.

```bash
# 1. Configure secrets. Copy the template, then fill in real values.
cp .env.example .env   # (if missing, create .env directly — see below)

# 2. Bring up the infra containers.
docker compose up -d   # postgres + redis + searxng + llama-swap

# 3. Backend.
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2

# 4. Frontend (separate terminal).
cd frontend
npm install
npm run dev -- -H 0.0.0.0
```

Open `http://localhost:3000`. From any LAN device, `http://<host-ip>:3000` works too (the frontend auto-derives the API URL from `window.location`).

### `.env` shape

Required (no defaults — startup fails fast if missing):

```
DB_USER=pryzm_admin
DB_PASSWORD=<choose-something>
DB_NAME=pryzm_core
PRYZM_API_TOKEN=<long-random-bearer-token>
SEARXNG_SECRET=<32-byte-hex>
```

Generate the random values with `python3 -c 'import secrets; print(secrets.token_hex(32))'`.

## Key features

- **Agentic tool loop** — model decides which of the registered tools (network diagnostics, knowledge-base search, web search, session rename) to call; chains them as needed.
- **Hybrid RAG over uploads** — drag-and-drop documents (txt/md/log/csv/json/yaml/conf, PDF, JPG/PNG/WebP) get chunked + embedded; retrieval is HNSW vector search + `content_tsv` keyword search merged via RRF.
- **Image captioning at upload time** — JPG/PNG/WebP get captioned by Qwen2-VL-2B (loaded on demand, unloads after 60s idle). The caption becomes the searchable record.
- **Web search via SearxNG** — `web_search` tool on a per-workspace toggle. Per-turn force-include via the globe icon in the chat input.
- **Per-turn modes** — small registry of behaviour overrides (`force_tools`, `directive`, `tier_override`) for one-shot routing decisions. `web_search` is mode #1.
- **Workspaces** — `it_copilot` (network/IT focus) and `personal` (general assistant) ship as defaults; each carries its own system prompt and enabled-tool set. Add more via Admin UI.

## Repo layout

```
backend/         FastAPI app: routers/, core/ (LLM engine, router, modes),
                 services/ (knowledge, ingest, image_describe, condense),
                 tools/ (network, retrieval, system, web), db/, alembic/, tests/
frontend/        Next.js app: src/app, src/components, src/context, src/hooks
infra/           docker-mounted configs (llama-swap-config.yaml, searxng/)
docs/specs/      Public design docs (committed)
docs/plans/      Public implementation plans (committed)
docker-compose.yml
```

## Common dev tasks

```bash
# Backend tests
cd backend && ./venv/bin/pytest

# Frontend lint + typecheck
cd frontend && npm run lint && npx tsc --noEmit

# Apply migrations
cd backend && ./venv/bin/alembic upgrade head

# Reload llama-swap config (model groups, tags) without restarting models
docker compose kill -s HUP llama-swap
# (full container restart if model `cmd:` lines changed — see infra/llama-swap-config.yaml)
```

## Status

Personal project, single deployment. APIs and DB schema may change without migration notice on minor versions. Bearer-token auth is provisional; a proper login flow is on the roadmap.
