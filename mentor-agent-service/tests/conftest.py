import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import reset_providers_cache, settings
from app.dependencies import get_db_session
from app.main import create_app
from app.models import Base

# Default test providers.yaml content — single provider for test isolation
_TEST_PROVIDERS_YAML = """\
providers:
  - id: "test-provider"
    display_name: "Test Provider"
    base_url: "http://test-proxy:3456/v1"
    api_key: "test-key"
    model: "test-model"
"""


@pytest.fixture(autouse=True)
def _providers_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Auto-use fixture: create a temporary providers.yaml for every test.

    This ensures get_providers() always has a valid config file,
    preventing ConfigurationError from leaking across tests.
    """
    yaml_file = tmp_path / "providers.yaml"
    yaml_file.write_text(_TEST_PROVIDERS_YAML)
    # Patch both the env var AND the already-instantiated settings singleton
    monkeypatch.setenv("PROVIDERS_YAML_PATH", str(yaml_file))
    monkeypatch.setattr(settings, "providers_yaml_path", str(yaml_file))
    # Reset cached providers so each test starts fresh
    reset_providers_cache()
    yield yaml_file
    reset_providers_cache()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite://", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    app = create_app()

    async def _override_db_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db_session] = _override_db_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.pop(get_db_session, None)
