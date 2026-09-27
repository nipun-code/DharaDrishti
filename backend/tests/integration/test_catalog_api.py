"""Acts list, section text (incl. re-joining overlapping chunks), IPC mapping and feedback.
Placeholder text; section numbers 9001/9002 and the mapping row are fictitious test data."""

import uuid
from collections.abc import AsyncIterator
from hashlib import sha256
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.config import Settings
from app.core.security import create_token_pair
from app.db.models import Act, ActStatus, Chunk, Document, QueryLog, SectionMapping, User
from app.main import create_app
from tests.conftest import unit_vector

pytestmark = pytest.mark.integration


async def seed(session: AsyncSession) -> dict[str, Any]:
    bns = Act(short_code="BNS", full_name="Placeholder New", year=2000)
    ipc = Act(short_code="IPC", full_name="Placeholder Old", year=1900, status=ActStatus.REPEALED)
    session.add_all([bns, ipc])
    await session.flush()
    doc = Document(act_id=bns.id, filename="n.pdf", sha256=sha256(b"n").hexdigest())
    old = Document(act_id=ipc.id, filename="o.pdf", sha256=sha256(b"o").hexdigest())
    session.add_all([doc, old])
    await session.flush()

    def chunk(
        act: Act, document: Document, section: str, text: str, page: int, *, sub: str | None = None
    ) -> Chunk:
        return Chunk(
            document_id=document.id,
            act_id=act.id,
            section_number=section,
            section_title=f"Placeholder {section}",
            subsection=sub,
            text=text,
            page_start=page,
            page_end=page,
            token_count=len(text.split()),
            embedding=unit_vector(1),
        )

    session.add_all(
        [
            # A long section split in two pieces; piece 2 starts with an overlap line.
            chunk(bns, doc, "9002", "(1) First part of the rule\nends with these words", 4),
            chunk(
                bns, doc, "9002", "ends with these words\n(2) Second part of the rule", 5, sub="(2)"
            ),
            chunk(ipc, old, "9001", "Old placeholder rule text.", 2),
            SectionMapping(
                from_act="IPC",
                from_section="9001",
                to_act="BNS",
                to_section="9002(1)",
                note="test row",
            ),
        ]
    )
    owner = User(email="owner@example.com", hashed_password="x")
    other = User(email="other@example.com", hashed_password="x")
    session.add_all([owner, other])
    await session.flush()
    log = QueryLog(user_id=owner.id, query="placeholder?")
    session.add(log)
    await session.commit()
    return {"owner": owner, "other": other, "log": log}


@pytest.fixture
async def env(
    settings: Settings, db_session: AsyncSession
) -> AsyncIterator[tuple[httpx.AsyncClient, dict[str, Any]]]:
    data = await seed(db_session)
    app = create_app(settings)
    app.dependency_overrides[get_db_session] = lambda: db_session

    def headers(user: User) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_token_pair(str(user.id), settings).access_token}"}

    data["as_owner"] = headers(data["owner"])
    data["as_other"] = headers(data["other"])
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client, data


async def test_acts_list_with_chunk_counts(env: Any) -> None:
    client, data = env

    acts = (await client.get("/api/v1/acts", headers=data["as_owner"])).json()

    assert [(a["short_code"], a["status"], a["chunks_count"]) for a in acts] == [
        ("BNS", "in_force", 2),
        ("IPC", "repealed", 1),
    ]
    assert (await client.get("/api/v1/acts")).status_code == 401


async def test_section_text_rejoins_overlapping_pieces(env: Any) -> None:
    client, data = env

    section = (await client.get("/api/v1/sections/bns/9002", headers=data["as_owner"])).json()

    assert (
        section["text"]
        == "(1) First part of the rule\nends with these words\n(2) Second part of the rule"
    )
    assert (section["page_start"], section["page_end"]) == (4, 5)
    assert section["act_name"] == "Placeholder New"


@pytest.mark.parametrize(
    ("path", "status"),
    [("/sections/BNS/abc", 400), ("/sections/BNS/1", 404), ("/sections/XYZ/1", 404)],
)
async def test_section_errors(env: Any, path: str, status: int) -> None:
    client, data = env

    response = await client.get(f"/api/v1{path}", headers=data["as_owner"])

    assert response.status_code == status


async def test_ipc_mapping_returns_both_texts(env: Any) -> None:
    client, data = env

    mapping = (await client.get("/api/v1/mapping/ipc/9001", headers=data["as_owner"])).json()

    assert mapping["source"]["act_status"] == "repealed"
    [target] = mapping["targets"]
    assert (target["to_act"], target["to_section"], target["note"]) == (
        "BNS",
        "9002(1)",
        "test row",
    )
    assert target["section"]["section_number"] == "9002"
    missing = await client.get("/api/v1/mapping/ipc/420", headers=data["as_owner"])
    assert missing.status_code == 404


async def test_feedback_is_per_owner_and_replaces_the_vote(env: Any) -> None:
    client, data = env
    log_id = str(data["log"].id)

    first = await client.post(
        "/api/v1/feedback", headers=data["as_owner"], json={"query_log_id": log_id, "rating": -1}
    )
    second = await client.post(
        "/api/v1/feedback", headers=data["as_owner"], json={"query_log_id": log_id, "rating": 1}
    )
    stranger = await client.post(
        "/api/v1/feedback", headers=data["as_other"], json={"query_log_id": log_id, "rating": 1}
    )
    bad_rating = await client.post(
        "/api/v1/feedback", headers=data["as_owner"], json={"query_log_id": log_id, "rating": 5}
    )
    unknown = await client.post(
        "/api/v1/feedback",
        headers=data["as_owner"],
        json={"query_log_id": str(uuid.uuid4()), "rating": 1},
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert second.json()["rating"] == 1
    assert stranger.status_code == 404  # can't rate someone else's answer
    assert bad_rating.status_code == 422
    assert unknown.status_code == 404
