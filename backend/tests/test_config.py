import pytest

from backend.app.config import Settings


@pytest.mark.parametrize("given,want", [
    ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    ("postgresql://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ("sqlite:///./x.db", "sqlite:///./x.db"),
])
def test_database_url_normalised(given, want, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", given)
    assert Settings().database_url == want


def test_default_is_local_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert Settings(_env_file=None).database_url.startswith("sqlite:///")
