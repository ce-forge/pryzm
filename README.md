# DaiNamik Pryzm

DaiNamik Pryzm is a locally hosted, highly customizable AI Copilot designed for IT management. It provides a secure environment for IT managers to process client information, execute automated network diagnostics, and query internal documentation using an agentic LLM workflow.

## Architecture Overview
The application is split into two main components:
* **/backend**: A FastAPI application powering the agentic loop, database connections (PostgreSQL/pgvector), and RAG vector search.
* **/frontend**: A Next.js/React application handling the UI, chat streaming state, and dynamic markdown rendering.

## Quick Start

1. Start the database infrastructure:
   ```bash
   docker-compose up -d
   ```
2. Start the Backend API (see `/backend/README.md` for details):
   ```bash
   cd backend
   fastapi dev main.py
   ```
3. Start the Frontend UI (see `/frontend/README.md` for details):
   ```bash
   cd frontend
   npm run dev
   ```

## Changing the AI Model
By default, Pryzm uses `gemma4:e4b` via Ollama, but it is **fully compatible with any Ollama model** (e.g., `llama3`, `mistral`, `qwen`). 

To change the active model, simply open `backend/ai_engine.py` and update the `MODEL_NAME` variable at the top of the file:
```python
# backend/ai_engine.py
MODEL_NAME = "llama3" # Change this to your preferred local model
```
*Ensure you have run `ollama pull <model-name>` on your host machine before starting the backend.*

## Key Features
* **Agentic Execution Loop**: Autonomously routes tasks and executes internal IT tools in sequence.
* **Knowledge Base RAG**: Drag-and-drop local documents for automatic vector embedding and context retrieval.
* **Dynamic Prompt Management**: Micro-prompts and failsafes are managed via a JSON template system for easy customization.
* **Workspace Isolation**: Strict separation between "IT Copilot" and "Personal" workspaces.
