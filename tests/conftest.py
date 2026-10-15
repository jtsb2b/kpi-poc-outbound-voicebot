from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from mongomock_motor import AsyncMongoMockClient

from kpi_voicebot.api import create_app
from kpi_voicebot.config import Settings
from kpi_voicebot.store import Store

TOKEN = "test-operator-token"


@pytest.fixture
def settings() -> Settings:
    return Settings(operator_token=TOKEN, sim_turn_delay_ms=0, _env_file=None)  # type: ignore[call-arg]


@pytest.fixture
async def store() -> Store:
    s = Store(AsyncMongoMockClient()["kpi_test"], retention_days=30)
    await s.ensure_indexes()
    return s


@pytest.fixture
async def client(settings: Settings, store: Store) -> AsyncIterator[AsyncClient]:
    app = create_app(settings, store)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test", headers=headers) as c,
    ):
        yield c
