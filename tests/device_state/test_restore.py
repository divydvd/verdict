import pytest

from tests.device_state.fake_adb import GBOARD, PLAY, TARGET, TARGET_IME, FakePhone
from verdict.core.exceptions import VerdictError
from verdict.device_state.baseline import (
    APP_DATA_TAR,
    PRETEST_APK,
    prepare_private_folder,
    take_baseline,
)
from verdict.device_state.restore import (
    FINAL_APK,
    delete_backups,
    ime_ids,
    load_baseline,
    restore,
)


@pytest.fixture
def folder(tmp_path):
    return prepare_private_folder(tmp_path / "evidence")


def baseline_then_test(folder, phone=None, code=101):
    phone = phone or FakePhone()
    baseline = take_baseline(phone, TARGET, PLAY, folder)
    phone.run_candidate_test(code)
    phone.commands.clear()
    return phone, baseline


def rows(report):
    return {row.item: row for row in report.rows}


def test_fail_puts_back_the_pretest_apk_and_everything_else(folder):
    phone, baseline = baseline_then_test(folder, code=100)
    report = restore(phone, baseline, folder, "FAIL")
    assert report.equal, report.rows
    assert [r for r in report.rows if r.status != "yes"] == []
    assert phone.packages[TARGET] == (100, "2.0-debug+abc1234")
    assert phone.app_files == {"./shared_prefs/a.xml": b"<a/>", "./files/b.db": b"db"}
    assert phone.system["font_scale"] == "1.0" and phone.night == "no"
    assert phone.secure["default_input_method"] == TARGET_IME
    assert ime_ids(phone.secure["enabled_input_methods"]) == {TARGET_IME, GBOARD}
    assert f"run-as {TARGET} rm -f -- ./files/new.db" in phone.commands
    assert not (folder / FINAL_APK).exists()


def test_restore_leaves_the_target_keyboard_until_the_end(folder):
    phone, baseline = baseline_then_test(folder, code=100)
    restore(phone, baseline, folder, "FAIL")
    first_set = next(c for c in phone.commands if c.startswith("ime set"))
    assert first_set == f"ime set {GBOARD}"
    sets = [c for c in phone.commands if c.startswith("ime set")]
    assert sets[-1] == f"ime set {TARGET_IME}"
    extract = next(c for c in phone.commands if c.startswith(f"run-as {TARGET} tar -xf - < "))
    assert phone.commands.index(sets[-1]) > phone.commands.index(extract)
    assert phone.commands.index(sets[-1]) > phone.commands.index("cmd uimode night no")


def test_pass_keeps_the_tested_build_as_an_expected_difference(folder):
    phone, baseline = baseline_then_test(folder)
    report = restore(phone, baseline, folder, "PASS")
    assert report.equal
    assert phone.packages[TARGET] == (101, "candidate-101")
    assert not any(c.startswith("install") for c in phone.commands)
    table = rows(report)
    assert table[f"package {TARGET}"].status == "expected"
    assert table["apk_sha256"].status == "expected"
    assert table["app data"].status == "yes"
    assert "PASS: the tested build stays installed" in report.notes


def test_fail_never_downgrades(folder):
    phone, baseline = baseline_then_test(folder, code=99)
    phone.packages[TARGET] = (100, "x")  # equal code: install -r is allowed
    report = restore(phone, baseline, folder, "BLOCKED")
    assert "install -r pretest.apk" in phone.commands
    assert report.equal

    folder2 = prepare_private_folder(folder.parent / "second")
    phone2, baseline2 = baseline_then_test(folder2)
    phone2.packages[TARGET] = (200, "newer")
    report2 = restore(phone2, baseline2, folder2, "FAIL")
    assert not any(c.startswith("install") for c in phone2.commands)
    assert phone2.packages[TARGET] == (200, "newer")
    assert rows(report2)[f"package {TARGET}"].status == "expected"
    assert report2.equal
    assert any("no downgrade" in note for note in report2.notes)


def test_target_not_installed_before_is_uninstalled_after_fail(folder):
    phone = FakePhone(packages={PLAY: (90, "1.9")})
    phone.secure["default_input_method"] = GBOARD
    baseline = take_baseline(phone, TARGET, PLAY, folder)
    phone.run_candidate_test()
    phone.secure["default_input_method"] = GBOARD
    report = restore(phone, baseline, folder, "FAIL")
    assert f"uninstall {TARGET}" in phone.commands
    assert TARGET not in phone.packages
    assert report.equal, report.rows


def test_target_not_installed_before_stays_after_pass(folder):
    phone = FakePhone(packages={PLAY: (90, "1.9")})
    phone.secure["default_input_method"] = GBOARD
    baseline = take_baseline(phone, TARGET, PLAY, folder)
    phone.run_candidate_test()
    report = restore(phone, baseline, folder, "PASS")
    assert not any(c.startswith("uninstall") for c in phone.commands)
    assert report.equal, report.rows
    assert rows(report)["app data"].status == "expected"


def test_a_difference_that_stays_is_reported_by_name_only(folder):
    phone, baseline = baseline_then_test(folder)
    phone.fail_on = set()
    original = phone.shell

    def stubborn(command):
        if command.startswith("settings put system font_scale"):
            phone.commands.append(command)
            return ""
        return original(command)

    phone.shell = stubborn
    report = restore(phone, baseline, folder, "FAIL")
    assert not report.equal
    row = rows(report)["font_scale"]
    assert (row.baseline, row.final, row.status) == ("1.0", "1.5", "no")
    for item in report.rows:
        assert "<a/>" not in item.baseline + item.final


