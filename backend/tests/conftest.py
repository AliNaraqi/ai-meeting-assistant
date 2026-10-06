"""Shared pytest fixtures for API tests."""

from __future__ import annotations

import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# Configure test settings before app imports create the engine.
os.environ["APP_ENV"] = "test"
os.environ["AUTH_MODE"] = "dev"
os.environ["SECRET_KEY"] = "test-secret-key-at-least-32-bytes-long"
os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["REDIS_URL"] = "redis://localhost:6379/15"
os.environ["STORAGE_BACKEND"] = "local"
os.environ["LOCAL_STORAGE_DIR"] = str(Path(__file__).resolve().parent / "_audio_tmp")
os.environ["APP_BASE_URL"] = "http://testserver"
os.environ["JOB_RUNNER"] = "inline"
os.environ["AUDIO_PREPROCESS_MODE"] = "mock"
# Disable IP upload limits unless a test explicitly enables them.
os.environ["MAX_UPLOADS_PER_IP_PER_DAY"] = "0"
os.environ["SEED_DEMO_ON_STARTUP"] = "false"


from app.config import get_settings
from app.database import get_db, get_engine, get_session_factory, reset_engine
from app.main import app
from app.models import Base


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    get_settings.cache_clear()
    reset_engine()
    engine = get_engine(get_settings())
    Base.metadata.create_all(bind=engine)
    session_factory = get_session_factory()

    def _override_db() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    reset_engine()
    get_settings.cache_clear()


@pytest.fixture()
def auth_header(client: TestClient) -> dict[str, str]:
    return bearer_for(client, "mina@example.com")


def bearer_for(client: TestClient, email: str) -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/dev-login",
        json={"email": email, "display_name": email.split("@")[0].title()},
    )
    assert response.status_code == 200, response.text
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
