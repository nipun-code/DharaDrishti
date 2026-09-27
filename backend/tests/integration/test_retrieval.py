"""Hybrid retrieval against real PostgreSQL (full-text + pgvector HNSW).

Searches run concurrently on separate connections, so this module commits real rows (instead of
using the rolled-back transaction fixture) and truncates them afterwards.

All text is placeholder. Section numbers 9001-9005 are deliberately fictitious (no such sections
exist) and the single mapping row is test-only data, not a real IPC->BNS correspondence.
"""

import uuid
from collections.abc import AsyncIterator
from hashlib import sha256

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_query_embedder, get_reranker
from app.core.config import Settings
from app.core.security import create_token_pair
from app.db.models import Act, ActStatus, Chunk, Document, SectionMapping, User, UserRole
from app.main import create_app
from app.services.retrieval.hybrid import HybridRetriever
from app.services.retrieval.search import PostgresSearchBackend
from app.services.retrieval.types import CandidateSource, RetrievalMode
from tests.conftest import FakeQueryEmbedder, FakeReranker, unit_vector

pytestmark = pytest.mark.integration

# chunk key -> (act, section, text, embedding dims)
CHUNKS = {
    "gizmo": ("BNS", "9002", "Placeholder rule about gizmo penalties.", (0,)),
    "widget": ("BNS", "9003", "Placeholder rule about widget registration.", (1,)),
    "both": ("BNS", "9004", "Placeholder rule on widget penalties involving a gizmo.", (0, 1)),
    "repealed": ("IPC", "9001", "Repealed placeholder rule about gizmo matters.", (0, 2)),
    "records": ("ITA", "9005", "Placeholder rule about electronic records.", (3,)),
}
QUERY_VECTORS = {
    "widget registration": unit_vector(1),
    "gizmo": unit_vector(0),
    "electronic": unit_vector(3),
}


