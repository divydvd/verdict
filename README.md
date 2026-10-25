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

## Device-test baseline

`verdict baseline` records a phone's state before a device test of one Android package. It
replaces the manual adb steps of a pretest baseline (for example, step 3 of SmarType's
`smartype-device-test` skill).

```bash
verdict baseline bha.keys.smartype.debug --packages-prefix bha.keys.smartype --dir "$EVIDENCE"
```

- It requires exactly one unlocked physical phone, user 0, and a private `--dir` (mode 700,
  outside any git work tree, with no old `baseline.json`).
- It records the package versions, the pretest APK (pulled, with its SHA-256), the keyboard and
  display settings, and an app-data tar with per-file checksums (by `run-as`, so a debuggable app).
- If the package is the default keyboard, it selects another keyboard that is not in the package
  family, so the keyboard does not run during the backup.
- Exit 0: saved. Exit 2: `BLOCKED: <reason>`. The phone is unchanged, or its keyboard is set back.
- It prints names, versions, settings, and counts. It never prints app data.

After the test, `verdict restore` puts the phone back (step 7 of the same skill):

```bash
verdict restore bha.keys.smartype.debug --dir "$EVIDENCE" --result PASS|FAIL|BLOCKED [--keep-backup]
```

1. Keyboard: it selects the baseline keyboard. If that is the package, it selects another
   keyboard until the end.
2. APK: after PASS, the tested build stays installed. After FAIL or BLOCKED, it installs the
   pretest APK again, but never as a downgrade. A package that was not installed at baseline
   is uninstalled after FAIL or BLOCKED (the only uninstall).
3. App data: it extracts the backup, then deletes each file that is not in the baseline list,
   one exact path at a time.
4. Settings: display settings, then the enabled keyboards, the default, and the subtype.
5. Check: it reads the state again and prints `| item | baseline | final | equal |`. A kept
   tested build shows `expected`.
6. Exit 0: equal, and the backups are deleted (unless `--keep-backup`). Exit 1: a difference
   stays, and the backups are kept. Exit 2: `BLOCKED: <reason>`.

## Development

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
pytest
```

Device-dependent tests (marked `@requires_device`) are skipped unless you pass `--run-device`.
Without that flag, no test can start `adb` or open a uiautomator2 connection, even when a phone
is attached. Use `--run-device` only when you have the phone.
