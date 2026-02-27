"""
Example market-making strategy for backtesting.

Quotes bid/ask around mid-price with inventory-aware skew.
"""


class Strategy:
    def __init__(self):
        self.spread_offset = 0.01
        self.order_size = 1.0
        self.max_position = 5.0

    def on_tick(self, snapshot: dict) -> list[dict]:
        mid = snapshot.get("midPrice")
        if mid is None:
            return []

        # In backtest mode there's no live position tracking from the server,
        # so we rely on the harness — but we can't see it here.
        # Instead, we just always quote both sides and let the harness
        # enforce fills. For inventory awareness, see strategies/skewed.py.
        orders = []

        orders.append({
            "side": "buy",
            "price": round(mid - self.spread_offset, 2),
            "qty": self.order_size,
        })

        orders.append({
            "side": "sell",
            "price": round(mid + self.spread_offset, 2),
            "qty": self.order_size,
        })

        return orders
