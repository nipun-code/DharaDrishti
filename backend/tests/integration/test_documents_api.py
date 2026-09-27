"""Upload / status / delete API against real PostgreSQL, with a fake job queue."""

import uuid
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session, get_job_queue
from app.core.config import Settings
from app.core.security import create_token_pair
from app.db.models import Act, ActStatus, Document, DocumentStatus, User, UserRole
from app.main import create_app
from app.repositories.users import UserRepository
from tests.conftest import FakeJobQueue

pytestmark = pytest.mark.integration

PDF_BYTES = b"%PDF-1.7\n% placeholder test file, not a real act\n%%EOF\n"
NEW_ACT = {"act_short_code": "tst", "act_full_name": "The Placeholder Test Act", "act_year": "2000"}


@pytest.fixture
def queue() -> FakeJobQueue:
    return FakeJobQueue()


@pytest.fixture
async def api(
    settings: Settings, db_session: AsyncSession, queue: FakeJobQueue
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings)
    app.dependency_overrides[get_db_session] = lambda: db_session
    app.dependency_overrides[get_job_queue] = lambda: queue
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


async def auth_headers(session: AsyncSession, settings: Settings, role: UserRole) -> dict[str, str]:
    user = await UserRepository(session).add(
        User(email=f"{role}-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role=role)
    )
    await session.commit()
    return {"Authorization": f"Bearer {create_token_pair(str(user.id), settings).access_token}"}


@pytest.fixture
async def admin(db_session: AsyncSession, settings: Settings) -> dict[str, str]:
    return await auth_headers(db_session, settings, UserRole.ADMIN)


async def upload(
    api: httpx.AsyncClient,
    headers: dict[str, str],
    *,
    data: dict[str, str] | None = None,
    content: bytes = PDF_BYTES,
    filename: str = "placeholder.pdf",
    content_type: str = "application/pdf",
) -> httpx.Response:
    return await api.post(
        "/api/v1/documents",
        headers=headers,
        data=NEW_ACT if data is None else data,
        files={"file": (filename, content, content_type)},
    )


def error_code(response: httpx.Response) -> Any:
    return response.json()["error"]["code"]


# ---------------------------------------------------------------- happy path
async def test_upload_creates_act_document_file_and_job(
    api: httpx.AsyncClient,
    admin: dict[str, str],
    db_session: AsyncSession,
    queue: FakeJobQueue,
    settings: Settings,
) -> None:
    response = await upload(api, admin, filename="../../weird name?.pdf")

    assert response.status_code == 202, response.text
    body = response.json()
    doc_id = uuid.UUID(body["document_id"])
    assert body["status"] == "pending"
    assert queue.enqueued == [doc_id]

    document = await db_session.get(Document, doc_id)
    assert document is not None
    assert document.filename == "weird name.pdf"
    assert document.progress == 0
    act = await db_session.get(Act, document.act_id)
    assert act is not None
    assert (act.short_code, act.full_name, act.year, act.status) == (
        "TST",
        "The Placeholder Test Act",
        2000,
        ActStatus.IN_FORCE,
    )
    stored = settings.upload_dir / f"{doc_id}.pdf"
    assert stored.read_bytes() == PDF_BYTES
    assert [p.name for p in settings.upload_dir.iterdir()] == [stored.name]  # no temp leftovers


async def test_existing_act_needs_only_code_and_can_be_updated(
    api: httpx.AsyncClient, admin: dict[str, str], db_session: AsyncSession
) -> None:
    await upload(api, admin)

    response = await upload(
        api,
        admin,
        data={"act_short_code": "TST", "act_status": "repealed"},
        content=PDF_BYTES + b"% version 2\n",
    )

    assert response.status_code == 202, response.text
    act = await db_session.scalar(select(Act).where(Act.short_code == "TST"))
    assert act is not None
    await db_session.refresh(act)
    assert act.status == ActStatus.REPEALED
    assert act.full_name == "The Placeholder Test Act"


async def test_octet_stream_accepted_for_pdf_name(
    api: httpx.AsyncClient, admin: dict[str, str]
) -> None:
    response = await upload(api, admin, content_type="application/octet-stream")

    assert response.status_code == 202


# ---------------------------------------------------------------- validation
async def test_new_act_requires_name_and_year(
    api: httpx.AsyncClient, admin: dict[str, str]
) -> None:
    response = await upload(api, admin, data={"act_short_code": "NEWONE"})

    assert response.status_code == 400
    assert "act_full_name" in response.json()["error"]["message"]


@pytest.mark.parametrize(
    "data",
    [
        {"act_short_code": "1BAD", "act_full_name": "Name", "act_year": "2000"},
        {"act_short_code": "OK", "act_full_name": "Name", "act_year": "20000"},
        {"act_short_code": "OK", "act_full_name": "Name", "act_year": "2000", "act_status": "x"},
    ],
)
async def test_invalid_act_metadata_is_422(
    api: httpx.AsyncClient, admin: dict[str, str], data: dict[str, str]
) -> None:
    response = await upload(api, admin, data=data)

    assert response.status_code == 422
    assert error_code(response) == "validation_error"


async def test_wrong_mime_type_rejected(api: httpx.AsyncClient, admin: dict[str, str]) -> None:
    response = await upload(api, admin, content_type="text/plain")

    assert response.status_code == 415


async def test_non_pdf_bytes_rejected_and_nothing_kept(
    api: httpx.AsyncClient, admin: dict[str, str], db_session: AsyncSession, settings: Settings
) -> None:
    response = await upload(api, admin, content=b"MZ\x90\x00 not a pdf at all")

    assert response.status_code == 415
    assert "not a valid PDF" in response.json()["error"]["message"]
    assert await db_session.scalar(select(func.count()).select_from(Document)) == 0
    assert await db_session.scalar(select(func.count()).select_from(Act)) == 0
    assert list(settings.upload_dir.iterdir()) == []


async def test_empty_file_rejected(api: httpx.AsyncClient, admin: dict[str, str]) -> None:
    response = await upload(api, admin, content=b"")

    assert response.status_code == 400


async def test_file_over_limit_rejected(
    api: httpx.AsyncClient, admin: dict[str, str], settings: Settings
) -> None:
    # Just over the file limit, but under the middleware's (limit + form overhead) allowance,
    # so this exercises the service's own streaming check.
    oversized = PDF_BYTES + b"0" * settings.max_upload_bytes

    response = await upload(api, admin, content=oversized)

    assert response.status_code == 413
    assert error_code(response) == "payload_too_large"
    assert list(settings.upload_dir.iterdir()) == []


async def test_duplicate_file_conflicts_with_existing_id(
    api: httpx.AsyncClient, admin: dict[str, str]
) -> None:
    first = await upload(api, admin)

    second = await upload(api, admin)

    assert second.status_code == 409
    assert second.json()["error"]["details"] == {"document_id": first.json()["document_id"]}


async def test_duplicate_of_failed_upload_is_allowed_and_replaces_it(
    api: httpx.AsyncClient, admin: dict[str, str], db_session: AsyncSession, settings: Settings
) -> None:
    first_id = uuid.UUID((await upload(api, admin)).json()["document_id"])
    first = await db_session.get(Document, first_id)
    assert first is not None
    first.status = DocumentStatus.FAILED
    await db_session.commit()

    retry = await upload(api, admin)

    assert retry.status_code == 202
    db_session.expunge_all()
    assert await db_session.get(Document, first_id) is None
    assert not (settings.upload_dir / f"{first_id}.pdf").exists()


async def test_queue_failure_returns_503_and_marks_document_failed(
    api: httpx.AsyncClient, admin: dict[str, str], db_session: AsyncSession, queue: FakeJobQueue
) -> None:
    queue.fail = True

    response = await upload(api, admin)

    assert response.status_code == 503
    document = await db_session.scalar(select(Document))
    assert document is not None
    assert document.status == DocumentStatus.FAILED
    assert document.error is not None


# ---------------------------------------------------------------- auth
async def test_upload_requires_admin(
    api: httpx.AsyncClient, db_session: AsyncSession, settings: Settings
) -> None:
    user_headers = await auth_headers(db_session, settings, UserRole.USER)

    assert (await upload(api, user_headers)).status_code == 403
    assert (await upload(api, {})).status_code == 401


# ---------------------------------------------------------------- status, list, delete
async def test_get_list_and_delete(
    api: httpx.AsyncClient,
    admin: dict[str, str],
    db_session: AsyncSession,
    settings: Settings,
) -> None:
    doc_id = (await upload(api, admin)).json()["document_id"]
    user_headers = await auth_headers(db_session, settings, UserRole.USER)

    status = await api.get(f"/api/v1/documents/{doc_id}", headers=user_headers)
    assert status.status_code == 200
    assert status.json()["act_short_code"] == "TST"
    assert status.json()["progress"] == 0

    listing = await api.get("/api/v1/documents", headers=admin)
    assert [d["id"] for d in listing.json()["items"]] == [doc_id]
    assert (await api.get("/api/v1/documents", headers=user_headers)).status_code == 403

    deleted = await api.delete(f"/api/v1/documents/{doc_id}", headers=admin)
    assert deleted.status_code == 204
    assert not (settings.upload_dir / f"{doc_id}.pdf").exists()
    missing = await api.get(f"/api/v1/documents/{doc_id}", headers=admin)
    assert missing.status_code == 404
    assert (await api.delete(f"/api/v1/documents/{doc_id}", headers=admin)).status_code == 404
