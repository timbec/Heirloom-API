import os

# Always point at the test database (never the dev one) before anything imports app settings.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/heirloom_test"
)

import asyncio  # noqa: E402
import subprocess  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.db import engine  # noqa: E402
from app.main import app  # noqa: E402


def alembic(*args: str) -> None:
    subprocess.run(["alembic", *args], check=True, capture_output=True)


async def _reset_schema() -> None:
    reset_engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with reset_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    await reset_engine.dispose()


@pytest.fixture(scope="session")
def migrated_db() -> None:
    """Build the test schema from the migrations (not create_all), so tests exercise
    exactly what production runs. Round-trips once to prove downgrade works too."""
    asyncio.run(_reset_schema())
    alembic("upgrade", "head")
    alembic("downgrade", "base")
    alembic("upgrade", "head")


@pytest.fixture
async def db(migrated_db: None) -> AsyncIterator[AsyncSession]:
    """A session whose work is rolled back after each test. Commits inside the test
    become savepoints, so the database is left untouched."""
    async with engine.connect() as conn:
        outer = await conn.begin()
        session = AsyncSession(
            bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint"
        )
        try:
            yield session
        finally:
            await session.close()
            await outer.rollback()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
