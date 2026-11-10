# IAP Chaos Stand

A training stand for testing in-app purchases under network faults. It is a small Android clicker game with an in-game shop, a backend and a fake app store. It reproduces a real purchase flow: catalog, payment in the store, server-side receipt validation, grant, and closing the transaction.

The stand is the system under test for IAP Chaos, a tool that injects network faults around purchases and checks economy invariants. The stand knows nothing about the tool. The contract between them is in [`spec/`](spec/).

## Contents

| Path | What |
| --- | --- |
| [`spec/`](spec/) | The contract: game rules, OpenAPI, purchase flow and failure handling, invariants I1–I10, audit API, UI IDs, launch |
| [`server/`](server/) | Backend and fake store: Python 3.12, FastAPI, SQLite. Two isolated modules in one process |
| [`client/`](client/) | Android client: Kotlin, Jetpack Compose |
| [`tests/happy`](tests/happy) | Happy-path API tests and an Appium purchase scenario. Green on the reference and with any single defect |
| [`tests/contract`](tests/contract) | Conformance to the spec: idempotency, error codes, concurrency. Green on the reference |
| [`defects/`](defects/) | Defect registry and the [open defects](defects/OPEN.md) |

## Quick start

You need Docker, the Android SDK with an emulator, JDK 17, and Python 3.12 with [uv](https://docs.astral.sh/uv/).

```bash
docker build -f server/Dockerfile -t iap-chaos-stand/server:stand-v1 .
```

```bash
STAND_DEFECTS= docker compose up -d --wait
```

```bash
(cd client && ./gradlew :app:assembleDebug)
```

```bash
adb install -r client/app/build/outputs/apk/debug/app-debug.apk
```

```bash
adb shell am start -W -n dev.iapchaos.stand/.MainActivity --es backend_url http://10.0.2.2:8080 --es defects '""'
```

The public API listens on port 8080, and the audit API on `127.0.0.1:8090`. See [spec/launch.md](spec/launch.md) for reset, restart and defect toggles.

## Tests

```bash
uv venv -p 3.12 .venv && uv pip install --python .venv/bin/python -r tests/requirements.txt
```

```bash
.venv/bin/pytest tests/happy tests/contract
```

Without `STAND_URL`, the tests start a local server themselves. To run them against the compose stand, set `STAND_URL=http://127.0.0.1:8080` and `STAND_AUDIT_URL=http://127.0.0.1:8090`. The Appium scenario runs when `APPIUM_URL` is set (for example `http://127.0.0.1:4723`) and an emulator with the APK is attached.

## Limits

The stand is simpler than a real game. There is no real store (Google Play Billing, StoreKit), no HTTPS, and no traffic between the backend and the store. Porting the approach to a real project means writing an adapter for its flows and binding the invariants to its own server-side data.
