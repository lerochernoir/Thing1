# agentos

A terminal-based coding agent driven by local, multi-GPU LLM inference —
edit → build → verify, on your own hardware.

Point it at one or more OpenAI-compatible inference servers (e.g. one
[vLLM](https://github.com/vllm-project/vllm) or `llama.cpp` server per GPU),
give it a task, and it will:

1. read the relevant files in your project,
2. ask the model for a plan and a unified diff,
3. apply the diff with a deterministic patcher (no shelling out to `patch`),
4. run your build/test command and feed the output back,
5. repeat until the build passes, the model reports `DONE`, or it hits the
   iteration limit,

all while a live terminal UI shows per-GPU utilization, memory, temperature,
and aggregate tokens/sec across replicas.

## Install

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

## Configure

Copy `agentos.example.yaml` to `agentos.yaml` and point `endpoints` at your
running inference server(s) — one entry per GPU replica if you're serving
the same model on multiple ports for throughput:

```yaml
endpoints:
  - http://127.0.0.1:8000/v1
  - http://127.0.0.1:8001/v1
model: local-model
build_cmd: "pytest -q"
```

## Run

```bash
agentos run "add input validation to the login handler" --workdir /path/to/project
```

Use `--no-tui` for plain log output (useful in CI or when piping).

Check GPU status on its own:

```bash
agentos gpus
```

## Layout

```
agentos/
  cli.py            entry point (click)
  config.py         YAML config loading
  llm/client.py     OpenAI-compatible client, round-robins across replicas
  diffing/diff.py   deterministic unified-diff parser/applier
  tools/fs.py        sandboxed file read/write within the workdir
  tools/shell.py     build/test command execution
  gpu/monitor.py     nvidia-smi based per-GPU stats
  agent/loop.py      the edit -> build -> verify orchestration
  agent/prompts.py   system/task prompt templates
  ui/tui.py          Rich live TUI (log panel + GPU panel)
```

## Tests

```bash
pytest -q
```
