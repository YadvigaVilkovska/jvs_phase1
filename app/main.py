from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api import chat_router, dev_router, memory_router, profile_router
from app.db import create_db_and_tables
from app.ui_shell import CHAT_HTML as _CHAT_HTML


def create_app() -> FastAPI:
    app = FastAPI(title="Jeeves Backend", version="0.1.0")

    @app.get("/health", tags=["health"])
    def health():
        return {"status": "ok"}

    app.include_router(chat_router)
    app.include_router(memory_router)
    app.include_router(profile_router)
    app.include_router(dev_router)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def root():
        return HTMLResponse(_CHAT_HTML)

    @app.on_event("startup")
    def _startup():
        create_db_and_tables()

    return app


app = create_app()
