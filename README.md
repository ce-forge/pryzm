# Pryzm

Local AI copilot for IT work. Runs on your own machine — chat, RAG over your docs, image captioning, network diagnostics, web search. Nothing leaves the box.

The model serving is llama.cpp under llama-swap, so swapping models is a config edit. Default lineup is the Gemma-4 family for chat, Qwen2-VL-2B for image captioning, and `nomic-embed-text` for embeddings. The router picks a small or large model per turn based on the prompt.

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

## Where to look

Backend internals: `backend/README.md`. Frontend internals: `frontend/README.md`. Specs and implementation plans live under `docs/specs/` and `docs/plans/`.
