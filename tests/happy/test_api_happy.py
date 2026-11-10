"""Happy-path API tests.

Every request here is sent exactly once, with no faults. This suite must pass
on the reference and with any single defect enabled.
"""

import pytest

from conftest import check_invariants


def test_register_creates_fresh_player(player):
    snapshot = player.get("/player").json()
    assert snapshot["player_id"] == player.player_id
    assert (snapshot["coins"], snapshot["crystals"]) == (0, 0)
    assert snapshot["upgrade"] == {"level": 1, "tap_income": 1, "next_cost": 20}
    assert snapshot["booster"]["charges"] == 0
    assert snapshot["offer"]["status"] == "available"
    assert snapshot["version"] == 0
    assert player.token.split(".")[1] == player.player_id


def test_catalog_lists_four_products(player):
    catalog = player.get("/catalog").json()
    assert [p["sku"] for p in catalog["products"]] == [
        "crystals_small", "crystals_medium", "crystals_large", "starter_offer"]
    prices = {p["sku"]: p["price_cents"] for p in catalog["products"]}
    assert prices == {"crystals_small": 99, "crystals_medium": 499, "crystals_large": 999,
                      "starter_offer": 199}
    offer = catalog["products"][3]
    assert offer["one_time"] is True and offer["offer"]["status"] == "available"


def test_tap_batch_credits_coins(player, audit):
    body = player.tap(25).json()
    assert body["credited_coins"] == 25 and body["duplicate"] is False
    assert body["player"]["coins"] == 25
    check_invariants(audit, after_recovery=True)


def test_upgrade_spends_coins(player, audit):
    player.tap(30)
    body = player.spend("upgrade").json()
    assert body["cost"] == {"coins": 20, "crystals": 0}
    assert body["player"]["coins"] == 10
    assert body["player"]["upgrade"]["level"] == 2
    assert player.tap(5).json()["credited_coins"] == 10
    check_invariants(audit, after_recovery=True)


@pytest.mark.parametrize("sku,crystals", [
    ("crystals_small", 100), ("crystals_medium", 550), ("crystals_large", 1200)])
def test_buy_crystal_pack(player, audit, sku, crystals):
    body = player.buy(sku)
    assert body["sku"] == sku and body["duplicate"] is False
    assert body["grant"] == {"coins": 0, "crystals": crystals}
    assert body["player"]["crystals"] == crystals
    assert player.get("/store/purchases", params={"status": "pending"}).json()["transactions"] == []
    check_invariants(audit, after_recovery=True)


def test_buy_starter_offer(player, audit):
    body = player.buy("starter_offer")
    assert body["grant"] == {"coins": 2000, "crystals": 300}
    assert body["player"]["offer"]["status"] == "purchased"
    catalog = player.get("/catalog").json()
    assert catalog["products"][3]["offer"]["status"] == "purchased"
    check_invariants(audit, after_recovery=True)


def test_booster_boosts_taps(player, audit):
    player.buy("crystals_small")
    body = player.spend("booster").json()
    assert body["cost"] == {"coins": 0, "crystals": 50}
    assert body["player"]["booster"]["charges"] == 100
    assert player.tap(10).json()["credited_coins"] == 30
    assert player.get("/player").json()["booster"]["charges"] == 90
    check_invariants(audit, after_recovery=True)


def test_audit_reflects_purchase(player, audit):
    validated = player.buy("crystals_medium")
    state = audit.get("/audit/backend/state").json()
    assert [p["player_id"] for p in state["players"]] == [player.player_id]
    grant = state["journal"][-1]
    assert grant["kind"] == "purchase_grant" and grant["ref"] == validated["transaction_id"]
    transactions = audit.get("/audit/store/transactions").json()["transactions"]
    assert [t["status"] for t in transactions] == ["acknowledged"]


def test_reset_empties_everything(player, audit):
    player.buy("crystals_small")
    audit.post("/audit/reset").raise_for_status()
    state = audit.get("/audit/backend/state").json()
    assert state["players"] == [] and state["journal"] == []
    assert audit.get("/audit/store/transactions").json()["transactions"] == []
