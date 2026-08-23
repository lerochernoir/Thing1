from .core import Tool

BROKEN_AUTH_TS = "function login(user, pass) {\n  return user.name = pass.match(/.*/);\n}\n"

FAKE_FS = {
    "auth.ts": BROKEN_AUTH_TS,
    "auth.test.ts": "test('login rejects empty password', () => { ... });\n",
}
TESTS_FIXED = {"value": False}


def reset_fs():
    FAKE_FS["auth.ts"] = BROKEN_AUTH_TS
    TESTS_FIXED["value"] = False


def _read(args: dict) -> str:
    path = args["path"]
    return FAKE_FS.get(path, f"ENOENT: {path}")


def _write(args: dict) -> str:
    FAKE_FS[args["path"]] = args["content"]
    if args["path"] == "auth.ts":
        TESTS_FIXED["value"] = True
    return f"wrote {len(args['content'])} bytes to {args['path']}"


def _grep(args: dict) -> str:
    pattern = args["pattern"]
    hits = [p for p, c in FAKE_FS.items() if pattern in c]
    return "\n".join(hits) or "no matches"


def _bash(args: dict) -> str:
    cmd = args["command"]
    if cmd == "npm test":
        if TESTS_FIXED["value"]:
            return "3 passed, 0 failed"
        return "0 passed, 3 failed\n  auth.test.ts: login rejects empty password"
    return f"ran: {cmd}"


def build_tools() -> dict[str, Tool]:
    return {
        "Read": Tool(
            "Read",
            read_only=True,
            fn=_read,
            cost_usd=0.001,
            description="Read the contents of a file at the given path.",
            input_schema={
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path to read"}},
                "required": ["path"],
            },
        ),
        "Grep": Tool(
            "Grep",
            read_only=True,
            fn=_grep,
            cost_usd=0.0005,
            description="Search file contents for a literal substring.",
            input_schema={
                "type": "object",
                "properties": {"pattern": {"type": "string", "description": "Substring to search for"}},
                "required": ["pattern"],
            },
        ),
        "Write": Tool(
            "Write",
            read_only=False,
            fn=_write,
            cost_usd=0.002,
            description="Write content to a file, replacing it if it already exists.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path to write"},
                    "content": {"type": "string", "description": "New file content"},
                },
                "required": ["path", "content"],
            },
        ),
        "Bash": Tool(
            "Bash",
            read_only=False,
            fn=_bash,
            cost_usd=0.003,
            description="Run a shell command.",
            input_schema={
                "type": "object",
                "properties": {"command": {"type": "string", "description": "Shell command to run"}},
                "required": ["command"],
            },
        ),
    }
