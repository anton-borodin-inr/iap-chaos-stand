"""Minimal reverse proxy for reproducing stand defects by hand.

It forwards everything to the upstream unchanged, except the N-th request
matching METHOD and PATH, which gets one fault:

* `late`        forward, then hold the response past the client call timeout
                (the server processed it; the client sees no response)
* `status:<n>`  answer with HTTP <n> without forwarding (the server saw nothing)

Usage:
    python tests/support/fault_proxy.py --listen 8081 --upstream http://127.0.0.1:8080 \\
        --method POST --path /purchases/validate --occurrence 1 --fault late

This is a stand-repo helper for manual reproduction only.
"""

import argparse
import asyncio
import re

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response

HOLD_SECONDS = 9


def build(upstream: str, method: str, path: str, occurrence: int, fault: str) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    client = httpx.AsyncClient(base_url=upstream, timeout=30)
    pattern = re.compile("^" + re.sub(r"\{[^/]+\}", "[^/]+", path) + "$")
    seen = 0

    @app.api_route("/{full:path}", methods=["GET", "POST"])
    async def proxy(full: str, request: Request) -> Response:
        nonlocal seen
        url_path = "/" + full
        hit = False
        if request.method == method and pattern.match(url_path):
            seen += 1
            hit = seen == occurrence
        if hit and fault.startswith("status:"):
            code = int(fault.split(":", 1)[1])
            print(f"FAULT {fault} on {request.method} {url_path}", flush=True)
            return Response(status_code=code, content=b'{"error":{"code":"INJECTED","message":"injected"}}',
                            media_type="application/json")
        headers = {k: v for k, v in request.headers.items() if k.lower() in ("authorization", "content-type")}
        upstream_response = await client.request(
            request.method, url_path, params=request.query_params, content=await request.body(), headers=headers)
        if hit and fault == "late":
            print(f"FAULT late on {request.method} {url_path} (server answered {upstream_response.status_code})",
                  flush=True)
            await asyncio.sleep(HOLD_SECONDS)
        return Response(status_code=upstream_response.status_code, content=upstream_response.content,
                        media_type=upstream_response.headers.get("content-type"))

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--listen", type=int, default=8081)
    parser.add_argument("--upstream", default="http://127.0.0.1:8080")
    parser.add_argument("--method", required=True)
    parser.add_argument("--path", required=True)
    parser.add_argument("--occurrence", type=int, default=1)
    parser.add_argument("--fault", required=True)
    args = parser.parse_args()
    app = build(args.upstream, args.method, args.path, args.occurrence, args.fault)
    uvicorn.run(app, host="0.0.0.0", port=args.listen, log_level="warning")


if __name__ == "__main__":
    main()
