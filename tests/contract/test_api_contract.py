"""Server conformance to spec/: idempotency, error codes, concurrency.

Required on the reference only. With a defect enabled, some tests may fail.
"""

import base64
import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from conftest import ROOT, Player, check_invariants

LOCAL_ONLY = pytest.mark.skipif(bool(os.environ.get("STAND_URL")), reason="needs a local server")


def error_code(response) -> str:
    return response.json()["error"]["code"]


# --- Idempotency -----------------------------------------------------------

def test_register_is_idempotent_by_install_id(api, new_player):
    first = new_player()
    second = Player(api, first.install_id)
    assert (second.player_id, second.token) == (first.player_id, first.token)


def test_tap_batch_repeat_has_no_new_effect(player, audit):
    batch = str(uuid.uuid4())
    first = player.tap(7, batch).json()
    second = player.tap(7, batch).json()
    assert second["duplicate"] is True and second["credited_coins"] == first["credited_coins"]
    assert second["player"]["coins"] == 7
    check_invariants(audit, after_recovery=True)


def test_tap_batch_conflict(player):
    batch = str(uuid.uuid4())
    player.tap(7, batch)
    response = player.tap(8, batch)
    assert response.status_code == 409 and error_code(response) == "IDEMPOTENCY_CONFLICT"


@pytest.mark.parametrize("item", ["upgrade", "booster"])
def test_spend_repeat_has_no_new_effect(player, audit, item):
    player.tap(100)
    player.buy("crystals_small")
    spend_id = str(uuid.uuid4())
    first = player.spend(item, spend_id).json()
    second = player.spend(item, spend_id).json()
    assert second["duplicate"] is True and second["cost"] == first["cost"]
    assert second["player"]["coins"] == first["player"]["coins"]
    assert second["player"]["crystals"] == first["player"]["crystals"]
    check_invariants(audit, after_recovery=True)


def test_spend_conflict(player):
    player.tap(100)
    player.buy("crystals_small")
    spend_id = str(uuid.uuid4())
    player.spend("upgrade", spend_id)
    response = player.spend("booster", spend_id)
    assert response.status_code == 409 and error_code(response) == "IDEMPOTENCY_CONFLICT"


def test_rejected_spend_is_not_recorded(player):
    spend_id = str(uuid.uuid4())
    rejected = player.spend("upgrade", spend_id)
    assert rejected.status_code == 409 and error_code(rejected) == "INSUFFICIENT_FUNDS"
    player.tap(20)
    assert player.spend("upgrade", spend_id).json()["duplicate"] is False


def test_store_purchase_repeat_returns_same_transaction(player, audit):
    key = str(uuid.uuid4())
    first = player.store_purchase("crystals_small", key)
    second = player.store_purchase("crystals_small", key)
    assert (first.status_code, second.status_code) == (201, 200)
    assert second.json() == first.json()
    assert len(audit.get("/audit/store/transactions").json()["transactions"]) == 1


def test_store_purchase_key_conflict(player):
    key = str(uuid.uuid4())
    player.store_purchase("crystals_small", key)
    response = player.store_purchase("crystals_large", key)
    assert response.status_code == 409 and error_code(response) == "IDEMPOTENCY_CONFLICT"


def test_validate_repeat_returns_previous_result(player, audit):
    tx = player.store_purchase("crystals_large").json()
    first = player.validate(tx["receipt"]).json()
    second = player.validate(tx["receipt"])
    assert second.status_code == 200, second.text
    second = second.json()
    assert second["duplicate"] is True and second["grant"] == first["grant"]
    assert second["player"]["crystals"] == 1200
    player.ack(tx["transaction_id"])
    check_invariants(audit, after_recovery=True)


def test_acknowledge_is_idempotent(player):
    tx = player.store_purchase("crystals_small").json()
    player.validate(tx["receipt"])
    first = player.ack(tx["transaction_id"]).json()
    second = player.ack(tx["transaction_id"]).json()
    assert second["status"] == "acknowledged" and second["acknowledged_at"] == first["acknowledged_at"]


def test_acknowledged_but_not_granted_is_granted(player, audit):
    tx = player.store_purchase("crystals_small").json()
    player.ack(tx["transaction_id"])
    body = player.validate(tx["receipt"]).json()
    assert body["duplicate"] is False and body["grant"]["crystals"] == 100
    check_invariants(audit, after_recovery=True)


# --- Concurrency -------------------------------------------------------------

def _parallel(fn, n=8):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(lambda _: fn(), range(n)))


