"""
Inventory-skewed market-making strategy.

Shifts quotes to reduce position risk: if long, sell more aggressively;
if short, buy more aggressively.
"""


class Strategy:
    def __init__(self):
        self.spread_offset = 0.01
        self.order_size = 1.0
        self.max_position = 5.0
        self.skew_factor = 0.01  # price shift per unit of position

    def on_tick(self, snapshot: dict) -> list[dict]:
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
