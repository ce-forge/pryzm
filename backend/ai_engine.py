import requests
import json
from config import settings

def analyze_chat(messages: list) -> str:
    """Standard fallback inference (non-streaming)"""
    url = f"{settings.OLLAMA_URL.rstrip('/')}/api/chat"
    payload = {"model": "gemma", "messages": messages, "stream": False}
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        return response.json().get("message", {}).get("content", "Error")
    except Exception as e:
        return f"Failure: {str(e)}"

def stream_chat(messages: list, mode: str = "it_copilot"):
    """Streams the LLM response word-by-word with dynamic system prompts."""
    # FIX: rstrip('/') prevents the double // bug!
    url = f"{settings.OLLAMA_URL.rstrip('/')}/api/chat"
    
    if mode == "it_copilot":
        system_msg = {"role": "system", "content": "You are DaiNamik Pryzm, an elite IT MSP Copilot. You provide concise, highly technical answers for IT professionals and system administrators."}
    else:
        system_msg = {"role": "system", "content": "You are a helpful, creative, and friendly personal AI assistant. You provide thoughtful and engaging answers."}
    
    full_messages =[system_msg] + messages
    payload = {"model": "gemma", "messages": full_messages, "stream": True}
    
    try:
        with requests.post(url, json=payload, stream=True) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    data = json.loads(line)
                    yield data.get("message", {}).get("content", "")
    except Exception as e:
        yield f"\n[Engine Error: {str(e)}]"

def generate_title(prompt: str) -> str:
    """Generates a concise summary to name the chat, with fallback safety."""
    url = f"{settings.OLLAMA_URL.rstrip('/')}/api/generate"
    
    system_prompt = (
        "You are a title generator. Based on the following user message, "
        "generate a concise 2 to 4 word title. "
        "Return ONLY the title text. Do not use quotes, punctuation, or explain yourself. "
        f"Message: {prompt}"
    )
    
    payload = {
        "model": "gemma",
        "prompt": system_prompt,
        "stream": False
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        text = response.json().get("response", "").strip(' \n"\'*.')
        
        bad_phrases =["does not", "irrelevant", "cannot", "i am", "unable"]
        if len(text.split()) > 5 or any(bad in text.lower() for bad in bad_phrases):
            words = prompt.split()
            return " ".join(words[:3]) + "..." if len(words) > 3 else prompt
            
        return text if text else "New Diagnostic"
    except Exception:
        words = prompt.split()
        return " ".join(words[:3]) + "..." if len(words) > 3 else "New Diagnostic"