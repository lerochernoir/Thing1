"""Secret redaction applied before any text leaves the machine (layer-2 tagging)
and to tool-input summaries stored in the graph."""
from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S)),
    ("ANTHROPIC_KEY", re.compile(r"sk-ant-[A-Za-z0-9_-]{10,}")),
    ("OPENAI_KEY", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("GITHUB_TOKEN", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("AWS_KEY", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("SLACK_TOKEN", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("GOOGLE_KEY", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}")),
    ("BEARER", re.compile(r"(?i)\b(bearer|token)\s+[A-Za-z0-9._~+/-]{20,}=*")),
    ("ASSIGNED_SECRET", re.compile(
        r"(?i)\b([A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|ACCESS_KEY)[A-Z0-9_]*)"
        r"(\s*[=:]\s*)(['\"]?)[^\s'\"]{6,}\3")),
    ("URL_CREDENTIALS", re.compile(r"(\w+://)[^/\s:@]+:[^/\s@]+@")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
]


def redact(text: str) -> str:
    if not text:
        return text
    for label, pat in _PATTERNS:
        if label == "ASSIGNED_SECRET":
            text = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED:{label}]", text)
        elif label == "URL_CREDENTIALS":
            text = pat.sub(lambda m: f"{m.group(1)}[REDACTED:{label}]@", text)
        else:
            text = pat.sub(f"[REDACTED:{label}]", text)
    return text
