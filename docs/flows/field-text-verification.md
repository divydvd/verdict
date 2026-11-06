# Field text verification

Last verified: 2026-11-06, source and host tests only. Physical verification remains deferred.

## Abstract
Verdict checks the preview field after keyboard input.
Android hierarchy XML can replace emoji with dots.
Field assertions use a platform text read to avoid that loss on Android.

## Purpose
The scenario report states whether the field contains the expected text.
It includes the actual field text, including Unicode and whitespace.

## Entry points
- Scenario `assert` with `text_inserted` or `autocorrect_applied` enters `scenario_engine/runner.py`.
- The assertion registry selects the implementation in `domains/ime/assertions.py`.

## Sequence
1. The runner creates the assertion and passes the run context.
2. The assertion calls `driver.get_text(TEXT_FIELD)`.
3. Android maps the selector through `_ui_object` and calls native `get_text(timeout=0)`.
4. iOS parses its existing XML source. It keeps its empty-field and placeholder rules.
5. The fake driver reads its configured node.
6. `text_inserted` checks substring membership in the actual text.
7. `autocorrect_applied` requires the corrected substring and rejects the original substring when supplied.
8. The runner records the result or error in the timeline. Existing settling and scenario retry rules remain unchanged.

## Key files
| File | Role |
| --- | --- |
| `src/verdict/device_driver/base.py` | Defines the text-read contract |
| `src/verdict/device_driver/android.py` | Reads native Android text and classifies read errors |
| `src/verdict/device_driver/ios_appium.py` | Uses the existing iOS source parser |
| `src/verdict/device_driver/ios_hierarchy.py` | Preserves iOS value and placeholder rules |
| `src/verdict/device_driver/fake.py` | Supplies host-only field state |
| `src/verdict/domains/ime/assertions.py` | Checks actual field text |
| `src/verdict/scenario_engine/runner.py` | Records failures and connection blockers |

## Invariants
- Read text without normalization, trimming, or punctuation substitution.
- Android field assertions never use hierarchy XML as a text fallback.
- A missing field never passes, including when the expected substring is empty.
- An empty field remains empty. iOS labels and placeholders are not inserted text.
- Android RPC failures raise `DriverError`. Connection errors propagate for the runner to report BLOCKED.
- Invalid Android text responses raise `DriverError`, not an empty or matching default.
- Hierarchy evidence remains available and unchanged. It can differ from the native Android field text.
- Preserve historical results. A repaired tool does not turn an older FAIL into a PASS.

## Tests
- `tests/device_driver/test_android_text.py`: lossy XML, exact emoji, combining text, negative results, errors, and scenario reporting.
- `tests/device_driver/test_ios_text.py`: Unicode, placeholders, empty fields, missing fields, and transport errors.
- `tests/domains/ime/test_assertions.py`: fake field reads, substring checks, and autocorrect negatives.
- `tests/device_driver/test_base.py`: protocol composition.
- Physical follow-up: Use synthetic text under a fresh coordinator grant. Check the native read before another full scenario.

## Pitfalls
- **Emoji assertion fails despite correct field text.** Android XML can contain dots before Python parses it. Use the native text read.
- **An empty iOS field appears to contain a prompt.** XCUITest can report a placeholder as its value. Keep the parser's safe empty-field rule.
- **A read failure looks like an assertion mismatch.** Do not substitute defaults or hierarchy text after native errors.

## Conclusion
Host tests cover the tool repair and its platform contracts.
The coordinator must use a fresh device grant for the physical follow-up.
Keep the original failed report and create separate evidence for the corrected tool.
