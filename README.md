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

## Key Features
* **Agentic Execution Loop**: Autonomously routes tasks and executes internal IT tools in sequence.
* **Knowledge Base RAG**: Drag-and-drop local documents for automatic vector embedding and context retrieval.
* **Workspace Isolation**: Strict separation between "IT Copilot" and "Personal" workspaces.
