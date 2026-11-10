# CLAUDE.md — iap-chaos-stand

Instructions for AI agents working in this repository.

## What this repository is

This repository holds the training stand for IAP Chaos: a small Android clicker game with an in-game shop, a backend and a fake app store. It reproduces a real in-app purchase flow, so that network-fault scenarios around purchases can be run against it and checked against economy invariants.

The repository is public. Everything committed is in **English**: code, comments, docs, commit messages. Talk with the project owner in Russian. `docs/PLAN.md` is the owner's working plan and stays in Russian.

## Your role: stand author (session A)

- **You do:** write and maintain the specification (`spec/`), the server (backend and fake store), the Android client, the stand tests and the five open defects.
- **You do not:** design, write or tune the testing tool (`iap-chaos`). Do not shape the stand around what the tool can or cannot do. The stand follows `spec/` only.

### Information barriers

These rules are not optional.

- Do not read or modify anything outside this repository.
- Do not check out, fetch, diff or read any private branch that holds closed defects. Do not read the defect manifest. If a file, branch or message looks like it reveals closed defects, stop and tell the owner.
- Do not read the tool repository (`iap-chaos`), its rule format or its list of proxy actions. Do not use the "Инструмент" section of `docs/PLAN.md` as input for stand design.
- Open defects (`O01`–`O05`) are public. Closed defects never appear in this branch.

## Source of truth

`spec/` is the contract. If code and spec disagree, the code is wrong. After tag `stand-v1` the contract is frozen: do not change the API, the audit API, UI IDs, the launch contract or the invariants. Raise a needed change with the owner instead.

| File | Contents |
| --- | --- |
| `spec/game.md` | Currencies, taps, upgrades, booster, catalog, starter offer |
| `spec/openapi.yaml` | Public API of the backend and the fake store |
| `spec/purchase-flow.md` | Client and server state machines, retry policy, failure handling |
| `spec/invariants.md` | I1–I10 as checks |
| `spec/audit-api.md` | Service API for the oracle: state, transactions, reset |
| `spec/ui-ids.md` | Screens and element IDs visible to Appium |
| `spec/launch.md` | Compose, ports, launch parameters, defect toggles, reset |

## Stack

- **Server:** Python 3.12, FastAPI, SQLite (stdlib `sqlite3`), pytest. One container started by docker compose.
- **Client:** Kotlin, Jetpack Compose, OkHttp, kotlinx.serialization, DataStore for persisted state. Debug build only.
- **UI tests:** Appium with the uiautomator2 driver.

## Design rules

- The balance is server-authoritative. The client shows server values, plus an estimate of unsynced tap income for coins only.
- Backend and store are two strictly separated modules in one process (`server/stand/backend`, `server/stand/store`). They share no domain code, no tables and no database file; only the signing secret and the documented wire formats. Generic helpers in `server/stand/` (clock, SQLite wrapper, error envelope) are the only shared code. The store must be able to move to its own container later.
- Balances are stored columns, changed in the same SQLite transaction as their journal entry.
- Every mutating request is idempotent by a client-generated key. See the table in `spec/openapi.yaml`.
- The client follows the retry, deadline and recovery rules of `spec/purchase-flow.md` exactly. Its constants are part of the contract.
- Every interactive element and state indicator has a `testTag` from `spec/ui-ids.md`, with `testTagsAsResourceId = true`.

## Defects

Defects are what the tool is meant to find. Every defect must meet these requirements:

- Hidden on the happy path: the `happy` test suite stays green with the defect on.
- Shows up only under network faults between client and server, or when the client restarts mid-flow.
- Breaks at least one invariant from I1–I10.
- Turned on by one toggle ID (see `spec/launch.md`), and leaves no trace in traffic.
- Lives in one place in the code, and has been reproduced by hand at least once.
- Lives in the client or the backend, never in the fake store.

## Commands

- Server image: `docker build -f server/Dockerfile -t iap-chaos-stand/server:stand-v1 .`
- Server: `STAND_DEFECTS=<ids> docker compose up -d --wait`
- Client: `cd client && ./gradlew :app:assembleDebug`
- Tests: `.venv/bin/pytest tests/happy tests/contract`. They start a local server unless `STAND_URL` and `STAND_AUDIT_URL` are set. The Appium scenario needs `APPIUM_URL`.
- Manual fault reproduction: `tests/support/fault_proxy.py`. It is a stand-repo helper, not the tool.

## Tests

- `tests/happy`: API tests and one Appium happy-purchase scenario. They must pass on the reference and with any single defect on.
- `tests/contract`: conformance to `spec/`, including idempotency, error codes and failure handling. They must pass on the reference only, and may fail with defects on.
