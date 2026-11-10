# Launch contract

Status: stage 0 contract. Frozen at tag `stand-v1`.

This is how to start, reset and restart the stand, and how to enable defects. The reference build and any build with defects start with the same commands. Only the defect ID differs.

## Artifacts

| Artifact | Name | Notes |
| --- | --- | --- |
| Server image | `iap-chaos-stand/server:stand-v1` | Backend and store in one container. Built from the repository root with `docker build -f server/Dockerfile -t iap-chaos-stand/server:stand-v1 .`, or loaded with `docker load` |
| Compose file | `compose.yaml` (repository root) | References the image by tag only. It has no `build:` section, so `up` never rebuilds from source |
| Android app | `stand-v1.apk`, package `dev.iapchaos.stand`, activity `.MainActivity` | Debug build. Cleartext HTTP is allowed to any host |

A build with defects ships under the same image tag and the same package name. Whichever artifact is loaded or installed is the one that runs.

## Server

### Ports

| Port | Bind on host | Serves |
| --- | --- | --- |
| 8080 | `0.0.0.0:8080` | Public API ([openapi.yaml](openapi.yaml)): backend and `/store/*` |
| 8090 | `127.0.0.1:8090` | Audit API ([audit-api.md](audit-api.md)) |

### Environment

| Variable | Default in `compose.yaml` | Meaning |
| --- | --- | --- |
| `STAND_DEFECTS` | empty | Comma-separated defect IDs to enable. Empty means the reference behavior |
| `RECEIPT_SECRET` | `stand-v1-public-dev-secret` | Shared signing secret for tokens and receipts. Public and fake by design |
| `OFFER_WINDOW_SECONDS` | `600` | Starter offer window. Runs use 600 |

Databases live inside the container (`/data/backend.db`, `/data/store.db`) without a volume. Recreating the container also empties them.

### Start

```bash
STAND_DEFECTS=<ids> docker compose up -d --wait
```

`--wait` returns once the health check passes (`GET /audit/health` → `ok`). When `STAND_DEFECTS` changes, the same command recreates the container. Stop it with `docker compose down`.

## Client

### Launch parameters

Parameters are passed as string intent extras on the launch intent:

| Extra | Default | Meaning |
| --- | --- | --- |
| `backend_url` | `http://10.0.2.2:8080` | Base URL for every public call. Point it at the proxy to inject faults. `10.0.2.2` is the host as seen from the Android emulator |
| `defects` | empty | Comma-separated defect IDs, the same value as `STAND_DEFECTS` |

```bash
adb shell am start -W -n dev.iapchaos.stand/.MainActivity --es backend_url http://10.0.2.2:8080 --es defects ""
```

With Appium, pass the same extras through `appium:optionalIntentArguments`.

### Persistence of parameters

- If the launch intent carries at least one of the two extras, the client stores both values. A missing extra takes its default.
- If the launch intent carries neither extra, the client uses the stored values. If nothing is stored, it uses the defaults.
- So a restart without extras (as in recovery) keeps the configuration of the run. Clearing app data returns to the defaults.

## Defect toggles

- **ID format:** `^[A-Z][0-9]{2}$`. Open defects use `O01` to `O05`. Closed defects use IDs assigned by their owner, which say nothing about the defect.
- **Registry:** each build carries a registry of every defect ID that build contains, each assigned to one component (client or backend). The fake store has no defects.
- **Same list everywhere:** pass the same list to the server and to the client. Each component enables the IDs that belong to it and ignores registered IDs that belong to the other.
- **Unknown ID:** an ID missing from the build's registry fails fast. The server exits during startup, so `up --wait` fails. The client shows `screen_config_error` and makes no requests.
- **No trace in traffic:** an enabled defect must not change any path, header, field name or field set on the happy path. Toggles do not appear in public API responses, audit responses, client requests or error messages. On the client, toggles live only in the stored launch config.
- **Switching:** start the server with the new `STAND_DEFECTS`, then do a full reset, launching the client with the new `defects`.

## Full reset

This returns the stand to a clean state between scenarios:

1. Stop the client:

   ```bash
   adb shell am force-stop dev.iapchaos.stand
   ```

2. Clear client data. This drops `install_id`, the token, queues, intents and the stored config:

   ```bash
   adb shell pm clear dev.iapchaos.stand
   ```

3. Reset the server:

   ```bash
   curl -fsS -X POST http://127.0.0.1:8090/audit/reset
   ```

4. Launch the client with both extras.

After step 4 the client registers a new guest. The offer window starts at that registration.

## Restart

Recovery and "restart" in [invariants.md](invariants.md#recovery) mean a cold restart with the stored configuration:

```bash
adb shell am force-stop dev.iapchaos.stand
```

```bash
adb shell am start -W -n dev.iapchaos.stand/.MainActivity
```

## Contract freeze

At tag `stand-v1` these are fixed: this file, [openapi.yaml](openapi.yaml), [audit-api.md](audit-api.md), [ui-ids.md](ui-ids.md), [invariants.md](invariants.md), [purchase-flow.md](purchase-flow.md) and [game.md](game.md), plus the artifact names, ports, parameter names and commands above. Builds with defects must keep all of them.
