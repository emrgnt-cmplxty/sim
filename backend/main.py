import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from orderbook import Orderbook, Side
from simulator import Simulator
from position import PositionTracker

STRATEGY_OWNER = "strategy"

orderbook = Orderbook()
simulator = Simulator(orderbook, base_price=100.00)
position_tracker = PositionTracker(STRATEGY_OWNER)

clients: set[WebSocket] = set()


@asynccontextmanager
async def lifespan(app):
    sim_task = asyncio.create_task(simulator.start())
    broadcast_task = asyncio.create_task(broadcast_loop())
    yield
    simulator.stop()
    sim_task.cancel()
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

            mid = snapshot["midPrice"] or simulator.mid
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

    order = orderbook.place_order(STRATEGY_OWNER, side, req.price, req.qty)
    _process_fills()

    return {
        "id": order.id,
        "side": order.side.value,
        "price": order.price,
        "qty": order.qty,
        "remaining": order.remaining,
    }


@app.delete("/orders/{order_id}")
async def cancel_order(order_id: str):
    order = orderbook.cancel_order(order_id)
    if not order:
        raise HTTPException(404, "Order not found.")
    if order.owner != STRATEGY_OWNER:
        # put it back — can't cancel market orders
        orderbook.orders[order.id] = order
        raise HTTPException(403, "Cannot cancel orders you don't own.")
    return {"cancelled": order_id}


@app.get("/orders")
async def list_orders():
    orders = orderbook.get_orders_by_owner(STRATEGY_OWNER)
    return [
        {
            "id": o.id,
            "side": o.side.value,
            "price": o.price,
            "qty": o.qty,
            "remaining": round(o.remaining, 4),
        }
        for o in orders
    ]


@app.get("/position")
async def get_position():
    mid = orderbook.best_bid() or simulator.mid
    ask = orderbook.best_ask()
    if mid and ask:
        mid = (mid + ask) / 2
    return position_tracker.to_dict(mid)


# ── WebSocket ────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    try:
        snapshot = orderbook.get_snapshot()
        mid = snapshot["midPrice"] or simulator.mid
        snapshot["strategyFills"] = []
        snapshot["position"] = position_tracker.to_dict(mid)
        await ws.send_text(json.dumps(snapshot))
        while True:
            await ws.receive_text()
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        clients.discard(ws)
