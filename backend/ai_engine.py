import os
import requests
import json
import inspect
import time
import database
import knowledge
import re
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


def stream_chat(messages: list, mode: str = "it_copilot", session_id: str = None):
    url = f"{BASE_OLLAMA_URL}/api/chat"
    
    if mode == "it_copilot":
        tool_names = ", ".join(AVAILABLE_TOOLS.keys())
        system_msg = {"role": "system", "content": get_system_prompt(mode, tool_names)}
        tools_payload = TOOL_DEFINITIONS
    else:
        system_msg = {"role": "system", "content": get_system_prompt(mode, "")}
        tools_payload = None 
       
    recent_messages = messages[-20:] if len(messages) > 20 else messages

    if recent_messages and recent_messages[-1].get("role") == "user":
        last_query = recent_messages[-1].get("content", "")
        
        has_attachment = "[Attached_File:" in last_query
        clean_user_text = re.sub(r'\[Attached_File:.*?\]', '', last_query).strip()
        
        # Use clean text for the RAG search so hidden tags don't break the vector math
        rag_query = clean_user_text if clean_user_text else "document overview"
        
        db = database.SessionLocal()
        try:
            rag_data = knowledge.retrieve_relevant_chunks(db, query=rag_query, workspace=mode, session_id=session_id)
            
            if rag_data and rag_data.get("context"):
                rag_context = rag_data["context"]
                sources_list = rag_data["sources"]
                
                # Format the prompt carefully based on context length
                if has_attachment and len(clean_user_text) < 15:
                    recent_messages[-1]["content"] = f"I have attached a file. Relevant context:\n{rag_context}\n\nMy message: {clean_user_text}\n\n[System Note: Acknowledge the file reception briefly in 1 sentence. DO NOT summarize the whole file unless asked.]"
                else:
                    recent_messages[-1]["content"] = f"{last_query}\n\n{rag_context}\n\n[System Note: Relevant documentation has been automatically injected above. Use it to answer the prompt directly. DO NOT call additional search tools unless absolutely necessary.]"
                
                # Yield the citation as a Markdown Blockquote so the UI can style it beautifully!
                sources_str = ", ".join(sources_list)
                yield f"> 📚 **Knowledge Base Reference:** `{sources_str}`\n\n"
                
        except Exception as rag_err:
            yield f"> ⚠️ **Knowledge Base Error:** `{str(rag_err)}`\n\n"
        finally:
            db.close()

    full_messages = [system_msg] + recent_messages

    max_loops = 8
    loop_count = 0
    finished_cleanly = False
    
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
                        
                        if "workspace" in valid_params:
                            safe_args["workspace"] = mode
                            
                        if "session_id" in valid_params:
                            safe_args["session_id"] = session_id
                        
                        yield f"\n\n> ⚙️ *Executing `{func_name}` on `{safe_args}`...*\n\n"
                        
                        try:
                            result = func(**safe_args)
                        except Exception as tool_err:
                            result = f"Tool execution failed: {str(tool_err)}"
                        
                        yield f"```text\n{result}\n```\n\n"
                            
                        full_messages.append({
                            "role": "tool", 
                            "content": result,
                            "name": func_name 
                        })
                        
                continue
                
            else:
                content = message.get("content")
                if content is None:
                    content = ""
                
                content = re.sub(r'<[^>]+>', '', content).strip()
                if content.startswith("thought") or "I must wait for the search results" in content:
                    content = "I don't have enough local context to answer that right now. Could you provide more details or upload the relevant documentation?"
                
                if not content.strip():
                    if loop_count > 1:
                        content = "I executed the search tools, but I couldn't find a definitive answer in the results."
                    else:
                        content = "I'm sorry, I don't have enough local context to answer that right now."
                
                words = content.split(" ")
                for i, word in enumerate(words):
                    yield word + (" " if i < len(words) - 1 else "")
                    time.sleep(0.02)
                
                finished_cleanly = True
                break
                
        if not finished_cleanly:
            yield "\n\n*[System Warning: Maximum agent loops reached. Execution stopped to prevent infinite loop.]*"
                
    except Exception as e:
        yield f"\n[Engine Error: {str(e)}]"


def generate_title(prompt: str) -> str:
    url = f"{BASE_OLLAMA_URL}/api/generate"
    
    clean_prompt = re.sub(r'\[Attached_File:.*?\]', '', prompt).strip()
    if not clean_prompt:
        return "Document Analysis"

    system_prompt = (
        "You are a title generator. Based on the user message, generate a concise 2 to 4 word title. "
        "Return ONLY the title text. Do not use quotes or punctuation. "
        f"Message: {clean_prompt}"
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
            words = clean_prompt.split()
            return " ".join(words[:3]) + "..." if len(words) > 3 else clean_prompt
        return text if text else "New Diagnostic"
    except Exception:
        words = clean_prompt.split()
        return " ".join(words[:3]) + "..." if len(words) > 3 else "New Diagnostic"