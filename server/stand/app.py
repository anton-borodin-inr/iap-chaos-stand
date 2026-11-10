"""Compose the public app (port 8080) and the audit app (port 8090)."""

import os
from dataclasses import dataclass

from fastapi import FastAPI

from . import clock, defects, errors
from .backend import audit as backend_audit
from .backend import db as backend_db
from .backend import routes as backend_routes
from .config import Settings
from .store import store


@dataclass
class Apps:
    public: FastAPI
    audit: FastAPI


def _bare_app() -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    errors.install(app)
    return app


def create_apps(settings: Settings) -> Apps:
    defects.configure(settings.backend_defects)
    os.makedirs(settings.data_dir, exist_ok=True)
    backend_database = backend_db.open_db(os.path.join(settings.data_dir, "backend.db"))
    store_database = store.open_db(os.path.join(settings.data_dir, "store.db"))

    public = _bare_app()
    public.include_router(
        backend_routes.build_router(backend_database, settings.secret, settings.offer_window_seconds))
    public.include_router(store.build_router(store_database, settings.secret), prefix="/store")

    audit = _bare_app()

    @audit.get("/audit/health")
    def health() -> dict:
        return {"status": "ok", "contract": "stand-v1", "server_time": clock.now_iso()}

    @audit.post("/audit/reset")
    def reset() -> dict:
        backend_audit.reset(backend_database)
        store.reset(store_database)
        return {"reset_at": clock.now_iso()}

    audit.include_router(backend_audit.build_router(backend_database))
    audit.include_router(store.build_audit_router(store_database))
    return Apps(public=public, audit=audit)
