"""OpenAI-compatible chat client with round-robin across local inference replicas.

Local servers such as vLLM or llama.cpp's server expose an OpenAI-compatible
`/chat/completions` endpoint. Running one replica per GPU (e.g. ports
8000-8003) and round-robining requests across them lets a single agent
saturate all GPUs, the same pattern shown by tools like Proofline.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field

import httpx


@dataclass
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wall_seconds: float = 0.0
    endpoint: str = ""

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def tokens_per_sec(self) -> float:
        return self.completion_tokens / self.wall_seconds if self.wall_seconds > 0 else 0.0


@dataclass
class ChatResult:
    content: str
    usage: Usage


class LLMClient:
    """Round-robin OpenAI-compatible chat client over one or more endpoints."""

    def __init__(
        self,
        endpoints: list[str],
        model: str,
        api_key: str = "not-needed",
        timeout: float = 120.0,
    ):
        if not endpoints:
            raise ValueError("at least one endpoint is required")
        self.endpoints = list(endpoints)
        self.model = model
        self._cycle = itertools.cycle(self.endpoints)
        self._client = httpx.Client(
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self.history: list[Usage] = []

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "LLMClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def chat(
        self,
        messages: list[dict],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
        endpoint: str | None = None,
    ) -> ChatResult:
        target = endpoint or next(self._cycle)
        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        start = time.monotonic()
        resp = self._client.post(f"{target.rstrip('/')}/chat/completions", json=payload)
        elapsed = time.monotonic() - start
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"]
        raw_usage = data.get("usage", {})
        usage = Usage(
            prompt_tokens=raw_usage.get("prompt_tokens", 0),
            completion_tokens=raw_usage.get("completion_tokens", 0),
            wall_seconds=elapsed,
            endpoint=target,
        )
        self.history.append(usage)
        return ChatResult(content=content, usage=usage)

    def aggregate_tokens_per_sec(self, window: int = 20) -> float:
        """Approximate combined throughput across replicas over the last N calls.

        Calls to different endpoints overlap in wall-clock time in practice (the
        agent loop issues them concurrently in the future); here we sum
        completion tokens over the window and divide by the max wall time seen,
        which is a reasonable aggregate estimate for sequential calls too.
        """
        recent = self.history[-window:]
        if not recent:
            return 0.0
        total_tokens = sum(u.completion_tokens for u in recent)
        total_time = max((u.wall_seconds for u in recent), default=0.0)
        return total_tokens / total_time if total_time > 0 else 0.0
