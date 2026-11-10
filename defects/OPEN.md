# Open defects

The open set is public. Its purpose is to debug the runner, the oracle and the prompts. Each defect is switched on by its ID (see [spec/launch.md](../spec/launch.md#defect-toggles)), lives in one place in the code, keeps the `happy` suite green, and was reproduced by hand on the Android emulator.

Reproduction uses the helper proxy [tests/support/fault_proxy.py](../tests/support/fault_proxy.py) between the client and the server:

```bash
.venv/bin/python tests/support/fault_proxy.py --listen 8081 --method <METHOD> --path <PATH> --fault <FAULT>
```

Run the server with `STAND_DEFECTS=<ID>`, do a full reset, and launch the client with `--es backend_url http://10.0.2.2:8081 --es defects <ID>`. "Recovery" below is the sequence from [spec/invariants.md](../spec/invariants.md#recovery). With the same scenario and the defect off, no invariant is violated.

| ID | Component | Category | Description | Shows up when | Breaks |
| --- | --- | --- | --- | --- | --- |
| O01 | Client | Retries, idempotency | A retry of `POST /store/purchases` sends a new idempotency key instead of the purchase's key | The store processed the purchase but the response did not reach the client in time | I10 |
| O02 | Client | Recovery of unclosed purchases | The client acknowledges the transaction before validating it | Validation does not complete: a final 4xx, or the app stops between acknowledge and validate | I2 |
| O03 | Client | UI states, trusting responses | A final non-receipt 4xx from validation is shown as a successful purchase | Validation is answered with such an error without being processed | I9, then I2 |
| O04 | Backend | Idempotency | Booster spends are not deduplicated by `spend_id` (upgrades are) | A booster spend is processed and its response is lost, so the client retries | I5 |
| O05 | Backend | Idempotency | Validating an already granted transaction fails with `500` instead of returning the earlier result | A validation is processed and its response is lost, so the client retries | I2, I8 (c) |

## Reproduction steps

**O01.** Fault: `--method POST --path /store/purchases --fault late`.
1. Open the shop and buy `crystals_small`.
2. The screen shows `success`, but the audit API lists two store transactions for one buy press: I10 is violated.
3. After recovery, both transactions are granted and acknowledged. The player paid twice.

**O02.** Fault: `--method POST --path /purchases/validate --fault status:403`.
1. Buy `crystals_small`. The screen shows `error` / `rejected`.
2. The store transaction is already `acknowledged` and not granted.
3. After recovery it is still not granted, because recovery only sees pending transactions: I2 is violated.

**O03.** Fault: `--method POST --path /purchases/validate --fault status:403`.
1. Buy `crystals_small`. The screen shows `success`, but the journal has no grant for `purchase_transaction_id`: I9 is violated.
2. The client acknowledged the transaction, so after recovery it stays acknowledged and not granted: I2 is violated.

**O04.** Fault: `--method POST --path /spend --fault late`.
1. Buy `crystals_small` and dismiss the result.
2. On the main screen, tap `booster_button`. The screen shows `success`.
3. The journal holds two `spend` entries with the same `ref`, and 100 crystals were charged instead of 50: I5 is violated.

**O05.** Fault: `--method POST --path /purchases/validate --fault late`.
1. Buy `crystals_small`. The first validation grants, and its response is lost. Both retries get `500`, so the screen shows `error` / `unavailable`.
2. After recovery, every startup validation also gets `500`. `sync_status` never reaches `idle` (I8 (c)), and the transaction stays `pending` (I2).