def test_concurrent_validate_grants_once(player, audit):
    tx = player.store_purchase("crystals_medium").json()
    results = _parallel(lambda: player.validate(tx["receipt"]))
    assert all(r.status_code == 200 for r in results)
    assert sum(not r.json()["duplicate"] for r in results) == 1
    player.ack(tx["transaction_id"])
    check_invariants(audit, after_recovery=True)


def test_concurrent_store_purchase_creates_one(player, audit):
    key = str(uuid.uuid4())
    results = _parallel(lambda: player.store_purchase("crystals_small", key))
    assert sorted(r.status_code for r in results) == [200] * 7 + [201]
    assert len({r.json()["transaction_id"] for r in results}) == 1


def test_concurrent_tap_batch_applies_once(player, audit):
    batch = str(uuid.uuid4())
    results = _parallel(lambda: player.tap(9, batch))
    assert sum(not r.json()["duplicate"] for r in results) == 1
    check_invariants(audit, after_recovery=True)


def test_concurrent_offer_purchases_sell_once(player):
    results = _parallel(lambda: player.store_purchase("starter_offer"))
    codes = sorted(r.status_code for r in results)
    assert codes == [201] + [409] * 7
    assert all(error_code(r) == "ALREADY_PURCHASED" for r in results if r.status_code == 409)


# --- Store rules ---------------------------------------------------------------

def test_offer_sold_once_per_player(player, new_player):
    player.buy("starter_offer")
    response = player.store_purchase("starter_offer")
    assert response.status_code == 409 and error_code(response) == "ALREADY_PURCHASED"
    other = new_player()
    assert other.store_purchase("starter_offer").status_code == 201


def test_pending_list_and_ordering(player):
    first = player.store_purchase("crystals_small").json()
    second = player.store_purchase("crystals_large").json()
    pending = player.get("/store/purchases", params={"status": "pending"}).json()
    assert pending["player_id"] == player.player_id
    assert [t["transaction_id"] for t in pending["transactions"]] == [
        first["transaction_id"], second["transaction_id"]]
    player.ack(first["transaction_id"])
    pending = player.get("/store/purchases", params={"status": "pending"}).json()["transactions"]
    assert [t["transaction_id"] for t in pending] == [second["transaction_id"]]


def test_get_transaction_returns_same_receipt(player):
    tx = player.store_purchase("crystals_small").json()
    again = player.get(f"/store/purchases/{tx['transaction_id']}").json()
    assert again["receipt"] == tx["receipt"]


def test_other_players_transaction_is_not_found(player, new_player):
    tx = player.store_purchase("crystals_small").json()
    other = new_player()
    assert other.get(f"/store/purchases/{tx['transaction_id']}").status_code == 404
    response = other.ack(tx["transaction_id"])
    assert response.status_code == 404 and error_code(response) == "TRANSACTION_NOT_FOUND"


def test_receipt_payload_matches_transaction(player):
    tx = player.store_purchase("crystals_medium").json()
    raw = tx["receipt"]["payload"]
    payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    assert payload == {"v": 1, "transaction_id": tx["transaction_id"], "player_id": player.player_id,
                       "sku": "crystals_medium", "quantity": 1, "purchased_at": tx["created_at"]}


# --- Validation errors ------------------------------------------------------------

def _tampered(receipt: dict, **changes) -> dict:
    raw = receipt["payload"]
    payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    payload.update(changes)
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    return {"payload": encoded, "signature": receipt["signature"]}


def test_invalid_signature_grants_nothing(player, audit):
    tx = player.store_purchase("crystals_small").json()
    response = player.validate(_tampered(tx["receipt"], sku="crystals_large"))
    assert response.status_code == 400 and error_code(response) == "INVALID_SIGNATURE"
    bad = dict(tx["receipt"], signature="0" * 64)
    assert error_code(player.validate(bad)) == "INVALID_SIGNATURE"
    assert audit.get("/audit/backend/state").json()["journal"] == []


def test_malformed_receipt(player):
    response = player.validate({"payload": "not-base64-json", "signature": "0" * 64})
    assert response.status_code == 400 and error_code(response) == "MALFORMED_RECEIPT"


def test_other_players_receipt_is_rejected(player, new_player, audit):
    tx = player.store_purchase("crystals_small").json()
    other = new_player()
    response = other.validate(tx["receipt"])
    assert response.status_code == 403 and error_code(response) == "RECEIPT_PLAYER_MISMATCH"
    assert audit.get("/audit/backend/state").json()["journal"] == []


