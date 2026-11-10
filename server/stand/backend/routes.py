"""Public backend API (spec/openapi.yaml)."""

import sqlite3
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header
from pydantic import BaseModel, ConfigDict, Field

from .. import clock, defects
from ..errors import ApiError
from ..sqlite import Database
from . import db as bdb
from . import game, signing

Uuid = Annotated[str, Field(pattern=signing.UUID_RE.pattern)]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterRequest(Strict):
    install_id: Uuid


class TapBatchRequest(Strict):
    batch_id: Uuid
    taps: Annotated[int, Field(ge=1, le=game.TAP_BATCH_MAX, strict=True)]


class SpendRequest(Strict):
    spend_id: Uuid
    item: Literal["upgrade", "booster"]


class Receipt(Strict):
    payload: str
    signature: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class ValidateRequest(Strict):
    receipt: Receipt


def build_router(database: Database, secret: bytes, offer_window_seconds: int) -> APIRouter:
    router = APIRouter()

    def authenticate(authorization: str | None) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise ApiError(401, "UNAUTHORIZED", "missing bearer token")
        player_id = signing.verify_token(secret, authorization[len("Bearer "):])
        if player_id is None:
            raise ApiError(401, "UNAUTHORIZED", "invalid token")
        return player_id

    def load_player(conn: sqlite3.Connection, player_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchone()
        if row is None:
            raise ApiError(401, "PLAYER_NOT_FOUND", "player does not exist")
        return row

    def offer_state(conn: sqlite3.Connection, player: sqlite3.Row, now_iso: str) -> dict:
        if bdb.has_offer_grant(conn, player["player_id"], game.OFFER_SKU):
            status = "purchased"
        elif now_iso < player["offer_expires_at"]:
            status = "available"
        else:
            status = "expired"
        return {"sku": game.OFFER_SKU, "expires_at": player["offer_expires_at"], "status": status}

    def snapshot(conn: sqlite3.Connection, player_id: str) -> dict:
        player = load_player(conn, player_id)
        now_iso = clock.now_iso()
        level = player["upgrade_level"]
        return {
            "player_id": player["player_id"],
            "coins": player["coins"],
            "crystals": player["crystals"],
            "upgrade": {"level": level, "tap_income": level, "next_cost": game.upgrade_cost(level)},
            "booster": {
                "charges": player["booster_charges"],
                "cost_crystals": game.BOOSTER_COST_CRYSTALS,
                "charges_per_purchase": game.BOOSTER_CHARGES,
            },
            "offer": offer_state(conn, player, now_iso),
            "version": player["version"],
            "server_time": now_iso,
        }

    @router.post("/players")
    def register(body: RegisterRequest) -> dict:
        with database.write() as conn:
            row = conn.execute(
                "SELECT player_id FROM players WHERE install_id = ?", (body.install_id,)
            ).fetchone()
            if row is None:
                player_id = str(uuid.uuid4())
                now = clock.now()
                conn.execute(
                    "INSERT INTO players (player_id, install_id, registered_at, offer_expires_at,"
                    " coins, crystals, upgrade_level, booster_charges, version)"
                    " VALUES (?, ?, ?, ?, 0, 0, 1, 0, 0)",
                    (player_id, body.install_id, clock.iso(now),
                     clock.plus_seconds_iso(now, offer_window_seconds)),
                )
            else:
                player_id = row["player_id"]
            return {
                "player_id": player_id,
                "token": signing.issue_token(secret, player_id),
                "player": snapshot(conn, player_id),
            }

    @router.get("/player")
    def get_player(authorization: Annotated[str | None, Header()] = None) -> dict:
        player_id = authenticate(authorization)
        with database.read() as conn:
            return snapshot(conn, player_id)

    @router.get("/catalog")
    def get_catalog(authorization: Annotated[str | None, Header()] = None) -> dict:
        player_id = authenticate(authorization)
        with database.read() as conn:
            player = load_player(conn, player_id)
            now_iso = clock.now_iso()
            offer = offer_state(conn, player, now_iso)
        products = []
        for sku, (title, price, coins, crystals, one_time) in game.CATALOG.items():
            products.append({
                "sku": sku,
                "title": title,
                "price_cents": price,
                "currency": "USD",
                "grant": {"coins": coins, "crystals": crystals},
                "one_time": one_time,
                "offer": {"expires_at": offer["expires_at"], "status": offer["status"],
                          "sku": sku} if sku == game.OFFER_SKU else None,
            })
        return {"server_time": now_iso, "products": products}

    @router.post("/taps/sync")
    def sync_taps(body: TapBatchRequest, authorization: Annotated[str | None, Header()] = None) -> dict:
        player_id = authenticate(authorization)
        with database.write() as conn:
            player = load_player(conn, player_id)
            existing = bdb.find_entry(conn, "tap_batch", body.batch_id)
            if existing is not None:
                if existing["player_id"] != player_id or existing["taps"] != body.taps:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "batch_id reused with different taps")
                credited, duplicate = existing["delta_coins"], True
            else:
                credited, boosted = game.tap_credit(
                    body.taps, player["upgrade_level"], player["booster_charges"])
                bdb.append(
                    conn, player, created_at=clock.now_iso(), kind="tap_batch", ref=body.batch_id,
                    delta_coins=credited, charges=player["booster_charges"] - boosted,
                    taps=body.taps, boosted_taps=boosted,
                )
                duplicate = False
            return {
                "batch_id": body.batch_id,
                "taps": body.taps,
                "credited_coins": credited,
                "duplicate": duplicate,
                "player": snapshot(conn, player_id),
            }

    @router.post("/spend")
    def spend(body: SpendRequest, authorization: Annotated[str | None, Header()] = None) -> dict:
        player_id = authenticate(authorization)
        with database.write() as conn:
            player = load_player(conn, player_id)
            existing = None
            if body.item == "upgrade" or not defects.on("O04"):
                existing = bdb.find_entry(conn, "spend", body.spend_id)
            if existing is not None:
                if existing["player_id"] != player_id or existing["item"] != body.item:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "spend_id reused with a different item")
                cost = {"coins": -existing["delta_coins"], "crystals": -existing["delta_crystals"]}
                duplicate = True
            else:
                if body.item == "upgrade":
                    price = game.upgrade_cost(player["upgrade_level"])
                    if price is None:
                        raise ApiError(409, "MAX_LEVEL", "upgrade is at the max level")
                    if player["coins"] < price:
                        raise ApiError(409, "INSUFFICIENT_FUNDS", "not enough coins")
                    cost = {"coins": price, "crystals": 0}
                    bdb.append(conn, player, created_at=clock.now_iso(), kind="spend",
                               ref=body.spend_id, item="upgrade", delta_coins=-price,
                               level=player["upgrade_level"] + 1)
                else:
                    if player["crystals"] < game.BOOSTER_COST_CRYSTALS:
                        raise ApiError(409, "INSUFFICIENT_FUNDS", "not enough crystals")
                    cost = {"coins": 0, "crystals": game.BOOSTER_COST_CRYSTALS}
                    bdb.append(conn, player, created_at=clock.now_iso(), kind="spend",
                               ref=body.spend_id, item="booster",
                               delta_crystals=-game.BOOSTER_COST_CRYSTALS,
                               charges=player["booster_charges"] + game.BOOSTER_CHARGES)
                duplicate = False
            return {
                "spend_id": body.spend_id,
                "item": body.item,
                "cost": cost,
                "duplicate": duplicate,
                "player": snapshot(conn, player_id),
            }

    @router.post("/purchases/validate")
    def validate(body: ValidateRequest, authorization: Annotated[str | None, Header()] = None) -> dict:
        player_id = authenticate(authorization)
        try:
            payload = signing.decode_payload(body.receipt.payload)
        except signing.MalformedReceipt as exc:
            raise ApiError(400, "MALFORMED_RECEIPT", str(exc)) from exc
        if not signing.receipt_signature_ok(secret, body.receipt.payload, body.receipt.signature):
            raise ApiError(400, "INVALID_SIGNATURE", "receipt signature does not match")
        if payload["player_id"] != player_id:
            raise ApiError(403, "RECEIPT_PLAYER_MISMATCH", "receipt belongs to another player")
        sku = payload["sku"]
        if sku not in game.CATALOG:
            raise ApiError(400, "UNKNOWN_SKU", f"unknown sku {sku}")
        transaction_id = payload["transaction_id"]
        with database.write() as conn:
            player = load_player(conn, player_id)
            existing = bdb.find_entry(conn, "purchase_grant", transaction_id)
            if existing is not None:
                if defects.on("O05"):
                    coins, crystals = game.grant(existing["item"], payload["quantity"])
                else:
                    coins, crystals = existing["delta_coins"], existing["delta_crystals"]
                duplicate = True
            else:
                one_time = game.CATALOG[sku][4]
                if one_time and bdb.has_offer_grant(conn, player_id, sku):
                    raise ApiError(409, "OFFER_ALREADY_OWNED", "one-time product already granted")
                coins, crystals = game.grant(sku, payload["quantity"])
                bdb.append(conn, player, created_at=clock.now_iso(), kind="purchase_grant",
                           ref=transaction_id, sku=sku, delta_coins=coins, delta_crystals=crystals)
                duplicate = False
            return {
                "transaction_id": transaction_id,
                "sku": sku,
                "grant": {"coins": coins, "crystals": crystals},
                "duplicate": duplicate,
                "player": snapshot(conn, player_id),
            }

    return router
