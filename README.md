# Verdict

An open-source, extensible agentic mobile testing platform. Executes end-to-end mobile
scenarios, collects evidence, verifies behaviour (deterministically and, where genuinely needed,
via an LLM), and produces reports — exposed through a CLI and an MCP server so AI coding agents
(Claude Code, Codex, Gemini CLI) can drive it directly.

Built first for [SmarType](https://github.com/) (an Android IME), designed to generalize beyond it.

## Status

Architecture v1.0 is frozen — see [`docs/architecture.md`](docs/architecture.md). Implementation
is in progress on `phase-1/core-execution-substrate` per [`docs/implementation-plan.md`](docs/implementation-plan.md).

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — frozen architecture, module boundaries, rationale.
- [`docs/implementation-plan.md`](docs/implementation-plan.md) — phases, milestones, testing strategy.
- [`docs/adr/`](docs/adr/) — architecture decision records.

## Development

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
pytest
```

Device-dependent tests (marked `@requires_device`) are skipped unless you pass `--run-device`.
Without that flag, no test can start `adb` or open a uiautomator2 connection, even when a phone
is attached. Use `--run-device` only when you have the phone.
