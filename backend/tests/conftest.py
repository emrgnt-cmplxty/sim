import pytest
from httpx import ASGITransport, AsyncClient

import main
from orderbook import Orderbook
from position import PositionTracker


@pytest.fixture
def fresh_orderbook():
    return Orderbook()


@pytest.fixture
def fresh_position():
    return PositionTracker("strategy")


@pytest.fixture(autouse=True)
def reset_global_state():
    """Reset the global singletons in main.py before each test."""
    main.orderbook = Orderbook()
    main.position_tracker = PositionTracker(main.STRATEGY_OWNER)
    main.clients = set()
    yield
    main.orderbook = Orderbook()
    main.position_tracker = PositionTracker(main.STRATEGY_OWNER)
    main.clients = set()


@pytest.fixture
async def client():
    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
