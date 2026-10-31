# ADR-0010: Keyboard selection as an optional driver capability

## Status
Accepted

## Context
SmarType is a keyboard. A SmarType scenario must make the SmarType keyboard the active keyboard
before it types.

- On Android, `adb shell ime set IME_ID` selects an input method. The SmarType runbook runs it
  before each run.
- On iOS, no command selects a keyboard (ADR-0009). The user turns the keyboard on one time in
  Settings > General > Keyboard > Keyboards. Then a long press on the globe key ("Next
  keyboard") shows a list of the keyboards that are on. A tap on a name selects that keyboard.

The SmarType iOS app will be a keyboard extension. Thus each iOS scenario needs a step that
selects the keyboard. The step must also check that the keyboard changed. A tap that does not
select the keyboard must not give a false PASS later in the scenario.

ADR-0007 splits the driver into capability protocols. A future Web or Desktop driver has no
on-screen keyboard to select.

## Decision
- A new optional protocol `KeyboardDriver` in `device_driver/base.py` has one method:
  `select_keyboard(name: str) -> None`. It is not part of the `DeviceDriver` composition. The
  runner checks it with `isinstance`. A driver without it gives a clear `DriverError`.
- The method selects the keyboard and checks it. When the keyboard is not available or does not
  become active, it raises `DriverError` (or `ElementNotFoundError` when the globe key is
  missing).
- **iOS** (`IosAppiumDriver`):
  1. Find the globe key: the system key `Next keyboard`, else `next_keyboard_key` (the name for
     a globe key that a keyboard extension draws itself).
  2. Long press it (`keyboard_press_ms`, 1000 ms) and wait for the list (`InputSwitcherTable`).
  3. Find the cell whose full label or first line is the name. If there is no such cell, close
     the list and fail. The error lists the names in the list.
  4. If the cell has the `Selected` trait, the keyboard is already active. Close the list.
  5. Else tap the cell, then open the list again. The step passes only when the cell of the name
     now has the `Selected` trait. Close the list (tap `PopoverDismissRegion` outside the list).
- **Android** (`AndroidUiautomator2Driver`): `name` is the IME id. The driver checks that the
  input method is on (`ime list -s`), runs `ime set`, and then reads
  `settings get secure default_input_method`. It does not turn on an input method.
- **Scenario step** `select_keyboard`. The `keyboard` field is required. It has a plain form for
  all platforms, or a per-platform form like the per-platform selectors (ADR-0009):

  ```yaml
  - action: select_keyboard
    keyboard: {android: "bha.keys.smartype.debug/bha.keys.smartype.FlorisImeService", ios: "SmarType"}
    selector: {resource_id: "keyboard_view"}
  ```

  The optional `selector` is an element of the selected keyboard. The step waits up to
  `timeout_ms` for it after the switch.

## Consequences
**Positive:**
- One step selects the keyboard on both platforms. A SmarType scenario can run on Android and
  iOS without a platform-specific setup script.
- The driver checks the result from the system state (`Selected` trait, `default_input_method`).
  It does not depend on how the keyboard looks.
- `DeviceDriver` does not change. Future drivers do not have to implement this method.

**Negative:**
- The iOS check opens the list a second time. A switch takes about 2 long presses.
- The iOS method depends on XCUITest names (`Next keyboard`, `InputSwitcherTable`,
  `PopoverDismissRegion`) and the `Selected` trait. These names were read on iOS 26. A future
  iOS version can change them. The errors then say which step failed.
- The names in the iOS list are localized and can have a subtitle ("SmarType, English"). A
  scenario must give the name as the list shows it.
- The name has a different meaning on each platform (IME id on Android, list name on iOS). The
  per-platform form makes this clear.

## Alternatives Considered
- **Tap the globe key until the keyboard changes.** Rejected: a short tap shows the next keyboard
  only. The driver cannot know how many taps it needs, and a loop can go past the keyboard.
- **Add `select_keyboard` to `InputDriver`.** Rejected: ADR-0007 keeps `InputDriver` universal.
  A Web driver has no on-screen keyboard.
- **Check the keyboard with an element of the keyboard only.** Rejected as the only check: a
  system keyboard has no stable element. The step keeps it as an optional extra check.
- **Android: a "not supported" error.** Rejected: `ime set` is simple and gives the same step on
  both platforms.
