"""Configuration for agentos: model endpoints, build command, agent limits."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class Config:
    endpoints: list[str] = field(default_factory=lambda: ["http://127.0.0.1:8000/v1"])
    model: str = "local-model"
    build_cmd: str | None = None
    test_cmd: str | None = None
    max_iterations: int = 8
    max_tokens: int = 4096
    temperature: float = 0.2
    api_key: str = "not-needed"
    workdir: str = "."

    @classmethod
    def load(cls, path: str | None) -> "Config":
        if path and os.path.exists(path):
            with open(path) as f:
                data = yaml.safe_load(f) or {}
            return cls(**{**cls().__dict__, **data})
        return cls()
