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
from prompt_manager import MICRO_PROMPTS

BASE_OLLAMA_URL = settings.OLLAMA_URL.strip().rstrip('/')

def condense_chat_memory(old_memory: str, messages: list, model_name: str) -> str:
    """Runs asynchronously to summarize older messages and prevent context window overflow."""
    url = f"{BASE_OLLAMA_URL}/api/generate"
    
    chat_text = "\n".join([f"{m['role'].capitalize()}: {m['content']}" for m in messages if m['role'] in ['user', 'assistant']])
    
    prompt = f"{MICRO_PROMPTS['memory_condenser_system']}\n\n"
    
    if old_memory:
        prompt += f"--- PREVIOUS MEMORY ---\n{old_memory}\n\n"
    prompt += f"--- NEW CHAT HISTORY TO ADD ---\n{chat_text}\n"

    payload = {
        "model": model_name,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 8192}
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
    except Exception as e:
        print(f"Memory Condensation Failed: {e}")
        return old_memory

def get_system_prompt(mode: str, tool_names: str) -> str:
    base_dir = os.path.dirname(__file__)
    prompt_path = os.path.join(base_dir, "prompts", f"{mode}.txt")
    
    try:
        with open(prompt_path, "r") as f:
            content = f.read()
        return content.replace("{tool_names}", tool_names)
    except FileNotFoundError:
        return "You are an AI assistant. Please configure your prompt files."

def stream_chat(messages: list, mode: str = "it_copilot", session_id: str = None, model_name: str = "gemma4:e4b"):
    url = f"{BASE_OLLAMA_URL}/api/chat"
    
    if mode == "it_copilot":
        tool_names = ", ".join(AVAILABLE_TOOLS.keys())
        system_msg = {"role": "system", "content": get_system_prompt(mode, tool_names)}
        tools_payload = TOOL_DEFINITIONS
    else:
        system_msg = {"role": "system", "content": get_system_prompt(mode, "")}
        tools_payload = None 
       
    memory_content = ""
    active_messages =[]
    
    for m in messages:
        if m.get("role") == "memory":
            try:
                mem_data = json.loads(m.get("content"))
                memory_content = mem_data.get("summary", "")
            except:
                memory_content = m.get("content")
        else:
            active_messages.append(m)
            
    recent_messages = active_messages[-10:] if len(active_messages) > 10 else active_messages

    if memory_content:
        system_msg["content"] += f"\n\n[SYSTEM MEMORY LOG: The following is a dense summary of earlier interactions in this session.]\n{memory_content}"

    if recent_messages and recent_messages[-1].get("role") == "user":
        last_query = recent_messages[-1].get("content", "")
        
        has_attachment = "[Attached_File:" in last_query
        clean_user_text = re.sub(r'\[Attached_File:.*?\]', '', last_query).strip()
        
        rag_query = clean_user_text if clean_user_text else "document overview"
        
        db = database.SessionLocal()
        try:
            rag_data = knowledge.retrieve_relevant_chunks(db, query=rag_query, workspace=mode, session_id=session_id)
            
            if rag_data and rag_data.get("context"):
                rag_context = rag_data["context"]
                sources_list = rag_data["sources"]
                
                if has_attachment and len(clean_user_text) < 15:
                    recent_messages[-1]["content"] = f"I have attached a file. Relevant context:\n{rag_context}\n\nMy message: {clean_user_text}\n\n{MICRO_PROMPTS['rag_short_file_upload']}"
                else:
                    recent_messages[-1]["content"] = f"{last_query}\n\n{rag_context}\n\n{MICRO_PROMPTS['rag_standard_injection']}"
                
                if not has_attachment:
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
            
            payload = {"model": model_name, 
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
                    content = MICRO_PROMPTS["fallback_thought_loop"]
                
                if not content.strip():
                    if loop_count > 1:
                        content = MICRO_PROMPTS["fallback_tool_failure"]
                    else:
                        content = MICRO_PROMPTS["fallback_generic"]
                
                words = content.split(" ")
                for i, word in enumerate(words):
                    yield word + (" " if i < len(words) - 1 else "")
                    time.sleep(0.02)
                
                finished_cleanly = True
                break
                
        if not finished_cleanly:
            yield MICRO_PROMPTS["warning_max_loops"]
                
    except Exception as e:
        yield f"\n[Engine Error: {str(e)}]"

def generate_title(prompt: str, model_name: str = "gemma4:e4b") -> str:
    url = f"{BASE_OLLAMA_URL}/api/generate"
    
    clean_prompt = re.sub(r'\[Attached_File:.*?\]', '', prompt).strip()
    if not clean_prompt:
        return MICRO_PROMPTS["title_document_default"]

    system_prompt = f"{MICRO_PROMPTS['title_generator_system']} Message: {clean_prompt}"

    payload = {
        "model": model_name, 
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
        return text if text else MICRO_PROMPTS["title_default"]
    except Exception:
        words = clean_prompt.split()
        return " ".join(words[:3]) + "..." if len(words) > 3 else MICRO_PROMPTS["title_default"]