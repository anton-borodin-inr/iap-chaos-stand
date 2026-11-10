"""Game rules (spec/game.md)."""

MAX_LEVEL = 10
BOOSTER_COST_CRYSTALS = 50
BOOSTER_CHARGES = 100
BOOST_FACTOR = 3
TAP_BATCH_MAX = 200
OFFER_SKU = "starter_offer"

# sku -> (title, price_cents, grant coins, grant crystals, one_time)
CATALOG: dict[str, tuple[str, int, int, int, bool]] = {
    "crystals_small": ("Handful of Crystals", 99, 0, 100, False),
    "crystals_medium": ("Pouch of Crystals", 499, 0, 550, False),
    "crystals_large": ("Chest of Crystals", 999, 0, 1200, False),
    "starter_offer": ("Starter Offer", 199, 2000, 300, True),
}


def upgrade_cost(level: int) -> int | None:
    """Coins needed to go from `level` to `level + 1`; None at the max level."""
    if level >= MAX_LEVEL:
        return None
    return 20 * 2 ** (level - 1)


def tap_credit(taps: int, level: int, charges: int) -> tuple[int, int]:
    """Return (credited coins, boosted taps) for one batch."""
    boosted = min(taps, charges)
    return level * (taps + (BOOST_FACTOR - 1) * boosted), boosted


def grant(sku: str, quantity: int) -> tuple[int, int]:
    _, _, coins, crystals, _ = CATALOG[sku]
    return coins * quantity, crystals * quantity
