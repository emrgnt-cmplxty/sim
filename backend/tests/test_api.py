import pytest


class TestHealth:
    async def test_health(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestPlaceOrder:
    async def test_default_owner_is_strategy(self, client):
        resp = await client.post("/orders", json={"side": "buy", "price": 100.0, "qty": 5.0})
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner"] == "strategy"

    async def test_explicit_owner(self, client):
        resp = await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0, "owner": "alice"
        })
        assert resp.status_code == 200
        assert resp.json()["owner"] == "alice"

    async def test_invalid_side(self, client):
        resp = await client.post("/orders", json={"side": "invalid", "price": 100.0, "qty": 5.0})
        assert resp.status_code == 400

    async def test_zero_price(self, client):
        resp = await client.post("/orders", json={"side": "buy", "price": 0, "qty": 5.0})
        assert resp.status_code == 400

    async def test_zero_qty(self, client):
        resp = await client.post("/orders", json={"side": "buy", "price": 100.0, "qty": 0})
        assert resp.status_code == 400

    async def test_crossing_fill(self, client):
        # Place a resting sell
        await client.post("/orders", json={
            "side": "sell", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        # Place a crossing buy
        resp = await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0
        })
        data = resp.json()
        assert data["remaining"] == 0.0


class TestCancelOrder:
    async def test_cancel_success(self, client):
        resp = await client.post("/orders", json={"side": "buy", "price": 100.0, "qty": 5.0})
        order_id = resp.json()["id"]
        resp = await client.delete(f"/orders/{order_id}")
        assert resp.status_code == 200
        assert resp.json()["cancelled"] == order_id

    async def test_cancel_404(self, client):
        resp = await client.delete("/orders/nonexistent")
        assert resp.status_code == 404

    async def test_cancel_403_wrong_owner(self, client):
        resp = await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        order_id = resp.json()["id"]
        resp = await client.delete(f"/orders/{order_id}", params={"owner": "strategy"})
        assert resp.status_code == 403

    async def test_cancel_403_restores_order(self, client):
        resp = await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        order_id = resp.json()["id"]
        await client.delete(f"/orders/{order_id}", params={"owner": "strategy"})
        # Order should still be in the book
        resp = await client.get("/orders", params={"owner": "market"})
        ids = [o["id"] for o in resp.json()]
        assert order_id in ids

    async def test_cancel_no_owner_allows_any(self, client):
        resp = await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        order_id = resp.json()["id"]
        resp = await client.delete(f"/orders/{order_id}")
        assert resp.status_code == 200


class TestListOrders:
    async def test_default_returns_strategy(self, client):
        await client.post("/orders", json={"side": "buy", "price": 100.0, "qty": 5.0})
        await client.post("/orders", json={
            "side": "buy", "price": 99.0, "qty": 5.0, "owner": "market"
        })
        resp = await client.get("/orders")
        orders = resp.json()
        assert len(orders) == 1
        assert orders[0]["owner"] == "strategy"

    async def test_owner_filter(self, client):
        await client.post("/orders", json={"side": "buy", "price": 100.0, "qty": 5.0})
        await client.post("/orders", json={
            "side": "buy", "price": 99.0, "qty": 5.0, "owner": "market"
        })
        resp = await client.get("/orders", params={"owner": "market"})
        orders = resp.json()
        assert len(orders) == 1
        assert orders[0]["owner"] == "market"

    async def test_owner_all(self, client):
        await client.post("/orders", json={"side": "buy", "price": 100.0, "qty": 5.0})
        await client.post("/orders", json={
            "side": "buy", "price": 99.0, "qty": 5.0, "owner": "market"
        })
        resp = await client.get("/orders", params={"owner": "all"})
        orders = resp.json()
        assert len(orders) == 2


class TestPosition:
    async def test_starts_flat(self, client):
        resp = await client.get("/position")
        data = resp.json()
        assert data["position"] == 0.0
        assert data["tradeCount"] == 0

    async def test_updates_on_fill(self, client):
        await client.post("/orders", json={
            "side": "sell", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0
        })
        resp = await client.get("/position")
        data = resp.json()
        assert data["position"] == 5.0
        assert data["tradeCount"] == 1

    async def test_ignores_market_fills(self, client):
        await client.post("/orders", json={
            "side": "sell", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        await client.post("/orders", json={
            "side": "buy", "price": 100.0, "qty": 5.0, "owner": "market"
        })
        resp = await client.get("/position")
        data = resp.json()
        assert data["position"] == 0.0
        assert data["tradeCount"] == 0


class TestBookSummary:
    async def test_empty_book(self, client):
        resp = await client.get("/book/summary")
        data = resp.json()
        assert data["bestBid"] is None
        assert data["bestAsk"] is None
        assert data["bidTopQty"] == 0.0
        assert data["askTopQty"] == 0.0

    async def test_with_orders(self, client):
        await client.post("/orders", json={"side": "buy", "price": 99.0, "qty": 3.0})
        await client.post("/orders", json={"side": "sell", "price": 101.0, "qty": 7.0})
        resp = await client.get("/book/summary")
        data = resp.json()
        assert data["bestBid"] == 99.0
        assert data["bestAsk"] == 101.0
        assert data["bidTopQty"] == 3.0
        assert data["askTopQty"] == 7.0

    async def test_counts_only_market(self, client):
        await client.post("/orders", json={"side": "buy", "price": 99.0, "qty": 3.0})
        await client.post("/orders", json={
            "side": "buy", "price": 98.0, "qty": 2.0, "owner": "market"
        })
        resp = await client.get("/book/summary")
        data = resp.json()
        assert data["marketBidCount"] == 1
