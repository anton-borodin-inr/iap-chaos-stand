"""Shared fixtures for the stand test suites.

The suites are black-box. They talk to a running stand:

* If `STAND_URL` and `STAND_AUDIT_URL` are set, they use that stand (for
  example the docker compose one). Its defects are whatever it was started with.
* Otherwise a local server is started from `server/` on free ports, with
  `STAND_DEFECTS` passed through from the environment.
"""

import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def stand_urls():
    if os.environ.get("STAND_URL") and os.environ.get("STAND_AUDIT_URL"):
        yield os.environ["STAND_URL"].rstrip("/"), os.environ["STAND_AUDIT_URL"].rstrip("/")
        return
    public_port, audit_port = _free_port(), _free_port()
    data_dir = tempfile.mkdtemp(prefix="stand-test-")
    env = dict(os.environ, DATA_DIR=data_dir, PUBLIC_HOST="127.0.0.1", PUBLIC_PORT=str(public_port),
               AUDIT_HOST="127.0.0.1", AUDIT_PORT=str(audit_port))
    proc = subprocess.Popen([sys.executable, "-m", "stand"], cwd=ROOT / "server", env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    audit = f"http://127.0.0.1:{audit_port}"
    deadline = time.monotonic() + 15
    while True:
        if proc.poll() is not None:
            raise RuntimeError(f"stand exited: {proc.stderr.read().decode()}")
        try:
            if httpx.get(audit + "/audit/health", timeout=1).json()["status"] == "ok":
                break
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            proc.kill()
            raise RuntimeError("stand did not become healthy")
        time.sleep(0.1)
    yield f"http://127.0.0.1:{public_port}", audit
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture
def audit(stand_urls):
    with httpx.Client(base_url=stand_urls[1], timeout=10) as client:
        client.post("/audit/reset").raise_for_status()
        yield client


@pytest.fixture
def api(stand_urls, audit):
    with httpx.Client(base_url=stand_urls[0], timeout=10) as client:
        yield client


class Player:
    def __init__(self, api: httpx.Client, install_id: str | None = None) -> None:
        self.api = api
        self.install_id = install_id or str(uuid.uuid4())
        response = api.post("/players", json={"install_id": self.install_id})
        response.raise_for_status()
        body = response.json()
        self.player_id = body["player_id"]
        self.token = body["token"]
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def get(self, path: str, **kw) -> httpx.Response:
        return self.api.get(path, headers=self.headers, **kw)

    def post(self, path: str, json=None, **kw) -> httpx.Response:
        return self.api.post(path, json=json, headers=self.headers, **kw)

    def tap(self, taps: int, batch_id: str | None = None) -> httpx.Response:
        return self.post("/taps/sync", {"batch_id": batch_id or str(uuid.uuid4()), "taps": taps})

    def spend(self, item: str, spend_id: str | None = None) -> httpx.Response:
        return self.post("/spend", {"spend_id": spend_id or str(uuid.uuid4()), "item": item})

    def store_purchase(self, sku: str, key: str | None = None) -> httpx.Response:
        return self.post("/store/purchases", {"sku": sku, "idempotency_key": key or str(uuid.uuid4())})

    def validate(self, receipt: dict) -> httpx.Response:
        return self.post("/purchases/validate", {"receipt": receipt})

    def ack(self, transaction_id: str) -> httpx.Response:
        return self.post(f"/store/purchases/{transaction_id}/acknowledge")

    def buy(self, sku: str) -> dict:
        """Full happy purchase: store, validate, acknowledge. Returns the validate body."""
        tx = self.store_purchase(sku)
        assert tx.status_code == 201, tx.text
        validated = self.validate(tx.json()["receipt"])
        assert validated.status_code == 200, validated.text
        assert self.ack(tx.json()["transaction_id"]).status_code == 200
        return validated.json()


@pytest.fixture
def player(api) -> Player:
    return Player(api)


@pytest.fixture
def new_player(api):
    return lambda install_id=None: Player(api, install_id)


def check_invariants(audit: httpx.Client, *, after_recovery: bool) -> None:
    """Audit-only invariants (I1, I2, I3, I5, I6, I7) over the whole stand state."""
    state = audit.get("/audit/backend/state").json()
    transactions = audit.get("/audit/store/transactions").json()["transactions"]
    journal, players = state["journal"], state["players"]
    grants = [e for e in journal if e["kind"] == "purchase_grant"]
    refs = {}
    for e in journal:
        refs.setdefault((e["kind"], e["ref"]), []).append(e)
    assert all(len(v) == 1 for v in refs.values()), "I1/I5: key applied twice"
    by_tx = {t["transaction_id"]: t for t in transactions}
    catalog = {"crystals_small": (0, 100), "crystals_medium": (0, 550),
               "crystals_large": (0, 1200), "starter_offer": (2000, 300)}
    for g in grants:
        tx = by_tx.get(g["ref"])
        assert tx is not None, "I7: grant without transaction"
        assert (tx["player_id"], tx["sku"]) == (g["player_id"], g["sku"]), "I7: mismatch"
        coins, crystals = catalog[tx["sku"]]
        assert (g["delta_coins"], g["delta_crystals"]) == (coins * tx["quantity"], crystals * tx["quantity"])
    for p in players:
        coins = crystals = 0
        for e in (e for e in journal if e["player_id"] == p["player_id"]):
            coins += e["delta_coins"]
            crystals += e["delta_crystals"]
            assert (coins, crystals) == (e["coins_after"], e["crystals_after"]), "I3: running sum"
            assert coins >= 0 and crystals >= 0, "I5: negative"
        assert (p["coins"], p["crystals"]) == (coins, crystals), "I3: balance"
        offers = [t for t in transactions if t["player_id"] == p["player_id"] and t["sku"] == "starter_offer"]
        assert len(offers) <= 1, "I6: two offer transactions"
        assert len([g for g in grants if g["player_id"] == p["player_id"]
                    and g["sku"] == "starter_offer"]) <= 1, "I6: two offer grants"
    if after_recovery:
        granted = {g["ref"] for g in grants}
        for t in transactions:
            assert t["status"] == "acknowledged" and t["transaction_id"] in granted, "I2"
