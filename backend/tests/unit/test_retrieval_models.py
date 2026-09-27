"""Model wrappers with fake sentence_transformers/torch modules (no downloads)."""

import math
import sys
import types
from typing import Any, ClassVar
from unittest.mock import patch

import pytest

from app import cli
from app.core.config import Settings
from app.db.models.types import EMBEDDING_DIM
from app.services.ingestion.embedder import SentenceTransformerEmbedder
from app.services.retrieval.reranker import CrossEncoderReranker, _sigmoid


class _FakeCrossEncoder:
    instances: ClassVar[list["_FakeCrossEncoder"]] = []

    def __init__(self, name: str, **kwargs: Any) -> None:
        self.name = name
        self.kwargs = kwargs
        _FakeCrossEncoder.instances.append(self)

    def predict(self, pairs: list[tuple[str, str]], **_: Any) -> list[float]:
        # Logit = number of query words found in the passage, minus 1.
        return [float(sum(w in passage for w in query.split()) - 1) for query, passage in pairs]


class _FakeSentenceTransformer:
    def __init__(self, name: str, device: str) -> None:
        self.name = name
        self.tokenizer = None
        self.seen: list[str] = []

    def get_sentence_embedding_dimension(self) -> int:
        return EMBEDDING_DIM

    def encode(self, texts: list[str], **_: Any) -> list[list[float]]:
        self.seen.extend(texts)
        return [[1.0] + [0.0] * (EMBEDDING_DIM - 1) for _ in texts]


@pytest.fixture
def fake_libs(monkeypatch: pytest.MonkeyPatch) -> None:
    st = types.ModuleType("sentence_transformers")
    st.CrossEncoder = _FakeCrossEncoder  # type: ignore[attr-defined]
    st.SentenceTransformer = _FakeSentenceTransformer  # type: ignore[attr-defined]
    torch = types.ModuleType("torch")
    nn = types.ModuleType("torch.nn")
    nn.Identity = lambda: "identity"  # type: ignore[attr-defined]
    torch.nn = nn  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "sentence_transformers", st)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "torch.nn", nn)
    _FakeCrossEncoder.instances = []


@pytest.mark.usefixtures("fake_libs")
def test_reranker_returns_sigmoid_scores_and_loads_once() -> None:
    reranker = CrossEncoderReranker("fake/reranker", max_length=256, batch_size=4)

    scores = reranker.score("alpha beta", ["alpha beta here", "nothing", "alpha"])
    reranker.score("x", ["y"])

    assert scores == pytest.approx([_sigmoid(1.0), _sigmoid(-1.0), _sigmoid(0.0)])
    assert scores[0] > scores[2] > scores[1]
    assert all(0 < s < 1 for s in scores)
    [model] = _FakeCrossEncoder.instances
    assert model.kwargs["max_length"] == 256
    assert model.kwargs["activation_fn"] == "identity"


@pytest.mark.usefixtures("fake_libs")
def test_reranker_empty_passages_skip_model() -> None:
    assert CrossEncoderReranker("fake/reranker").score("q", []) == []
    assert _FakeCrossEncoder.instances == []


def test_sigmoid_is_numerically_stable() -> None:
    assert _sigmoid(0) == 0.5
    assert _sigmoid(1000) == pytest.approx(1.0)
    assert _sigmoid(-1000) == pytest.approx(0.0)
    assert _sigmoid(2) == pytest.approx(1 / (1 + math.exp(-2)))


@pytest.mark.usefixtures("fake_libs")
def test_query_embedding_adds_instruction_prefix() -> None:
    embedder = SentenceTransformerEmbedder("fake/embedder", query_instruction="Q: ")

    vectors = embedder.embed_queries(["first", "second"])

    assert len(vectors) == 2
    assert embedder._model.seen == ["Q: first", "Q: second"]


@pytest.mark.usefixtures("fake_libs")
def test_download_models_warms_both(settings: Settings) -> None:
    assert cli.download_models(settings) == [
        settings.embedding_model_name,
        settings.reranker_model_name,
    ]


def test_cli_download_models_command(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    with patch.object(cli, "download_models", return_value=["m1", "m2"]):
        assert cli.main(["download-models"], settings) == 0

    assert capsys.readouterr().out == "Ready: m1\nReady: m2\n"
