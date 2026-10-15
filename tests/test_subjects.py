from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InterviewSession

URL = "/api/heirloom/v1/subjects"


async def create(client: AsyncClient, headers: dict, **fields) -> dict:
    response = await client.post(URL, json={"name": "Grandma Rose", **fields}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_requires_auth(client: AsyncClient):
    assert (await client.get(URL)).status_code == 401
    assert (await client.post(URL, json={"name": "X"})).status_code == 401


async def test_create(client: AsyncClient, auth_headers: dict):
    body = await create(
        client,
        auth_headers,
        name="  Grandma Rose ",
        birth_year=1938,
        places_lived="Leeds, then Toronto",
        interests="",  # the frontend sends "" for blank fields
    )
    assert body["id"] > 0
    assert body["name"] == "Grandma Rose"
    assert body["birth_year"] == 1938
    assert body["places_lived"] == "Leeds, then Toronto"
    assert body["interests"] is None
    assert body["sessions_count"] == 0
    assert body["created_at"]


async def test_create_validation(client: AsyncClient, auth_headers: dict):
    next_year = datetime.now(UTC).year + 1
    for payload, field in [
        ({}, "name"),
        ({"name": "   "}, "name"),
        ({"name": "X" * 256}, "name"),
        ({"name": "Rose", "birth_year": 1899}, "birth_year"),
        ({"name": "Rose", "birth_year": next_year}, "birth_year"),
    ]:
        response = await client.post(URL, json=payload, headers=auth_headers)
        assert response.status_code == 422, payload
        assert field in response.json()["errors"], payload

    await create(client, auth_headers, birth_year=None)


async def test_list_is_every_own_subject_with_session_counts(
    client: AsyncClient, db: AsyncSession, auth_headers: dict, other_headers: dict
):
    mine = [await create(client, auth_headers, name=f"Subject {i}") for i in range(25)]
    await create(client, other_headers, name="Not mine")
    db.add_all([InterviewSession(subject_id=mine[0]["id"]) for _ in range(2)])
    await db.flush()

    response = await client.get(URL, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    # All 25, not a first page of 20: the frontend resolves slugs from this list.
    assert [s["id"] for s in data] == [s["id"] for s in mine]
    assert data[0]["sessions_count"] == 2
    assert data[1]["sessions_count"] == 0


async def test_get(client: AsyncClient, auth_headers: dict, other_headers: dict):
    subject = await create(client, auth_headers)

    response = await client.get(f"{URL}/{subject['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == subject

    response = await client.get(f"{URL}/{subject['id']}", headers=other_headers)
    assert response.status_code == 403
    assert response.json() == {"message": "Forbidden"}

    assert (await client.get(f"{URL}/999999", headers=auth_headers)).status_code == 404


async def test_update_changes_only_sent_fields(
    client: AsyncClient, auth_headers: dict, other_headers: dict
):
    subject = await create(client, auth_headers, birth_year=1938, interests="Gardening")
    url = f"{URL}/{subject['id']}"

    response = await client.patch(
        url, json={"interests": "Opera", "name": None}, headers=auth_headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["interests"] == "Opera"
    assert body["name"] == "Grandma Rose"  # null name is ignored, not cleared
    assert body["birth_year"] == 1938

    response = await client.put(url, json={"birth_year": 1800}, headers=auth_headers)
    assert response.status_code == 422

    response = await client.patch(url, json={"name": "Hijacked"}, headers=other_headers)
    assert response.status_code == 403


async def test_delete_cascades(
    client: AsyncClient, db: AsyncSession, auth_headers: dict, other_headers: dict
):
    subject = await create(client, auth_headers)
    db.add(InterviewSession(subject_id=subject["id"]))
    await db.flush()
    url = f"{URL}/{subject['id']}"

    assert (await client.delete(url, headers=other_headers)).status_code == 403

    response = await client.delete(url, headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"message": "Deleted"}
    assert (await client.get(url, headers=auth_headers)).status_code == 404
    assert await db.scalar(select(func.count()).select_from(InterviewSession)) == 0
