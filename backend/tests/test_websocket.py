from starlette.testclient import TestClient
from main import app


def test_ws_initial_snapshot_structure():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert "bids" in data
        assert "asks" in data
        assert "spread" in data
        assert "midPrice" in data
        assert "trades" in data
        assert "strategyFills" in data
        assert "timestamp" in data


def test_ws_position_included():
    client = TestClient(app)
    with client.websocket_connect("/ws") as ws:
        data = ws.receive_json()
        assert "position" in data
        pos = data["position"]
        assert pos["owner"] == "strategy"
        assert pos["position"] == 0.0
