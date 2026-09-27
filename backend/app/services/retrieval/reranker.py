"""Cross-encoder re-ranking (BAAI/bge-reranker-base by default).

Scores are sigmoid(logit) in [0, 1], so a fixed relevance threshold can be applied later
(retrieval guardrail). The model is loaded lazily and cached under HF_HOME.
"""

import math
import threading
from collections.abc import Sequence
from typing import Any, Protocol


class Reranker(Protocol):
    """Synchronous (CPU-bound) relevance scoring; callers run it in a worker thread."""

    def score(self, query: str, passages: Sequence[str]) -> list[float]: ...


def _sigmoid(x: float) -> float:
    if x >= 0:
        return 1.0 / (1.0 + math.exp(-x))
    z = math.exp(x)
    return z / (1.0 + z)


class CrossEncoderReranker:
    def __init__(
        self,
        model_name: str,
        *,
        device: str = "cpu",
        max_length: int = 512,
        batch_size: int = 16,
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.max_length = max_length
        self.batch_size = batch_size
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                import torch  # noqa: PLC0415  # heavy imports
                from sentence_transformers import CrossEncoder  # noqa: PLC0415

                # Identity activation: we apply the sigmoid ourselves, independent of the
                # library's default for this model.
                self._model = CrossEncoder(
                    self.model_name,
                    device=self.device,
                    max_length=self.max_length,
                    activation_fn=torch.nn.Identity(),
                )
            return self._model

    def warm_up(self) -> None:
        self._load()

    def score(self, query: str, passages: Sequence[str]) -> list[float]:
        if not passages:
            return []
        logits = self._load().predict(
            [(query, passage) for passage in passages],
            batch_size=self.batch_size,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [_sigmoid(float(x)) for x in logits]
