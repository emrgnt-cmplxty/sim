"""
Parameterized market-making strategy.

All tunable knobs are set via the constructor so the optimizer can sweep them.
"""


class Strategy:
    def __init__(
        self,
        spread_offset=0.02,
        order_size=1.0,
        max_position=5.0,
        skew_factor=0.01,
    ):
        self.spread_offset = spread_offset
        self.order_size = order_size
        self.max_position = max_position
        self.skew_factor = skew_factor

    def on_tick(self, snapshot):
        mid = snapshot.get("midPrice")
        if mid is None:
            return []

        position = snapshot.get("_bt_position", 0.0)
        skew = position * self.skew_factor

        orders = []

        if position < self.max_position:
            orders.append({
                "side": "buy",
                "price": round(mid - self.spread_offset - skew, 2),
                "qty": self.order_size,
            })

        if position > -self.max_position:
            orders.append({
                "side": "sell",
                "price": round(mid + self.spread_offset - skew, 2),
                "qty": self.order_size,
            })

        return orders

    def __repr__(self):
        return (
            f"Strategy(spread={self.spread_offset}, size={self.order_size}, "
            f"max_pos={self.max_position}, skew={self.skew_factor})"
        )
