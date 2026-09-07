import os
import time
import json
import logging
from dataclasses import dataclass, field
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

from app.engineering_tools import TOOL_SCHEMAS, execute_tool_call

load_dotenv()

logger = logging.getLogger("aegis_prime.router")
logger.setLevel(logging.INFO)
if not logger.handlers:
    ch = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    ch.setFormatter(formatter)
    logger.addHandler(ch)

@dataclass
class KeyPool:
    keys: list[str]
    _index: int = field(default=0, init=False)
    _cooldowns: dict = field(default_factory=dict, init=False)

    def get_key_info(self) -> tuple[str, int]:
        n = len(self.keys)
        if n == 0:
            raise RuntimeError("No keys configured for this provider")
        for _ in range(n):
            idx = self._index % n
            key = self.keys[idx]
            self._index += 1
            if self._cooldowns.get(key, 0) < time.time():
                return key, idx
        raise RuntimeError("All keys in this pool are cooling down")

    def mark_failed(self, key: str, cooldown_seconds: int = 60):
        self._cooldowns[key] = time.time() + cooldown_seconds

def _keys_from_env(prefix: str, count: int) -> list[str]:
    keys = []
    for i in range(1, count + 1):
        val = os.getenv(f"{prefix}_{i}")
        if val:
            keys.append(val)
    single = os.getenv(prefix)
    if single:
        keys.append(single)
    return keys

PROVIDERS = {
    "nvidia": {
        "base_url": "https://integrate.api.nvidia.com/v1",
        "keys": _keys_from_env("NVIDIA_KEY", 3),
        "default_model": "meta/llama-3.1-405b-instruct",
        "supports_tools": True,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "keys": _keys_from_env("OPENROUTER_KEY", 3),
        "default_model": "anthropic/claude-3.5-sonnet",
        "supports_tools": True,
    },
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "keys": _keys_from_env("GEMINI_KEY", 2),
        "default_model": "gemini-2.0-flash",
        "supports_tools": True,
    },
}

class AIRouter:
    def __init__(self, providers: dict = PROVIDERS):
        self.providers = providers
        self.pools = {name: KeyPool(cfg["keys"]) for name, cfg in providers.items()}

    def generate_with_fallback(self, prompt: str, chain: list[tuple[str, str]],
                                system_prompt: str | None = None) -> tuple[str, str, str]:
        last_error = None
        for provider, model in chain:
            try:
                cfg = self.providers[provider]
                pool = self.pools[provider]
                key, key_idx = pool.get_key_info()
                client = OpenAI(api_key=key, base_url=cfg["base_url"])
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})

                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    max_tokens=1000,
                )
                return resp.choices[0].message.content, provider, model
            except Exception as e:
                last_error = e
                continue
        raise RuntimeError(f"All providers in fallback chain failed: {last_error}")

    def generate_with_tools_fallback(self, prompt: str, chain: list[tuple[str, str]],
                                      system_prompt: str | None = None) -> dict:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        last_error = None
        for provider, model in chain:
            if not self.providers[provider].get("supports_tools", False):
                continue
            try:
                cfg = self.providers[provider]
                pool = self.pools[provider]
                key, _ = pool.get_key_info()
                client = OpenAI(api_key=key, base_url=cfg["base_url"])
                
                tool_trace = []
                resp = client.chat.completions.create(
                    model=model,
                    messages=messages,
                    tools=TOOL_SCHEMAS,
                    max_tokens=1500,
                )
                choice = resp.choices[0]
                message = choice.message

                if message.tool_calls:
                    for tc in message.tool_calls:
                        result = execute_tool_call(tc.function.name, tc.function.arguments)
                        tool_trace.append({"tool": tc.function.name, "arguments": tc.function.arguments, "result": result})

                return {
                    "response": message.content or "Executed tool routines successfully.",
                    "provider": provider,
                    "model": model,
                    "tool_calls": tool_trace,
                }
            except Exception as e:
                last_error = e
                continue

        raise RuntimeError(f"All tool-capable providers failed: {last_error}")

AEGIS_PRIME_CHAIN = [
    ("nvidia", "meta/llama-3.1-405b-instruct"),
    ("openrouter", "anthropic/claude-3.5-sonnet"),
    ("gemini", "gemini-2.0-flash")
]
