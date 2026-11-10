# Audit API

Status: stage 0 contract. Frozen at tag `stand-v1`.

The audit API is the oracle's direct, read-mostly access to server state. It runs on its own port. The client never calls it, and it must never be routed through the fault-injecting proxy.

## Access

- Base URL from the host: `http://127.0.0.1:8090`. It is published only on the loopback interface (see [launch.md](launch.md)).
- No authentication.
- JSON bodies and the error envelope follow [openapi.yaml](openapi.yaml). Timestamps are RFC 3339 UTC with milliseconds.
- The public port (8080) does not serve `/audit/*`, and the audit port serves nothing else.

## Confidentiality of defect toggles

No audit response, header or error reveals which defects are enabled, which defect IDs exist, or the value of the signing secret.

## Endpoints

### `GET /audit/health`

```json
{ "status": "ok", "contract": "stand-v1", "server_time": "2026-11-10T12:00:00.123Z" }
```

`status` is `ok` once both modules have opened their databases. The compose health check uses it.

### `GET /audit/backend/state`

Players and journal, read in one database transaction, so the two are consistent with each other.

| Query parameter | Default | Meaning |
| --- | --- | --- |
| `player_id` | — | Limit to one player |
| `after_entry_id` | 0 | Return only journal entries with a greater `entry_id` |

```json
{
  "server_time": "2026-11-10T12:00:05.000Z",
  "players": [
    {
      "player_id": "6f1c…",
      "install_id": "0b9e…",
      "registered_at": "2026-11-10T12:00:00.000Z",
      "offer_expires_at": "2026-11-10T12:10:00.000Z",
      "coins": 2140,
      "crystals": 250,
      "upgrade_level": 2,
      "booster_charges": 60,
      "version": 7
    }
  ],
  "journal": [
    {
      "entry_id": 7,
      "created_at": "2026-11-10T12:00:04.512Z",
      "player_id": "6f1c…",
      "kind": "purchase_grant",
      "ref": "a3d2…",
      "sku": "starter_offer",
      "item": null,
      "taps": null,
      "boosted_taps": null,
      "delta_coins": 2000,
      "delta_crystals": 300,
      "coins_after": 2140,
      "crystals_after": 250,
      "upgrade_level_after": 2,
      "booster_charges_after": 60
    }
  ]
}
```

#### Player row

| Field | Type | Meaning |
| --- | --- | --- |
| `player_id` | uuid | |
| `install_id` | uuid | The key the player was registered with |
| `registered_at` | timestamp | |
| `offer_expires_at` | timestamp | `registered_at` + offer window |
| `coins`, `crystals` | int | Stored balance columns, not computed from the journal |
| `upgrade_level` | int 1–10 | |
| `booster_charges` | int | |
| `version` | int | `entry_id` of the player's latest journal entry, 0 if none |

#### Journal entry

The backend writes one entry per applied state change. Rejected requests and idempotent repeats write nothing.

| Field | Type | Meaning |
| --- | --- | --- |
| `entry_id` | int | Strictly increasing across all players, starting at 1 after a reset |
| `created_at` | timestamp | Server time of the commit |
| `player_id` | uuid | |
| `kind` | `tap_batch`, `spend` or `purchase_grant` | |
| `ref` | uuid | Idempotency key: `batch_id`, `spend_id` or `transaction_id` respectively. `(kind, ref)` is unique |
| `sku` | sku or null | `purchase_grant` only |
| `item` | `upgrade`, `booster` or null | `spend` only |
| `taps` | int or null | `tap_batch` only: raw taps in the batch |
| `boosted_taps` | int or null | `tap_batch` only |
| `delta_coins`, `delta_crystals` | int | Signed change. Taps and grants are ≥ 0, spends are ≤ 0 |
| `coins_after`, `crystals_after` | int | Balances right after this entry |
| `upgrade_level_after`, `booster_charges_after` | int | State right after this entry |

Entries are returned in `entry_id` order.

### `GET /audit/store/transactions`

| Query parameter | Default | Meaning |
| --- | --- | --- |
| `player_id` | — | Limit to one player |
| `status` | — | `pending` or `acknowledged` |

```json
{
  "server_time": "2026-11-10T12:00:05.000Z",
  "transactions": [
    {
      "transaction_id": "a3d2…",
      "player_id": "6f1c…",
      "sku": "starter_offer",
      "quantity": 1,
      "price_cents": 199,
      "currency": "USD",
      "status": "acknowledged",
      "idempotency_key": "c71e…",
      "created_at": "2026-11-10T12:00:03.900Z",
      "acknowledged_at": "2026-11-10T12:00:04.700Z",
      "receipt": { "payload": "eyJ2Ijox…", "signature": "9f2c…" }
    }
  ]
}
```

The fields match `StoreTransaction` in [openapi.yaml](openapi.yaml). Transactions are ordered by `created_at`, then `transaction_id`. They are never deleted except by a reset.

### `POST /audit/reset`

Empties both databases: players, journal, idempotency records and store transactions. Then `entry_id` restarts at 1. The signing secret and enabled defects do not change.

- Request body: none.
- Response `200`: `{ "reset_at": "<timestamp>" }`.
- It is synchronous. When it returns, every audit read shows empty state.
- Requests in flight during a reset have undefined results. The caller must stop the client first (see [launch.md](launch.md#full-reset)).
- Tokens issued before a reset still pass signature checks. The backend answers them with `401 PLAYER_NOT_FOUND`.

## Module boundary

`/audit/backend/*` reads only the backend database, and `/audit/store/*` reads only the store database. `/audit/reset` calls each module's own reset. If the store later moves to its own container, its audit routes move with it. Keeping the prefixes means callers do not change.
