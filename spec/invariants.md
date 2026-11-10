# Invariants

Status: stage 0 contract. Frozen at tag `stand-v1`.

These are the economy and UI invariants of the stand, written as checks. Breaking any of them is a finding. The reference stand keeps all of them under the fault model of [purchase-flow.md](purchase-flow.md#1-assumptions-and-guarantee).

## Data sources

| Symbol | Source | How it is read |
| --- | --- | --- |
| `P` | Backend players | `GET /audit/backend/state` → `players` ([audit-api.md](audit-api.md)) |
| `J` | Backend journal | `GET /audit/backend/state` → `journal`. Read in the same database transaction as `P` |
| `T` | Store transactions | `GET /audit/store/transactions` |
| `S` | Screen | Appium, by the resource IDs in [ui-ids.md](ui-ids.md) |
| `F` | Flow counters | Supplied by whoever runs the flow (see [I10](#i10--no-more-traces-than-actions)) |
| `GRANT[sku]` | Static catalog | [game.md](game.md#catalog) |

`P`, `J` and `T` always come from the audit port, never through the proxy. A scenario starts from a full reset (see [launch.md](launch.md#full-reset)), so the sets cover exactly one scenario. In the reference, `P` holds exactly one player per scenario.

Journal entry fields used below: `entry_id`, `player_id`, `kind` (`tap_batch`, `spend` or `purchase_grant`), `ref`, `sku`, `taps`, `delta_coins`, `delta_crystals`, `coins_after`, `crystals_after`.

## Check moments

| Moment | Definition |
| --- | --- |
| `imm` (immediately) | The flow's last triggering action reached its terminal state (`purchase_state` or `spend_state` is `success` or `error`), or N expired. The audit read follows right after the screen read. |
| `rec` (after recovery) | The recovery sequence below has finished. |

If the scenario itself killed or restarted the app during an action, that action has no terminal state. In that case I8a, I8b and I9 are not evaluated for it at `imm`, and every other check still runs.

### Recovery

1. Remove the fault: from now on, every call is delivered and answered normally.
2. Wait P1 = 5 s.
3. Restart the app: force-stop, then launch without extras (see [launch.md](launch.md#restart)).
4. Wait until `sync_status` = `idle`, polling, for at most R = 60 s.
5. Wait P2 = 2 s.
6. Read `S`, then `P`, `J` and `T`.

If step 4 times out, I8c is violated, and I4 is reported as not evaluated (it is defined only at `idle`).

### Constants

| Constant | Value | Why |
| --- | --- | --- |
| N | 60 s | Client action deadline (45 s) plus margin for UI and Appium |
| Responsiveness timeout | 3 s | I8b |
| P1 | 5 s | Lets in-flight responses settle after the fault is removed |
| R | 60 s | Startup with every call succeeding takes a few seconds; 60 s covers several worst-case calls |
| P2 | 2 s | Lets the last snapshot render |

## I1 — One transaction, at most one grant

- **Condition:** for every `t`: `|{ e ∈ J : e.kind = purchase_grant ∧ e.ref = t }| ≤ 1`.
- **Sources:** `J`.
- **When:** `imm`, `rec`.

## I2 — Every paid transaction is granted and closed

- **Condition:** for every `tx ∈ T`: `tx.status = acknowledged` and there is an `e ∈ J` with `e.kind = purchase_grant ∧ e.ref = tx.transaction_id`.
- **Sources:** `T`, `J`.
- **When:** `rec` only. At `imm` a background acknowledge may still be running.
- **Priority:** if I2 conflicts with another invariant, I2 wins. For example, a transaction that is acknowledged but not granted must be granted.

## I3 — Server balance equals the journal

- **Condition:** for every player `p ∈ P` and currency `c ∈ {coins, crystals}`:
  - `p.c = Σ e.delta_c` over `e ∈ J` with `e.player_id = p.player_id`;
  - the running sum, taken in `entry_id` order, equals `e.c_after` at every entry.
- **Sources:** `P`, `J`, from one consistent read.
- **When:** `imm`, `rec`.

## I4 — Screen balance equals the server

- **Condition:**
  - `S.sync_status = idle`;
  - `S.coins_value = P[S.player_id_value].coins`;
  - `S.crystals_value = P[S.player_id_value].crystals`.
- **Sources:** `S`, `P`.
- **When:** `rec`, at step 6 of recovery.
- **Note:** the plan named `GET /player` as the source. The audit player row is used instead, so the proxy cannot affect the check.

## I5 — No negative balance, no double application

- **Condition:**
  - (a) for every `e ∈ J`: `e.coins_after ≥ 0 ∧ e.crystals_after ≥ 0`, and for every `p ∈ P`: `p.coins ≥ 0 ∧ p.crystals ≥ 0`;
  - (b) for every `ref`: `|{ e ∈ J : e.kind = spend ∧ e.ref = ref }| ≤ 1`, where `ref` is the `spend_id`;
  - (c) for every `ref`: `|{ e ∈ J : e.kind = tap_batch ∧ e.ref = ref }| ≤ 1`, where `ref` is the `batch_id`.
- **Sources:** `J`, `P`.
- **When:** `imm`, `rec`.
- **Limit:** (b) and (c) catch a key applied twice. They cannot catch a client that sends one action under two keys. I10 covers that case for taps and purchases.

## I6 — The one-time offer is bought at most once

- **Condition:** for every player `p`:
  - `|{ tx ∈ T : tx.player_id = p ∧ tx.sku = starter_offer }| ≤ 1`;
  - `|{ e ∈ J : e.kind = purchase_grant ∧ e.player_id = p ∧ e.sku = starter_offer }| ≤ 1`.
- **Sources:** `T`, `J`.
- **When:** `imm`, `rec`.
- **Not a violation:** buying the offer after its timer expired ([game.md](game.md#starter-offer)).

## I7 — No grant without a matching paid transaction

- **Condition:** for every `e ∈ J` with `e.kind = purchase_grant`, there is a `tx ∈ T` with:
  - `tx.transaction_id = e.ref`;
  - `tx.player_id = e.player_id`;
  - `tx.sku = e.sku`;
  - `(e.delta_coins, e.delta_crystals) = GRANT[tx.sku] × tx.quantity`.
- **Sources:** `J`, `T`, `GRANT`.
- **When:** `imm`, `rec`.
- **What it covers:** grants from forged receipts (unknown transaction, other player, changed SKU or amount) and grants for another player's receipt.
- **Cannot be checked:** a grant made from a receipt with a bad signature whose content exactly matches a real transaction of the same player. The audit API does not record the validated signature, and the oracle does not hold the secret. The effect equals a legitimate grant, so balances are not harmed. A backend that skips the signature check is caught only when the forged content differs from a real transaction.

## I8 — The client reaches a terminal state and stays responsive

- **(a) Terminal state.** After a tap on `buy_<sku>`, `purchase_retry`, `upgrade_button`, `booster_button` or `spend_retry`, the matching state (`purchase_state` or `spend_state`) reaches `success` or `error` within N = 60 s.
- **(b) Responsive.** After (a), a tap on `purchase_dismiss` (or `spend_dismiss`) sets the state to `idle` within 3 s.
- **(c) Sync settles.** During recovery, `sync_status` reaches `idle` within R = 60 s after the restart.
- **Process alive.** In (a), (b) and (c), the app process must stay alive and in the foreground. A crash or ANR is a violation.
- **Sources:** `S`.
- **When:** (a) and (b) at `imm`, (c) at `rec`.

## I9 — Success is shown only with a grant

- **Condition:** at the moment `purchase_state` becomes terminal:
  - if it is `success`, then `S.purchase_transaction_id` is a transaction ID `t`, and `J` contains a `purchase_grant` with `ref = t` for player `S.player_id_value`;
  - if `J` has no grant for the purchase, the state is `error`.
- `error` while a grant exists is allowed: a response was lost, and recovery fixes the display (I4).
- **Sources:** `S`, `J`. `J` is read right after the screen.
- **When:** `imm`.
- **Note:** together with I8a, the two clauses mean: `success ⇒ granted`, and `not granted ⇒ error`.

## I10 — No more traces than actions

- **Condition:**
  - `|T| ≤ F.buy_presses`: store transactions are not more than presses of any `buy_<sku>` button since the reset;
  - `Σ e.taps` over `e ∈ J` with `e.kind = tap_batch` is at most `F.taps_made`: credited taps are not more than presses of `tap_button` since the reset.
- **Sources:** `T`, `J`, `F`.
- **When:** `imm`, `rec`.
- **Counters come from the flow.** `F.buy_presses` and `F.taps_made` are not available through the audit API or the screen. Whoever runs the flow must count its own taps and supply them. Retry, dismiss and navigation taps are not counted.
- **Why taps are counted, not coins:** a journal `tap_batch` entry stores the raw tap count, so the comparison does not depend on booster charges or level.
- **Trust boundary:** the server credits the tap count a batch reports (see [purchase-flow.md §1](purchase-flow.md#1-assumptions-and-guarantee)). A batch whose count differs from the taps actually made breaks I10 even on the reference.

## Checkability summary

| ID | Audit | Screen | Flow counters | Fully checkable through the contract |
| --- | --- | --- | --- | --- |
| I1 | ✓ | | | Yes |
| I2 | ✓ | | | Yes |
| I3 | ✓ | | | Yes |
| I4 | ✓ | ✓ | | Yes, when `sync_status` reaches `idle` |
| I5 | ✓ | | | Yes |
| I6 | ✓ | | | Yes |
| I7 | ✓ | | | Partly: signature validity itself is not observable (see I7) |
| I8 | | ✓ | | Yes |
| I9 | ✓ | ✓ | | Yes |
| I10 | ✓ | | ✓ | Only with counters supplied by the flow |
