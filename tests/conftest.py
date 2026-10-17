import os
import tempfile

# Always point at the test database (never the dev one) before anything imports app settings.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://localhost:5432/heirloom_test"
)
# Fixed fake AI settings, so tests never depend on (or call with) the real key in .env.
os.environ["SECRET_KEY"] = "test-secret-key"
# Uploads go to a throwaway folder, never the real storage/.
os.environ["STORAGE_DIR"] = tempfile.mkdtemp(prefix="heirloom-test-storage-")
os.environ["GROQ_API_KEY"] = "test-key"
os.environ["GROQ_BASE_URL"] = "https://groq.test/openai/v1"
os.environ["GROQ_MODEL"] = "test-narrative-model"
os.environ["GROQ_SCORING_MODEL"] = "test-scoring-model"
os.environ["GROQ_TRANSCRIPTION_MODEL"] = "test-transcription-model"

import asyncio  # noqa: E402
import subprocess  # noqa: E402
from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from app.admin import admin_login_limiter  # noqa: E402
from app.db import engine, get_db  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.rate_limit import login_limiter  # noqa: E402
from app.security import hash_password  # noqa: E402


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
async def client(db: AsyncSession) -> AsyncIterator[AsyncClient]:
    """An HTTP client for the app, sharing the test's rolled-back database session."""
    app.dependency_overrides[get_db] = lambda: db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            yield c
    finally:
        app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def reset_rate_limits() -> None:
    login_limiter.reset()
    admin_login_limiter.reset()


PASSWORD = "correct horse battery"


async def make_user(db: AsyncSession, email: str = "ada@example.com", **kwargs) -> User:
    user = User(email=email, name="Ada", password_hash=hash_password(PASSWORD), **kwargs)
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def user(db: AsyncSession) -> User:
    return await make_user(db)


async def login_headers(client: AsyncClient, user: User) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login", json={"email": user.email, "password": PASSWORD}
    )
    return {"Authorization": f"Bearer {response.json()['token']}"}


@pytest.fixture
async def auth_headers(client: AsyncClient, user: User) -> dict[str, str]:
    return await login_headers(client, user)


@pytest.fixture
async def other_headers(client: AsyncClient, db: AsyncSession) -> dict[str, str]:
    """A second, unrelated user, for checking that users can't see each other's data."""
    return await login_headers(client, await make_user(db, email="bob@example.com"))
