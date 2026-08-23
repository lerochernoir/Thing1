import pytest

from agentos.diffing.diff import PatchError, apply_unified_diff, parse_unified_diff


def test_parse_simple_diff():
    diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,3 +1,3 @@
 def add(a, b):
-    return a - b
+    return a + b

"""
    patches = parse_unified_diff(diff)
    assert len(patches) == 1
    assert patches[0].old_path == "foo.py"
    assert patches[0].new_path == "foo.py"
    assert len(patches[0].hunks) == 1


def test_apply_modifies_existing_file():
    original = {"foo.py": "def add(a, b):\n    return a - b\n"}
    diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
    updated = apply_unified_diff(original, diff)
    assert updated["foo.py"] == "def add(a, b):\n    return a + b\n"


def test_apply_creates_new_file():
    diff = """\
--- /dev/null
+++ b/bar.py
@@ -0,0 +1,2 @@
+def hello():
+    return "hi"
"""
    updated = apply_unified_diff({}, diff)
    assert updated["bar.py"] == 'def hello():\n    return "hi"\n'


def test_apply_deletes_file():
    original = {"bar.py": "x = 1\n"}
    diff = """\
--- a/bar.py
+++ /dev/null
@@ -1,1 +0,0 @@
-x = 1
"""
    updated = apply_unified_diff(original, diff)
    assert "bar.py" not in updated


def test_apply_multi_file_diff():
    original = {"a.py": "a = 1\n", "b.py": "b = 1\n"}
    diff = """\
--- a/a.py
+++ b/a.py
@@ -1,1 +1,1 @@
-a = 1
+a = 2
--- a/b.py
+++ b/b.py
@@ -1,1 +1,1 @@
-b = 1
+b = 2
"""
    updated = apply_unified_diff(original, diff)
    assert updated["a.py"] == "a = 2\n"
    assert updated["b.py"] == "b = 2\n"


def test_context_mismatch_raises_patch_error():
    original = {"foo.py": "x = 1\n"}
    diff = """\
--- a/foo.py
+++ b/foo.py
@@ -1,1 +1,1 @@
-y = 1
+y = 2
"""
    with pytest.raises(PatchError):
        apply_unified_diff(original, diff)


def test_apply_tolerates_shifted_context():
    original = {"foo.py": "# header\n# extra line\ndef add(a, b):\n    return a - b\n"}
    diff = """\
--- a/foo.py
+++ b/foo.py
@@ -2,2 +2,2 @@
 def add(a, b):
-    return a - b
+    return a + b
"""
    updated = apply_unified_diff(original, diff)
    assert "return a + b" in updated["foo.py"]
