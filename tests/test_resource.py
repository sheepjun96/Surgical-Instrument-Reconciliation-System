from fastapi.testclient import TestClient

from main import app


client = TestClient(app)


def test_dashboard_page_is_served():
    response = client.get("/")

    assert response.status_code == 200
    assert "수술도구 모니터" in response.text
    assert "수술도구 비교표" in response.text


def test_current_dashboard_has_before_and_after_results():
    response = client.get("/api/dashboard/current")
    payload = response.json()

    assert response.status_code == 200
    assert payload["captures"]["before"] is not None
    assert payload["captures"]["after"] is not None
    assert payload["counts"]["before"]["scissors"] == 3
    assert payload["counts"]["after"]["scissors"] == 3


def test_heartbeat_returns_active_session_information():
    response = client.post(
        "/api/device/heartbeat",
        json={"device_id": "jetson-nano-test", "camera_ready": True},
    )
    payload = response.json()

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["session_id"] >= 1
    assert payload["expected_phase"] in {"before", "after", "complete"}

