"""Appium happy path: taps, then buying a crystal pack on the emulator.

Runs only when APPIUM_URL is set (for example http://127.0.0.1:4723) and an
emulator with the stand APK installed is attached. Requires `adb` on PATH.
"""

import os
import subprocess
import time

import pytest

from conftest import check_invariants

APPIUM_URL = os.environ.get("APPIUM_URL")
PACKAGE = "dev.iapchaos.stand"
pytestmark = pytest.mark.skipif(not APPIUM_URL, reason="APPIUM_URL not set")


def adb(*args: str) -> None:
    subprocess.run(["adb", "shell", *args], check=True, capture_output=True)


@pytest.fixture
def driver(stand_urls, audit):
    from appium import webdriver
    from appium.options.android import UiAutomator2Options

    device_url = stand_urls[0].replace("127.0.0.1", "10.0.2.2").replace("localhost", "10.0.2.2")
    defects = os.environ.get("STAND_DEFECTS", "")
    # Full reset (spec/launch.md): stop, clear data, reset the server (done by `audit`), launch.
    adb("am", "force-stop", PACKAGE)
    adb("pm", "clear", PACKAGE)
    options = UiAutomator2Options()
    options.app_package = PACKAGE
    options.app_activity = ".MainActivity"
    options.no_reset = True
    options.set_capability("appium:optionalIntentArguments",
                           f'--es backend_url {device_url} --es defects "{defects}"')
    drv = webdriver.Remote(APPIUM_URL, options=options)
    yield drv
    drv.quit()


def element(drv, rid: str):
    from appium.webdriver.common.appiumby import AppiumBy
    return drv.find_element(AppiumBy.ANDROID_UIAUTOMATOR, f'new UiSelector().resourceId("{rid}")')


def wait_text(drv, rid: str, expected: set[str], timeout: float) -> str:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = element(drv, rid).text
            if last in expected:
                return last
        except Exception:
            pass
        time.sleep(0.25)
    raise AssertionError(f"{rid} = {last!r}, expected one of {expected}")


def test_happy_purchase(driver, audit):
    wait_text(driver, "sync_status", {"idle"}, 30)
    player_id = element(driver, "player_id_value").text

    for _ in range(25):
        element(driver, "tap_button").click()
    wait_text(driver, "sync_status", {"idle"}, 30)
    wait_text(driver, "coins_value", {"25"}, 10)

    element(driver, "nav_shop").click()
    wait_text(driver, "catalog_state", {"ready"}, 20)
    assert element(driver, "offer_status").text == "available"
    assert element(driver, "product_crystals_small_price").text == "$0.99"

    element(driver, "buy_crystals_small").click()
    state = wait_text(driver, "purchase_state", {"success", "error"}, 60)
    assert state == "success"
    transaction_id = element(driver, "purchase_transaction_id").text

    # I9: success shown only with a grant for this transaction.
    journal = audit.get("/audit/backend/state").json()["journal"]
    assert any(e["kind"] == "purchase_grant" and e["ref"] == transaction_id and e["player_id"] == player_id
               for e in journal)

    # I8b: the screen answers input.
    element(driver, "purchase_dismiss").click()
    wait_text(driver, "purchase_state", {"idle"}, 3)
    element(driver, "nav_back").click()
    wait_text(driver, "sync_status", {"idle"}, 30)

    # I4: screen equals server once sync is idle.
    player = audit.get("/audit/backend/state", params={"player_id": player_id}).json()["players"][0]
    assert element(driver, "coins_value").text == str(player["coins"]) == "25"
    assert element(driver, "crystals_value").text == str(player["crystals"]) == "100"

    # I2: the transaction is closed once the background acknowledge has run.
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        statuses = [t["status"] for t in audit.get("/audit/store/transactions").json()["transactions"]]
        if statuses == ["acknowledged"]:
            break
        time.sleep(0.5)
    check_invariants(audit, after_recovery=True)
