import asyncio

import aiohttp
import pytest
import uvicorn

import main
from orderbook import Side
from simulator import Simulator


@pytest.fixture
async def live_server():
    config = uvicorn.Config(main.app, host="127.0.0.1", port=0, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    await task


async def test_seed_book_populates_orderbook(live_server):
    sim = Simulator(base_url=live_server, base_price=100.0, seed=42)
    async with aiohttp.ClientSession() as session:
        sim._session = session
        await sim._seed_book()
    buy_count = sum(1 for o in main.orderbook.orders.values() if o.side == Side.BUY)
    sell_count = sum(1 for o in main.orderbook.orders.values() if o.side == Side.SELL)
    assert buy_count == 18
    assert sell_count == 18


async def test_single_tick_no_crash(live_server):
    sim = Simulator(base_url=live_server, base_price=100.0, seed=42)
    async with aiohttp.ClientSession() as session:
        sim._session = session
        await sim._seed_book()
        await sim._tick()
    assert len(main.orderbook.orders) > 0
