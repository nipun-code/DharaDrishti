"""Sentence embeddings (BAAI/bge-small-en-v1.5 by default) via sentence-transformers.

The model is loaded lazily on first use and cached on disk by Hugging Face (HF_HOME), which
docker compose mounts as a volume so it is downloaded only once.

Passages are embedded as-is; queries get the model's instruction prefix (`query_instruction`,
for bge: "Represent this sentence for searching relevant passages: ").
"""

import threading
from collections.abc import Sequence
from typing import Any, Protocol

from app.db.models.types import EMBEDDING_DIM
from app.services.ingestion.types import IngestionError


class Embedder(Protocol):
    """Synchronous (CPU-bound) embedding interface; callers run it in a worker thread."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...

    def count_tokens(self, text: str) -> int: ...


class SentenceTransformerEmbedder:
    def __init__(
        self,
        model_name: str,
        *,
        batch_size: int = 32,
        device: str = "cpu",
        query_instruction: str = "",
    ) -> None:
        self.model_name = model_name
        self.batch_size = batch_size
        self.device = device
        self.query_instruction = query_instruction
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        with self._lock:
            if self._model is None:
                from sentence_transformers import SentenceTransformer  # noqa: PLC0415  # heavy

                model = SentenceTransformer(self.model_name, device=self.device)
                dim = model.get_sentence_embedding_dimension()
                if dim != EMBEDDING_DIM:
                    raise IngestionError(
                        f"Embedding model {self.model_name!r} produces {dim}-d vectors but the "
                        f"database column is vector({EMBEDDING_DIM})."
                    )
                self._model = model
            return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._load().encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,  # unit vectors: cosine distance == 1 - dot product
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in row] for row in vectors]

    def embed_queries(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed search queries (with the model's query instruction prefix)."""
        return self.embed([f"{self.query_instruction}{text}" for text in texts])

    def warm_up(self) -> None:
        """Load (and if needed download) the model now instead of on first use."""
        self._load()

    def count_tokens(self, text: str) -> int:
        tokenizer = self._load().tokenizer
        encoded = tokenizer(text, add_special_tokens=False, truncation=False, verbose=False)
        return len(encoded["input_ids"])
