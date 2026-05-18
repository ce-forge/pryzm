# Pryzm

Self-hosted, multi-user AI copilot. Runs on your own machine — chat, RAG over your docs, image captioning, web search, per-workspace tools, and an admin dashboard for managing users and observing what's happening. Nothing leaves the box.

Model serving is llama.cpp under llama-swap, so swapping models is a config edit. Default lineup is Gemma-4 for chat, Qwen2-VL-2B for image captioning, and `nomic-embed-text` for embeddings. A heuristic router picks small vs large per turn.

## Running it

You need Docker (with the NVIDIA Container Toolkit if you want GPU inference), Python 3.12, and Node 20+.

```bash
cp .env.example .env       # then edit with your own values
docker compose up -d
cd backend && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
./venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000 --reload --reload-delay 2
```

In another terminal:

```bash
cd frontend && npm install && npm run dev -- -H 0.0.0.0
```

Open `http://localhost:3000`. From your phone or another LAN device, swap `localhost` for the host's IP.

First boot pulls ~10 GB of model weights from HuggingFace. After that it's offline.

## First login

The first time the backend starts, an `admin` account is auto-created with the password from `PRYZM_BOOTSTRAP_ADMIN_PASSWORD` (defaults to `admin` if unset). The first login forces you to change it. From there, manage everything from the admin dashboard at `/admin`:

- **Users** — create accounts, assign starter workspaces, reset passwords, deactivate, delete
- **Workspaces** — instantiate templates per user, push template changes, manage orphans
- **System** — model add/remove/edit, micro-prompt overrides
- **Engine** — llama-swap's UI proxied through admin auth (no separate port exposed)
- **Audit** — every action, queryable by user/event-type/workspace/time-range
- **Bug reports** — triage user-submitted reports; resolutions notify the reporter

Voluntary password changes by users are not supported by design — admin owns all credentials. Users get a temp password from admin, change it on first login, and from then on can only request a new one via admin reset.

## Where to look

Backend internals: `backend/README.md`. Frontend internals: `frontend/README.md`. Specs and implementation plans live under `docs/specs/` and `docs/plans/`.
