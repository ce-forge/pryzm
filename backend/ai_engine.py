import os
import requests
import json
import inspect
import time
from config import settings

from tools import AVAILABLE_TOOLS, TOOL_DEFINITIONS

BASE_OLLAMA_URL = settings.OLLAMA_URL.strip().rstrip('/')
MODEL_NAME = "gemma4:e4b"

def get_system_prompt(mode: str, tool_names: str) -> str:
    """Reads the system prompt from the text files dynamically."""
    base_dir = os.path.dirname(__file__)
    prompt_path = os.path.join(base_dir, "prompts", f"{mode}.txt")
    
    try:
        with open(prompt_path, "r") as f:
            content = f.read()
        return content.replace("{tool_names}", tool_names)
    except FileNotFoundError:
        return "You are an AI assistant. Please configure your prompt files."


def stream_chat(messages: list, mode: str = "it_copilot"):
    url = f"{BASE_OLLAMA_URL}/api/chat"
    
    if mode == "it_copilot":
        tool_names = ", ".join(AVAILABLE_TOOLS.keys())
        system_msg = {"role": "system", "content": get_system_prompt(mode, tool_names)
        }
        tools_payload = TOOL_DEFINITIONS
    else:
        system_msg = {"role": "system", "content": get_system_prompt(mode, "")}
        tools_payload = None 
       
    full_messages =[system_msg] + messages
    
    max_loops = 5
    loop_count = 0
    
    try:
        while loop_count < max_loops:
            loop_count += 1
            
            payload = {"model": MODEL_NAME, 
                       "messages": full_messages, 
                       "stream": False,
                       "option": {"num_ctx": 8192}
                       }
            if tools_payload:
                payload["tools"] = tools_payload
                
            resp = requests.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            message = data.get("message", {})
            
            if message.get("tool_calls"):
                full_messages.append(message) 
                
                for tool in message["tool_calls"]:
                    func_name = tool["function"]["name"]
                    args = tool["function"]["arguments"]
                    
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except:
                            args = {}
                    
                    if func_name in AVAILABLE_TOOLS:
                        func = AVAILABLE_TOOLS[func_name]
                        
                        valid_params = inspect.signature(func).parameters.keys()
                        safe_args = {k: v for k, v in args.items() if k in valid_params}
                        
                        yield f"\n\n> ⚙️ *Executing `{func_name}` on `{safe_args}`...*\n\n"
                        
                        try:
                            result = func(**safe_args)
                        except Exception as tool_err:
                            result = f"Tool execution failed: {str(tool_err)}"
                        
                        yield f"```bash\n{result}\n```\n\n"
                            
                        full_messages.append({
                            "role": "tool", 
                            "content": result,
                            "name": func_name 
                        })
                        
                continue
                
            else:
                content = message.get("content", "")
                
                words = content.split(" ")
                for i, word in enumerate(words):
                    yield word + (" " if i < len(words) - 1 else "")
                    time.sleep(0.02)
                
                break
                
        if loop_count >= max_loops:
            yield "\n\n*[System Warning: Maximum agent loops reached. Execution stopped to prevent infinite loop.]*"
                
    except Exception as e:
        yield f"\n[Engine Error: {str(e)}]"


def generate_title(prompt: str) -> str:
    url = f"{BASE_OLLAMA_URL}/api/generate"
    system_prompt = (
        "You are a title generator. Based on the user message, generate a concise 2 to 4 word title. "
        "Return ONLY the title text. Do not use quotes or punctuation. "
        f"Message: {prompt}"
    )

    payload = {
        "model": MODEL_NAME, 
        "prompt": system_prompt, 
        "stream": False,
        "options": {"num_ctx": 4096}
        }    
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        text = response.json().get("response", "").strip(' \n"\'*.')
        if len(text.split()) > 5:
            words = prompt.split()
            return " ".join(words[:3]) + "..." if len(words) > 3 else prompt
        return text if text else "New Diagnostic"
    except Exception:
        words = prompt.split()
        return " ".join(words[:3]) + "..." if len(words) > 3 else "New Diagnostic"