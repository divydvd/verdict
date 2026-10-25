import subprocess
from pathlib import Path

import pytest
import uiautomator2

_ROOT_CONFTEST = Path(__file__).parent / "conftest.py"


@pytest.mark.parametrize(
    "args",
    [["adb", "devices"], ["/usr/local/bin/adb", "shell", "input", "keyevent", "3"], "adb devices"],
)
def test_subprocess_run_cannot_start_adb(args):
    with pytest.raises(AssertionError, match="adb|uiautomator2"):
        subprocess.run(args, capture_output=True, check=False)


def test_subprocess_popen_cannot_start_adb():
    with pytest.raises(AssertionError, match="adb|uiautomator2"):
        subprocess.Popen(["adb", "devices"])


def test_uiautomator2_connect_is_blocked():
    with pytest.raises(AssertionError, match="adb|uiautomator2"):
        uiautomator2.connect()


def test_other_commands_still_run():
    result = subprocess.run(["true"], check=False)
    assert result.returncode == 0


def test_device_tests_are_skipped_without_opt_in(pytester):
    pytester.makeconftest(_ROOT_CONFTEST.read_text())
    pytester.makepyfile(
        """
        import pytest

        @pytest.mark.requires_device
        def test_on_phone():
            raise AssertionError("must not run")
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(skipped=1)
