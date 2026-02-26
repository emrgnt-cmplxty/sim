from orderbook import Fill, Side


class PositionTracker:
    def __init__(self, owner: str):
        self.owner = owner
        self.position: float = 0.0     # net qty (positive = long, negative = short)
        self.cash: float = 0.0         # realized cash flow
        self.total_bought: float = 0.0
        self.total_sold: float = 0.0
        self.trade_count: int = 0

    def apply_fill(self, fill: Fill):
        """Update position from a fill that involves this owner."""
        if fill.buy_owner == self.owner:
            qty = fill.qty
            self.position += qty
            self.cash -= fill.price * qty
            self.total_bought += qty
            self.trade_count += 1
        elif fill.sell_owner == self.owner:
            qty = fill.qty
            self.position -= qty
            self.cash += fill.price * qty
            self.total_sold += qty
            self.trade_count += 1

    def unrealized_pnl(self, mid_price: float) -> float:
        """Mark-to-market PnL on open position."""
        return self.position * mid_price

    def total_pnl(self, mid_price: float) -> float:
        """Cash + unrealized."""
        return self.cash + self.unrealized_pnl(mid_price)

    def to_dict(self, mid_price: float) -> dict:
        return {
            "owner": self.owner,
            "position": round(self.position, 4),
            "cash": round(self.cash, 4),
            "unrealizedPnl": round(self.unrealized_pnl(mid_price), 4),
            "totalPnl": round(self.total_pnl(mid_price), 4),
            "totalBought": round(self.total_bought, 4),
            "totalSold": round(self.total_sold, 4),
            "tradeCount": self.trade_count,
        }
