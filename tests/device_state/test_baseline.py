import json
import stat

import pytest

from tests.device_state.fake_adb import GBOARD, PLAY, SAMSUNG, TARGET, TARGET_IME, FakePhone
from verdict.core.exceptions import VerdictError
from verdict.device_state.baseline import (
    APP_DATA_SHA256,
    APP_DATA_TAR,
    BASELINE_FILE,
    PRETEST_APK,
    Baseline,
    BlockedError,
    preflight,
    prepare_private_folder,
    sha256_file,
    take_baseline,
)


@pytest.fixture
def folder(tmp_path):
    return prepare_private_folder(tmp_path / "evidence")


def test_private_folder_is_mode_700(folder):
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_private_folder_refuses_a_git_work_tree(tmp_path):
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    with pytest.raises(VerdictError, match="git work tree"):
        prepare_private_folder(tmp_path / "repo" / "evidence")


def test_private_folder_refuses_an_old_baseline(folder):
    (folder / BASELINE_FILE).write_text("{}")
    with pytest.raises(VerdictError, match="already has a baseline"):
        prepare_private_folder(folder)


@pytest.mark.parametrize(
    ("phone", "reason"),
    [
        (FakePhone(devices_list=[]), "no phone"),
        (FakePhone(devices_list=[("A", "device"), ("B", "device")]), "2 devices"),
        (FakePhone(devices_list=[("emulator-5554", "device")]), "emulator"),
        (FakePhone(devices_list=[("R5CX", "unauthorized")]), "unauthorized"),
        (FakePhone(user="10"), "current user"),
        (FakePhone(window="mDreamingLockscreen=true"), "locked"),
    ],
)
def test_preflight_blocks(phone, reason):
    with pytest.raises(BlockedError, match=reason):
        preflight(phone, None)


def test_preflight_blocks_a_wrong_serial():
    with pytest.raises(BlockedError, match="--device"):
        preflight(FakePhone(), "OTHER")


def test_preflight_passes_for_one_unlocked_phone():
    preflight(FakePhone(), "R5CX")


def test_baseline_records_everything_and_switches_keyboard(folder):
    phone = FakePhone()
    baseline = take_baseline(phone, TARGET, PLAY, folder)

    state = baseline.state
    assert set(state.packages) == {PLAY, TARGET}
    assert state.packages[TARGET].version_code == 100
    assert state.packages[TARGET].version_name == "2.0-debug+abc1234"
    assert state.apk_sha256 == sha256_file(folder / PRETEST_APK)
    assert state.keyboard["default_input_method"] == TARGET_IME
    assert state.display == {
        "font_scale": "1.0",
        "accelerometer_rotation": "1",
        "user_rotation": "0",
        "stay_on_while_plugged_in": "0",
        "night_mode": "no",
    }
    assert set(state.app_data_sha256) == {"./shared_prefs/a.xml", "./files/b.db"}
    assert baseline.app_data_tar == APP_DATA_TAR
    assert baseline.ime_enabled_by_verdict is None
    # Gboard was already enabled, so it is selected; the debug keyboard no longer runs.
    assert phone.secure["default_input_method"] == GBOARD
    force_stop = phone.commands.index(f"am force-stop {TARGET}")
    assert force_stop < phone.commands.index(f"exec-out run-as {TARGET} tar -cf - .")
    saved = Baseline.model_validate_json((folder / BASELINE_FILE).read_text())
    assert saved == baseline
    for name in (BASELINE_FILE, APP_DATA_TAR, APP_DATA_SHA256):
        assert stat.S_IMODE((folder / name).stat().st_mode) == 0o600


def test_baseline_reads_before_it_changes_the_phone(folder):
    phone = FakePhone()
    take_baseline(phone, TARGET, PLAY, folder)
    first_change = next(i for i, c in enumerate(phone.commands) if c.startswith("ime set"))
    reads = [c for c in phone.commands[:first_change]]
    assert any(c.startswith("pull ") for c in reads)
    assert "cmd uimode night" in reads


def test_baseline_enables_a_keyboard_when_no_other_is_enabled(folder):
    phone = FakePhone()
    phone.secure["enabled_input_methods"] = TARGET_IME
    phone.all_imes = [f"{PLAY}/bha.keys.smartype.FlorisImeService", TARGET_IME, SAMSUNG]
    baseline = take_baseline(phone, TARGET, PLAY, folder)
    assert baseline.ime_enabled_by_verdict == SAMSUNG
    assert phone.secure["default_input_method"] == SAMSUNG


def test_baseline_never_selects_a_keyboard_of_the_package_family(folder):
    phone = FakePhone()
    phone.secure["enabled_input_methods"] = f"{TARGET_IME}:{PLAY}/x.Ime"
    phone.all_imes = [TARGET_IME, f"{PLAY}/x.Ime"]
    with pytest.raises(BlockedError, match="no other keyboard"):
        take_baseline(phone, TARGET, PLAY, folder)


def test_baseline_keeps_keyboard_when_target_is_not_the_default(folder):
    phone = FakePhone()
    phone.secure["default_input_method"] = GBOARD
    take_baseline(phone, TARGET, PLAY, folder)
    assert not any(c.startswith("ime ") for c in phone.commands if c != "ime list -s")


def test_baseline_without_installed_app_changes_nothing(folder):
    phone = FakePhone(packages={PLAY: (90, "1.9")})
    baseline = take_baseline(phone, TARGET, PLAY, folder)
    assert baseline.pretest_apk is None
    assert baseline.app_data_tar is None
    assert not (folder / PRETEST_APK).exists()
    changing = [c for c in phone.commands if c.startswith(("ime set", "ime enable", "am force-stop"))]
    assert changing == []
    assert json.loads((folder / BASELINE_FILE).read_text())["package"] == TARGET


def test_baseline_blocks_split_apks(folder):
    phone = FakePhone(apk_paths=["/data/app/base.apk", "/data/app/split_config.arm64.apk"])
    with pytest.raises(BlockedError, match="2 APK files"):
        take_baseline(phone, TARGET, PLAY, folder)


def test_failed_backup_sets_keyboard_back_and_blocks(folder):
    phone = FakePhone(tar_override=b"run-as: package not debuggable")
    with pytest.raises(BlockedError, match="keyboard set back"):
        take_baseline(phone, TARGET, PLAY, folder)
    assert phone.secure["default_input_method"] == TARGET_IME


def test_failed_backup_disables_the_keyboard_it_enabled(folder):
    phone = FakePhone(tar_override=b"")
    phone.secure["enabled_input_methods"] = TARGET_IME
    with pytest.raises(BlockedError):
        take_baseline(phone, TARGET, PLAY, folder)
    assert phone.secure["default_input_method"] == TARGET_IME
    assert phone.secure["enabled_input_methods"] == TARGET_IME


def test_backup_that_misses_a_file_blocks(folder):
    from tests.device_state.fake_adb import make_tar

    phone = FakePhone()
    phone.tar_override = make_tar({"./shared_prefs/a.xml": b"<a/>"})
    with pytest.raises(BlockedError, match="misses 1 file"):
        take_baseline(phone, TARGET, PLAY, folder)


def test_invalid_package_name_is_rejected_before_any_command(folder):
    phone = FakePhone()
    with pytest.raises(VerdictError, match="invalid package"):
        take_baseline(phone, "x; reboot", PLAY, folder)
    assert phone.commands == []
