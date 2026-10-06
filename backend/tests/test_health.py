from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_live(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body


@patch("app.main.check_redis", return_value=True)
@patch("app.main.check_database", return_value=True)
def test_health_ready_ok(_mock_db: object, _mock_redis: object, client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["database"] == "ok"
    assert body["redis"] == "ok"
    assert "version" in body


@patch("app.main.check_redis", return_value=False)
@patch("app.main.check_database", return_value=True)
def test_health_ready_redis_down(_mock_db: object, _mock_redis: object, client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["database"] == "ok"
    assert body["redis"] == "unavailable"
