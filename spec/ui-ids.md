# UI identifiers

Status: stage 0 contract. Frozen at tag `stand-v1`.

This is every screen, interactive element and state indicator of the client that the oracle and flows can rely on. Elements not listed here are not part of the contract.

## Locating elements

- Every listed element has a Compose `testTag` equal to its ID. The root sets `testTagsAsResourceId = true`, so Appium (uiautomator2) sees the ID as `resource-id` exactly, without a package prefix.
- The robust locator is `-android uiautomator` with `new UiSelector().resourceId("<id>")`, or XPath `//*[@resource-id='<id>']`. A plain `id` locator may get the app package prepended by the driver and is not guaranteed.
- `<sku>` in an ID stands for one of `crystals_small`, `crystals_medium`, `crystals_large`, `starter_offer`.

## Value formats

- **State indicators** show their state token as their visible text, exactly: lowercase, no extra words.
- **Numeric values** are base-10 integers without separators or units, for example `2140`. Before the first snapshot they show `-`.
- **IDs** (player, transaction) are the lowercase UUID, or empty text when unknown.
- **Enabled state** is the Appium `enabled` attribute. Disabled elements stay present.

## Screens

Exactly one screen root is present at a time.

| ID | Screen | Shown when |
| --- | --- | --- |
| `screen_main` | Main | Default after launch |
| `screen_shop` | Shop | After `nav_shop` |
| `screen_config_error` | Config error | The launch config has an unknown defect ID or an invalid `backend_url`. No requests are made |

## Global elements (on Main and Shop)

| ID | Kind | Value | Enabled |
| --- | --- | --- | --- |
| `coins_value` | Number | Server coins + estimate of unsynced taps (see [game.md](game.md#display-rules)) | — |
| `crystals_value` | Number | Server crystals | — |
| `player_id_value` | Text | Player ID from the stored token | — |
| `sync_status` | State | `syncing`, `idle` or `error` (see [purchase-flow.md §7](purchase-flow.md#7-startup-sequence-and-sync-status)) | — |
| `sync_retry` | Button | Present only when `sync_status` = `error` | Always |

## Main screen

| ID | Kind | Value | Enabled |
| --- | --- | --- | --- |
| `tap_button` | Button | — | Always |
| `tap_income_value` | Number | Coins per normal tap (level) | — |
| `upgrade_level_value` | Number | 1–10 | — |
| `upgrade_cost_value` | Number | Next cost, or `-` at level 10 | — |
| `upgrade_button` | Button | — | `spend_state` ≠ `in_progress`, startup finished, level < 10 |
| `booster_charges_value` | Number | Charges left | — |
| `booster_cost_value` | Number | `50` | — |
| `booster_button` | Button | — | `spend_state` ≠ `in_progress`, startup finished |
| `spend_state` | State | `idle`, `in_progress`, `success` or `error` | — |
| `spend_error_code` | Text | `unavailable`, `insufficient_funds`, `max_level` or `rejected` when `spend_state` = `error`, else empty | — |
| `spend_retry` | Button | Present only when `spend_state` = `error` | Always |
| `spend_dismiss` | Button | Present only when `spend_state` is `success` or `error` | Always |
| `nav_shop` | Button | — | `spend_state` ≠ `in_progress` |

Balances are not checked on the client. A spend the player cannot afford is sent and ends in `error` / `insufficient_funds`.

## Shop screen

| ID | Kind | Value | Enabled |
| --- | --- | --- | --- |
| `nav_back` | Button | — | `purchase_state` ≠ `in_progress` |
| `catalog_state` | State | `loading`, `ready` or `error` | — |
| `catalog_retry` | Button | Present only when `catalog_state` = `error` | Always |
| `product_<sku>` | Container | Card of one product. Present when `catalog_state` = `ready` | — |
| `product_<sku>_price` | Text | Price, for example `$0.99` | — |
| `product_<sku>_grant` | Text | For example `100 crystals`, `300 crystals + 2000 coins` | — |
| `buy_<sku>` | Button | — | See below |
| `offer_status` | State | `available`, `expired` or `purchased` | — |
| `offer_timer` | Text | Time left as `mm:ss`; `00:00` when expired; empty when purchased | — |
| `purchase_state` | State | `idle`, `in_progress`, `success` or `error`. Always present on the Shop screen | — |
| `purchase_sku` | Text | SKU of the current purchase, empty when `idle` | — |
| `purchase_transaction_id` | Text | Transaction ID when `success`; the known transaction ID or empty when `error`; empty otherwise | — |
| `purchase_error_code` | Text | `unavailable`, `invalid_receipt`, `already_purchased` or `rejected` when `error`, else empty | — |
| `purchase_message` | Text | Human-readable result. Not for assertions | — |
| `purchase_retry` | Button | Present only when `purchase_state` = `error` | Always |
| `purchase_dismiss` | Button | Present only when `purchase_state` is `success` or `error` | Always |

A `buy_<sku>` button is enabled only when all of these hold:

- `catalog_state` = `ready`;
- `purchase_state` = `idle`;
- the startup sequence has finished;
- for `buy_starter_offer` only: `offer_status` = `available`.

The offer timer counts down locally, from `expires_at − server_time` of the last catalog response, using a monotonic clock. At zero, `offer_status` becomes `expired` without a new request.

Leaving the Shop (`nav_back`) while `purchase_state` is `success` or `error` dismisses it. Coming back shows `idle`.

## Terminal states

| Indicator | Terminal values | Leaves terminal state by |
| --- | --- | --- |
| `purchase_state` | `success`, `error` | `purchase_dismiss` or `nav_back` → `idle`; `purchase_retry` → `in_progress` |
| `spend_state` | `success`, `error` | `spend_dismiss` → `idle`; `spend_retry`, `upgrade_button` or `booster_button` → `in_progress` |
| `sync_status` | `idle`, `error` | New work → `syncing` (automatic retry from `error` every 10 s) |
| `catalog_state` | `ready`, `error` | `catalog_retry` or reopening the Shop → `loading` |

Terminal states persist until left by one of the actions above. They are never cleared by a timer. After a process restart, `purchase_state` and `spend_state` start at `idle`.

## Responsiveness check (I8b)

From a terminal `purchase_state`, tap `purchase_dismiss`. `purchase_state` must read `idle` within 3 s. The same applies to `spend_state` with `spend_dismiss`.
