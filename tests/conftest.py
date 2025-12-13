import os
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

# Ensure the app uses a local SQLite DB and no Redis for tests
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("STAYCIRCLE_JWT_SECRET", "test-secret")

import sys
# Ensure the backend/ directory is on sys.path so 'app' resolves when running pytest from repo root.
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.main import app  # noqa: E402
from app.db import Base, engine  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _bootstrap_db() -> Iterator[None]:
    """
    Session-level DB bootstrap. We use SQLite file DB for simplicity.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def _clean_db() -> Iterator[None]:
    """
    Function-level isolation: reset schema before each test.
    This is simple and sufficient for our small test suite.
    """
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture()
def client() -> Iterator[TestClient]:
    """
    FastAPI TestClient for API tests.
    """
    with TestClient(app) as c:
        yield c
