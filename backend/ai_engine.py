# backend/ai_engine.py
import requests
import json
import inspect
import time
from config import settings

from tools import AVAILABLE_TOOLS, TOOL_DEFINITIONS

BASE_OLLAMA_URL = settings.OLLAMA_URL.strip().rstrip('/')
MODEL_NAME = "llama3.1"

def stream_chat(messages: list, mode: str = "it_copilot"):
    url = f"{BASE_OLLAMA_URL}/api/chat"
    
    if mode == "it_copilot":
        tool_names = ", ".join(AVAILABLE_TOOLS.keys())
        system_msg = {
            "role": "system", 
            "content": (
                f"You are DaiNamik Pryzm, an elite IT Copilot. You have access to these tools: {tool_names}. "
                "CRITICAL DIRECTIVES: "
                "1. CASUAL CONVERSATION: If the user asks a general knowledge question (e.g., 'What is an orange?'), answer it normally and conversationally. DO NOT use tools for non-IT questions. "
                "2. FINDING IPs: If you need to find an IP address, ALWAYS use 'dns_lookup'. Do not try to extract IPs from ping results. "
                "3. SEQUENTIAL EXECUTION: If you need an IP address to check a port, run 'dns_lookup' FIRST, wait for the result, and then run 'check_port'. Do not guess IPs (like 192.168.1.1). "
                "4. NO RAW JSON: NEVER output raw JSON in your final conversational response. "
                "5. SUMMARIZE: Always read the tool results carefully and provide a clean, human-readable summary."
            )
        }
        tools_payload = TOOL_DEFINITIONS
    else:
        system_msg = {"role": "system",
                      "content": (
                "You are a helpful assistant. You can answer questions and provide information. "
                "If you don't know the answer, say you don't know. Do not try to make up answers."
            )}
        tools_payload = None 
        
    full_messages =[system_msg] + messages
    
    max_loops = 5
    loop_count = 0
    
    try:
        while loop_count < max_loops:
            loop_count += 1
            
            payload = {"model": MODEL_NAME, "messages": full_messages, "stream": False}
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
    payload = {"model": MODEL_NAME, "prompt": system_prompt, "stream": False}
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