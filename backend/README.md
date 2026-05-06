# Pryzm Backend

The backend is built with FastAPI and Python. It serves as the orchestrator between the PostgreSQL database, the local Ollama LLM, and the Python execution environment.

## Setup Instructions

1. Ensure Ollama is running locally with the required models:
   ```bash
   ollama pull gemma4:e4b
   ollama pull nomic-embed-text
   ```
2. Create and activate a Python virtual environment:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Windows: venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Start the server:
   ```bash
   fastapi dev main.py
   ```

## Core Components

* **`ai_engine.py`**: The core LLM orchestrator. Handles streaming responses, dynamic prompt construction, and the `while` loop that allows the AI to execute multiple tools sequentially before returning a final answer.
* **`knowledge.py`**: Manages the Retrieval-Augmented Generation (RAG) pipeline. Splits text into chunks, generates vector embeddings using `nomic-embed-text`, and queries the pgvector database.
* **`/routers/chat.py`**: Contains the REST API endpoints for session management, folder management, file uploads, and the `/analyze` stream.

## Adding New AI Tools

The AI agent can dynamically execute Python functions. To add a new capability (e.g., Active Directory lookup):
1. Navigate to `/tools`.
2. Write your Python function and decorate it with `@tool` from `tools.registry`.
3. Add Google-style docstrings and type hints. The AI engine parses these automatically to understand how and when to use your tool.
