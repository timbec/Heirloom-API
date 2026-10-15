from httpx import AsyncClient

URL = "/api/heirloom/v1/sessions"
SUBJECTS = "/api/heirloom/v1/subjects"


async def make_subject(client: AsyncClient, headers: dict, name: str = "Grandma Rose") -> dict:
    response = await client.post(SUBJECTS, json={"name": name}, headers=headers)
    assert response.status_code == 201
    return response.json()


async def make_session(client: AsyncClient, headers: dict, subject_id: int, **fields) -> dict:
    response = await client.post(URL, json={"subject_id": subject_id, **fields}, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


async def test_requires_auth(client: AsyncClient):
    assert (await client.get(URL)).status_code == 401
    assert (await client.get(f"{URL}/1")).status_code == 401


async def test_create(client: AsyncClient, auth_headers: dict):
    subject = await make_subject(client, auth_headers)
    body = await make_session(client, auth_headers, subject["id"], title="Childhood")

    assert body["status"] == "pending"
    assert body["title"] == "Childhood"
    assert body["subject_id"] == subject["id"]
    assert body["subject"]["id"] == subject["id"]
    assert body["subject"]["name"] == "Grandma Rose"

    blank = await make_session(client, auth_headers, subject["id"], title="")
    assert blank["title"] is None

    response = await client.post(
        URL, json={"subject_id": subject["id"], "title": "X" * 256}, headers=auth_headers
    )
    assert response.status_code == 422
    assert "title" in response.json()["errors"]


async def test_cannot_create_for_someone_elses_or_missing_subject(
    client: AsyncClient, auth_headers: dict, other_headers: dict
):
    theirs = await make_subject(client, other_headers)
    for subject_id in (theirs["id"], 999999):
        response = await client.post(URL, json={"subject_id": subject_id}, headers=auth_headers)
        assert response.status_code == 422
        assert "subject_id" in response.json()["errors"]


async def test_list_newest_first_with_subject(
    client: AsyncClient, auth_headers: dict, other_headers: dict
):
    rose = await make_subject(client, auth_headers)
    first = await make_session(client, auth_headers, rose["id"], title="One")
    second = await make_session(client, auth_headers, rose["id"], title="Two")
    theirs = await make_subject(client, other_headers)
    await make_session(client, other_headers, theirs["id"])

    response = await client.get(URL, headers=auth_headers)
    assert response.status_code == 200
    data = response.json()["data"]
    assert [s["id"] for s in data] == [second["id"], first["id"]]
    assert data[0]["subject"]["name"] == "Grandma Rose"


async def test_list_filters_by_subject(
    client: AsyncClient, auth_headers: dict, other_headers: dict
):
    """The Laravel version ignored ?subject_id=, so every subject page listed every session."""
    rose = await make_subject(client, auth_headers, "Rose")
    walter = await make_subject(client, auth_headers, "Walter")
    roses = await make_session(client, auth_headers, rose["id"])
    await make_session(client, auth_headers, walter["id"])

    response = await client.get(URL, params={"subject_id": rose["id"]}, headers=auth_headers)
    assert [s["id"] for s in response.json()["data"]] == [roses["id"]]

    # Filtering on someone else's subject shows nothing of theirs.
    response = await client.get(URL, params={"subject_id": rose["id"]}, headers=other_headers)
    assert response.json()["data"] == []


async def test_get(client: AsyncClient, auth_headers: dict, other_headers: dict):
    subject = await make_subject(client, auth_headers)
    session = await make_session(client, auth_headers, subject["id"])

    response = await client.get(f"{URL}/{session['id']}", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == session

    response = await client.get(f"{URL}/{session['id']}", headers=other_headers)
    assert response.status_code == 403
    assert response.json() == {"message": "Forbidden"}

    assert (await client.get(f"{URL}/999999", headers=auth_headers)).status_code == 404
