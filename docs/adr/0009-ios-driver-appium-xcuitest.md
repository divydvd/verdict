# ADR-0009: iOS driver through Appium XCUITest

## Status
Accepted

## Context
The owner wants agents to test the iOS app on a real iPhone, not only on Android. Verdict has
one driver now: `AndroidUiautomator2Driver`. Only `device_driver/` knows the platform
(ADR-0005, ADR-0007). Thus an iOS driver must implement the same `DeviceDriver` composition:
`InputDriver`, `AppLifecycleDriver`, and `DiagnosticsDriver`.

The frozen architecture already selects Appium's XCUITest driver for iOS (architecture §4, §10).
§3.9 accommodates an iOS driver but schedules it for Phase 4. ADR-0002 rejects Appium for
Android only. It does not apply to iOS.

The owner asked to start the iOS driver now. Thus the iOS driver moves ahead of its Phase 4
slot.

## Decision
- The iOS driver is `IosAppiumDriver` in `src/verdict/device_driver/ios_appium.py`.
- It uses Appium's XCUITest driver
  ([appium/appium-xcuitest-driver](https://github.com/appium/appium-xcuitest-driver)). This
  driver contains WebDriverAgent (WDA), the test runner on the iPhone. It also builds and signs
  WDA.
- Verdict sends commands to Appium through the Appium Python client (`appium-python-client`).
- The client is an optional dependency in an `[ios]` extra: `pip install -e '.[ios]'`. Android
  users do not install it.
- Verdict does not include a custom WDA client.
- The iOS driver is a current track. It does not wait for Phase 2 and Phase 3.

**Selector mapping.** The `Selector` model does not change. The iOS driver maps its fields to
XCUITest attributes:

| Selector field | iOS attribute |
|---|---|
| `resource_id` | `name` (accessibility identifier) |
| `text` | `label`, then `value` |
| `description` | `label` |
| `class_name` | `type` (for example `XCUIElementTypeButton`) |

Element ids can be different on each platform. Thus a scenario step can give one selector for
each platform:

```yaml
- action: tap
  selector:
    android: { resource_id: "com.app:id/send" }
    ios: { resource_id: "sendButton" }
```

## Consequences
**Positive:**
- Verdict reuses a maintained, widely used project for iOS UI automation. It does not write
  its own iPhone control layer.
- The decision agrees with the frozen architecture (§4, §10). ADR-0002 stays valid.
- The scenario engine, assertions, evidence, and reports do not change (ADR-0005).
- Android users get no new dependency, because the Appium client is an optional extra.

**Negative (known limits on iOS):**
- **No per-app data backup.** iOS does not let a tool back up the data of one app without a
  jailbreak. Thus `baseline` and `restore` stay Android-only.
- **No back key.** iOS has no back key. `press_key(BACK)` gives an error. Scenarios must tap the
  app's own back button.
- **Keyboard selection.** iOS has no command to select a keyboard. A test must tap the globe key
  until the correct keyboard shows.
- **Secure fields.** iOS does not show custom keyboards in password fields.
- **`clear_data`.** iOS has no clear-data command. The driver uninstalls the app and then
  installs it again.
- **`collect_bugreport`.** iOS has no equivalent. The method returns `None`, as ADR-0007
  permits.
- **Signing.** WDA must be signed. With a free Apple ID, the signing expires every 7 days.
- **Two technologies.** Android uses `uiautomator2` and iOS uses Appium. ADR-0002 already
  accepts this cost.
- **Speed.** WDA is slower than uiautomator2. Timeouts can need larger values on iOS.

## Alternatives Considered
- **facebook-wda** (a Python WDA client). Rejected: its maintenance is sporadic, and it does not
  build or sign WDA.
- **A custom WDA client.** Rejected: Verdict would have to build, sign, start, and maintain WDA.
  Appium's XCUITest driver already does this work.
- **go-ios / pymobiledevice3.** Rejected for UI automation: these tools manage devices (list,
  install, logs). They do not find or operate UI elements. `pymobiledevice3` stays an optional
  tool for diagnostics.
