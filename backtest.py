"""
Backtest harness — replays a recorded orderbook session and runs strategy
functions against it to measure P&L.

Usage:
    python3 backtest.py                          # latest recording, default strategy
    python3 backtest.py --recording 1            # specific recording
    python3 backtest.py --strategy my_strats.py  # custom strategy file

Strategy interface:
    Your strategy file must define a class called `Strategy` with:

        class Strategy:
            def on_tick(self, snapshot: dict) -> list[dict]:
                '''Return orders to place this tick.
                Each order: {"side": "buy" or "sell", "price": float, "qty": float}
                All previous orders are implicitly cancelled each tick.'''
                return []

See strategies/example.py for a starter.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sqlite3
import sys

DB_PATH = "strategy.db"


# ── Simple fill simulator ────────────────────────

class BacktestEngine:
    """Replays recorded ticks and simulates fills for a strategy."""

    def __init__(self):
        self.position = 0.0
        self.cash = 0.0
        self.total_bought = 0.0
        self.total_sold = 0.0
        self.trade_count = 0
        self.trades: list[dict] = []
        self.pnl_curve: list[dict] = []

    def _try_fill(self, order: dict, snapshot: dict):
        """Check if a strategy order would fill against the recorded book."""
        side = order["side"]
        price = order["price"]
        qty = order["qty"]

        if side == "buy":
            # Buy order fills if our price >= best ask
            asks = snapshot.get("asks", [])
            if not asks:
                return
            best_ask_price = asks[0][0]
            best_ask_size = asks[0][1]
            if price >= best_ask_price:
                fill_qty = min(qty, best_ask_size)
                fill_price = best_ask_price
                self.position += fill_qty
                self.cash -= fill_price * fill_qty
                self.total_bought += fill_qty
                self.trade_count += 1
                self.trades.append({
                    "timestamp": snapshot.get("timestamp"),
                    "side": "buy",
                    "price": fill_price,
                    "qty": fill_qty,
                    "position_after": self.position,
                })

        elif side == "sell":
            # Sell order fills if our price <= best bid
            bids = snapshot.get("bids", [])
            if not bids:
                return
            best_bid_price = bids[0][0]
            best_bid_size = bids[0][1]
            if price <= best_bid_price:
                fill_qty = min(qty, best_bid_size)
                fill_price = best_bid_price
                self.position -= fill_qty
                self.cash += fill_price * fill_qty
                self.total_sold += fill_qty
                self.trade_count += 1
                self.trades.append({
                    "timestamp": snapshot.get("timestamp"),
                    "side": "sell",
                    "price": fill_price,
                    "qty": fill_qty,
                    "position_after": self.position,
                })

    def unrealized_pnl(self, mid_price: float) -> float:
        return self.position * mid_price

    def total_pnl(self, mid_price: float) -> float:
        return self.cash + self.unrealized_pnl(mid_price)

    def _check_resting_fills(self, resting_orders: list[dict], snapshot: dict):
        """Check if any resting orders from the previous tick would fill
        given the current snapshot's BBO and trades."""
        filled = []
        # Check if recorded trades swept through our price
        trades = snapshot.get("trades", [])
        trade_prices = [t["price"] for t in trades]

        for order in resting_orders:
            side = order["side"]
            price = order["price"]
            qty = order["qty"]

            if side == "buy":
                # Our resting bid fills if: best ask dropped to our price,
                # or a trade occurred at/below our price
                asks = snapshot.get("asks", [])
                best_ask = asks[0][0] if asks else None
                fills = (best_ask is not None and best_ask <= price) or any(tp <= price for tp in trade_prices)
                if fills:
                    fill_price = price  # maker gets their price
                    available = asks[0][1] if asks and asks[0][0] <= price else qty
                    fill_qty = min(qty, available)
                    self.position += fill_qty
                    self.cash -= fill_price * fill_qty
                    self.total_bought += fill_qty
                    self.trade_count += 1
                    self.trades.append({
                        "timestamp": snapshot.get("timestamp"),
                        "side": "buy",
                        "price": fill_price,
                        "qty": fill_qty,
                        "position_after": self.position,
                    })
                    filled.append(order)

            elif side == "sell":
                # Our resting ask fills if: best bid rose to our price,
                # or a trade occurred at/above our price
                bids = snapshot.get("bids", [])
                best_bid = bids[0][0] if bids else None
                fills = (best_bid is not None and best_bid >= price) or any(tp >= price for tp in trade_prices)
                if fills:
                    fill_price = price
                    available = bids[0][1] if bids and bids[0][0] >= price else qty
                    fill_qty = min(qty, available)
                    self.position -= fill_qty
                    self.cash += fill_price * fill_qty
                    self.total_sold += fill_qty
                    self.trade_count += 1
                    self.trades.append({
                        "timestamp": snapshot.get("timestamp"),
                        "side": "sell",
                        "price": fill_price,
                        "qty": fill_qty,
                        "position_after": self.position,
                    })
                    filled.append(order)

        return [o for o in resting_orders if o not in filled]

    def run(self, ticks: list[dict], strategy) -> dict:
        """Run strategy against recorded ticks. Returns summary."""
        resting_orders: list[dict] = []

        for i, snapshot in enumerate(ticks):
            mid = snapshot.get("midPrice")
            if mid is None:
                continue

            # Check if resting orders from last tick got filled this tick
            resting_orders = self._check_resting_fills(resting_orders, snapshot)

            # Inject current backtest position into snapshot so strategy can use it
            snapshot["_bt_position"] = self.position

            # Ask strategy what orders it wants (implicitly cancels previous)
            resting_orders = strategy.on_tick(snapshot)

            # Record P&L curve
            self.pnl_curve.append({
                "tick": i,
                "timestamp": snapshot.get("timestamp"),
                "mid_price": mid,
                "position": round(self.position, 4),
                "cash": round(self.cash, 4),
                "unrealized_pnl": round(self.unrealized_pnl(mid), 4),
                "total_pnl": round(self.total_pnl(mid), 4),
            })

        final_mid = ticks[-1]["midPrice"] if ticks else 0
        return {
            "final_pnl": round(self.total_pnl(final_mid), 4),
            "final_position": round(self.position, 4),
            "cash": round(self.cash, 4),
            "total_bought": round(self.total_bought, 4),
            "total_sold": round(self.total_sold, 4),
            "trade_count": self.trade_count,
            "ticks_processed": len(self.pnl_curve),
        }


