import asyncio
import os
import sys

from httpx import AsyncClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import engine
from app.models import ApiToken, User
from app.security import hash_token, verify_password
from tests.conftest import PASSWORD

BAD_CREDENTIALS = "The credentials you provided are incorrect."


async def login(client: AsyncClient, email: str, password: str = PASSWORD):
    return await client.post("/api/auth/login", json={"email": email, "password": password})


async def test_login_returns_token_and_user(client: AsyncClient, db: AsyncSession, user: User):
    response = await login(client, "ada@example.com")

    assert response.status_code == 200
    body = response.json()
    assert len(body["token"]) == 40
    assert body["user"]["id"] == user.id
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["is_admin"] is False
    assert "password_hash" not in body["user"]

    # Only the hash is stored.
    stored = await db.scalar(select(ApiToken).where(ApiToken.user_id == user.id))
    assert stored.token_hash == hash_token(body["token"])


async def test_login_email_is_case_insensitive(client: AsyncClient, user: User):
    response = await login(client, "  ADA@Example.COM ")
    assert response.status_code == 200


async def test_wrong_password_matches_laravel_response(client: AsyncClient, user: User):
    response = await login(client, "ada@example.com", "wrong password")
    assert response.status_code == 422
    assert response.json() == {"message": BAD_CREDENTIALS, "errors": {"email": [BAD_CREDENTIALS]}}


async def test_unknown_email_gets_same_response(client: AsyncClient):
    response = await login(client, "nobody@example.com")
    assert response.status_code == 422
    assert response.json()["message"] == BAD_CREDENTIALS


async def test_missing_fields_are_validation_errors(client: AsyncClient):
    response = await client.post("/api/auth/login", json={"email": "ada@example.com"})
    assert response.status_code == 422
    assert "password" in response.json()["errors"]


async def test_login_rate_limited_per_ip(client: AsyncClient, user: User):
    for _ in range(5):
        assert (await login(client, "ada@example.com", "wrong")).status_code == 422

    response = await login(client, "ada@example.com")  # right password, still blocked
    assert response.status_code == 429
    assert response.json()["message"].startswith("Too many login attempts")
    assert int(response.headers["retry-after"]) > 0


async def test_token_authenticates(client: AsyncClient, auth_headers: dict[str, str]):
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    assert response.json()["email"] == "ada@example.com"


async def test_token_records_last_use(
    client: AsyncClient, db: AsyncSession, auth_headers: dict[str, str]
):
    await client.get("/api/auth/me", headers=auth_headers)
    token = await db.scalar(select(ApiToken))
    assert token.last_used_at is not None


async def test_missing_or_bad_token_is_401(client: AsyncClient):
    for headers in ({}, {"Authorization": "Bearer not-a-real-token"}, {"Authorization": "x"}):
        response = await client.get("/api/auth/me", headers=headers)
        assert response.status_code == 401
        assert response.json() == {"message": "Unauthenticated."}


async def test_logout_revokes_only_that_token(client: AsyncClient, user: User):
    first = {"Authorization": f"Bearer {(await login(client, user.email)).json()['token']}"}
    second = {"Authorization": f"Bearer {(await login(client, user.email)).json()['token']}"}

    assert (await client.post("/api/auth/logout", headers=first)).status_code == 204
    assert (await client.get("/api/auth/me", headers=first)).status_code == 401
    assert (await client.get("/api/auth/me", headers=second)).status_code == 200


async def run_cli(*args: str) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.cli", *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=os.environ,
    )  # fmt: skip
    stdout, stderr = await process.communicate()
    return process.returncode, stdout.decode(), stderr.decode()


async def test_cli_creates_admin_user(migrated_db: None):
    """Runs the real command in a subprocess, which commits, so clean up afterwards."""
    email = "cli-test@example.com"
    try:
        code, out, err = await run_cli(
            "create-user", "--email", "CLI-Test@Example.com", "--name", "Cli Test",
            "--password", "a long password", "--admin",
        )  # fmt: skip
        assert code == 0, err
        assert f"Created admin {email}" in out

        async with engine.connect() as conn:
            row = (await conn.execute(select(User).where(User.email == email))).one()
        assert row.is_admin is True
        assert verify_password("a long password", row.password_hash)

        code, _, err = await run_cli(
            "create-user", "--email", email, "--name", "X", "--password", "a long password"
        )
        assert code != 0
        assert "already exists" in err
    finally:
        async with engine.begin() as conn:
            await conn.execute(delete(User).where(User.email == email))


async def test_cli_rejects_short_password(migrated_db: None):
    code, _, err = await run_cli(
        "create-user", "--email", "short@example.com", "--name", "S", "--password", "short"
    )
    assert code != 0
    assert "at least 8 characters" in err
