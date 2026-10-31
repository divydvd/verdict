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
- The working branch is `main` (the default branch). Base each PR on it, or on the PR below it in a stack.
- `~/verdict` is the checkout that SmarType agents run. Do not change its branch.
- The architecture and the module limits: `docs/architecture.md` and `docs/adr/`.

## iOS device tests
The owner's Mac has Xcode, Appium 3 with the `xcuitest` driver, and `ffmpeg`. The README section "iOS device tests" gives all the options.
1. Install the iOS extra once: `.venv/bin/pip install -e '.[dev,ios]'`.
2. Start the Appium server as a background process: `appium`. It listens at `http://127.0.0.1:4723`.
3. Check the setup: `.venv/bin/verdict doctor ios --capabilities-file ~/.verdict/ios-capabilities.json`. Exit 0 means ready. The output gives the iPhone UDID. Appium needs a USB cable; an iPhone on Wi-Fi only gives a FAIL.
4. Run a scenario: `.venv/bin/verdict run scenario.yaml --platform ios --device UDID --capabilities-file ~/.verdict/ios-capabilities.json`.
5. After the run, stop Appium. Also stop any `xcodebuild` process for `WebDriverAgent` that is still running.

Notes:
- `~/.verdict/ios-capabilities.json` has the WDA signing capabilities. It is outside the repository. Do not commit its team ID.
- The first run takes about 1 minute, because Appium builds and installs WebDriverAgent on the iPhone.
- The free signing profile expires after 7 days. The next run signs WebDriverAgent again.
- The iPhone must be connected and unlocked. `launch` opens the app in its last state; it does not restart the app.
