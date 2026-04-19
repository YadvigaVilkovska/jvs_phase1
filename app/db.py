from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from sqlalchemy.engine import Engine
from sqlmodel import Session, SQLModel, create_engine

from app.settings import settings

_engine: Engine | None = None


def validate_database_url(url: str) -> None:
    """
    Fail fast with a readable message before SQLAlchemy raises an obscure engine error.
    """
    raw = (url or "").strip()
    if not raw:
        raise ValueError(
            "DATABASE_URL is empty. Set a SQLAlchemy URL, for example "
            "sqlite:///./data/jeeves.db for local SQLite."
        )

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("sqlite", "postgresql", "postgres"):
        raise ValueError(
            f"Unsupported DATABASE_URL scheme {scheme!r}. Use sqlite:///... or postgresql://... "
            "with a valid SQLAlchemy dialect."
        )

    if scheme.startswith("postgres"):
        qs = parse_qs(parsed.query)
        unsupported = [k for k in ("schema", "search_path") if k in qs]
        if unsupported:
            raise ValueError(
                "DATABASE_URL must not use unsupported query parameters such as "
                "`schema=` or `search_path=` (they are not applied the way some ORMs use them). "
                "For local development prefer SQLite: sqlite:///./data/jeeves.db "
                "or a plain postgresql://USER:PASS@HOST:PORT/DBNAME without those parameters."
            )


def _ensure_sqlite_parent_dir(url: str) -> None:
    if ":memory:" in url:
        return
    if not url.startswith("sqlite:///"):
        return
    path_part = url[len("sqlite:///") :].split("?")[0]
    if not path_part or path_part.startswith(":"):
        return
    p = Path(path_part)
    if p.parent != Path(".") and str(p.parent):
        p.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> Engine:
    """Return a process-wide engine instance (lazy singleton for the current settings)."""
    global _engine
    if _engine is not None:
        return _engine
    validate_database_url(settings.database_url)
    _ensure_sqlite_parent_dir(settings.database_url)
    try:
        _engine = create_engine(settings.database_url, echo=False)
    except Exception as e:
        raise RuntimeError(
            f"Could not create database engine (check DATABASE_URL and connectivity): {e}"
        ) from e
    return _engine


def create_db_and_tables() -> None:
    engine = get_engine()
    SQLModel.metadata.create_all(engine)


def get_session() -> Session:
    engine = get_engine()
    return Session(engine)
