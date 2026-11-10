"""Backend part of the audit API (spec/audit-api.md)."""

from fastapi import APIRouter

from .. import clock
from ..sqlite import Database
from . import db as bdb


def build_router(database: Database) -> APIRouter:
    router = APIRouter()

    @router.get("/audit/backend/state")
    def state(player_id: str | None = None, after_entry_id: int = 0) -> dict:
        with database.read() as conn:
            if player_id is None:
                players = conn.execute("SELECT * FROM players ORDER BY registered_at, player_id").fetchall()
                journal = conn.execute(
                    "SELECT * FROM journal WHERE entry_id > ? ORDER BY entry_id", (after_entry_id,)
                ).fetchall()
            else:
                players = conn.execute("SELECT * FROM players WHERE player_id = ?", (player_id,)).fetchall()
                journal = conn.execute(
                    "SELECT * FROM journal WHERE player_id = ? AND entry_id > ? ORDER BY entry_id",
                    (player_id, after_entry_id),
                ).fetchall()
            return {
                "server_time": clock.now_iso(),
                "players": [{k: row[k] for k in bdb.PLAYER_FIELDS} for row in players],
                "journal": [{k: row[k] for k in bdb.JOURNAL_FIELDS} for row in journal],
            }

    return router


def reset(database: Database) -> None:
    bdb.reset(database)
