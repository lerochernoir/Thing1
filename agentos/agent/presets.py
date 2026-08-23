"""The lint/type-error fixer: the narrowest, safest first agent to run.

Unlike a free-form `agentos run "<task>"`, this preset never invents its own
task — it runs your lint/type-check command, turns the failure output
directly into the task, and only seeds the files the linter actually named.
Success is exactly "the same command now exits 0," so there's no ambiguity
about whether the agent did its job.
"""
from __future__ import annotations

import re

from agentos.tools.fs import Workspace

LINT_FIX_SYSTEM_PROMPT = """You are agentos running in lint-fix mode: a narrow, low-risk agent whose \
only job is to make a failing lint/type-check command pass.

Rules:
- Fix only what the linter/type-checker reported. Do not refactor, rename, reorganize imports beyond \
what's needed, or touch any code unrelated to a reported violation.
- Do not edit test files unless the violation was reported inside one.
- Prefer the smallest change that silences the violation correctly. Do not add \
`# noqa` / `# type: ignore` / disable comments to suppress a violation instead of fixing it, unless the \
violation text itself says the check is a false positive.
- If a reported violation is not visible in the files you were given, say so in your plan sentence and \
make no changes to that file.

Respond with a one-sentence plan, then a single unified diff (git-style, `--- a/path` / `+++ b/path` \
headers, ```diff fenced block). If the lint output shows no fixable violations in the given files, \
respond with exactly: DONE
"""

# Matches file references in linter/type-checker output, in either of the
# two common shapes: a line starting with `path/to/file.ext:line:col:...`
# (flake8, eslint's unix formatter, mypy, tsc, `ruff --output-format=concise`)
# or ruff's default `  --> path/to/file.ext:line:col` grouped format.
_PATH_LINE_RE = re.compile(r"(?:^|-->\s*)([^\s:]+\.\w+):\d+(?::\d+)?", re.MULTILINE)


def build_lint_task(lint_output: str) -> str:
    return (
        "The following lint/type-check command failed. Fix the reported violations so it passes.\n\n"
        f"```\n{lint_output}\n```"
    )


def extract_paths_from_output(output: str, workspace: Workspace) -> list[str]:
    """Pull file paths named in linter output that exist in the workspace, deduped, in order seen."""
    seen: dict[str, None] = {}
    for match in _PATH_LINE_RE.finditer(output):
        raw = match.group(1).strip()
        candidate = raw[2:] if raw.startswith("./") else raw
        if workspace.exists(candidate):
            seen.setdefault(candidate, None)
    return list(seen)
