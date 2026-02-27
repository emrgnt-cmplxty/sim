import asyncio
import json
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orderbook import Orderbook, Side
from position import PositionTracker

STRATEGY_OWNER = "strategy"

orderbook = Orderbook()
position_tracker = PositionTracker(STRATEGY_OWNER)

clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app):
    broadcast_task = asyncio.create_task(broadcast_loop())
    yield
    broadcast_task.cancel()


app = FastAPI(title="Orderbook Demo", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _process_fills():
    """Drain new fills and apply any involving the strategy to the position tracker."""
    fills = orderbook.drain_new_fills()
    strategy_fills = []
    for fill in fills:
        if fill.buy_owner == STRATEGY_OWNER or fill.sell_owner == STRATEGY_OWNER:
            position_tracker.apply_fill(fill)
            strategy_fills.append(fill.to_dict())
    return strategy_fills


async def broadcast_loop():
    while True:
        if clients:
            strategy_fills = _process_fills()
            snapshot = orderbook.get_snapshot()

            mid = snapshot["midPrice"] or orderbook.last_mid
            snapshot["strategyFills"] = strategy_fills
            snapshot["position"] = position_tracker.to_dict(mid)

            data = json.dumps(snapshot)
            disconnected = set()
            for ws in list(clients):
                try:
                    await ws.send_text(data)
                except Exception:
                    disconnected.add(ws)
            clients.difference_update(disconnected)
        else:
            # still drain fills even with no clients connected
            _process_fills()
        await asyncio.sleep(0.1)


# ── REST API ─────────────────────────────────────


class PlaceOrderRequest(BaseModel):
    side: str  # "buy" or "sell"
    price: float
    qty: float
    owner: Optional[str] = None


@app.get("/")
async def health():
    return {"status": "ok"}


@app.post("/orders")
async def place_order(req: PlaceOrderRequest):
    try:
        side = Side(req.side.lower())
    except ValueError:
        raise HTTPException(400, f"Invalid side: {req.side}. Use 'buy' or 'sell'.")

    if req.price <= 0:
        raise HTTPException(400, "Price must be positive.")
    if req.qty <= 0:
        raise HTTPException(400, "Quantity must be positive.")

    owner = req.owner or STRATEGY_OWNER
    order = orderbook.place_order(owner, side, req.price, req.qty)
    _process_fills()

    return {
        "id": order.id,
        "owner": order.owner,
        "side": order.side.value,
        "price": order.price,
        "qty": order.qty,
        "remaining": order.remaining,
    }


@app.delete("/orders/{order_id}")
async def cancel_order(order_id: str, owner: Optional[str] = Query(None)):
    order = orderbook.cancel_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found.")
    # If an owner was specified, verify ownership
    if owner and order.owner != owner:
        orderbook.orders[order.id] = order
        raise HTTPException(403, "Cannot cancel orders you don't own.")
    return {"cancelled": order_id}


@app.get("/orders")
async def list_orders(owner: Optional[str] = Query(None)):
    if owner is None:
        # Default: strategy orders for backwards compat
        orders = orderbook.get_orders_by_owner(STRATEGY_OWNER)
    elif owner == "all":
        orders = [o for o in orderbook.orders.values() if o.remaining > 0]
    else:
        orders = orderbook.get_orders_by_owner(owner)
    return [
        {
            "id": o.id,
            "owner": o.owner,
            "side": o.side.value,
            "price": o.price,
            "qty": o.qty,
            "remaining": round(o.remaining, 4),
        }
        for o in orders
    ]


@app.get("/position")
async def get_position():
    mid = orderbook.best_bid()
    ask = orderbook.best_ask()
    if mid and ask:
        mid = (mid + ask) / 2
    else:
        mid = orderbook.last_mid
    return position_tracker.to_dict(mid)


# ── Book summary (simulator reads this) ──────────


@app.get("/book/summary")
async def book_summary():
    best_bid = orderbook.best_bid()
    best_ask = orderbook.best_ask()

    bid_top_qty = 0.0
    ask_top_qty = 0.0
    if best_bid is not None:
        bid_top_qty = sum(
            o.remaining for o in orderbook.orders.values()
            if o.side == Side.BUY and o.price == best_bid and o.remaining > 0
        )
    if best_ask is not None:
        ask_top_qty = sum(
            o.remaining for o in orderbook.orders.values()
            if o.side == Side.SELL and o.price == best_ask and o.remaining > 0
        )

    market_bid_count = sum(
        1 for o in orderbook.orders.values()
        if o.side == Side.BUY and o.remaining > 0 and o.owner == "market"
    )
    market_ask_count = sum(
        1 for o in orderbook.orders.values()
        if o.side == Side.SELL and o.remaining > 0 and o.owner == "market"
    )

    return {
        "bestBid": best_bid,
        "bestAsk": best_ask,
        "bidTopQty": round(bid_top_qty, 4),
        "askTopQty": round(ask_top_qty, 4),
        "marketBidCount": market_bid_count,
        "marketAskCount": market_ask_count,
    }


# ── Batch endpoint (one round-trip for simulator) ──


class BatchOrderItem(BaseModel):
    side: str
    price: float
    qty: float
    owner: Optional[str] = "market"


class BatchRequest(BaseModel):
    cancels: list[str] = []
    orders: list[BatchOrderItem] = []
    get_summary: bool = False


@app.post("/batch")
async def batch(req: BatchRequest):
    # 1. Process cancels
    cancelled = []
    for oid in req.cancels:
        order = orderbook.cancel_order(oid)
        if order:
            cancelled.append(oid)

    # 2. Process placements
    placed = []
    for item in req.orders:
        try:
            side = Side(item.side.lower())
        except ValueError:
            continue
        if item.price <= 0 or item.qty <= 0:
            continue
        owner = item.owner or "market"
        order = orderbook.place_order(owner, side, item.price, item.qty)
        placed.append({
            "id": order.id,
            "owner": order.owner,
            "side": order.side.value,
            "price": order.price,
            "qty": order.qty,
            "remaining": order.remaining,
        })

    # 3. Process fills
    _process_fills()

    result: dict = {"cancelled": cancelled, "placed": placed}

    # 4. Optionally return book summary
    if req.get_summary:
        result["summary"] = await book_summary()

    return result


# ── WebSocket ────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        snapshot = orderbook.get_snapshot()
        mid = snapshot["midPrice"] or orderbook.last_mid
        snapshot["strategyFills"] = []
        snapshot["position"] = position_tracker.to_dict(mid)
        await ws.send_text(json.dumps(snapshot))
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        clients.discard(ws)
