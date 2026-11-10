"""Player tokens (issued here) and receipts (verified here)."""

import base64
import binascii
import hashlib
import hmac
import json
import re

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _mac(secret: bytes, message: str) -> str:
    return hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()


def issue_token(secret: bytes, player_id: str) -> str:
    return f"v1.{player_id}.{_mac(secret, 'player.v1.' + player_id)}"


def verify_token(secret: bytes, token: str) -> str | None:
    """Return the player ID of a correctly signed token, else None."""
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != "v1" or not UUID_RE.match(parts[1]):
        return None
    if not hmac.compare_digest(parts[2], _mac(secret, "player.v1." + parts[1])):
        return None
    return parts[1]


class MalformedReceipt(ValueError):
    pass


def decode_payload(payload: str) -> dict:
    try:
        raw = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise MalformedReceipt(str(exc)) from exc
    if not isinstance(data, dict):
        raise MalformedReceipt("payload is not an object")
    checks = (
        data.get("v") == 1,
        isinstance(data.get("transaction_id"), str) and UUID_RE.match(data["transaction_id"]),
        isinstance(data.get("player_id"), str) and UUID_RE.match(data["player_id"]),
        isinstance(data.get("sku"), str),
        type(data.get("quantity")) is int and data["quantity"] >= 1,
        isinstance(data.get("purchased_at"), str),
    )
    if not all(checks):
        raise MalformedReceipt("payload fields are invalid")
    return data


def receipt_signature_ok(secret: bytes, payload: str, signature: str) -> bool:
    return hmac.compare_digest(signature, _mac(secret, "receipt.v1." + payload))
