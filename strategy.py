"""
Market-making strategy starter template.

Connects to the orderbook backend via WebSocket (market data) and REST (order management).
Persists trades, P&L snapshots, and session metadata to a local SQLite database (strategy.db).

Run with:
    python3 strategy.py                # no seed tracking
    python3 strategy.py --seed 42      # records which seed was used
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time

import aiohttp

# ── Configuration ────────────────────────────────

BASE_URL = "http://localhost:8765"
WS_URL = "ws://localhost:8765/ws"
DB_PATH = "strategy.db"

SPREAD_OFFSET = 0.05      # how far from mid-price to quote on each side
ORDER_SIZE = 1.0           # quantity per order
MAX_POSITION = 5.0         # stop quoting one side if position exceeds this
REQUOTE_INTERVAL = 1.0     # seconds between requote cycles


# ── Database ─────────────────────────────────────

def init_db() -> sqlite3.Connection:
    """Create tables if they don't exist and return a connection."""
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            seed        INTEGER,
            started_at  REAL    NOT NULL,
            ended_at    REAL,
            final_pnl   REAL,
            trade_count INTEGER
        );

        CREATE TABLE IF NOT EXISTS trades (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES sessions(id),
            timestamp       REAL    NOT NULL,
            side            TEXT    NOT NULL,
            price           REAL    NOT NULL,
            qty             REAL    NOT NULL,
            buy_owner       TEXT    NOT NULL,
            sell_owner      TEXT    NOT NULL,
            buy_order_id    TEXT    NOT NULL,
            sell_order_id   TEXT    NOT NULL,
            position_after  REAL    NOT NULL,
            cash_after      REAL    NOT NULL,
            total_pnl       REAL    NOT NULL
        );

        CREATE TABLE IF NOT EXISTS snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id      INTEGER NOT NULL REFERENCES sessions(id),
            timestamp       REAL    NOT NULL,
            mid_price       REAL    NOT NULL,
            spread          REAL,
            position        REAL    NOT NULL,
            cash            REAL    NOT NULL,
            unrealized_pnl  REAL    NOT NULL,
            total_pnl       REAL    NOT NULL,
            total_bought    REAL    NOT NULL,
            total_sold      REAL    NOT NULL,
            trade_count     INTEGER NOT NULL
        );
    """)
    conn.commit()
    return conn


def start_session(conn: sqlite3.Connection, seed: int | None) -> int:
    """Insert a new session row and return its id."""
    cur = conn.execute(
        "INSERT INTO sessions (seed, started_at) VALUES (?, ?)",
        (seed, time.time()),
    )
    conn.commit()
    return cur.lastrowid


def end_session(conn: sqlite3.Connection, session_id: int, final_pnl: float, trade_count: int):
    """Stamp the session with end time and final P&L."""
    conn.execute(
        "UPDATE sessions SET ended_at = ?, final_pnl = ?, trade_count = ? WHERE id = ?",
        (time.time(), final_pnl, trade_count, session_id),
    )
    conn.commit()


def record_trades(conn: sqlite3.Connection, session_id: int, fills: list, pos_data: dict):
    """Insert new strategy fills into the trades table."""
    now = time.time()
    for fill in fills:
        conn.execute(
            "INSERT INTO trades (session_id, timestamp, side, price, qty, buy_owner, sell_owner, buy_order_id, sell_order_id, position_after, cash_after, total_pnl) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                fill.get("timestamp", now),
                fill["aggressor"],
                fill["price"],
                fill["qty"],
                fill["buyOwner"],
                fill["sellOwner"],
                fill["buyOrderId"],
                fill["sellOrderId"],
                pos_data["position"],
                pos_data["cash"],
                pos_data["totalPnl"],
            ),
        )
    conn.commit()


def record_snapshot(conn: sqlite3.Connection, session_id: int, data: dict):
    """Insert a P&L snapshot."""
    pos = data["position"]
    conn.execute(
        "INSERT INTO snapshots (session_id, timestamp, mid_price, spread, position, cash, unrealized_pnl, total_pnl, total_bought, total_sold, trade_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            session_id,
            data.get("timestamp", time.time()),
            data["midPrice"],
            data.get("spread"),
            pos["position"],
            pos["cash"],
            pos.get("unrealizedPnl", 0),
            pos.get("totalPnl", 0),
            pos.get("totalBought", 0),
            pos.get("totalSold", 0),
            pos.get("tradeCount", 0),
        ),
    )
    conn.commit()


# ── Helpers ──────────────────────────────────────

async def cancel_all_orders(session: aiohttp.ClientSession):
    """Cancel every active strategy order."""
    async with session.get(f"{BASE_URL}/orders") as resp:
        orders = await resp.json()
    for order in orders:
        await session.delete(f"{BASE_URL}/orders/{order['id']}")


async def place_order(session: aiohttp.ClientSession, side: str, price: float, qty: float):
    """Place a limit order and return the response."""
    payload = {"side": side, "price": round(price, 2), "qty": qty}
    async with session.post(f"{BASE_URL}/orders", json=payload) as resp:
        return await resp.json()


# ── Main loop ────────────────────────────────────

async def run(seed: int | None = None):
    conn = init_db()
    session_id = start_session(conn, seed)
    http = aiohttp.ClientSession()
    print(f"Database: {DB_PATH}")
    print(f"Session:  {session_id}  (seed={seed})")

    last_pnl = 0.0
    last_trade_count = 0

    try:
        ws = await http.ws_connect(WS_URL)
        print("Connected to orderbook feed.")

        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue

            data = json.loads(msg.data)
            mid = data.get("midPrice")
            if mid is None:
                continue

            pos_data = data["position"]
            position = pos_data["position"]
            last_pnl = pos_data.get("totalPnl", 0)
            last_trade_count = pos_data.get("tradeCount", 0)

            # ── Record any new fills ──
            fills = data.get("strategyFills", [])
            if fills:
                record_trades(conn, session_id, fills, pos_data)

            # ── Record P&L snapshot ──
            record_snapshot(conn, session_id, data)

            # --- 1. Cancel stale orders ---
            await cancel_all_orders(http)

            # --- 2. Decide quotes ---
            bid_price = mid - SPREAD_OFFSET
            ask_price = mid + SPREAD_OFFSET

            # --- 3. Place new orders (respect inventory limits) ---
            if position < MAX_POSITION:
                await place_order(http, "buy", bid_price, ORDER_SIZE)

            if position > -MAX_POSITION:
                await place_order(http, "sell", ask_price, ORDER_SIZE)

            # --- 4. Throttle ---
            await asyncio.sleep(REQUOTE_INTERVAL)

    except KeyboardInterrupt:
        print("Shutting down...")
    finally:
        await cancel_all_orders(http)
        await http.close()
        end_session(conn, session_id, last_pnl, last_trade_count)
        conn.close()
        print(f"Session {session_id} ended. Final P&L: {last_pnl:.4f}  Trades: {last_trade_count}")


# ── CLI ──────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Market-making strategy")
    parser.add_argument("--seed", type=int, default=None, help="Simulator seed (must match SIM_SEED on backend)")
    args = parser.parse_args()
    asyncio.run(run(seed=args.seed))