# ── Load recorded ticks from DB ─────────────────

def load_ticks(db_path: str, recording_id: int | None = None) -> tuple[list[dict], int]:
    """Load recorded snapshots. Returns (ticks, recording_id)."""
    conn = sqlite3.connect(db_path)

    if recording_id is None:
        row = conn.execute("SELECT id FROM recordings ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            print("No recordings found. Run recorder.py first.")
            sys.exit(1)
        recording_id = row[0]

    rows = conn.execute(
        "SELECT snapshot FROM recorded_ticks WHERE recording_id = ? ORDER BY seq",
        (recording_id,),
    ).fetchall()
    conn.close()

    ticks = [json.loads(row[0]) for row in rows]
    print(f"Loaded recording {recording_id}: {len(ticks)} ticks")
    return ticks, recording_id


# ── Load strategy ────────────────────────────────

def load_strategy(path: str | None):
    """Import a Strategy class from a file, or use the default."""
    if path is None:
        path = "strategies/example.py"

    spec = importlib.util.spec_from_file_location("strategy_module", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    if not hasattr(mod, "Strategy"):
        print(f"Error: {path} must define a 'Strategy' class.")
        sys.exit(1)

    return mod.Strategy()


# ── Main ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Backtest a strategy against recorded data")
    parser.add_argument("--recording", type=int, default=None, help="Recording ID (default: latest)")
    parser.add_argument("--strategy", type=str, default=None, help="Path to strategy .py file")
    parser.add_argument("--db", type=str, default=DB_PATH, help="SQLite database path")
    args = parser.parse_args()

    ticks, rec_id = load_ticks(args.db, args.recording)
    strategy = load_strategy(args.strategy)

    print(f"Strategy: {strategy.__class__.__name__}")
    print(f"Running backtest...")

    engine = BacktestEngine()
    result = engine.run(ticks, strategy)

    print()
    print("═" * 40)
    print("  BACKTEST RESULTS")
    print("═" * 40)
    print(f"  Recording:      {rec_id}")
    print(f"  Ticks:          {result['ticks_processed']}")
    print(f"  Trades:         {result['trade_count']}")
    print(f"  Final position: {result['final_position']}")
    print(f"  Cash:           {result['cash']}")
    print(f"  Final P&L:      {result['final_pnl']}")
    print("═" * 40)

    # Print P&L at intervals
    curve = engine.pnl_curve
    if len(curve) > 10:
        step = len(curve) // 10
        print("\n  P&L over time:")
        for point in curve[::step]:
            print(f"    tick {point['tick']:>4}  pos={point['position']:>7.2f}  pnl={point['total_pnl']:>8.4f}")
        print(f"    tick {curve[-1]['tick']:>4}  pos={curve[-1]['position']:>7.2f}  pnl={curve[-1]['total_pnl']:>8.4f}")


if __name__ == "__main__":
    main()
