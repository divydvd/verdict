# AGENTS.md

This file gives guidance to coding agents (Copilot, Claude Code, and others) when they work with code in this repository.

## Dev-loop profile
<!-- The dev-loop plugin reads this section. Keep it short and exact. Put only project facts here. Generic rules go in the plugin. -->

### Commands
- Set up once: `python3.12 -m venv .venv && .venv/bin/pip install -e '.[dev]'` (Python 3.11 or later).
- Tests: `.venv/bin/pytest -q`. The tests use `FakeDeviceDriver` and need no phone. Tests marked `requires_device` need a phone. They run only with `--run-device`; do not use that flag without the owner's approval. Without it, `tests/conftest.py` blocks `adb` and `uiautomator2.connect`.
- Lint: `.venv/bin/ruff check .`
- Type check: `.venv/bin/mypy src`

### Test tiers
- Docs only: `git diff --check`. No test run.
- Code under `src/` or `tests/`: the tests, the lint, and the type check above. All three must pass.

### Risky areas
None known.

## Rules
- The working branch is `phase-1/core-execution-substrate` (the default branch). Base each PR on it, or on the PR below it in a stack.
- `~/verdict` is the checkout that SmarType agents run. Do not change its branch.
- The architecture and the module limits: `docs/architecture.md` and `docs/adr/`.
