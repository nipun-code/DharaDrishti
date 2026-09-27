"""Evaluation API and run lifecycle against real PostgreSQL (the runner itself is faked)."""

import json
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_job_queue
from app.core.config import Settings
from app.core.security import create_token_pair
from app.db.models import EvalRunStatus, User, UserRole
from app.main import create_app
from app.services.evaluation.runner import EvalConfig, EvalReport
from app.services.evaluation.service import EvaluationService
from tests.conftest import FakeJobQueue

pytestmark = pytest.mark.integration

ROW = {
    "id": "q1",
    "question": "Placeholder question?",
    "expected_sections": [{"act": "BNS", "section": "1"}],
    "category": "semantic",
}


@pytest.fixture
async def factory(test_database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(test_database_url)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE eval_runs, users RESTART IDENTITY CASCADE"))
        await engine.dispose()


@pytest.fixture
def eval_settings(settings: Settings, test_database_url: str, tmp_path: Path) -> Settings:
    return settings.model_copy(
        update={
            "database_url": SecretStr(test_database_url),
            "eval_dataset_path": tmp_path / "golden.jsonl",
        }
    )


@pytest.fixture
async def api(
    eval_settings: Settings, factory: async_sessionmaker[AsyncSession]
) -> AsyncIterator[tuple[httpx.AsyncClient, FakeJobQueue, dict[str, str]]]:
    queue = FakeJobQueue()
    app = create_app(eval_settings)
    app.dependency_overrides[get_job_queue] = lambda: queue
    async with factory() as session:
        admin = User(email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
        session.add(admin)
        await session.commit()
    token = create_token_pair(str(admin.id), eval_settings).access_token
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client, queue, {"Authorization": f"Bearer {token}"}


async def test_run_requires_a_valid_dataset(api: Any, eval_settings: Settings) -> None:
    client, queue, headers = api

    missing = await client.post("/api/v1/eval/run", headers=headers, json={})
    eval_settings.golden_dataset_path.write_text('{"id": "x"}\n', encoding="utf-8")
    invalid = await client.post("/api/v1/eval/run", headers=headers, json={})
    status = (await client.get("/api/v1/eval/dataset", headers=headers)).json()

    assert missing.status_code == 400
    assert "not found" in missing.json()["error"]["message"]
    assert invalid.status_code == 400
    assert invalid.json()["error"]["details"]["errors"][0].startswith("line 1:")
    assert status["exists"] is True
    assert status["errors"]
    assert queue.enqueued == []


async def test_run_is_created_queued_and_listed(api: Any, eval_settings: Settings) -> None:
    client, queue, headers = api
    eval_settings.golden_dataset_path.write_text(json.dumps(ROW) + "\n", encoding="utf-8")

    created = await client.post(
        "/api/v1/eval/run", headers=headers, json={"modes": ["hybrid", "vector"], "limit": 5}
    )

    assert created.status_code == 202
    run_id = created.json()["eval_run_id"]
    assert queue.enqueued == [uuid.UUID(run_id)]
    runs = (await client.get("/api/v1/eval/runs", headers=headers)).json()
    assert [(r["id"], r["status"]) for r in runs] == [(run_id, "pending")]
    detail = (await client.get(f"/api/v1/eval/runs/{run_id}", headers=headers)).json()
    assert detail["config"]["modes"] == ["hybrid", "vector"]
    assert detail["metrics"] is None
    assert (await client.get("/api/v1/eval/dataset", headers=headers)).json()["questions"] == 1


async def test_endpoints_are_admin_only(
    api: Any, factory: async_sessionmaker[AsyncSession], eval_settings: Settings
) -> None:
    client, _, _ = api
    async with factory() as session:
        member = User(email="member@example.com", hashed_password="x", role=UserRole.USER)
        session.add(member)
        await session.commit()
    headers = {
        "Authorization": f"Bearer {create_token_pair(str(member.id), eval_settings).access_token}"
    }

    assert (await client.get("/api/v1/eval/runs", headers=headers)).status_code == 403
    assert (await client.post("/api/v1/eval/run", headers=headers, json={})).status_code == 403


class _Runner:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    async def run(self, items: Any, config: EvalConfig, progress: Any) -> EvalReport:
        await progress(50)
        if self.fail:
            raise RuntimeError("LLM quota exhausted")
        return EvalReport({"modes": {"hybrid": {"recall_at_5": 1.0, "mrr": 1.0}}}, [{"id": "q1"}])


@pytest.mark.parametrize("fail", [False, True])
async def test_execute_marks_run_completed_or_failed(
    factory: async_sessionmaker[AsyncSession], eval_settings: Settings, fail: bool
) -> None:
    eval_settings.golden_dataset_path.write_text(json.dumps(ROW) + "\n", encoding="utf-8")
    service = EvaluationService(factory, eval_settings)
    run_id = await service.create_run(EvalConfig())

    if fail:
        with pytest.raises(RuntimeError):
            await service.execute(run_id, _Runner(fail=True))  # type: ignore[arg-type]
    else:
        await service.execute(run_id, _Runner())  # type: ignore[arg-type]

    run = await service.get_run(run_id)
    assert run.finished_at is not None
    if fail:
        assert (run.status, run.progress) == (EvalRunStatus.FAILED, 50)
        assert run.error is not None
        assert "quota" in run.error
    else:
        assert (run.status, run.progress) == (EvalRunStatus.COMPLETED, 100)
        assert run.metrics == {"modes": {"hybrid": {"recall_at_5": 1.0, "mrr": 1.0}}}
        assert run.per_question == [{"id": "q1"}]
