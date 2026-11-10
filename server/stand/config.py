"""Process configuration from the environment (see spec/launch.md)."""

import os
from dataclasses import dataclass

from . import defects


@dataclass(frozen=True)
class Settings:
    secret: bytes
    backend_defects: frozenset[str]
    offer_window_seconds: int
    data_dir: str
    public_host: str
    public_port: int
    audit_host: str
    audit_port: int


def load() -> Settings:
    registry = defects.load_registry()
    return Settings(
        secret=os.environ.get("RECEIPT_SECRET", "stand-v1-public-dev-secret").encode(),
        backend_defects=defects.parse(os.environ.get("STAND_DEFECTS", ""), registry),
        offer_window_seconds=int(os.environ.get("OFFER_WINDOW_SECONDS", "600")),
        data_dir=os.environ.get("DATA_DIR", "/data"),
        public_host=os.environ.get("PUBLIC_HOST", "0.0.0.0"),
        public_port=int(os.environ.get("PUBLIC_PORT", "8080")),
        audit_host=os.environ.get("AUDIT_HOST", "0.0.0.0"),
        audit_port=int(os.environ.get("AUDIT_PORT", "8090")),
    )
