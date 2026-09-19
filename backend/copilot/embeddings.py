from __future__ import annotations

"""
NETRA 5.0 — Forensic Embedding Service

Provider-agnostic embedding abstraction, batching, caching, and offline verification:
1. Provider Abstraction:
   - Base interface (EmbeddingProvider)
   - Local ONNX/Chroma all-MiniLM-L6-v2 provider (offline, 384 dimensions)
   - Deterministic Fallback provider (explicitly identified, zero-download, reproducible)
2. High-Performance Batch Processing:
   - Chunked batch processing (batch_size=32)
   - Batch order strictly preserved
3. Forensic Deterministic Caching:
   - Cache key tied to provider, model, dimension, case_id, chunk_id, and text
   - Zero cross-case cache contamination
   - Invalidation on model / dimension changes
4. Dimension & Grounding Integrity:
   - Explicit validation against configured dimension (e.g. 384)
   - Rejects mismatched dimensions
   - Preserves DocumentChunk provenance completely untouched
"""

import hashlib
import math
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from .config import get_copilot_config
from .schemas import DocumentChunk


# ─────────────────────────────────────────────────────────────────────────────
# 1. Provider Abstraction Base
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingProvider(ABC):
    """Abstract interface for embedding generation."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider identifier (e.g. 'local-chroma', 'deterministic-fallback')."""
        pass

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Model identifier (e.g. 'all-MiniLM-L6-v2')."""
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Vector dimensionality (e.g. 384)."""
        pass

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Embed a single text string."""
        pass

    @abstractmethod
    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Embed a batch of text strings preserving order."""
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 2. Deterministic Fallback Provider (Offline & Test Harness)
# ─────────────────────────────────────────────────────────────────────────────

class DeterministicFallbackEmbeddingProvider(EmbeddingProvider):
    """
    Zero-dependency deterministic pseudo-embedding provider.
    Explicitly identified as fallback. Produces unit-normalized, reproducible
    vectors using token-seeded SHA-256 projections.
    """

    def __init__(self, dimension: int = 384, model_name: str = "sha256-projection-384"):
        self._dimension = dimension
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "deterministic-fallback"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def _project_text(self, text: str) -> List[float]:
        """Compute unit-normalized deterministic projection."""
        if not text or not text.strip():
            return []

        tokens = text.lower().split()
        vec = [0.0] * self._dimension

        # Token-level hash projection
        for idx, tok in enumerate(tokens):
            tok_bytes = hashlib.sha256(f"{idx}:{tok}".encode("utf-8")).digest()
            for i in range(self._dimension):
                b = tok_bytes[i % len(tok_bytes)]
                vec[i] += (b - 127.5) / 127.5

        # Document-level global hash projection
        doc_bytes = hashlib.sha256(text.encode("utf-8")).digest()
        for i in range(self._dimension):
            b = doc_bytes[i % len(doc_bytes)]
            vec[i] += (b - 127.5) / 127.5

        # L2 Normalization (unit length)
        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 0:
            return [round(x / norm, 6) for x in vec]
        return [0.0] * self._dimension

    def embed(self, text: str) -> List[float]:
        return self._project_text(text)

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        return [self._project_text(t) for t in texts]


# ─────────────────────────────────────────────────────────────────────────────
# 3. Local Chroma / ONNX all-MiniLM-L6-v2 Provider
# ─────────────────────────────────────────────────────────────────────────────

class LocalChromaEmbeddingProvider(EmbeddingProvider):
    """
    Local embedding provider utilizing ChromaDB's ONNX-based all-MiniLM-L6-v2.
    Runs completely offline with 384-dimensional dense vectors.
    """

    def __init__(self, model_name: str = "all-MiniLM-L6-v2", dimension: int = 384):
        self._model_name = model_name
        self._dimension = dimension
        self._ef = None
        self._init_error = None

        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            self._ef = DefaultEmbeddingFunction()
        except Exception as e:
            self._init_error = str(e)

    @property
    def provider_name(self) -> str:
        return "local"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimension(self) -> int:
        return self._dimension

    def is_available(self) -> bool:
        return self._ef is not None

    def embed(self, text: str) -> List[float]:
        if not text or not text.strip():
            return []
        if not self._ef:
            raise RuntimeError(f"Local Chroma embedding provider unavailable: {self._init_error}")
        res = self._ef([text])
        return [float(x) for x in res[0]]

    def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        if not self._ef:
            raise RuntimeError(f"Local Chroma embedding provider unavailable: {self._init_error}")

        # Map non-empty vs empty texts
        non_empty_indices = [i for i, t in enumerate(texts) if t and t.strip()]
        non_empty_texts = [texts[i] for i in non_empty_indices]

        results: List[List[float]] = [[] for _ in texts]
        if non_empty_texts:
            embeddings = self._ef(non_empty_texts)
            for idx, emb in zip(non_empty_indices, embeddings):
                results[idx] = [float(x) for x in emb]

        return results


# ─────────────────────────────────────────────────────────────────────────────
# 4. Central Embedding Service (Batching, Caching, Validation)
# ─────────────────────────────────────────────────────────────────────────────

