import pytest
from orderbook import Fill, Side
from position import PositionTracker


class TestApplyFill:
    def test_buy_fill_increases_position(self, fresh_position):
        pt = fresh_position
        fill = Fill(price=100.0, qty=5.0, buy_order_id="b1", sell_order_id="s1",
                    buy_owner="strategy", sell_owner="market", aggressor=Side.BUY)
        pt.apply_fill(fill)
        assert pt.position == 5.0
        assert pt.cash == -500.0
        assert pt.total_bought == 5.0
        assert pt.trade_count == 1

    def test_sell_fill_decreases_position(self, fresh_position):
        pt = fresh_position
        fill = Fill(price=100.0, qty=3.0, buy_order_id="b1", sell_order_id="s1",
                    buy_owner="market", sell_owner="strategy", aggressor=Side.SELL)
        pt.apply_fill(fill)
        assert pt.position == -3.0
        assert pt.cash == 300.0
        assert pt.total_sold == 3.0
        assert pt.trade_count == 1

    def test_ignores_other_owner(self, fresh_position):
        pt = fresh_position
        fill = Fill(price=100.0, qty=5.0, buy_order_id="b1", sell_order_id="s1",
                    buy_owner="alice", sell_owner="bob", aggressor=Side.BUY)
        pt.apply_fill(fill)
        assert pt.position == 0.0
        assert pt.trade_count == 0


class TestRoundTrip:
    def test_profit(self, fresh_position):
        pt = fresh_position
        buy = Fill(price=100.0, qty=5.0, buy_order_id="b1", sell_order_id="s1",
                   buy_owner="strategy", sell_owner="market", aggressor=Side.BUY)
        sell = Fill(price=105.0, qty=5.0, buy_order_id="b2", sell_order_id="s2",
                    buy_owner="market", sell_owner="strategy", aggressor=Side.SELL)
        pt.apply_fill(buy)
        pt.apply_fill(sell)
        assert pt.position == 0.0
        assert pt.cash == 25.0  # 105*5 - 100*5

    def test_loss(self, fresh_position):
        pt = fresh_position
        buy = Fill(price=105.0, qty=5.0, buy_order_id="b1", sell_order_id="s1",
                   buy_owner="strategy", sell_owner="market", aggressor=Side.BUY)
        sell = Fill(price=100.0, qty=5.0, buy_order_id="b2", sell_order_id="s2",
                    buy_owner="market", sell_owner="strategy", aggressor=Side.SELL)
        pt.apply_fill(buy)
        pt.apply_fill(sell)
        assert pt.position == 0.0
        assert pt.cash == -25.0


class TestUnrealizedPnl:
    def test_long_position(self, fresh_position):
        pt = fresh_position
        fill = Fill(price=100.0, qty=5.0, buy_order_id="b1", sell_order_id="s1",
                    buy_owner="strategy", sell_owner="market", aggressor=Side.BUY)
        pt.apply_fill(fill)
        assert pt.unrealized_pnl(110.0) == 550.0  # 5 * 110

    def test_short_position(self, fresh_position):
        pt = fresh_position
        fill = Fill(price=100.0, qty=5.0, buy_order_id="b1", sell_order_id="s1",
                    buy_owner="market", sell_owner="strategy", aggressor=Side.SELL)
        pt.apply_fill(fill)
        assert pt.unrealized_pnl(90.0) == -450.0  # -5 * 90


class TestTotalPnl:
    def test_cash_plus_unrealized(self, fresh_position):
        pt = fresh_position
        fill = Fill(price=100.0, qty=5.0, buy_order_id="b1", sell_order_id="s1",
                    buy_owner="strategy", sell_owner="market", aggressor=Side.BUY)
        pt.apply_fill(fill)
        # cash = -500, unrealized at 110 = 550, total = 50
        assert pt.total_pnl(110.0) == 50.0


class TestToDict:
    def test_has_all_keys_and_rounds(self, fresh_position):
        pt = fresh_position
        fill = Fill(price=100.0, qty=5.0, buy_order_id="b1", sell_order_id="s1",
                    buy_owner="strategy", sell_owner="market", aggressor=Side.BUY)
        pt.apply_fill(fill)
        d = pt.to_dict(100.0)
        assert d["owner"] == "strategy"
        assert d["position"] == 5.0
        assert d["cash"] == -500.0
        assert d["unrealizedPnl"] == 500.0
        assert d["totalPnl"] == 0.0
        assert d["totalBought"] == 5.0
        assert d["totalSold"] == 0.0
        assert d["tradeCount"] == 1
