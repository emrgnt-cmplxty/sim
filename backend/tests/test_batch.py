import pytest


class TestBatch:
    async def test_cancel_only(self, client):
        resp = await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        order_id = resp.json()["id"]
        resp = await client.post("/batch", json={"cancels": [order_id]})
        data = resp.json()
        assert order_id in data["cancelled"]
        assert data["placed"] == []

    async def test_place_only(self, client):
        resp = await client.post("/batch", json={
            "orders": [{"side": "buy", "price": 100.0, "qty": 5.0}]
        })
        data = resp.json()
        assert len(data["placed"]) == 1
        assert data["placed"][0]["side"] == "buy"
        assert data["cancelled"] == []

    async def test_cancel_and_place(self, client):
        resp = await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        order_id = resp.json()["id"]
        resp = await client.post("/batch", json={
            "cancels": [order_id],
            "orders": [{"side": "sell", "price": 101.0, "qty": 3.0}]
        })
        data = resp.json()
        assert order_id in data["cancelled"]
        assert len(data["placed"]) == 1

    async def test_get_summary_flag(self, client):
        await client.post("/orders", json={
            "side": "buy", "price": 99.0, "qty": 5.0, "owner": "market"
        })
        resp = await client.post("/batch", json={
            "orders": [{"side": "sell", "price": 101.0, "qty": 3.0}],
            "get_summary": True,
        })
        data = resp.json()
        assert "summary" in data
        assert "bestBid" in data["summary"]

    async def test_no_summary_without_flag(self, client):
        resp = await client.post("/batch", json={
            "orders": [{"side": "buy", "price": 100.0, "qty": 5.0}]
        })
        assert "summary" not in resp.json()

    async def test_skip_invalid_side(self, client):
        resp = await client.post("/batch", json={
            "orders": [
                {"side": "buy", "price": 100.0, "qty": 5.0},
                {"side": "invalid", "price": 100.0, "qty": 5.0},
            ]
        })
        assert len(resp.json()["placed"]) == 1

    async def test_skip_invalid_price_qty(self, client):
        resp = await client.post("/batch", json={
            "orders": [
                {"side": "buy", "price": 0, "qty": 5.0},
                {"side": "buy", "price": 100.0, "qty": -1},
                {"side": "buy", "price": 100.0, "qty": 5.0},
            ]
        })
        assert len(resp.json()["placed"]) == 1

    async def test_nonexistent_cancel_ignored(self, client):
        resp = await client.post("/batch", json={"cancels": ["nonexistent"]})
        assert resp.status_code == 200
        assert resp.json()["cancelled"] == []

    async def test_default_owner_is_market(self, client):
        resp = await client.post("/batch", json={
            "orders": [{"side": "buy", "price": 100.0, "qty": 5.0}]
        })
        assert resp.json()["placed"][0]["owner"] == "market"

    async def test_triggers_matching(self, client):
        # Place a strategy sell first
        await client.post("/orders", json={"side": "sell", "price": 100.0, "qty": 5.0})
        # Batch a market buy that crosses
        resp = await client.post("/batch", json={
            "orders": [{"side": "buy", "price": 100.0, "qty": 5.0}]
        })
        placed = resp.json()["placed"][0]
        assert placed["remaining"] == 0.0

    async def test_processes_strategy_fills(self, client):
        # Place a strategy buy
        await client.post("/orders", json={"side": "buy", "price": 100.0, "qty": 5.0})
        # Batch a market sell that crosses
        await client.post("/batch", json={
            "orders": [{"side": "sell", "price": 100.0, "qty": 5.0}]
        })
        # Position should reflect the fill
        resp = await client.get("/position")
        assert resp.json()["position"] == 5.0

    async def test_empty_request(self, client):
        resp = await client.post("/batch", json={})
        assert resp.status_code == 200
        data = resp.json()
        assert data["cancelled"] == []
        assert data["placed"] == []
