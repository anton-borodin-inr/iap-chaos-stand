"""Entry point: `python -m stand` serves both ports from one process."""

import asyncio
import sys

import uvicorn

from . import config, defects
from .app import create_apps

EXIT_CONFIG = 78


async def _serve() -> None:
    try:
        settings = config.load()
    except defects.UnknownDefectError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    apps = create_apps(settings)
    servers = [
        uvicorn.Server(uvicorn.Config(apps.public, host=settings.public_host,
                                      port=settings.public_port, log_level="info")),
        uvicorn.Server(uvicorn.Config(apps.audit, host=settings.audit_host,
                                      port=settings.audit_port, log_level="warning")),
    ]
    await asyncio.gather(*(server.serve() for server in servers))


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
