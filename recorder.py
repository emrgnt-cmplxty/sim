"""
Records orderbook snapshots from the live backend for a fixed duration.

Usage:
    python3 recorder.py                     # 50 seconds, default DB
    python3 recorder.py --duration 30       # 30 seconds
    python3 recorder.py --seed 42           # tag recording with seed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sqlite3
import time

import aiohttp

WS_URL = "ws://localhost:8765/ws"
DB_PATH = "strategy.db"


def init_db(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS recordings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            seed        INTEGER,
            started_at  REAL    NOT NULL,
            ended_at    REAL,
            tick_count  INTEGER,
            duration    REAL
        );

        CREATE TABLE IF NOT EXISTS recorded_ticks (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id INTEGER NOT NULL REFERENCES recordings(id),
            seq          INTEGER NOT NULL,
            timestamp    REAL    NOT NULL,
            snapshot     TEXT    NOT NULL
        );
    """)
    conn.commit()
    return conn


async def record(duration: float, seed: int | None, db_path: str):
    conn = init_db(db_path)

    cur = conn.execute(
        "INSERT INTO recordings (seed, started_at, duration) VALUES (?, ?, ?)",
        (seed, time.time(), duration),
    )
    conn.commit()
    recording_id = cur.lastrowid
    print(f"Recording {recording_id}: {duration}s (seed={seed})")

    session = aiohttp.ClientSession()
    ws = await session.ws_connect(WS_URL)
    print("Connected. Recording...")

    start = time.time()
    seq = 0

    try:
        async for msg in ws:
            elapsed = time.time() - start
            if elapsed >= duration:
                break

            if msg.type != aiohttp.WSMsgType.TEXT:
                continue

            data = json.loads(msg.data)
            if data.get("midPrice") is None:
                continue

            conn.execute(
                "INSERT INTO recorded_ticks (recording_id, seq, timestamp, snapshot) VALUES (?, ?, ?, ?)",
                (recording_id, seq, data.get("timestamp", time.time()), msg.data),
            )
            seq += 1

            if seq % 50 == 0:
                conn.commit()
                print(f"  {elapsed:.1f}s  {seq} ticks")

    finally:
        conn.commit()
        conn.execute(
            "UPDATE recordings SET ended_at = ?, tick_count = ? WHERE id = ?",
            (time.time(), seq, recording_id),
        )
        conn.commit()
        await ws.close()
        await session.close()
        conn.close()
        print(f"Done. Recorded {seq} ticks as recording {recording_id}.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record orderbook snapshots")
    parser.add_argument("--duration", type=float, default=50.0, help="Seconds to record (default 50)")
    parser.add_argument("--seed", type=int, default=None, help="Tag recording with simulator seed")
    parser.add_argument("--db", type=str, default=DB_PATH, help="SQLite database path")
    args = parser.parse_args()
    asyncio.run(record(args.duration, args.seed, args.db))
