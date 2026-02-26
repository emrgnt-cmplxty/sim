# Orderbook Demo

Real-time orderbook with a Python backend, React frontend, and a REST API for building trading strategies.

A FastAPI server simulates market activity — random orders around a drifting mid-price with momentum bias — and streams orderbook snapshots over WebSocket at ~10Hz. The React UI renders the orderbook, depth chart, recent trades, and strategy P&L.

## Quick Start

**Backend** (terminal 1):

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --port 8765
```

**Frontend** (terminal 2):

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

## Project Structure

```
backend/
├── main.py            # FastAPI app, REST + WebSocket endpoints
├── orderbook.py       # Order-level book with price-time priority matching
├── simulator.py       # Market data generator with momentum bias
├── position.py        # Position & P&L tracker
└── requirements.txt

frontend/
└── src/
    ├── App.jsx
    ├── App.css
    ├── hooks/useOrderbook.js
    └── components/
        ├── Orderbook.jsx      # Bid/ask depth table
        ├── Spread.jsx         # Mid-price & spread
        ├── DepthChart.jsx     # SVG stepped area chart
        ├── RecentTrades.jsx   # Scrolling trade ticker
        └── PositionPanel.jsx  # Strategy P&L display
```

## How It Works

1. The **simulator** places passive (non-crossing) limit orders on both sides, occasionally injecting aggressive orders that cross the spread to generate trades
2. The **orderbook** tracks individual orders with IDs and ownership, matching with price-time priority. Fills are attributed to the order owner
3. The **broadcast loop** sends snapshots (top 20 levels, recent trades, strategy P&L) to all WebSocket clients at ~10Hz
4. The **React frontend** renders the orderbook, depth chart, trade ticker, and P&L panel from a single shared WebSocket stream

## Strategy API

The backend exposes REST endpoints for building a trading strategy. All strategy orders are placed under the `"strategy"` owner.

### Place an order

```
POST /orders
Content-Type: application/json

{"side": "buy", "price": 99.50, "qty": 2.0}
```

Response:
```json
{"id": "a1b2c3d4e5f6", "side": "buy", "price": 99.50, "qty": 2.0, "remaining": 2.0}
```

### Cancel an order

```
DELETE /orders/{order_id}
```

### List active orders

```
GET /orders
```

### Get position & P&L

```
GET /position
```

Response:
```json
{
  "owner": "strategy",
  "position": 1.5,
  "cash": -149.25,
  "unrealizedPnl": 150.75,
  "totalPnl": 1.50,
  "totalBought": 3.0,
  "totalSold": 1.5,
  "tradeCount": 4
}
```

### WebSocket feed

Connect to `ws://localhost:8765/ws` to receive JSON snapshots every ~100ms:

```json
{
  "bids": [[price, size], ...],
  "asks": [[price, size], ...],
  "spread": 0.02,
  "midPrice": 100.50,
  "trades": [{"price": 100.01, "qty": 1.5, "aggressor": "buy", ...}, ...],
  "strategyFills": [...],
  "position": {"position": 1.5, "totalPnl": 1.50, ...},
  "timestamp": 1234567890.123
}
```

## Interview Task

Your task is to implement a market-making strategy that quotes both sides of the book for a profit. You have:

- **Market data** via WebSocket (orderbook levels, trades, mid-price)
- **Order management** via REST (`POST /orders`, `DELETE /orders/{id}`)
- **Position tracking** via REST (`GET /position`) or WebSocket (`position` field)

Build a strategy (in Python, or any language that can call HTTP + connect to a WebSocket) that:
1. Continuously quotes bid and ask prices around the mid-price
2. Manages inventory risk (don't accumulate too large a position)
3. Turns a profit over time

The P&L panel in the frontend will show your results in real time.
# sim