@pytest.mark.parametrize("token", ["x", "garbage", "v1.00000000-0000-4000-8000-000000000000.abc"])
def test_bad_token_is_unauthorized(api, token):
    for method, path in [("get", "/player"), ("get", "/catalog"), ("get", "/store/purchases")]:
        response = getattr(api, method)(path, headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401 and error_code(response) == "UNAUTHORIZED"


def test_missing_token_is_unauthorized(api):
    response = api.get("/player")
    assert response.status_code == 401 and error_code(response) == "UNAUTHORIZED"


def test_unknown_player_after_reset(player, audit):
    audit.post("/audit/reset").raise_for_status()
    response = player.get("/player")
    assert response.status_code == 401 and error_code(response) == "PLAYER_NOT_FOUND"


def test_schema_violations(player):
    assert player.tap(0).status_code == 422
    assert player.tap(201).status_code == 422
    response = player.post("/spend", {"spend_id": str(uuid.uuid4()), "item": "sword"})
    assert response.status_code == 422 and error_code(response) == "VALIDATION_ERROR"
    assert player.post("/store/purchases", {"sku": "gold", "idempotency_key": str(uuid.uuid4())}).status_code == 422


def test_insufficient_funds_and_max_level(player, audit):
    response = player.spend("booster")
    assert response.status_code == 409 and error_code(response) == "INSUFFICIENT_FUNDS"
    player.buy("starter_offer")
    costs = []
    while len(costs) < 9:
        response = player.spend("upgrade")
        if response.status_code == 409:
            assert error_code(response) == "INSUFFICIENT_FUNDS"
            player.tap(200)
            continue
        costs.append(response.json()["cost"]["coins"])
    assert costs == [20, 40, 80, 160, 320, 640, 1280, 2560, 5120]
    response = player.spend("upgrade")
    assert response.status_code == 409 and error_code(response) == "MAX_LEVEL"
    check_invariants(audit, after_recovery=True)


def test_boosted_batch_larger_than_charges(player):
    player.buy("crystals_small")
    player.spend("booster")
    assert player.tap(150).json()["credited_coins"] == 150 + 2 * 100
    assert player.get("/player").json()["booster"]["charges"] == 0


def test_version_grows_with_every_entry(player):
    v0 = player.get("/player").json()["version"]
    v1 = player.tap(1).json()["player"]["version"]
    v2 = player.tap(1).json()["player"]["version"]
    assert v0 < v1 < v2


def test_audit_filters(player, new_player, audit):
    player.tap(3)
    other = new_player()
    other.tap(4)
    state = audit.get("/audit/backend/state", params={"player_id": other.player_id}).json()
    assert [p["player_id"] for p in state["players"]] == [other.player_id]
    assert [e["taps"] for e in state["journal"]] == [4]
    first_id = audit.get("/audit/backend/state").json()["journal"][0]["entry_id"]
    rest = audit.get("/audit/backend/state", params={"after_entry_id": first_id}).json()["journal"]
    assert [e["taps"] for e in rest] == [4]


# --- Process configuration (local server only) --------------------------------------

def _run_server(extra_env: dict, tmp_path: Path, timeout=5):
    env = dict(os.environ, DATA_DIR=str(tmp_path), PUBLIC_PORT="0", AUDIT_PORT="0", **extra_env)
    return subprocess.run([sys.executable, "-m", "stand"], cwd=ROOT / "server", env=env,
                          capture_output=True, timeout=timeout)


@LOCAL_ONLY
def test_unknown_defect_fails_fast(tmp_path):
    result = _run_server({"STAND_DEFECTS": "Z99"}, tmp_path)
    assert result.returncode == 78
    assert b"unknown defect id" in result.stderr


@LOCAL_ONLY
def test_offer_expires(tmp_path):
    import socket
    import time

    import httpx

    ports = []
    for _ in range(2):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            ports.append(s.getsockname()[1])
    env = dict(os.environ, DATA_DIR=str(tmp_path), PUBLIC_HOST="127.0.0.1", AUDIT_HOST="127.0.0.1",
               PUBLIC_PORT=str(ports[0]), AUDIT_PORT=str(ports[1]), OFFER_WINDOW_SECONDS="1")
    proc = subprocess.Popen([sys.executable, "-m", "stand"], cwd=ROOT / "server", env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{ports[0]}"
        for _ in range(100):
            try:
                httpx.get(f"http://127.0.0.1:{ports[1]}/audit/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        with httpx.Client(base_url=base) as api:
            p = Player(api)
            assert p.get("/catalog").json()["products"][3]["offer"]["status"] == "available"
            time.sleep(1.2)
            assert p.get("/catalog").json()["products"][3]["offer"]["status"] == "expired"
            # Paid is paid: the store ignores the timer and the backend grants.
            body = p.buy("starter_offer")
            assert body["grant"]["crystals"] == 300
            assert body["player"]["offer"]["status"] == "purchased"
    finally:
        proc.terminate()
        proc.wait(timeout=10)
