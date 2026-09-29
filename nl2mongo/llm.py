"""One OpenAI-compatible chat client for every model.

llama.cpp's llama-server and the hosted APIs (OpenAI, Anthropic's OpenAI-compatible
endpoint, Gemini, Groq, OpenRouter) all speak /v1/chat/completions, so switching
model is a --base-url and --model change, not a code change.
"""
import os
import time
from dataclasses import dataclass

from openai import OpenAI


@dataclass
class Usage:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0


class LLM:
    def __init__(self, model, base_url, api_key_env=None, max_tokens=1024):
        key = os.environ.get(api_key_env, "") if api_key_env else ""
        self.client = OpenAI(base_url=base_url, api_key=key or "none", timeout=300, max_retries=2)
        self.model = model
        self.max_tokens = max_tokens

    def chat(self, messages, usage, tools=None):
        kwargs = dict(model=self.model, messages=messages, temperature=0, max_tokens=self.max_tokens)
        if tools:
            kwargs["tools"] = tools
        t0 = time.perf_counter()
        resp = self.client.chat.completions.create(**kwargs)
        usage.seconds += time.perf_counter() - t0
        usage.calls += 1
        if resp.usage:
            usage.prompt_tokens += resp.usage.prompt_tokens or 0
            usage.completion_tokens += resp.usage.completion_tokens or 0
        return resp.choices[0].message
