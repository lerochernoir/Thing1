#!/usr/bin/env bash
# Run the whole pipeline for one Claude Code session transcript.
#
#   ./build.sh <session.jsonl> [--out DIR] [--no-tag] [--tagged FILE] [--require-tag]
#
# Writes (default DIR = ./out):
#   DIR/<uuid>/extract.json   normalized turns / tool calls / files / skills
#   DIR/<uuid>/graph.rl       this session's Relate store (single file)
#   DIR/<uuid>/tagged.json    layer-2 tags (model output)
#   DIR/<uuid>/graph.json     what the renderer read back out of Relate
#   DIR/<uuid>/graph.svg|png  the picture
#   DIR/global/               the cross-session Relate store (directory; serve it over MCP)
#
# Layer-2 tagging is the only step that sends text off the machine (redacted first).
# --no-tag skips it; --tagged FILE loads an existing tagged.json instead of calling Claude.
# Without credentials the pipeline warns and finishes with layer 1 only, unless --require-tag.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
OUT="out"; TAG=1; TAGGED=""; REQUIRE_TAG=0; SESSION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --out) OUT="$2"; shift 2 ;;
    --no-tag) TAG=0; shift ;;
    --tagged) TAGGED="$2"; shift 2 ;;
    --require-tag) REQUIRE_TAG=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    -*) echo "build.sh: unknown flag $1" >&2; exit 2 ;;
    *) SESSION="$1"; shift ;;
  esac
done
[[ -n "$SESSION" && -f "$SESSION" ]] || { echo "usage: build.sh <session.jsonl> [--out DIR] [--no-tag] [--tagged FILE]" >&2; exit 2; }

"$PY" -c 'import relate, sys; v = relate.__version__; sys.exit(0 if v == "1.3.0" else f"relate-db {v} installed; this pipeline is pinned to 1.3.0 (pip install -r requirements.txt)")'
[[ -d "$HERE/render/node_modules" ]] || (cd "$HERE/render" && npm ci --no-audit --no-fund >/dev/null)

SID="$(basename "$SESSION" .jsonl)"
DIR="$OUT/$SID"; DB="$DIR/graph.rl"; GLOBAL="$OUT/global"
mkdir -p "$DIR"

echo "== 1 extract"
"$PY" "$HERE/extract.py" "$SESSION" -o "$DIR/extract.json"

for STORE in "$DB" "$GLOBAL"; do
  echo "== 2 schema   -> $STORE"
  "$PY" "$HERE/run_cypher.py" --db "$STORE" "$HERE/schema.cypher"
  echo "== 3 layer 1  -> $STORE"
  "$PY" "$HERE/run_cypher.py" --db "$STORE" "$HERE/load.cypher" --params "$DIR/extract.json"
done

echo "== 4 tag"
if [[ -n "$TAGGED" ]]; then
  cp "$TAGGED" "$DIR/tagged.json"
elif [[ $TAG -eq 1 ]]; then
  if ! "$PY" "$HERE/tag.py" "$DIR/extract.json" -o "$DIR/tagged.json"; then
    [[ $REQUIRE_TAG -eq 1 ]] && { echo "tagging failed (--require-tag)" >&2; exit 1; }
    echo "!! tagging failed; continuing with layer 1 only" >&2
    rm -f "$DIR/tagged.json"
  fi
else
  echo "skipped (--no-tag)"
fi

if [[ -f "$DIR/tagged.json" ]]; then
  for STORE in "$DB" "$GLOBAL"; do
    echo "== 5 layer 2  -> $STORE"
    "$PY" "$HERE/run_cypher.py" --db "$STORE" "$HERE/layer2.cypher" --params "$DIR/tagged.json"
  done
fi

echo "== 6 render"
"$PY" "$HERE/query.py" --db "$DB" --session "$SID" -o "$DIR/graph.json"
node "$HERE/render/render.mjs" "$DIR/graph.json" "$DIR/graph.svg" "$DIR/graph.png"
echo "done: $DIR/graph.png"
