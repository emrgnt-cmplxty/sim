import pytest
from orderbook import Orderbook, Order, Fill, Side


class TestPlaceOrder:
    def test_returns_order_with_correct_fields(self, fresh_orderbook):
        ob = fresh_orderbook
        order = ob.place_order("alice", Side.BUY, 100.0, 5.0)
        assert isinstance(order, Order)
        assert order.owner == "alice"
        assert order.side == Side.BUY
        assert order.price == 100.0
        assert order.qty == 5.0
        assert order.remaining == 5.0
        assert len(order.id) == 12

    def test_rounds_price_to_2_decimals(self, fresh_orderbook):
        order = fresh_orderbook.place_order("a", Side.BUY, 100.123, 1.0)
        assert order.price == 100.12

    def test_rounds_qty_to_4_decimals(self, fresh_orderbook):
        order = fresh_orderbook.place_order("a", Side.BUY, 100.0, 1.23456)
        assert order.qty == 1.2346

    def test_assigns_unique_ids(self, fresh_orderbook):
        ob = fresh_orderbook
        ids = {ob.place_order("a", Side.BUY, 100.0 - i, 1.0).id for i in range(20)}
        assert len(ids) == 20


class TestMatching:
    def test_no_match_when_uncrossed(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 99.0, 5.0)
        ob.place_order("b", Side.SELL, 101.0, 5.0)
        assert len(ob.recent_trades) == 0
        assert len(ob.orders) == 2

    def test_exact_match(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 100.0, 5.0)
        ob.place_order("b", Side.SELL, 100.0, 5.0)
        assert len(ob.recent_trades) == 1
        assert ob.recent_trades[0].qty == 5.0
        assert ob.recent_trades[0].price == 100.0
        assert len(ob.orders) == 0

    def test_partial_fill(self, fresh_orderbook):
        ob = fresh_orderbook
        buy = ob.place_order("a", Side.BUY, 100.0, 10.0)
        ob.place_order("b", Side.SELL, 100.0, 3.0)
        assert len(ob.recent_trades) == 1
        assert ob.recent_trades[0].qty == 3.0
        assert buy.remaining == 7.0
        assert buy.id in ob.orders

    def test_maker_price_priority_buy_is_maker(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 101.0, 5.0)   # resting buy
        ob.place_order("b", Side.SELL, 100.0, 5.0)   # aggressive sell
        fill = ob.recent_trades[0]
        assert fill.price == 101.0
        assert fill.aggressor == Side.SELL

    def test_maker_price_priority_sell_is_maker(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.SELL, 99.0, 5.0)    # resting sell
        ob.place_order("b", Side.BUY, 100.0, 5.0)    # aggressive buy
        fill = ob.recent_trades[0]
        assert fill.price == 99.0
        assert fill.aggressor == Side.BUY

    def test_price_priority_buys(self, fresh_orderbook):
        """Higher-priced buy should match first."""
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 99.0, 5.0)
        ob.place_order("b", Side.BUY, 101.0, 5.0)
        ob.place_order("c", Side.SELL, 99.0, 5.0)
        fill = ob.recent_trades[0]
        assert fill.price == 101.0

    def test_price_priority_sells(self, fresh_orderbook):
        """Lower-priced sell should match first."""
        ob = fresh_orderbook
        ob.place_order("a", Side.SELL, 102.0, 5.0)
        ob.place_order("b", Side.SELL, 99.0, 5.0)
        ob.place_order("c", Side.BUY, 102.0, 5.0)
        fill = ob.recent_trades[0]
        assert fill.price == 99.0

    def test_time_priority(self, fresh_orderbook):
        """At same price, earlier order matches first."""
        ob = fresh_orderbook
        o1 = ob.place_order("first", Side.BUY, 100.0, 5.0)
        o2 = ob.place_order("second", Side.BUY, 100.0, 5.0)
        # Ensure distinct timestamps
        o1.timestamp = 1.0
        o2.timestamp = 2.0
        ob.place_order("seller", Side.SELL, 100.0, 5.0)
        fill = list(ob.recent_trades)[-1]
        assert fill.buy_order_id == o1.id

    def test_multi_level_sweep(self, fresh_orderbook):
        """Large aggressive order eats through multiple price levels."""
        ob = fresh_orderbook
        ob.place_order("a", Side.SELL, 100.0, 2.0)
        ob.place_order("b", Side.SELL, 101.0, 3.0)
        ob.place_order("c", Side.SELL, 102.0, 5.0)
        buy = ob.place_order("d", Side.BUY, 102.0, 12.0)
        assert len(ob.recent_trades) == 3
        total_filled = sum(t.qty for t in ob.recent_trades)
        assert total_filled == 10.0
        assert buy.remaining == pytest.approx(2.0, abs=1e-8)

    def test_owner_info_on_fills(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("buyer1", Side.BUY, 100.0, 5.0)
        ob.place_order("seller1", Side.SELL, 100.0, 5.0)
        fill = ob.recent_trades[0]
        assert fill.buy_owner == "buyer1"
        assert fill.sell_owner == "seller1"


class TestCancel:
    def test_cancel_existing(self, fresh_orderbook):
        ob = fresh_orderbook
        order = ob.place_order("a", Side.BUY, 100.0, 5.0)
        cancelled = ob.cancel_order(order.id)
        assert cancelled is not None
        assert cancelled.id == order.id
        assert order.id not in ob.orders

    def test_cancel_nonexistent(self, fresh_orderbook):
        result = fresh_orderbook.cancel_order("nonexistent")
        assert result is None


class TestBBO:
    def test_best_bid(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 99.0, 1.0)
        ob.place_order("b", Side.BUY, 101.0, 1.0)
        assert ob.best_bid() == 101.0

    def test_best_ask(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.SELL, 102.0, 1.0)
        ob.place_order("b", Side.SELL, 99.0, 1.0)
        assert ob.best_ask() == 99.0

    def test_best_bid_empty(self, fresh_orderbook):
        assert fresh_orderbook.best_bid() is None

    def test_best_ask_empty(self, fresh_orderbook):
        assert fresh_orderbook.best_ask() is None


class TestGetOrdersByOwner:
    def test_returns_only_matching_owner(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("alice", Side.BUY, 99.0, 1.0)
        ob.place_order("bob", Side.BUY, 98.0, 1.0)
        ob.place_order("alice", Side.SELL, 102.0, 1.0)
        orders = ob.get_orders_by_owner("alice")
        assert len(orders) == 2
        assert all(o.owner == "alice" for o in orders)


class TestSnapshot:
    def test_structure(self, fresh_orderbook):
        snap = fresh_orderbook.get_snapshot()
        assert "bids" in snap
        assert "asks" in snap
        assert "spread" in snap
        assert "midPrice" in snap
        assert "trades" in snap
        assert "timestamp" in snap

    def test_aggregation(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 100.0, 3.0)
        ob.place_order("b", Side.BUY, 100.0, 2.0)
        snap = ob.get_snapshot()
        assert len(snap["bids"]) == 1
        assert snap["bids"][0][1] == 5.0

    def test_includes_trades(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 100.0, 5.0)
        ob.place_order("b", Side.SELL, 100.0, 5.0)
        snap = ob.get_snapshot()
        assert len(snap["trades"]) == 1

    def test_depth_limit(self, fresh_orderbook):
        ob = fresh_orderbook
        for i in range(25):
            ob.place_order("a", Side.BUY, 100.0 - i, 1.0)
        snap = ob.get_snapshot(depth=5)
        assert len(snap["bids"]) == 5

    def test_bids_sorted_descending(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 99.0, 1.0)
        ob.place_order("b", Side.BUY, 101.0, 1.0)
        ob.place_order("c", Side.BUY, 100.0, 1.0)
        snap = ob.get_snapshot()
        prices = [level[0] for level in snap["bids"]]
        assert prices == sorted(prices, reverse=True)

    def test_asks_sorted_ascending(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.SELL, 103.0, 1.0)
        ob.place_order("b", Side.SELL, 101.0, 1.0)
        ob.place_order("c", Side.SELL, 102.0, 1.0)
        snap = ob.get_snapshot()
        prices = [level[0] for level in snap["asks"]]
        assert prices == sorted(prices)


class TestLastMid:
    def test_updated_by_snapshot(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 99.0, 1.0)
        ob.place_order("a", Side.SELL, 101.0, 1.0)
        ob.get_snapshot()
        assert ob.last_mid == 100.0

    def test_not_updated_when_empty(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.get_snapshot()
        assert ob.last_mid == 100.0


class TestDrainNewFills:
    def test_returns_fills_and_clears(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 100.0, 5.0)
        ob.place_order("b", Side.SELL, 100.0, 5.0)
        fills = ob.drain_new_fills()
        assert len(fills) == 1
        assert fills[0].qty == 5.0

    def test_idempotent(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("a", Side.BUY, 100.0, 5.0)
        ob.place_order("b", Side.SELL, 100.0, 5.0)
        ob.drain_new_fills()
        assert ob.drain_new_fills() == []


class TestRecentTrades:
    def test_max_limit(self):
        ob = Orderbook(max_trades=3)
        for i in range(5):
            ob.place_order("a", Side.BUY, 100.0, 1.0)
            ob.place_order("b", Side.SELL, 100.0, 1.0)
        assert len(ob.recent_trades) == 3


class TestFillToDict:
    def test_structure(self, fresh_orderbook):
        ob = fresh_orderbook
        ob.place_order("buyer", Side.BUY, 100.0, 5.0)
        ob.place_order("seller", Side.SELL, 100.0, 5.0)
        fill = ob.recent_trades[0]
        d = fill.to_dict()
        assert d["price"] == 100.0
        assert d["qty"] == 5.0
        assert d["buyOwner"] == "buyer"
        assert d["sellOwner"] == "seller"
        assert d["aggressor"] == "sell"
        assert "buyOrderId" in d
        assert "sellOrderId" in d
        assert "timestamp" in d
