from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from pydantic import BaseModel

from app.config import Settings
from app.main import create_app


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_docs_live_under_api(client: AsyncClient) -> None:
    assert (await client.get("/api/docs")).status_code == 200
    assert (await client.get("/api/openapi.json")).status_code == 200


async def test_cors_preflight_allows_frontend_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/api/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"


async def test_cors_preflight_rejects_unknown_origin(client: AsyncClient) -> None:
    response = await client.options(
        "/api/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_cors_origins_parse_from_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    assert Settings().cors_origins == ["http://a.test", "http://b.test"]


async def test_unknown_route_returns_message(client: AsyncClient) -> None:
    response = await client.get("/api/nope")
    assert response.status_code == 404
    assert response.json() == {"message": "Not Found"}


class _Payload(BaseModel):
    name: str
    birth_year: int


async def test_errors_use_laravel_shape() -> None:
    app = create_app()

    @app.post("/validate")
    async def validate(payload: _Payload) -> dict:
        return {}

    @app.get("/forbidden")
    async def forbidden() -> dict:
        raise HTTPException(status_code=403, detail="Forbidden")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        response = await c.post("/validate", json={"name": "Ada", "birth_year": "soon"})
        assert response.status_code == 422
        body = response.json()
        assert list(body["errors"]) == ["birth_year"]
        assert body["message"].startswith("birth_year:")

        response = await c.get("/forbidden")
        assert response.status_code == 403
        assert response.json() == {"message": "Forbidden"}