def test_unsafe_app_data_path_is_never_deleted(folder):
    phone, baseline = baseline_then_test(folder)
    phone.app_files["./files/../../etc"] = b"x"
    with pytest.raises(VerdictError, match="not a plain relative path"):
        restore(phone, baseline, folder, "FAIL")
    assert not any(" rm " in c and ".." in c for c in phone.commands)


def test_load_baseline_checks_the_package(folder):
    with pytest.raises(VerdictError, match="run `verdict baseline` first"):
        load_baseline(folder, TARGET)
    take_baseline(FakePhone(), TARGET, PLAY, folder)
    with pytest.raises(VerdictError, match="is for"):
        load_baseline(folder, "other.app")


def test_delete_backups_keeps_the_baseline_record(folder):
    take_baseline(FakePhone(), TARGET, PLAY, folder)
    delete_backups(folder)
    assert not (folder / PRETEST_APK).exists() and not (folder / APP_DATA_TAR).exists()
    assert (folder / "baseline.json").exists()


def test_ime_ids_strips_subtypes():
    assert ime_ids("a/.X;123;456:b/.Y") == {"a/.X", "b/.Y"}
    assert ime_ids("null") == set()


def test_backup_goes_through_a_private_staging_folder_that_is_deleted(folder):
    phone, baseline = baseline_then_test(folder, code=100)
    restore(phone, baseline, folder, "FAIL")
    mkdir = next(c for c in phone.commands if c.startswith("mkdir -m 700 /data/local/tmp/verdict-restore-"))
    staging = mkdir.split()[-1]
    remote = f"{staging}/app-data.tar"
    order = [
        mkdir,
        f"push app-data.tar {remote}",
        f"chmod 600 {remote}",
        f"run-as {TARGET} tar -xf - < {remote}",
        f"rm -rf -- {staging}",
    ]
    assert [phone.commands.index(c) for c in order] == sorted(phone.commands.index(c) for c in order)
    assert phone.staging == {} and phone.remote_files == {}
    assert not any(c.startswith("shell -T") for c in phone.commands)


def test_staging_folder_is_deleted_when_the_extract_fails(folder):
    phone, baseline = baseline_then_test(folder, code=100)
    phone.fail_on = {"tar -xf"}
    with pytest.raises(Exception, match="scripted failure"):
        restore(phone, baseline, folder, "FAIL")
    assert phone.staging == {} and phone.remote_files == {}


def test_keyboard_start_after_the_check_point_gives_no_false_difference(folder):
    phone, baseline = baseline_then_test(folder, code=100)
    phone.keyboard_start_writes = True
    report = restore(phone, baseline, folder, "FAIL")
    assert report.equal, [r for r in report.rows if r.status == "no"]
    assert rows(report)["app data"].status == "yes"
    # The keyboard did start and write its file, after the app-data read.
    assert "./files/analytics.db" in phone.app_files
    read = max(i for i, c in enumerate(phone.commands) if "sha256sum" in c)
    last_set = max(i for i, c in enumerate(phone.commands) if c == f"ime set {TARGET_IME}")
    assert read < last_set


def test_null_default_keyboard_is_deleted(folder):
    phone = FakePhone()
    del phone.secure["default_input_method"]
    baseline = take_baseline(phone, TARGET, PLAY, folder)
    assert baseline.state.keyboard["default_input_method"] == "null"
    phone.run_candidate_test(100)
    report = restore(phone, baseline, folder, "FAIL")
    assert "default_input_method" not in phone.secure
    assert "settings delete secure default_input_method" in phone.commands
    row = rows(report)["default_input_method"]
    assert (row.baseline, row.final, row.status) == ("null", "null", "yes")


def test_keyboard_subtypes_are_put_back_exactly(folder):
    phone = FakePhone()
    recorded = f"{TARGET_IME};123;456:{GBOARD};789"
    phone.secure["enabled_input_methods"] = recorded
    phone.secure["selected_input_method_subtype"] = "123"
    baseline = take_baseline(phone, TARGET, PLAY, folder)
    phone.run_candidate_test(100)
    phone.secure["selected_input_method_subtype"] = "-1"
    report = restore(phone, baseline, folder, "FAIL")
    assert phone.secure["enabled_input_methods"] == recorded
    assert phone.secure["selected_input_method_subtype"] == "123"
    assert rows(report)["enabled_input_methods"].status == "yes"


def test_compare_shows_a_lost_subtype():
    from verdict.device_state.baseline import DeviceState
    from verdict.device_state.restore import compare

    keyboard = {
        "default_input_method": TARGET_IME,
        "enabled_input_methods": f"{TARGET_IME};123:{GBOARD}",
        "selected_input_method_subtype": "123",
    }
    before = DeviceState(packages={}, keyboard=keyboard, display={})
    after = DeviceState(
        packages={}, keyboard={**keyboard, "enabled_input_methods": f"{TARGET_IME}:{GBOARD}"}, display={}
    )
    row = next(r for r in compare(before, after, set()) if r.item == "enabled_input_methods")
    assert row.status == "no"
