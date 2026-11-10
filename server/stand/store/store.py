"""Store database, signing and routes (spec/openapi.yaml, tag `store`)."""

import base64
import hashlib
import hmac
import json
import re
import sqlite3
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Header
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .. import clock
from ..errors import ApiError
from ..sqlite import Database

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")

# sku -> (price_cents, one_time). The store's own price list.
PRODUCTS: dict[str, tuple[int, bool]] = {
    "crystals_small": (99, False),
    "crystals_medium": (499, False),
    "crystals_large": (999, False),
    "starter_offer": (199, True),
}
ONE_TIME_SKUS = tuple(sku for sku, (_, one_time) in PRODUCTS.items() if one_time)

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS transactions (
    transaction_id TEXT PRIMARY KEY,
    player_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    price_cents INTEGER NOT NULL,
    currency TEXT NOT NULL,
    status TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    acknowledged_at TEXT,
    payload TEXT NOT NULL,
    signature TEXT NOT NULL,
    UNIQUE (player_id, idempotency_key)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_time_per_player ON transactions (player_id, sku)
    WHERE sku IN ({", ".join(f"'{s}'" for s in ONE_TIME_SKUS)});
CREATE INDEX IF NOT EXISTS transactions_player ON transactions (player_id, created_at);
"""

FIELDS = (
    "transaction_id", "player_id", "sku", "quantity", "price_cents", "currency", "status",
    "idempotency_key", "created_at", "acknowledged_at",
)


def open_db(path: str) -> Database:
    db = Database(path, SCHEMA)
    db.init()
    return db


def reset(db: Database) -> None:
    with db.write() as conn:
        conn.execute("DELETE FROM transactions")


def _mac(secret: bytes, message: str) -> str:
    return hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()


def player_from_token(secret: bytes, authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "UNAUTHORIZED", "missing bearer token")
    parts = authorization[len("Bearer "):].split(".")
    if len(parts) != 3 or parts[0] != "v1" or not UUID_RE.match(parts[1]):
        raise ApiError(401, "UNAUTHORIZED", "invalid token")
    if not hmac.compare_digest(parts[2], _mac(secret, "player.v1." + parts[1])):
        raise ApiError(401, "UNAUTHORIZED", "invalid token")
    return parts[1]


def make_receipt(secret: bytes, payload: dict) -> tuple[str, str]:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    encoded = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return encoded, _mac(secret, "receipt.v1." + encoded)


def as_json(row: sqlite3.Row) -> dict:
    data = {k: row[k] for k in FIELDS}
    data["receipt"] = {"payload": row["payload"], "signature": row["signature"]}
    return data


class CreatePurchaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sku: Literal["crystals_small", "crystals_medium", "crystals_large", "starter_offer"]
    idempotency_key: Annotated[str, Field(pattern=UUID_RE.pattern)]


def build_router(database: Database, secret: bytes) -> APIRouter:
    router = APIRouter()

    def get_own(conn: sqlite3.Connection, player_id: str, transaction_id: str) -> sqlite3.Row:
        row = conn.execute(
            "SELECT * FROM transactions WHERE transaction_id = ? AND player_id = ?",
            (transaction_id, player_id),
        ).fetchone()
        if row is None:
            raise ApiError(404, "TRANSACTION_NOT_FOUND", "no such transaction")
        return row

    @router.post("/purchases")
    def create(body: CreatePurchaseRequest, authorization: Annotated[str | None, Header()] = None):
        player_id = player_from_token(secret, authorization)
        with database.write() as conn:
            existing = conn.execute(
                "SELECT * FROM transactions WHERE player_id = ? AND idempotency_key = ?",
                (player_id, body.idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["sku"] != body.sku:
                    raise ApiError(409, "IDEMPOTENCY_CONFLICT", "idempotency_key reused with another sku")
                return JSONResponse(status_code=200, content=as_json(existing))
            price, one_time = PRODUCTS[body.sku]
            if one_time:
                owned = conn.execute(
                    "SELECT 1 FROM transactions WHERE player_id = ? AND sku = ?", (player_id, body.sku)
                ).fetchone()
                if owned is not None:
                    raise ApiError(409, "ALREADY_PURCHASED", "one-time product already purchased")
            transaction_id = str(uuid.uuid4())
            created_at = clock.now_iso()
            payload, signature = make_receipt(secret, {
                "v": 1,
                "transaction_id": transaction_id,
                "player_id": player_id,
                "sku": body.sku,
                "quantity": 1,
                "purchased_at": created_at,
            })
            conn.execute(
                "INSERT INTO transactions (transaction_id, player_id, sku, quantity, price_cents,"
                " currency, status, idempotency_key, created_at, acknowledged_at, payload, signature)"
                " VALUES (?, ?, ?, 1, ?, 'USD', 'pending', ?, ?, NULL, ?, ?)",
                (transaction_id, player_id, body.sku, price, body.idempotency_key, created_at,
                 payload, signature),
            )
            row = get_own(conn, player_id, transaction_id)
            return JSONResponse(status_code=201, content=as_json(row))

    @router.get("/purchases")
    def list_purchases(
        status: Literal["pending", "acknowledged"] | None = None,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict:
        player_id = player_from_token(secret, authorization)
        with database.read() as conn:
            query = "SELECT * FROM transactions WHERE player_id = ?"
            args: list = [player_id]
            if status is not None:
                query += " AND status = ?"
                args.append(status)
            rows = conn.execute(query + " ORDER BY created_at, transaction_id", args).fetchall()
        return {"player_id": player_id, "transactions": [as_json(r) for r in rows]}

    @router.get("/purchases/{transaction_id}")
    def get_purchase(transaction_id: str, authorization: Annotated[str | None, Header()] = None) -> dict:
        player_id = player_from_token(secret, authorization)
        with database.read() as conn:
            return as_json(get_own(conn, player_id, transaction_id))

    @router.post("/purchases/{transaction_id}/acknowledge")
    def acknowledge(transaction_id: str, authorization: Annotated[str | None, Header()] = None) -> dict:
        player_id = player_from_token(secret, authorization)
        with database.write() as conn:
            row = get_own(conn, player_id, transaction_id)
            if row["status"] == "pending":
                conn.execute(
                    "UPDATE transactions SET status = 'acknowledged', acknowledged_at = ?"
                    " WHERE transaction_id = ?",
                    (clock.now_iso(), transaction_id),
                )
                row = get_own(conn, player_id, transaction_id)
            return as_json(row)

    return router


def build_audit_router(database: Database) -> APIRouter:
    router = APIRouter()

    @router.get("/audit/store/transactions")
    def transactions(
        player_id: str | None = None,
        status: Literal["pending", "acknowledged"] | None = None,
    ) -> dict:
        query = "SELECT * FROM transactions WHERE 1 = 1"
        args: list = []
        if player_id is not None:
            query += " AND player_id = ?"
            args.append(player_id)
        if status is not None:
            query += " AND status = ?"
            args.append(status)
        with database.read() as conn:
            rows = conn.execute(query + " ORDER BY created_at, transaction_id", args).fetchall()
        return {"server_time": clock.now_iso(), "transactions": [as_json(r) for r in rows]}

    return router