class EmbeddingService:
    """
    High-level forensic embedding orchestrator.
    Enforces dimensional integrity, strict case-isolated caching,
    and batching while preserving original chunk provenance.
    """

    def __init__(
        self,
        provider: Optional[EmbeddingProvider] = None,
        config: Optional[Any] = None,
    ):
        self.config = config or get_copilot_config()
        self._cache: Dict[str, List[float]] = {}

        if provider is not None:
            self._provider = provider
        else:
            self._provider = self._resolve_provider()

        # Dimension validation check on startup
        if self._provider.dimension != self.config.embedding_dimensions:
            raise ValueError(
                f"Embedding provider dimension mismatch: provider={self._provider.dimension} "
                f"vs config={self.config.embedding_dimensions}"
            )

    def _resolve_provider(self) -> EmbeddingProvider:
        """Resolve embedding provider based on configuration."""
        prov_name = (self.config.embedding_provider or "").lower()

        if prov_name in ("local", "chroma"):
            try:
                local_p = LocalChromaEmbeddingProvider(
                    model_name=self.config.embedding_model,
                    dimension=self.config.embedding_dimensions,
                )
                if local_p.is_available():
                    return local_p
            except Exception:
                pass

        # Deterministic fallback
        return DeterministicFallbackEmbeddingProvider(
            dimension=self.config.embedding_dimensions,
            model_name=self.config.embedding_model,
        )

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model_name

    @property
    def dimension(self) -> int:
        return self._provider.dimension

    # ─────────────────────────────────────────────────────────────────────────
    # Cache Key Generation
    # ─────────────────────────────────────────────────────────────────────────

    def compute_cache_key(self, text: str, chunk_id: str = "", case_id: str = "") -> str:
        """
        Deterministic cache key tied to provider, model, dimension, case, and content.
        Guarantees zero cross-case contamination and auto-invalidates on model changes.
        """
        raw = f"{self.provider_name}:{self.model_name}:{self.dimension}:{case_id}:{chunk_id}:{text.strip()}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # ─────────────────────────────────────────────────────────────────────────
    # Single Embedding
    # ─────────────────────────────────────────────────────────────────────────

    def embed(self, text: str, case_id: str = "", chunk_id: str = "") -> List[float]:
        """Embed a single string with caching and dimension verification."""
        if not text or not text.strip():
            return []

        cache_key = self.compute_cache_key(text, chunk_id=chunk_id, case_id=case_id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        vector = self._provider.embed(text)

        # Dimension validation
        if len(vector) != self.dimension:
            raise ValueError(
                f"Embedding vector dimension mismatch: expected {self.dimension}, got {len(vector)}"
            )

        self._cache[cache_key] = vector
        return vector

    # ─────────────────────────────────────────────────────────────────────────
    # Batch Embedding
    # ─────────────────────────────────────────────────────────────────────────

    def embed_batch(
        self,
        texts: Sequence[str],
        case_id: str = "",
        batch_size: int = 32,
    ) -> List[List[float]]:
        """
        Embed a sequence of texts preserving strict original ordering.
        Resolves cache hits first and batches uncached items.
        """
        if not texts:
            return []

        results: List[Optional[List[float]]] = [None] * len(texts)
        uncached_indices: List[int] = []
        uncached_texts: List[str] = []

        # 1. Check cache & handle empty inputs
        for idx, t in enumerate(texts):
            if not t or not t.strip():
                results[idx] = []
                continue

            cache_key = self.compute_cache_key(t, case_id=case_id)
            if cache_key in self._cache:
                results[idx] = self._cache[cache_key]
            else:
                uncached_indices.append(idx)
                uncached_texts.append(t)

        # 2. Batch process uncached items
        if uncached_texts:
            for b_start in range(0, len(uncached_texts), batch_size):
                b_end = b_start + batch_size
                batch_slice = uncached_texts[b_start:b_end]
                batch_idx_slice = uncached_indices[b_start:b_end]

                batch_vectors = self._provider.embed_batch(batch_slice)

                for orig_idx, txt, vec in zip(batch_idx_slice, batch_slice, batch_vectors):
                    if len(vec) != self.dimension:
                        raise ValueError(
                            f"Batch embedding dimension mismatch: expected {self.dimension}, got {len(vec)}"
                        )
                    cache_key = self.compute_cache_key(txt, case_id=case_id)
                    self._cache[cache_key] = vec
                    results[orig_idx] = vec

        return [r if r is not None else [] for r in results]

    # ─────────────────────────────────────────────────────────────────────────
    # Forensic Chunk Embedding
    # ─────────────────────────────────────────────────────────────────────────

    def embed_chunks(
        self,
        chunks: Sequence[DocumentChunk],
        batch_size: int = 32,
    ) -> List[Tuple[DocumentChunk, List[float]]]:
        """
        Embed a sequence of DocumentChunks while preserving their exact provenance.
        Returns list of (DocumentChunk, vector) tuples.
        """
        if not chunks:
            return []

        texts = [c.text for c in chunks]
        case_id = chunks[0].case_id if chunks else ""

        vectors = self.embed_batch(texts, case_id=case_id, batch_size=batch_size)

        output: List[Tuple[DocumentChunk, List[float]]] = []
        for chunk, vec in zip(chunks, vectors):
            # Invariant validation
            assert chunk.case_id == case_id or case_id == "", "Cross-case chunk contamination"
            output.append((chunk, vec))

        return output

    def clear_cache(self) -> None:
        """Clear the in-memory embedding cache."""
        self._cache.clear()
