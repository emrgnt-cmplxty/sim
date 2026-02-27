"""
Optimizer — generates N random strategy parameter combinations, backtests
each against a recorded session, and ranks by risk-adjusted P&L.

Usage:
    python3 optimize.py                    # 100 strategies, latest recording
    python3 optimize.py -n 500            # 500 strategies
    python3 optimize.py --recording 1     # specific recording
    python3 optimize.py --top 20          # show top 20

Risk-adjusted P&L = final_pnl - penalty * max(|position|)
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sqlite3
import sys

from backtest import BacktestEngine, load_ticks
from strategies.parameterized import Strategy

DB_PATH = "strategy.db"

# ── Parameter space ──────────────────────────────

PARAM_RANGES = {
    "spread_offset": (0.005, 0.10),    # how far from mid to quote
    "order_size":    (0.1, 5.0),       # qty per order
    "max_position":  (1.0, 20.0),      # inventory limit
    "skew_factor":   (0.0, 0.05),      # price shift per unit position
}


def sample_params() -> dict:
    """Sample a random parameter combination."""
    return {
        key: round(random.uniform(lo, hi), 4)
        for key, (lo, hi) in PARAM_RANGES.items()
    }


# ── Scoring ──────────────────────────────────────

def score(engine: BacktestEngine, result: dict) -> dict:
    """Compute risk-adjusted metrics from a backtest run."""
    final_pnl = result["final_pnl"]
    final_pos = result["final_position"]
    trade_count = result["trade_count"]

    # Peak absolute position during the run
    max_abs_position = 0.0
    for point in engine.pnl_curve:
        max_abs_position = max(max_abs_position, abs(point["position"]))

    # P&L standard deviation (volatility of returns)
    pnls = [p["total_pnl"] for p in engine.pnl_curve]
    if len(pnls) > 1:
        mean_pnl = sum(pnls) / len(pnls)
        variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
        pnl_std = math.sqrt(variance)
    else:
        pnl_std = 0.0

    # Risk-adjusted P&L: penalize large positions
    position_penalty = 0.5  # per unit of max position
    risk_adjusted_pnl = final_pnl - position_penalty * max_abs_position

    # Simple Sharpe-like ratio (P&L / volatility)
    sharpe = final_pnl / pnl_std if pnl_std > 0 else 0.0

    return {
        "final_pnl": final_pnl,
        "risk_adjusted_pnl": round(risk_adjusted_pnl, 4),
        "sharpe": round(sharpe, 4),
        "max_abs_position": round(max_abs_position, 4),
        "final_position": final_pos,
        "pnl_std": round(pnl_std, 4),
        "trade_count": trade_count,
    }


# ── Main ─────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Optimize strategy parameters")
    parser.add_argument("-n", type=int, default=100, help="Number of random strategies to test (default 100)")
    parser.add_argument("--recording", type=int, default=None, help="Recording ID (default: latest)")
    parser.add_argument("--top", type=int, default=10, help="Show top N results (default 10)")
    parser.add_argument("--db", type=str, default=DB_PATH, help="SQLite database path")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible sweeps")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    ticks, rec_id = load_ticks(args.db, args.recording)

    print(f"Optimizing {args.n} strategies against recording {rec_id} ({len(ticks)} ticks)")
    print(f"Parameter ranges: {json.dumps(PARAM_RANGES, indent=2)}")
    print()

    results = []

    for i in range(args.n):
        params = sample_params()
        strategy = Strategy(**params)
        engine = BacktestEngine()
        result = engine.run(ticks, strategy)
        scores = score(engine, result)

        results.append({
            "rank": 0,
            "params": params,
            "scores": scores,
        })

        if (i + 1) % 25 == 0 or i == 0:
            print(f"  [{i + 1}/{args.n}] latest: pnl={scores['final_pnl']:.2f}  risk_adj={scores['risk_adjusted_pnl']:.2f}  pos={scores['final_position']:.2f}")

    # Sort by risk-adjusted P&L
    results.sort(key=lambda r: r["scores"]["risk_adjusted_pnl"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    # Display top results
    print()
    print("=" * 80)
    print(f"  TOP {args.top} STRATEGIES (by risk-adjusted P&L)")
    print("=" * 80)

    for r in results[:args.top]:
        s = r["scores"]
        p = r["params"]
        print(f"\n  #{r['rank']}")
        print(f"    spread={p['spread_offset']:.4f}  size={p['order_size']:.4f}  max_pos={p['max_position']:.4f}  skew={p['skew_factor']:.4f}")
        print(f"    P&L={s['final_pnl']:>8.2f}  risk_adj={s['risk_adjusted_pnl']:>8.2f}  sharpe={s['sharpe']:>6.2f}  trades={s['trade_count']}  max|pos|={s['max_abs_position']:.2f}  final_pos={s['final_position']:.2f}")

    # Save to DB
    conn = sqlite3.connect(args.db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS optimization_runs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            recording_id    INTEGER NOT NULL,
            n_strategies    INTEGER NOT NULL,
            timestamp       REAL    NOT NULL,
            best_params     TEXT,
            best_risk_adj   REAL,
            best_pnl        REAL
        );

        CREATE TABLE IF NOT EXISTS optimization_results (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id          INTEGER NOT NULL REFERENCES optimization_runs(id),
            rank            INTEGER NOT NULL,
            spread_offset   REAL,
            order_size      REAL,
            max_position    REAL,
            skew_factor     REAL,
            final_pnl       REAL,
            risk_adjusted   REAL,
            sharpe          REAL,
            max_abs_pos     REAL,
            final_pos       REAL,
            trade_count     INTEGER
        );
    """)

    import time
    best = results[0]
    cur = conn.execute(
        "INSERT INTO optimization_runs (recording_id, n_strategies, timestamp, best_params, best_risk_adj, best_pnl) VALUES (?, ?, ?, ?, ?, ?)",
        (rec_id, args.n, time.time(), json.dumps(best["params"]), best["scores"]["risk_adjusted_pnl"], best["scores"]["final_pnl"]),
    )
    run_id = cur.lastrowid

    for r in results:
        p = r["params"]
        s = r["scores"]
        conn.execute(
            "INSERT INTO optimization_results (run_id, rank, spread_offset, order_size, max_position, skew_factor, final_pnl, risk_adjusted, sharpe, max_abs_pos, final_pos, trade_count) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, r["rank"], p["spread_offset"], p["order_size"], p["max_position"], p["skew_factor"], s["final_pnl"], s["risk_adjusted_pnl"], s["sharpe"], s["max_abs_position"], s["final_position"], s["trade_count"]),
        )

    conn.commit()
    conn.close()

    print(f"\nResults saved to {args.db} (run {run_id})")
    print(f"\nTo use the best strategy live:")
    best_p = best["params"]
    print(f'  spread_offset={best_p["spread_offset"]}  order_size={best_p["order_size"]}  max_position={best_p["max_position"]}  skew_factor={best_p["skew_factor"]}')


if __name__ == "__main__":
    main()
