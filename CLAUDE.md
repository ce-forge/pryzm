# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working in this repository.

## Stack Overview

Pryzm is a locally hosted AI copilot for IT management. Two services:
- **Backend**: FastAPI (Python) on port 8000 — agentic LLM loop, PostgreSQL/pgvector RAG, Redis caching
- **Frontend**: Next.js 16 (React 19) on port 3000 — chat UI with SSE streaming

Infrastructure is run via `docker-compose.yml`: PostgreSQL (with pgvector), Redis, and Ollama.

## Development Commands

```bash
# Start infrastructure (PostgreSQL, Redis, Ollama)
docker-compose up -d

# Backend (from /backend)
fastapi dev main.py          # port 8000

# Frontend (from /frontend)
npm run dev                  # port 3000
npm run build                # production build
npm run lint                 # ESLint
```

No test suite is configured. The `test_suite.json` in `frontend/src/data/` is a data-driven test runner for automated tool-use scenarios, not a unit test framework.

## Environment

The backend reads DB credentials from `../.env` (root `.env` file). Key variables: `DB_USER`, `DB_PASSWORD`, `DB_NAME`. The frontend uses `NEXT_PUBLIC_API_URL` (defaults to `http://127.0.0.1:8000`).

## Backend Architecture

### Agentic Tool Loop (`core/ai_engine.py`)
The `stream_chat()` function is the heart of the system. It sends messages to Ollama and enters a `while` loop (up to `MAXIMUM_TOOL_LOOPS` iterations) where:
1. If the LLM returns `tool_calls`, each tool is executed, results are appended as `tool` role messages, and the loop retries
2. If no tool calls, the final response is word-streamed back via SSE

The `/analyze` endpoint (`routers/chat.py`) wraps this in a `StreamingResponse` yielding NDJSON lines, saves messages to DB, and triggers background memory condensation when the message count exceeds `MEMORY_CONDENSE_THRESHOLD` (15).

### Tool Registry (`tools/registry.py`)
Tools are registered with a `@tool(properties, required)` decorator that populates `AVAILABLE_TOOLS` (callable map) and `TOOL_DEFINITIONS` (JSON schema for the LLM). Tools live in `tools/network.py`, `tools/retrieval.py`, `tools/system.py`. New tools just need the decorator, type hints, and a Google-style docstring.

### RAG Pipeline (`services/knowledge.py`)
Documents are chunked via `RecursiveCharacterTextSplitter`, embedded with `nomic-embed-text` through Ollama, and stored as `DocumentChunk` rows with a 768-dim vector column. Retrieval uses cosine distance (< 0.65 threshold) with a fallback to ILIKE text search.

### Prompt System (`core/prompt_manager.py`)
System prompts are loaded from `core/prompts/{mode}.txt` (e.g., `it_copilot.txt`). Micro-prompts are stored in `micro_prompts.json` (user overrides) layered over `micro_prompts.default.json`. Editable via the Settings UI or `/api/prompts` endpoint.

### Database (`db/models.py`)
Five ORM models: `Session`, `Message`, `Folder`, `Document`, `DocumentChunk`. Messages have a `role` field that includes `"memory"` (used for condensed chat summaries, not shown to users).

## Frontend Architecture

### State Management (`context/ChatContext.tsx`)
All state is composed from custom hooks and exposed through `ChatProvider`:
- `useSession` — session CRUD, URL routing, message cache
- `useInference` — SSE streaming, optimistic IDs → real DB UUID handoff, abort control
- `useUploader` — file upload queue with progress tracking
- `useTestSuite` — automated multi-step tool execution from `test_suite.json`
- `useMessageActions` — edit, delete, branch, rerun

### Streaming Flow (`hooks/useInference.ts`)
1. User sends message → optimistic ID (`optimistic-{ts}`) is used for the message cache
2. POST to `/analyze` → SSE stream parsed line-by-line
3. First line contains real `session_id` → cache is copied to the new key (URL handoff)
4. Final response finalizes both optimistic and real-ID buckets
5. `streamingSessionIdsRef` tracks which sessions are mid-stream (used by UI for loading state)

### Next.js 16 Warning
This project uses Next.js 16.2.4 which has breaking API changes from earlier versions. Read `node_modules/next/dist/docs/` before writing framework-specific code.

### Key Components
- `ActiveSession.tsx` — main chat area, delegates to `ChatBubble.tsx`
- `ChatBubble.tsx` — renders `AssistantMessage.tsx` (with `MarkdownRenderer`) and `UserMessage.tsx`
- `Sidebar.tsx` / `SessionDirectory.tsx` — session list with folders, search, drag-and-drop
