import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    id: str
    owner: str  # "market" for simulator, "strategy" for user
    side: Side
    price: float
    qty: float
    remaining: float = 0.0
    timestamp: float = 0.0

    def __post_init__(self):
        if self.remaining == 0.0:
            self.remaining = self.qty
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class Fill:
    price: float
    qty: float
    buy_order_id: str
    sell_order_id: str
    buy_owner: str
    sell_owner: str
    aggressor: Side
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "price": self.price,
            "qty": round(self.qty, 4),
            "buyOrderId": self.buy_order_id,
            "sellOrderId": self.sell_order_id,
            "buyOwner": self.buy_owner,
            "sellOwner": self.sell_owner,
            "aggressor": self.aggressor.value,
            "timestamp": self.timestamp,
        }


class Orderbook:
    def __init__(self, max_trades: int = 50):
        self.orders: dict[str, Order] = {}  # id -> Order
        self.recent_trades: deque[Fill] = deque(maxlen=max_trades)
        self._new_fills: list[Fill] = []  # fills since last snapshot

    def place_order(self, owner: str, side: Side, price: float, qty: float) -> Order:
        order = Order(
            id=uuid.uuid4().hex[:12],
            owner=owner,
            side=side,
            price=round(price, 2),
            qty=round(qty, 4),
        )
        self.orders[order.id] = order
        self._match()
        return order

    def cancel_order(self, order_id: str) -> Optional[Order]:
        order = self.orders.pop(order_id, None)
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        return self.orders.get(order_id)

    def get_orders_by_owner(self, owner: str) -> list[Order]:
        return [o for o in self.orders.values() if o.owner == owner and o.remaining > 0]

    def _match(self):
        """Price-time priority matching."""
        while True:
            buys = sorted(
                [o for o in self.orders.values() if o.side == Side.BUY and o.remaining > 0],
                key=lambda o: (-o.price, o.timestamp),
            )
            sells = sorted(
                [o for o in self.orders.values() if o.side == Side.SELL and o.remaining > 0],
                key=lambda o: (o.price, o.timestamp),
            )

            if not buys or not sells:
                break

            best_buy = buys[0]
            best_sell = sells[0]

            if best_buy.price < best_sell.price:
                break

            # match at the resting order's price (maker gets their price)
            # the order that was placed first is the maker
            if best_buy.timestamp <= best_sell.timestamp:
                match_price = best_buy.price
                aggressor = Side.SELL
            else:
                match_price = best_sell.price
                aggressor = Side.BUY

            match_qty = round(min(best_buy.remaining, best_sell.remaining), 4)

            best_buy.remaining = round(best_buy.remaining - match_qty, 4)
            best_sell.remaining = round(best_sell.remaining - match_qty, 4)

            fill = Fill(
                price=round(match_price, 2),
                qty=match_qty,
                buy_order_id=best_buy.id,
                sell_order_id=best_sell.id,
                buy_owner=best_buy.owner,
                sell_owner=best_sell.owner,
                aggressor=aggressor,
            )
            self.recent_trades.append(fill)
            self._new_fills.append(fill)

            # remove fully filled orders
            if best_buy.remaining <= 1e-8:
                self.orders.pop(best_buy.id, None)
            if best_sell.remaining <= 1e-8:
                self.orders.pop(best_sell.id, None)

    def drain_new_fills(self) -> list[Fill]:
        fills = self._new_fills
        self._new_fills = []
        return fills

    def best_bid(self) -> Optional[float]:
        buys = [o.price for o in self.orders.values() if o.side == Side.BUY and o.remaining > 0]
        return max(buys) if buys else None

    def best_ask(self) -> Optional[float]:
        sells = [o.price for o in self.orders.values() if o.side == Side.SELL and o.remaining > 0]
        return min(sells) if sells else None

    def _aggregate_levels(self, side: Side, depth: int) -> list[list[float]]:
        orders = [o for o in self.orders.values() if o.side == side and o.remaining > 0]
        levels: dict[float, float] = {}
        for o in orders:
            levels[o.price] = levels.get(o.price, 0) + o.remaining

        reverse = side == Side.BUY
        sorted_levels = sorted(levels.items(), key=lambda x: x[0], reverse=reverse)[:depth]
        return [[round(p, 2), round(q, 4)] for p, q in sorted_levels]

    def get_snapshot(self, depth: int = 20) -> dict:
        bids = self._aggregate_levels(Side.BUY, depth)
        asks = self._aggregate_levels(Side.SELL, depth)

        bb = bids[0][0] if bids else 0
        ba = asks[0][0] if asks else 0
        spread = ba - bb if bb and ba else 0
        mid_price = (bb + ba) / 2 if bb and ba else 0

        return {
            "bids": bids,
            "asks": asks,
            "spread": round(spread, 2),
            "midPrice": round(mid_price, 2),
            "trades": [t.to_dict() for t in reversed(self.recent_trades)],
            "timestamp": time.time(),
        }
