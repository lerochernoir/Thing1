SYSTEM_PROMPT = """You are agentos, an autonomous coding agent working directly in a project's \
working directory. You are given a task, the relevant file contents, and (after the first \
iteration) the output of a build/test command.

Respond with a plan of one or two sentences, then a single unified diff (git-style, with \
`--- a/path` / `+++ b/path` headers and `@@` hunks) inside a fenced ```diff block that makes \
the necessary changes. Use `--- /dev/null` for new files. Only touch files relevant to the \
task. Do not include explanations after the diff block.

If the task is already complete and the last build/test output shows success, respond with \
exactly: DONE
"""

TASK_TEMPLATE = """# Task
{task}

# Relevant files
{files_block}
"""

FEEDBACK_TEMPLATE = """# Build/test output (iteration {iteration})
command: {command}
exit code: {returncode}
```
{output}
```

# Current relevant files
{files_block}
"""


def render_files_block(files: dict[str, str]) -> str:
    if not files:
        return "(no files yet)"
    parts = []
    for path, content in files.items():
        parts.append(f"## {path}\n```\n{content}\n```")
    return "\n\n".join(parts)
