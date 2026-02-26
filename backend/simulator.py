import asyncio
import random

from orderbook import Orderbook, Side

# Half-spread: passive orders are placed at least this far from mid
MIN_HALF_SPREAD = 0.02
MAX_DEPTH_OFFSET = 0.25
TARGET_LEVELS_PER_SIDE = 18


class Simulator:
    def __init__(self, orderbook: Orderbook, base_price: float = 100.0):
        self.ob = orderbook
        self.mid = base_price
        self.volatility = 0.015
        self.bias = 0.0
        self.bias_decay = 0.995
        self.bias_noise = 0.002
        self._running = False
        self._market_order_ids: set[str] = set()

    async def start(self):
        self._running = True
        self._seed_book()
        while self._running:
            self._tick()
            await asyncio.sleep(0.1)

    def stop(self):
        self._running = False

    def _place(self, side: Side, price: float, qty: float):
        order = self.ob.place_order("market", side, price, qty)
        self._market_order_ids.add(order.id)

    def _cancel(self, oid: str):
        self._market_order_ids.discard(oid)
        self.ob.cancel_order(oid)

    def _seed_book(self):
        for i in range(1, TARGET_LEVELS_PER_SIDE + 1):
            spread = MIN_HALF_SPREAD + i * 0.01
            self._place(Side.BUY, round(self.mid - spread, 2), round(random.uniform(1.0, 10.0), 4))
            self._place(Side.SELL, round(self.mid + spread, 2), round(random.uniform(1.0, 10.0), 4))

    def _tick(self):
        # evolve bias and mid
        self.bias = self.bias * self.bias_decay + random.gauss(0, self.bias_noise)
        self.mid += self.bias + random.gauss(0, self.volatility)
        self.mid = max(1.0, self.mid)

        # ── 1. Cleanup: remove stale/wrong-sided market orders ───────
        self._market_order_ids = {
            oid for oid in self._market_order_ids if oid in self.ob.orders
        }

        to_cancel = []
        for oid in self._market_order_ids:
            order = self.ob.orders.get(oid)
            if not order:
                continue
            # wrong-sided: bids above mid or asks below mid
            if order.side == Side.BUY and order.price > self.mid:
                to_cancel.append(oid)
            elif order.side == Side.SELL and order.price < self.mid:
                to_cancel.append(oid)
            # too far from mid
            elif order.side == Side.BUY and order.price < self.mid - 0.50:
                to_cancel.append(oid)
            elif order.side == Side.SELL and order.price > self.mid + 0.50:
                to_cancel.append(oid)

        for oid in to_cancel:
            self._cancel(oid)

        # random churn: cancel a few orders
        if self._market_order_ids:
            for _ in range(random.randint(0, 2)):
                oid = random.choice(list(self._market_order_ids))
                self._cancel(oid)

        # ── 2. Aggressive trades (BEFORE passive replenishment) ──────
        if random.random() < 0.15:
            best_ask = self.ob.best_ask()
            if best_ask is not None:
                # cap qty at what's resting at best ask so we don't cascade
                resting = sum(
                    o.remaining for o in self.ob.orders.values()
                    if o.side == Side.SELL and o.price == best_ask and o.remaining > 0
                )
                qty = round(min(random.uniform(0.1, 1.5), resting), 4)
                if qty > 0:
                    self._place(Side.BUY, best_ask, qty)

        if random.random() < 0.15:
            best_bid = self.ob.best_bid()
            if best_bid is not None:
                resting = sum(
                    o.remaining for o in self.ob.orders.values()
                    if o.side == Side.BUY and o.price == best_bid and o.remaining > 0
                )
                qty = round(min(random.uniform(0.1, 1.5), resting), 4)
                if qty > 0:
                    self._place(Side.SELL, best_bid, qty)

        # ── 3. Passive replenishment (AFTER aggressive, with fresh BBO) ──
        best_ask = self.ob.best_ask()
        best_bid = self.ob.best_bid()

        bid_count = sum(
            1 for o in self.ob.orders.values()
            if o.side == Side.BUY and o.remaining > 0 and o.owner == "market"
        )
        ask_count = sum(
            1 for o in self.ob.orders.values()
            if o.side == Side.SELL and o.remaining > 0 and o.owner == "market"
        )

        bids_needed = max(0, TARGET_LEVELS_PER_SIDE - bid_count)
        asks_needed = max(0, TARGET_LEVELS_PER_SIDE - ask_count)

        # always add at least 1-2 for churn even if at target
        bids_needed = max(bids_needed, random.randint(0, 2))
        asks_needed = max(asks_needed, random.randint(0, 2))

        for _ in range(bids_needed):
            offset = random.uniform(MIN_HALF_SPREAD, MAX_DEPTH_OFFSET)
            price = round(self.mid - offset, 2)
            # guard: don't cross best ask
            if best_ask is not None and price >= best_ask:
                price = round(best_ask - 0.01, 2)
            if price <= 0:
                continue
            qty = round(random.uniform(0.5, 8.0), 4)
            self._place(Side.BUY, price, qty)

        for _ in range(asks_needed):
            offset = random.uniform(MIN_HALF_SPREAD, MAX_DEPTH_OFFSET)
            price = round(self.mid + offset, 2)
            # guard: don't cross best bid
            if best_bid is not None and price <= best_bid:
                price = round(best_bid + 0.01, 2)
            qty = round(random.uniform(0.5, 8.0), 4)
            self._place(Side.SELL, price, qty)
