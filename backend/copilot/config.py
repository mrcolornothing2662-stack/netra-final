from __future__ import annotations

"""
NETRA 5.0 — Copilot RAG Configuration

Central configuration for the Hybrid Forensic RAG pipeline.

This module contains configuration only:
- retrieval limits
- RRF fusion
- chunking
- embeddings
- vector storage
- reranking
- context limits
- generation
- verification
- security

No retrieval, database, or LLM execution belongs here.
"""

import os
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CopilotConfig(BaseSettings):
    """Runtime configuration for the NETRA Copilot RAG pipeline."""

    model_config = SettingsConfigDict(
        env_prefix="NETRA_COPILOT_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        protected_namespaces=(),
    )

    # ──────────────────────────────────────────────────────────────────────
    # Retrieval
    # ──────────────────────────────────────────────────────────────────────

    default_top_k: int = Field(default=5, ge=1, le=50)

    vector_top_k: int = Field(default=12, ge=1, le=100)
    graph_top_k: int = Field(default=12, ge=1, le=100)
    structured_top_k: int = Field(default=12, ge=1, le=100)
    timeline_top_k: int = Field(default=12, ge=1, le=100)

    max_retrieval_candidates: int = Field(
        default=50,
        ge=1,
        le=500,
    )

    # Reciprocal Rank Fusion:
    # score(d) = Σ weight / (k + rank)
    rrf_k: int = Field(default=60, ge=1, le=500)

    vector_rrf_weight: float = Field(default=1.0, ge=0.0, le=10.0)
    graph_rrf_weight: float = Field(default=1.2, ge=0.0, le=10.0)
    structured_rrf_weight: float = Field(default=1.2, ge=0.0, le=10.0)
    timeline_rrf_weight: float = Field(default=1.0, ge=0.0, le=10.0)

    # ──────────────────────────────────────────────────────────────────────
    # Chunking
    # ──────────────────────────────────────────────────────────────────────

    chunk_size: int = Field(default=900, ge=100, le=8000)
    chunk_overlap: int = Field(default=150, ge=0, le=2000)
    minimum_chunk_size: int = Field(default=80, ge=1, le=1000)

    # ──────────────────────────────────────────────────────────────────────
    # Embeddings
    # ──────────────────────────────────────────────────────────────────────

    embedding_provider: str = Field(default="local")
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2"
    )
    embedding_dimensions: int = Field(default=384, ge=1)

    # ──────────────────────────────────────────────────────────────────────
    # Vector Store
    # ──────────────────────────────────────────────────────────────────────

    vector_store_provider: str = Field(default="chroma")
    vector_collection_prefix: str = Field(default="netra_case")
    vector_distance_metric: str = Field(default="cosine")

    # ──────────────────────────────────────────────────────────────────────
    # Reranking
    # ──────────────────────────────────────────────────────────────────────

    reranker_enabled: bool = Field(default=False)

    reranker_provider: str = Field(default="local")
    reranker_model: str = Field(default="BAAI/bge-reranker-base")

    reranker_candidate_k: int = Field(default=30, ge=1, le=200)
    reranker_final_k: int = Field(default=12, ge=1, le=100)

    # ──────────────────────────────────────────────────────────────────────
    # Graph Retrieval
    # ──────────────────────────────────────────────────────────────────────

    default_graph_hops: int = Field(default=2, ge=1, le=5)
    max_graph_hops: int = Field(default=3, ge=1, le=6)

    include_observed_relationships: bool = Field(default=True)
    include_inferred_relationships: bool = Field(default=True)

    # Inferred relationships must remain distinguishable from observations.
    inferred_relationship_weight: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
    )

    # ──────────────────────────────────────────────────────────────────────
    # Context Assembly
    # ──────────────────────────────────────────────────────────────────────

    max_context_items: int = Field(default=24, ge=1, le=200)
    max_context_tokens: int = Field(default=12000, ge=1000, le=100000)

    max_document_chunks: int = Field(default=12, ge=1, le=100)
    max_context_documents: int = Field(default=12, ge=1, le=100)
    max_graph_nodes: int = Field(default=30, ge=1, le=500)
    max_graph_edges: int = Field(default=50, ge=1, le=1000)
    max_timeline_events: int = Field(default=50, ge=1, le=1000)

    # ──────────────────────────────────────────────────────────────────────
    # Generation
    # ──────────────────────────────────────────────────────────────────────

    llm_provider: str = Field(
        default_factory=lambda: os.getenv("NETRA_COPILOT_LLM_PROVIDER") or os.getenv("LLM_PROVIDER") or "ollama"
    )
    llm_model: str = Field(
        default_factory=lambda: os.getenv("NETRA_COPILOT_LLM_MODEL") or os.getenv("LLM_MODEL") or os.getenv("OLLAMA_MODEL") or "llama3.2:1b"
    )
    ollama_base_url: str = Field(
        default_factory=lambda: os.getenv("NETRA_COPILOT_OLLAMA_BASE_URL") or os.getenv("OLLAMA_BASE_URL") or "http://localhost:11434"
    )

    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=2000, ge=128, le=16000)

    generation_timeout_seconds: float = Field(
        default=30.0,
        ge=0.01,
        le=300.0,
    )

    # ──────────────────────────────────────────────────────────────────────
    # Grounding / Verification
    # ──────────────────────────────────────────────────────────────────────

    grounding_required: bool = Field(default=True)

    minimum_grounded_claim_ratio: float = Field(
        default=0.90,
        ge=0.0,
        le=1.0,
    )

    minimum_citation_count: int = Field(default=1, ge=0, le=100)

    abstain_on_ungrounded_claims: bool = Field(default=True)

    require_output_verifier: bool = Field(default=True)

    # ──────────────────────────────────────────────────────────────────────
    # Security / Isolation
    # ──────────────────────────────────────────────────────────────────────

    enforce_case_isolation: bool = Field(default=True)

    evidence_sandbox_tag: str = Field(
        default="untrusted_case_evidence"
    )

    prompt_injection_protection: bool = Field(default=True)

    allow_evidence_to_override_system_instructions: bool = Field(
        default=False
    )

    # ──────────────────────────────────────────────────────────────────────
    # Operational limits
    # ──────────────────────────────────────────────────────────────────────

    retrieval_timeout_seconds: float = Field(
        default=10.0,
        ge=1.0,
        le=120.0,
    )

    graph_timeout_seconds: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
    )

    structured_timeout_seconds: float = Field(
        default=5.0,
        ge=1.0,
        le=60.0,
    )


@lru_cache(maxsize=1)
def get_copilot_config() -> CopilotConfig:
    """Return the process-wide immutable configuration instance."""
    return CopilotConfig()
