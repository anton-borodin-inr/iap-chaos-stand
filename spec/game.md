# Game rules

Status: stage 0 contract. Frozen at tag `stand-v1`.

The stand is a clicker game with two screens (Main and Shop) and two currencies. All game state lives on the server. The client displays it, with one documented exception: an estimate of not-yet-synced tap income (see [Display rules](#display-rules)).

## Currencies

| Currency | Field | Earned by | Spent on |
| --- | --- | --- | --- |
| Coins | `coins` | Taps, starter offer | Upgrades |
| Crystals | `crystals` | In-app purchases | Booster |

- Both are non-negative integers.
- A new player starts with 0 coins, 0 crystals, upgrade level 1 and 0 booster charges.
- Only the backend changes balances. Every change is one journal entry (see [audit-api.md](audit-api.md)).

## Taps

- One press of the tap button is one tap.
- At upgrade level `L`, a normal tap earns `L` coins and a boosted tap earns `3 × L` coins.
- The client reports taps in batches (`POST /taps/sync`). A batch holds 1 to 200 taps.
- The backend credits a batch when it processes it, using the player's level and booster charges at that moment:

  ```
  boosted  = min(taps, booster_charges)
  credited = L × (taps + 2 × boosted)
  booster_charges -= boosted
  ```

- The client decides when to send a batch: see [purchase-flow.md](purchase-flow.md#8-tap-sync).

## Upgrades

Levels run from 1 to 10. Raising the level from `L` to `L + 1` costs `20 × 2^(L − 1)` coins.

| From | To | Cost (coins) | Tap income after |
| --- | --- | --- | --- |
| 1 | 2 | 20 | 2 |
| 2 | 3 | 40 | 3 |
| 3 | 4 | 80 | 4 |
| 4 | 5 | 160 | 5 |
| 5 | 6 | 320 | 6 |
| 6 | 7 | 640 | 7 |
| 7 | 8 | 1280 | 8 |
| 8 | 9 | 2560 | 9 |
| 9 | 10 | 5120 | 10 |

At level 10 the upgrade is unavailable (`MAX_LEVEL`).

## Booster

- Costs 50 crystals and adds 100 booster charges.
- Charges stack without a limit and never expire.
- Each tap consumes one charge while charges remain (see the formula above).

## Spending

- Upgrades and boosters are bought with `POST /spend`, item `upgrade` or `booster`.
- If the balance is insufficient, the spend is rejected (`INSUFFICIENT_FUNDS`) and nothing changes.
- The client flushes queued taps before it sends a spend.

## Catalog

The shop sells four products. Every store transaction has quantity 1. The grant for a transaction is the product grant multiplied by the quantity.

| SKU | Title | Price (USD cents) | Grant | Type |
| --- | --- | --- | --- | --- |
| `crystals_small` | Handful of Crystals | 99 | 100 crystals | Consumable |
| `crystals_medium` | Pouch of Crystals | 499 | 550 crystals | Consumable |
| `crystals_large` | Chest of Crystals | 999 | 1200 crystals | Consumable |
| `starter_offer` | Starter Offer | 199 | 300 crystals + 2000 coins | One-time |

Money exists only in the fake store. The store always approves a payment: there is no card decline and no user cancellation. The backend never handles prices. It only shows them in the catalog.

## Starter offer

- **Window.** The offer is shown from the player's registration time `registered_at` for 600 seconds: `expires_at = registered_at + 600 s`. The server reads the window length from `OFFER_WINDOW_SECONDS`. The contract value is 600, and runs must use it; other values are for manual exploration only.
- **One-time.** The store sells `starter_offer` at most once per player. A second purchase with a different idempotency key is rejected with `409 ALREADY_PURCHASED`. A repeat with the same key returns the original transaction. The backend also refuses a second grant (`409 OFFER_ALREADY_OWNED`). While the store behaves correctly, that refusal cannot be reached.
- **Timer is advisory.** The backend catalog reports `expires_at` and an offer status, and the client disables the buy button after expiry. The store does not check the timer. A paid offer is always granted, even after the timer has expired. A purchase after expiry is not a violation.
- **Status** as reported by `GET /catalog` and shown in the UI:

  | Status | Condition |
  | --- | --- |
  | `purchased` | The journal holds a `starter_offer` grant for the player |
  | `available` | Not purchased, and server time < `expires_at` |
  | `expired` | Not purchased, and server time ≥ `expires_at` |

  An offer that is paid but not yet granted is reported as `available` or `expired`. If the client tries to buy it again, the store answers `409 ALREADY_PURCHASED` and the client runs pending-purchase recovery, which grants it (see [purchase-flow.md](purchase-flow.md#5-client-purchase-state-machine)).

## Display rules

- Crystals on screen always equal the last server snapshot the client accepted.
- Coins on screen equal that server value plus an estimate of the income from taps that are queued or in flight. The estimate is not normative. When the tap queue is empty and no batch is in flight, coins on screen must equal the snapshot value exactly.
- Before the first snapshot arrives, both balances show `-`.

## Who enforces what

| Rule | Enforced by |
| --- | --- |
| Balances, tap income, upgrade and booster costs, one grant per transaction | Backend |
| Prices, idempotent purchase creation, one-time sale of `starter_offer` | Store |
| Offer timer | Backend catalog and client UI, advisory only |
| Receipt authenticity | Store signs, backend verifies (shared secret) |
