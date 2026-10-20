"""Text embedders. Local and independent of the chat provider."""

from __future__ import annotations

import hashlib
import math
import re
from abc import ABC, abstractmethod


class EmbeddingError(Exception):
    """The embedding model could not be loaded or run."""


class Embedder(ABC):
    model_name: str

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        ...


class FastEmbedEmbedder(Embedder):
    """ONNX sentence embeddings via fastembed (no PyTorch). Downloads the model on first use."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        try:
            from fastembed import TextEmbedding
        except ImportError as e:
            raise EmbeddingError("The 'fastembed' package is required for embeddings.") from e
        try:
            self._model = TextEmbedding(model_name=model_name)
        except Exception as e:  # unknown model name, failed download, ONNX runtime error
            raise EmbeddingError(f"Cannot load embedding model '{model_name}': {e}") from e

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self._model.passage_embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return next(iter(self._model.query_embed(text))).tolist()


class HashEmbedder(Embedder):
    """Deterministic hashed bag-of-words. For tests only: no download, no semantics."""

    def __init__(self, dim: int = 256):
        self.dim = dim
        self.model_name = f"hash-bow-{dim}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dim] += 1.0
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]


def get_embedder(model_name: str) -> Embedder:
    return FastEmbedEmbedder(model_name)
