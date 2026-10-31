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
3. App data: it pushes the backup to a new mode-700 folder in `/data/local/tmp` that only the
   shell user can read, extracts it with `run-as <package> tar -xf - < <file>` on the phone, and
   deletes the folder. Then it deletes each file that is not in the baseline list, one exact path
   at a time. It reads the app-data checksums before the keyboard step, because the keyboard
   start writes its own files.
4. Settings: display settings, then the enabled keyboards, the default, and the subtype.
5. Check: it reads the state again and prints `| item | baseline | final | equal |`. A kept
   tested build shows `expected`.
6. Exit 0: equal, and the backups are deleted (unless `--keep-backup`). Exit 1: a difference
   stays, and the backups are kept. Exit 2: `BLOCKED: <reason>`.

## iOS device tests

Verdict runs iOS scenarios through an Appium server with the XCUITest driver (see
[ADR-0009](docs/adr/0009-ios-driver-appium-xcuitest.md)). Install the iOS extra first:
`pip install -e '.[ios]'`.

Check that the Mac is ready:

```bash
verdict doctor ios [--device UDID] [--appium-url http://127.0.0.1:4723]
```

- It checks Xcode, `appium`, the `xcuitest` driver, the Appium server, the iPhone or booted
  Simulator, and the iOS extra.
- It prints one line for each check (`OK`, `WARN`, or `FAIL`) and a fix for each problem.
- Exit 0: no required check failed. Exit 2: a required check failed. A server that does not
  answer is only a `WARN`.

Run a scenario on iOS:

```bash
verdict run scenario.yaml --platform ios --device UDID --app bha.keys.smartype=/path/SmarType.app
```

- `--platform` is `android` by default. On iOS, `--device` is the UDID of the iPhone or the
  Simulator.
- `--appium-url` sets the server URL. `--app BUNDLE_ID=PATH` gives the app file for `clear_data`.
  You can give `--app` more than one time.
- `--capability KEY=VALUE` gives one Appium capability. A JSON value (`true`, `8100`) is parsed;
  other values stay text. `--capabilities-file PATH` reads a JSON object. A `--capability` value
  overrides the file value. A real iPhone needs WDA signing, for example:
  `--capability appium:xcodeOrgId=TEAMID --capability "appium:xcodeSigningId=Apple Development"`.
- `--app`, `--capability`, and `--capabilities-file` are usage errors on Android.
- Exit 0: PASSED. Exit 1: FAILED. Exit 2: BLOCKED (the connection failed, or the iOS extra is not
  installed). Exit 3: SKIPPED (the scenario does not support the platform; the reason is printed).
- `verdict baseline` and `verdict restore` are for Android only.

## Development

Requires Python 3.11+.

```bash
pip install -e ".[dev]"
pytest
```

Device-dependent tests (marked `@requires_device`) are skipped unless you pass `--run-device`.
Without that flag, no test can start `adb` or open a uiautomator2 connection, even when a phone
is attached. Use `--run-device` only when you have the phone.
