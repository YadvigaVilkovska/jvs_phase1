import pytest

from app.db import validate_database_url


def test_validate_empty_database_url():
    with pytest.raises(ValueError, match="DATABASE_URL is empty"):
        validate_database_url("")


def test_validate_bad_scheme():
    with pytest.raises(ValueError, match="Unsupported DATABASE_URL scheme"):
        validate_database_url("mysql://localhost/db")


def test_validate_postgres_schema_query_param():
    with pytest.raises(ValueError, match="schema="):
        validate_database_url("postgresql://u:p@localhost:5432/jeeves?schema=public")
