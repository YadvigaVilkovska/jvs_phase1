from __future__ import annotations

from collections.abc import Generator

from fastapi import Depends
from sqlmodel import Session

from app.db import get_session


def db_session() -> Generator[Session, None, None]:
    session = get_session()
    try:
        yield session
    finally:
        session.close()

