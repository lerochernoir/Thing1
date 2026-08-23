from agentos.agent.presets import build_lint_task, extract_paths_from_output
from agentos.tools.fs import Workspace


def _workspace_with(tmp_path, files: dict[str, str]) -> Workspace:
    for rel_path, content in files.items():
        full = tmp_path / rel_path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
    return Workspace(str(tmp_path))


def test_extract_paths_ruff_style(tmp_path):
    ws = _workspace_with(tmp_path, {"pkg/foo.py": "x=1\n", "pkg/bar.py": "y=2\n"})
    output = (
        "pkg/foo.py:3:1: E225 missing whitespace around operator\n"
        "pkg/bar.py:10:5: F401 'os' imported but unused\n"
    )
    assert extract_paths_from_output(output, ws) == ["pkg/foo.py", "pkg/bar.py"]


def test_extract_paths_mypy_style(tmp_path):
    ws = _workspace_with(tmp_path, {"pkg/foo.py": "x: int = 'a'\n"})
    output = 'pkg/foo.py:1: error: Incompatible types in assignment  [assignment]\n'
    assert extract_paths_from_output(output, ws) == ["pkg/foo.py"]


def test_extract_paths_dedupes_and_preserves_order(tmp_path):
    ws = _workspace_with(tmp_path, {"a.py": "1\n", "b.py": "2\n"})
    output = "a.py:1:1: E1\na.py:2:1: E2\nb.py:5:1: E3\n"
    assert extract_paths_from_output(output, ws) == ["a.py", "b.py"]


def test_extract_paths_ignores_files_outside_workspace(tmp_path):
    ws = _workspace_with(tmp_path, {"a.py": "1\n"})
    output = "a.py:1:1: E1\n/etc/passwd:1:1: not a real finding\nghost.py:2:2: F401\n"
    assert extract_paths_from_output(output, ws) == ["a.py"]


def test_extract_paths_ruff_default_arrow_format(tmp_path):
    # ruff's default output groups violations under `  --> path:line:col`
    # rather than leading each line with the path (unlike --output-format=concise).
    ws = _workspace_with(tmp_path, {"bad.py": "import os\nx=1\n"})
    output = (
        "I001 [*] Import block is un-sorted or un-formatted\n"
        " --> bad.py:1:1\n"
        "  |\n"
        "1 | import os\n"
        "  |\n"
        "F401 [*] `os` imported but unused\n"
        " --> bad.py:1:8\n"
    )
    assert extract_paths_from_output(output, ws) == ["bad.py"]


def test_extract_paths_empty_on_no_matches(tmp_path):
    ws = _workspace_with(tmp_path, {"a.py": "1\n"})
    assert extract_paths_from_output("All checks passed!", ws) == []


def test_build_lint_task_includes_raw_output():
    task = build_lint_task("a.py:1:1: E225 missing whitespace")
    assert "E225" in task
    assert "a.py:1:1" in task
