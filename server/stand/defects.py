"""Defect toggles (see spec/launch.md, "Defect toggles").

The registry lists every defect ID this build contains and the component it
belongs to. Toggles never change anything visible on the happy path.
"""

import json
import os
import re
from pathlib import Path

ID_PATTERN = re.compile(r"^[A-Z][0-9]{2}$")
COMPONENTS = {"client", "backend"}


class UnknownDefectError(ValueError):
    pass


def registry_path() -> Path:
    override = os.environ.get("STAND_DEFECT_REGISTRY")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "defects" / "registry.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("defects/registry.json not found")


def load_registry() -> dict[str, str]:
    data = json.loads(registry_path().read_text())
    for defect_id, component in data.items():
        if not ID_PATTERN.match(defect_id) or component not in COMPONENTS:
            raise ValueError(f"bad registry entry {defect_id}: {component}")
    return data


def parse(raw: str, registry: dict[str, str]) -> frozenset[str]:
    """Parse a comma-separated list and return the IDs that belong to the backend."""
    ids = [part.strip() for part in raw.split(",") if part.strip()]
    for defect_id in ids:
        if defect_id not in registry:
            raise UnknownDefectError(f"unknown defect id: {defect_id}")
    return frozenset(i for i in ids if registry[i] == "backend")


_enabled: frozenset[str] = frozenset()


def configure(backend_ids: frozenset[str]) -> None:
    global _enabled
    _enabled = backend_ids


def on(defect_id: str) -> bool:
    return defect_id in _enabled
