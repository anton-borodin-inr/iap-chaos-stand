"""Backend database: players and the journal.

Balances are stored columns. Every change writes one journal entry and updates
the player row in the same transaction. The journal is also the idempotency
record: `(kind, ref)` identifies an applied batch, spend or grant.
"""

import sqlite3

from ..sqlite import Database

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    player_id TEXT PRIMARY KEY,
    install_id TEXT NOT NULL UNIQUE,
    registered_at TEXT NOT NULL,
    offer_expires_at TEXT NOT NULL,
    coins INTEGER NOT NULL,
    crystals INTEGER NOT NULL,
    upgrade_level INTEGER NOT NULL,
    booster_charges INTEGER NOT NULL,
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS journal (
    entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    player_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    ref TEXT NOT NULL,
    sku TEXT,
    item TEXT,
    taps INTEGER,
    boosted_taps INTEGER,
    delta_coins INTEGER NOT NULL,
    delta_crystals INTEGER NOT NULL,
    coins_after INTEGER NOT NULL,
    crystals_after INTEGER NOT NULL,
    upgrade_level_after INTEGER NOT NULL,
    booster_charges_after INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS journal_kind_ref ON journal (kind, ref);
CREATE INDEX IF NOT EXISTS journal_player ON journal (player_id, entry_id);
"""

PLAYER_FIELDS = (
    "player_id", "install_id", "registered_at", "offer_expires_at", "coins", "crystals",
    "upgrade_level", "booster_charges", "version",
)
JOURNAL_FIELDS = (
    "entry_id", "created_at", "player_id", "kind", "ref", "sku", "item", "taps", "boosted_taps",
    "delta_coins", "delta_crystals", "coins_after", "crystals_after", "upgrade_level_after",
    "booster_charges_after",
)


def open_db(path: str) -> Database:
    db = Database(path, SCHEMA)
    db.init()
    return db


def reset(db: Database) -> None:
    with db.write() as conn:
        conn.execute("DELETE FROM journal")
        conn.execute("DELETE FROM players")
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'journal'")


def find_entry(conn: sqlite3.Connection, kind: str, ref: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM journal WHERE kind = ? AND ref = ? ORDER BY entry_id LIMIT 1", (kind, ref)
    ).fetchone()


def has_offer_grant(conn: sqlite3.Connection, player_id: str, offer_sku: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM journal WHERE kind = 'purchase_grant' AND player_id = ? AND sku = ? LIMIT 1",
        (player_id, offer_sku),
    ).fetchone()
    return row is not None


def append(
    conn: sqlite3.Connection,
    player: sqlite3.Row,
    *,
    created_at: str,
    kind: str,
    ref: str,
    delta_coins: int = 0,
    delta_crystals: int = 0,
    level: int | None = None,
    charges: int | None = None,
    sku: str | None = None,
    item: str | None = None,
    taps: int | None = None,
    boosted_taps: int | None = None,
) -> int:
    """Write one journal entry and the new player state. Returns the entry ID."""
    coins = player["coins"] + delta_coins
    crystals = player["crystals"] + delta_crystals
    level = player["upgrade_level"] if level is None else level
    charges = player["booster_charges"] if charges is None else charges
    if coins < 0 or crystals < 0:
        raise ValueError("balance would become negative")
    cursor = conn.execute(
        "INSERT INTO journal (created_at, player_id, kind, ref, sku, item, taps, boosted_taps,"
        " delta_coins, delta_crystals, coins_after, crystals_after, upgrade_level_after,"
        " booster_charges_after) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (created_at, player["player_id"], kind, ref, sku, item, taps, boosted_taps,
         delta_coins, delta_crystals, coins, crystals, level, charges),
    )
    entry_id = cursor.lastrowid
    conn.execute(
        "UPDATE players SET coins = ?, crystals = ?, upgrade_level = ?, booster_charges = ?,"
        " version = ? WHERE player_id = ?",
        (coins, crystals, level, charges, entry_id, player["player_id"]),
    )
    return entry_id
