"""Benchmarking utility for local AI models."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import httpx

from app.tools.registry import ToolRegistry

BENCHMARK_PROMPTS = [
    {
        "name": "Casual conversation",
        "prompt": "Hey Airi, how are you doing today?",
        "needs_tools": False,
    },
    {
        "name": "Simple reasoning",
        "prompt": "If I increase my volume from 30% to 60%, by what percentage did it increase?",
        "needs_tools": False,
    },
    {
        "name": "Tool selection",
        "prompt": "Set my volume to 40%.",
        "needs_tools": True,
    },
    {
        "name": "Multi-step reasoning",
        "prompt": "Take a screenshot and tell me what application is currently visible.",
        "needs_tools": True,
    },
    {
        "name": "Offline awareness",
        "prompt": "Open YouTube and subscribe to ElectroBOOM.",
        "needs_tools": True,
    },
]


async def run_benchmark() -> None:
    """Run benchmarks against all local Ollama models."""
    print("=" * 60)
    print("  Airi Local Model Benchmark")
    print("=" * 60)

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            res = await client.get("http://127.0.0.1:11434/api/tags")
            res.raise_for_status()
            tags = res.json().get("models", [])
    except Exception as e:
        print(f"Error connecting to Ollama: {e}")
        return

    if not tags:
        print("No models found in Ollama.")
        return

    from app.__main__ import _import_all_tools
    _import_all_tools()
    registry = ToolRegistry()
    tools_schema = registry.to_openai_tools()

    print(f"Found {len(tags)} models. Starting benchmark...\n")

    for tag in tags:
        model_name = tag["name"]
        size_gb = tag.get("size", 0) / (1024**3)
        print(f"► Testing Model: {model_name} ({size_gb:.1f} GB)")
        print("-" * 60)

        for bp in BENCHMARK_PROMPTS:
            print(f"  Task: {bp['name']}")
            print(f"  Prompt: \"{bp['prompt']}\"")
            
            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": bp["prompt"]}],
                "stream": False,
                "options": {"temperature": 0.0}
            }
            if bp["needs_tools"]:
                # Use OpenAI compatible endpoint for tools
                url = "http://127.0.0.1:11434/v1/chat/completions"
                payload["tools"] = tools_schema
            else:
                url = "http://127.0.0.1:11434/api/chat"
                
            start_time = time.time()
            ttft = 0.0
            
            try:
                payload["stream"] = True
                async with httpx.AsyncClient(timeout=60.0) as client:
                    async with client.stream("POST", url, json=payload) as r:
                        r.raise_for_status()
                        first_chunk = True
                        content = ""
                        tool_calls = False
                        
                        prompt_tokens = 0
                        completion_tokens = 0
                        eval_duration_s = 0.0
                        
                        async for line in r.aiter_lines():
                            if not line:
                                continue
                                
                            if first_chunk:
                                ttft = time.time() - start_time
                                first_chunk = False
                                
                            if bp["needs_tools"]:
                                # OpenAI compat format: 'data: {...}'
                                if not line.startswith("data: "):
                                    continue
                                data_str = line[6:]
                                if data_str == "[DONE]":
                                    break
                                data = json.loads(data_str)
                                choice = data["choices"][0]
                                delta = choice.get("delta", {})
                                if "content" in delta and delta["content"]:
                                    content += delta["content"]
                                if "tool_calls" in delta:
                                    tool_calls = True
                                # Usage is sometimes sent in the last chunk in OpenAI format
                                if "usage" in data and data["usage"]:
                                    prompt_tokens = data["usage"].get("prompt_tokens", 0)
                                    completion_tokens = data["usage"].get("completion_tokens", 0)
                            else:
                                # Native Ollama format: '{...}'
                                data = json.loads(line)
                                if "message" in data:
                                    content += data["message"].get("content", "")
                                if data.get("done"):
                                    prompt_tokens = data.get("prompt_eval_count", 0)
                                    completion_tokens = data.get("eval_count", 0)
                                    eval_duration_s = data.get("eval_duration", 0) / 1e9
                                    
                        total_time = time.time() - start_time
                        
                        if eval_duration_s > 0 and completion_tokens > 0:
                            tps = completion_tokens / eval_duration_s
                        elif completion_tokens > 0 and total_time > ttft:
                            tps = completion_tokens / (total_time - ttft)
                        else:
                            tps = 0.0
                        
                        res_type = "[TOOL CALLS]" if tool_calls else "[TEXT]"
                        print(f"    Result: {res_type}")
                        if not tool_calls and len(content) > 60:
                            print(f"    Preview: {content[:60]}...")
                        elif not tool_calls:
                            print(f"    Preview: {content}")
                            
                        print(f"    TTFT: {ttft:.2f}s | Total: {total_time:.2f}s")
                        print(f"    Tokens: {prompt_tokens} prompt, {completion_tokens} completion ({tps:.1f} t/s)")
                        print()
                        
            except Exception as e:
                print(f"    Failed: {e}\n")
                continue
                
    print("=" * 60)
    print("  Benchmark complete.")
    print("=" * 60)
