"""
Standalone market simulator — runs as a separate process and talks to the
backend via HTTP (the same REST API that strategies use).

Run with:
    python3 simulator.py                 # random seed
    python3 simulator.py --seed 42       # deterministic
    python3 simulator.py --url http://localhost:8765
"""

from __future__ import annotations

import argparse
import asyncio
import random

import aiohttp

# ── Tuning constants ─────────────────────────────

MIN_HALF_SPREAD = 0.02
MAX_DEPTH_OFFSET = 0.25
TARGET_LEVELS_PER_SIDE = 18


class Simulator:
    def __init__(self, base_url: str = "http://localhost:8765",
                 base_price: float = 100.0, seed: int | None = None):
        self.base_url = base_url.rstrip("/")
        self.mid = base_price
        self.volatility = 0.015
        self.bias = 0.0
        self.bias_decay = 0.995
        self.bias_noise = 0.002
        self._running = False
        self._market_order_ids: set[str] = set()
        self.seed = seed
        if seed is not None:
            random.seed(seed)

    async def start(self):
        self._running = True
        async with aiohttp.ClientSession() as session:
            self._session = session
            await self._wait_for_backend()
            await self._seed_book()
            while self._running:
                await self._tick()
                await asyncio.sleep(0.1)

    def stop(self):
        self._running = False

    async def _wait_for_backend(self):
        """Poll the backend health endpoint until it's ready."""
        while True:
            try:
                async with self._session.get(f"{self.base_url}/") as resp:
                    if resp.status == 200:
                        print(f"Connected to backend at {self.base_url}")
                        return
            except aiohttp.ClientError:
                pass
            print("Waiting for backend...")
            await asyncio.sleep(1.0)

    async def _batch(self, cancels: list[str], orders: list[dict],
                     get_summary: bool = False) -> dict:
        payload = {
            "cancels": cancels,
            "orders": orders,
            "get_summary": get_summary,
        }
        async with self._session.post(f"{self.base_url}/batch", json=payload) as resp:
            return await resp.json()

    async def _get_market_orders(self) -> list[dict]:
        async with self._session.get(f"{self.base_url}/orders",
                                     params={"owner": "market"}) as resp:
            return await resp.json()

    async def _get_summary(self) -> dict:
        async with self._session.get(f"{self.base_url}/book/summary") as resp:
            return await resp.json()

    async def _seed_book(self):
        orders = []
        for i in range(1, TARGET_LEVELS_PER_SIDE + 1):
            spread = MIN_HALF_SPREAD + i * 0.01
            orders.append({
                "side": "buy",
                "price": round(self.mid - spread, 2),
                "qty": round(random.uniform(1.0, 10.0), 4),
                "owner": "market",
            })
            orders.append({
                "side": "sell",
                "price": round(self.mid + spread, 2),
                "qty": round(random.uniform(1.0, 10.0), 4),
                "owner": "market",
            })

        result = await self._batch([], orders)
        # Track the placed order IDs
        for placed in result.get("placed", []):
            self._market_order_ids.add(placed["id"])

    async def _tick(self):
        # Evolve bias and mid
        self.bias = self.bias * self.bias_decay + random.gauss(0, self.bias_noise)
        self.mid += self.bias + random.gauss(0, self.volatility)
        self.mid = max(1.0, self.mid)

        # Fetch current state: market orders + book summary
        market_orders, summary = await asyncio.gather(
            self._get_market_orders(),
            self._get_summary(),
        )

        # Rebuild local tracking from server state
        live_ids = {o["id"] for o in market_orders}
        self._market_order_ids = self._market_order_ids & live_ids

        best_bid = summary["bestBid"]
        best_ask = summary["bestAsk"]
        bid_top_qty = summary["bidTopQty"]
        ask_top_qty = summary["askTopQty"]
        market_bid_count = summary["marketBidCount"]
        market_ask_count = summary["marketAskCount"]

        # Build an index for fast lookup
        orders_by_id = {o["id"]: o for o in market_orders}

        # ── 1. Cleanup: remove stale/wrong-sided market orders ───────
        to_cancel = []
        for oid in list(self._market_order_ids):
            order = orders_by_id.get(oid)
            if not order:
                continue
            price = order["price"]
            side = order["side"]
            # wrong-sided: bids above mid or asks below mid
            if side == "buy" and price > self.mid:
                to_cancel.append(oid)
            elif side == "sell" and price < self.mid:
                to_cancel.append(oid)
            # too far from mid
            elif side == "buy" and price < self.mid - 0.50:
                to_cancel.append(oid)
            elif side == "sell" and price > self.mid + 0.50:
                to_cancel.append(oid)

        # random churn: cancel a few orders
        churn_pool = list(self._market_order_ids - set(to_cancel))
        if churn_pool:
            for _ in range(random.randint(0, 2)):
                to_cancel.append(random.choice(churn_pool))

        # ── 2. Aggressive trades (BEFORE passive replenishment) ──────
        new_orders: list[dict] = []

        if random.random() < 0.15 and best_ask is not None:
            qty = round(min(random.uniform(0.1, 1.5), ask_top_qty), 4)
            if qty > 0:
                new_orders.append({
                    "side": "buy",
                    "price": best_ask,
                    "qty": qty,
                    "owner": "market",
                })

        if random.random() < 0.15 and best_bid is not None:
            qty = round(min(random.uniform(0.1, 1.5), bid_top_qty), 4)
            if qty > 0:
                new_orders.append({
                    "side": "sell",
                    "price": best_bid,
                    "qty": qty,
                    "owner": "market",
                })

        # ── 3. Passive replenishment (AFTER aggressive, with fresh BBO) ──
        # Estimate how many bids/asks we'll have after cancels
        cancel_set = set(to_cancel)
        remaining_bid_count = market_bid_count - sum(
            1 for oid in cancel_set
            if orders_by_id.get(oid, {}).get("side") == "buy"
        )
        remaining_ask_count = market_ask_count - sum(
            1 for oid in cancel_set
            if orders_by_id.get(oid, {}).get("side") == "sell"
        )

        bids_needed = max(0, TARGET_LEVELS_PER_SIDE - remaining_bid_count)
        asks_needed = max(0, TARGET_LEVELS_PER_SIDE - remaining_ask_count)

        # always add at least 1-2 for churn even if at target
        bids_needed = max(bids_needed, random.randint(0, 2))
        asks_needed = max(asks_needed, random.randint(0, 2))

        for _ in range(bids_needed):
            offset = random.uniform(MIN_HALF_SPREAD, MAX_DEPTH_OFFSET)
            price = round(self.mid - offset, 2)
            if best_ask is not None and price >= best_ask:
                price = round(best_ask - 0.01, 2)
            if price <= 0:
                continue
            qty = round(random.uniform(0.5, 8.0), 4)
            new_orders.append({
                "side": "buy",
                "price": price,
                "qty": qty,
                "owner": "market",
            })

        for _ in range(asks_needed):
            offset = random.uniform(MIN_HALF_SPREAD, MAX_DEPTH_OFFSET)
            price = round(self.mid + offset, 2)
            if best_bid is not None and price <= best_bid:
                price = round(best_bid + 0.01, 2)
            qty = round(random.uniform(0.5, 8.0), 4)
            new_orders.append({
                "side": "sell",
                "price": price,
                "qty": qty,
                "owner": "market",
            })

        # ── 4. Single batch call ─────────────────────────────────────
        result = await self._batch(to_cancel, new_orders)

        # Update local tracking
        self._market_order_ids -= cancel_set
        for placed in result.get("placed", []):
            self._market_order_ids.add(placed["id"])


# ── CLI ──────────────────────────────────────────

async def main():
    parser = argparse.ArgumentParser(description="Orderbook market simulator")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    parser.add_argument("--url", type=str, default="http://localhost:8765", help="Backend URL")
    parser.add_argument("--base-price", type=float, default=100.0, help="Starting mid price")
    args = parser.parse_args()

    sim = Simulator(base_url=args.url, base_price=args.base_price, seed=args.seed)
    print(f"Simulator starting (seed={args.seed}, base_price={args.base_price})")
    try:
        await sim.start()
    except KeyboardInterrupt:
        sim.stop()
        print("Simulator stopped.")


if __name__ == "__main__":
    asyncio.run(main())
