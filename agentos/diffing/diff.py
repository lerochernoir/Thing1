"""Deterministic unified-diff parsing and application.

Parses standard `diff -u` / git-style unified diff text and applies it to
in-memory file contents without shelling out to `patch`. Context lines are
matched exactly, with a small fuzzy fallback (search a window around the
expected offset) so patches survive minor upstream drift.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HEADER_PREFIXES = ("---", "+++", "diff ", "index ", "new file", "deleted file")


class PatchError(Exception):
    pass


@dataclass
class Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str] = field(default_factory=list)  # includes leading ' ', '+', '-'


@dataclass
class FilePatch:
    old_path: str | None
    new_path: str | None
    hunks: list[Hunk] = field(default_factory=list)
    is_new_file: bool = False
    is_deleted_file: bool = False


def parse_unified_diff(text: str) -> list[FilePatch]:
    lines = text.splitlines()
    patches: list[FilePatch] = []
    i = 0
    n = len(lines)

    def strip_prefix(path: str) -> str:
        path = path.strip()
        if path in ("/dev/null",):
            return path
        for prefix in ("a/", "b/"):
            if path.startswith(prefix):
                return path[len(prefix):]
        return path

    while i < n:
        line = lines[i]
        if line.startswith("--- "):
            old_path = strip_prefix(line[4:].split("\t")[0])
            i += 1
            if i >= n or not lines[i].startswith("+++ "):
                raise PatchError(f"expected '+++' after '---' at line {i}")
            new_path = strip_prefix(lines[i][4:].split("\t")[0])
            i += 1

            patch = FilePatch(
                old_path=None if old_path == "/dev/null" else old_path,
                new_path=None if new_path == "/dev/null" else new_path,
                is_new_file=old_path == "/dev/null",
                is_deleted_file=new_path == "/dev/null",
            )

            while i < n and lines[i].startswith("@@"):
                hunk, i = _parse_hunk(lines, i)
                patch.hunks.append(hunk)

            patches.append(patch)
            continue
        i += 1

    if not patches:
        raise PatchError("no valid '--- '/'+++ ' file headers found in diff")
    return patches


def _parse_hunk(lines: list[str], i: int) -> tuple[Hunk, int]:
    header = lines[i]
    body = header[2:].split("@@")[0].strip()
    old_part, new_part = body.split(" ")
    old_start, old_count = _parse_range(old_part)
    new_start, new_count = _parse_range(new_part)
    hunk = Hunk(old_start=old_start, old_count=old_count, new_start=new_start, new_count=new_count)
    i += 1
    while i < len(lines):
        l = lines[i]
        if l.startswith("@@") or l.startswith("--- ") or (l.startswith("diff ")):
            break
        if l.startswith(("+", "-", " ")):
            hunk.lines.append(l)
            i += 1
        elif l == r"\ No newline at end of file":
            i += 1
        else:
            break
    return hunk, i


def _parse_range(part: str) -> tuple[int, int]:
    sign = part[0]
    assert sign in "+-"
    body = part[1:]
    if "," in body:
        start_s, count_s = body.split(",")
        return int(start_s), int(count_s)
    return int(body), 1


def apply_patch(original: str, patch: FilePatch, *, fuzz: int = 3) -> str:
    """Apply a single FilePatch to `original` text, returning the new text."""
    if patch.is_new_file:
        src_lines: list[str] = []
    else:
        src_lines = original.splitlines()

    out: list[str] = []
    cursor = 0  # 0-based index into src_lines already emitted

    for hunk in patch.hunks:
        target = max(hunk.old_start - 1, 0) if hunk.old_count else hunk.old_start
        start = _locate_hunk(src_lines, hunk, cursor, fuzz)
        out.extend(src_lines[cursor:start])
        cursor = start

        for hline in hunk.lines:
            tag, content = hline[0], hline[1:]
            if tag == " ":
                if cursor >= len(src_lines) or src_lines[cursor] != content:
                    raise PatchError(
                        f"context mismatch applying hunk near old line {hunk.old_start}: "
                        f"expected {content!r}, got {src_lines[cursor] if cursor < len(src_lines) else '<eof>'!r}"
                    )
                out.append(content)
                cursor += 1
            elif tag == "-":
                if cursor >= len(src_lines) or src_lines[cursor] != content:
                    raise PatchError(
                        f"deletion mismatch applying hunk near old line {hunk.old_start}: "
                        f"expected {content!r}, got {src_lines[cursor] if cursor < len(src_lines) else '<eof>'!r}"
                    )
                cursor += 1
            elif tag == "+":
                out.append(content)
            else:
                raise PatchError(f"unrecognized diff line: {hline!r}")

    out.extend(src_lines[cursor:])
    text = "\n".join(out)
    if original.endswith("\n") or (not original and patch.is_new_file):
        text += "\n"
    return text


def _locate_hunk(src_lines: list[str], hunk: Hunk, cursor: int, fuzz: int) -> int:
    """Find the 0-based start offset for this hunk, tolerating small drift."""
    expected = max(hunk.old_start - 1, 0)
    first_context = next((l[1:] for l in hunk.lines if l[0] in " -"), None)

    if first_context is None:
        return max(expected, cursor)

    if expected < len(src_lines) and src_lines[expected] == first_context and expected >= cursor:
        return expected

    for offset in range(1, fuzz + 1):
        for candidate in (expected + offset, expected - offset):
            if cursor <= candidate < len(src_lines) and src_lines[candidate] == first_context:
                return candidate

    for idx in range(max(cursor, 0), len(src_lines)):
        if src_lines[idx] == first_context:
            return idx

    raise PatchError(f"could not locate hunk context {first_context!r} (expected near line {hunk.old_start})")


def apply_unified_diff(files: dict[str, str], diff_text: str) -> dict[str, str]:
    """Apply a multi-file unified diff to a dict of {path: contents}.

    Returns a new dict with updated/added paths; deleted files are removed.
    Does not mutate the input dict.
    """
    result = dict(files)
    for patch in parse_unified_diff(diff_text):
        path = patch.new_path if patch.new_path is not None else patch.old_path
        if patch.is_deleted_file:
            if patch.old_path in result:
                del result[patch.old_path]
            continue
        original = result.get(patch.old_path, "") if patch.old_path else ""
        result[path] = apply_patch(original, patch)
    return result
