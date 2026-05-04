import requests
from config import settings

def analyze_chat(messages: list) -> str:
    """
    Sends the rolling conversation history to the local model.
    """
    url = f"{settings.OLLAMA_URL.rstrip('/')}/api/chat"

    payload = {
        "model": "gemma",
        "messages": messages,
        "stream": False
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data.get("message", {}).get("content", "Error: Empty response from engine.")
    except Exception as e:
        return f"Inference Engine Failure: {str(e)}"