@pytest.fixture
async def factory(test_database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(test_database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield session_factory
    finally:
        async with engine.begin() as conn:
            await conn.execute(
                text("TRUNCATE acts, section_mappings, users RESTART IDENTITY CASCADE")
            )
        await engine.dispose()


@pytest.fixture
async def chunk_ids(factory: async_sessionmaker[AsyncSession]) -> dict[str, int]:
    async with factory() as session:
        acts = {
            "BNS": Act(short_code="BNS", full_name="Placeholder A", year=2000),
            "IPC": Act(
                short_code="IPC", full_name="Placeholder B", year=1900, status=ActStatus.REPEALED
            ),
            "ITA": Act(short_code="ITA", full_name="Placeholder C", year=2000),
        }
        session.add_all(acts.values())
        await session.flush()
        docs = {
            code: Document(
                act_id=act.id, filename=f"{code}.pdf", sha256=sha256(code.encode()).hexdigest()
            )
            for code, act in acts.items()
        }
        session.add_all(docs.values())
        await session.flush()
        chunks = {
            key: Chunk(
                document_id=docs[act].id,
                act_id=acts[act].id,
                section_number=section,
                section_title=f"Placeholder heading {section}",
                text=body,
                token_count=len(body.split()),
                embedding=unit_vector(*dims),
            )
            for key, (act, section, body, dims) in CHUNKS.items()
        }
        session.add_all(chunks.values())
        session.add(
            SectionMapping(from_act="IPC", from_section="9001", to_act="BNS", to_section="9002")
        )
        await session.commit()
        return {key: chunk.id for key, chunk in chunks.items()}


@pytest.fixture
def reranker() -> FakeReranker:
    return FakeReranker()


@pytest.fixture
def retriever(
    factory: async_sessionmaker[AsyncSession], settings: Settings, reranker: FakeReranker
) -> HybridRetriever:
    return HybridRetriever(
        PostgresSearchBackend(factory, ef_search=settings.hnsw_ef_search),
        FakeQueryEmbedder(QUERY_VECTORS),
        reranker,
        settings,
    )


def keys(chunk_ids: dict[str, int], candidates: list) -> list[str]:  # type: ignore[type-arg]
    by_id = {v: k for k, v in chunk_ids.items()}
    return [by_id[c.chunk.id] for c in candidates]


# ---------------------------------------------------------------- keyword
async def test_keyword_search_ranks_and_excludes_repealed_by_default(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve("gizmo", mode=RetrievalMode.KEYWORD)

    assert set(keys(chunk_ids, result.final)) == {"gizmo", "both"}
    hits = result.keyword["gizmo"]
    assert hits[0].score >= hits[-1].score > 0
    assert all(c.chunk.act_status == ActStatus.IN_FORCE for c in result.final)


async def test_explicit_act_filter_includes_repealed(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve("gizmo", acts=["IPC"], mode=RetrievalMode.KEYWORD)

    assert keys(chunk_ids, result.final) == ["repealed"]
    assert result.final[0].chunk.act_status == ActStatus.REPEALED


async def test_websearch_syntax_supported(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve("gizmo -widget", mode=RetrievalMode.KEYWORD)

    assert keys(chunk_ids, result.final) == ["gizmo"]


async def test_stopword_only_query_returns_nothing(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve("the and of", mode=RetrievalMode.KEYWORD)

    assert result.final == []


# ---------------------------------------------------------------- vector
async def test_vector_search_orders_by_cosine_similarity(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve("widget registration", mode=RetrievalMode.VECTOR, top_k=3)

    assert keys(chunk_ids, result.final)[:2] == ["widget", "both"]
    hits = result.vector["widget registration"]
    assert hits[0].score == pytest.approx(1.0, abs=1e-5)
    assert hits[1].score == pytest.approx(2**-0.5, abs=1e-5)
    assert "repealed" not in keys(chunk_ids, result.final)


async def test_vector_search_with_selective_filter_still_returns_results(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    # The ITA chunk is orthogonal to the query vector, but it's the only row passing the filter.
    result = await retriever.retrieve("gizmo", acts=["ITA"], mode=RetrievalMode.VECTOR)

    assert keys(chunk_ids, result.final) == ["records"]


# ---------------------------------------------------------------- hybrid & rerank
async def test_hybrid_combines_both_rankings(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve("gizmo", mode=RetrievalMode.HYBRID)

    fused = dict(zip(keys(chunk_ids, result.fused), result.fused, strict=True))
    assert fused["gizmo"].keyword_rank is not None
    assert fused["gizmo"].vector_rank == 1
    assert keys(chunk_ids, result.final)[0] == "gizmo"
    assert all(c.rrf_score for c in result.fused)
    assert {"keyword_search", "vector_branch", "embed_query", "total"} <= set(result.timings_ms)


async def test_hybrid_rerank_uses_cross_encoder_scores(
    retriever: HybridRetriever, reranker: FakeReranker, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve("widget registration", top_k=1)

    assert result.mode == RetrievalMode.HYBRID_RERANK
    assert keys(chunk_ids, result.final) == ["widget"]
    assert result.final[0].rerank_score == 1.0
    assert reranker.calls[0][1] == len(result.reranked)


# ---------------------------------------------------------------- section references
async def test_section_reference_and_mapping_come_first(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve(
        "What does IPC 9001 say about gizmo?", mode=RetrievalMode.HYBRID
    )

    assert keys(chunk_ids, result.direct) == ["repealed", "gizmo"]
    assert [c.source for c in result.direct] == [
        CandidateSource.SECTION_REF,
        CandidateSource.MAPPING,
    ]
    assert result.direct[1].matched_ref == "IPC 9001 -> BNS 9002"
    final = keys(chunk_ids, result.final)
    assert final[:2] == ["repealed", "gizmo"]
    assert final.count("gizmo") == 1


async def test_reference_to_missing_section_finds_nothing(
    retriever: HybridRetriever, chunk_ids: dict[str, int]
) -> None:
    result = await retriever.retrieve("BNS 9999", mode=RetrievalMode.KEYWORD)

    assert [r.label for r in result.section_refs] == ["BNS 9999"]
    assert result.direct == []


# ---------------------------------------------------------------- debug endpoint
@pytest.fixture
async def api(
    settings: Settings, factory: async_sessionmaker[AsyncSession], reranker: FakeReranker
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings.model_copy(update={"database_url": _url(factory)}))
    app.dependency_overrides[get_query_embedder] = lambda: FakeQueryEmbedder(QUERY_VECTORS)
    app.dependency_overrides[get_reranker] = lambda: reranker
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


def _url(factory: async_sessionmaker[AsyncSession]) -> object:
    from pydantic import SecretStr  # noqa: PLC0415

    engine = factory.kw["bind"]
    return SecretStr(engine.url.render_as_string(hide_password=False))


async def _headers(
    factory: async_sessionmaker[AsyncSession], settings: Settings, role: UserRole
) -> dict[str, str]:
    async with factory() as session:
        user = User(
            email=f"{role}-{uuid.uuid4().hex[:6]}@example.com", hashed_password="x", role=role
        )
        session.add(user)
        await session.commit()
    return {"Authorization": f"Bearer {create_token_pair(str(user.id), settings).access_token}"}


async def test_debug_endpoint_returns_every_stage(
    api: httpx.AsyncClient,
    factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    chunk_ids: dict[str, int],
) -> None:
    headers = await _headers(factory, settings, UserRole.ADMIN)

    response = await api.post(
        "/api/v1/retrieval/debug",
        headers=headers,
        json={"query": "IPC 9001 gizmo", "top_k": 2, "extra_queries": ["widget registration"]},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["mode"] == "hybrid_rerank"
    assert body["search_queries"] == ["IPC 9001 gizmo", "widget registration"]
    assert [r["label"] for r in body["section_refs"]] == ["IPC 9001"]
    assert [d["source"] for d in body["direct"]] == ["section_ref", "mapping"]
    assert set(body["keyword"]) == set(body["vector"]) == set(body["search_queries"])
    assert body["vector"]["widget registration"][0]["rank"] == 1
    assert all(c["rrf_score"] is not None for c in body["fused"])
    assert all(c["rerank_score"] is not None for c in body["reranked"])
    assert len(body["final"]) == 2 + 2  # direct hits + top_k
    assert body["final"][0]["act_status"] == "repealed"
    assert body["timings_ms"]["total"] > 0


async def test_debug_endpoint_admin_only_and_validated(
    api: httpx.AsyncClient, factory: async_sessionmaker[AsyncSession], settings: Settings
) -> None:
    user = await _headers(factory, settings, UserRole.USER)
    admin = await _headers(factory, settings, UserRole.ADMIN)

    assert (await api.post("/api/v1/retrieval/debug", json={"query": "gizmo"})).status_code == 401
    forbidden = await api.post("/api/v1/retrieval/debug", headers=user, json={"query": "gizmo"})
    assert forbidden.status_code == 403
    bad = await api.post(
        "/api/v1/retrieval/debug", headers=admin, json={"query": "hi", "mode": "magic"}
    )
    assert bad.status_code == 422
