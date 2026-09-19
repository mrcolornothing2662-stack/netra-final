"""
NETRA 5.0 — Autonomous Copilot Engine
Modular, multi-modal, evidence-grounded RAG pipeline with AST statutory verification.
"""

from .schemas import (
    Citation,
    CopilotQuery,
    CopilotResponse,
    RetrievedSnippet,
    QueryIntentType,
    QueryPlan,
    ModalityType,
    DocumentChunk,
    GraphNodeSnippet,
    GraphEdgeSnippet,
    StructuredRecordSnippet,
    StructuredRecordContext,
    RetrievedItem,
    FusedItem,
    CaseContextSnapshot,
    AssembledContext,
    GenerationPrompt,
    GenerationRequest,
    GeneratedResponse,
    Claim,
    SpanGrounding,
    StatutoryAuditItem,
    VerificationReport,
    ClaimVerificationReport,
    VerifiedResponse,
)
from .config import (
    CopilotConfig,
    get_copilot_config,
)
from .query_planner import (
    QueryPlanner,
)
from .chunker import (
    ForensicChunker,
)
from .embeddings import (
    EmbeddingService,
    EmbeddingProvider,
    DeterministicFallbackEmbeddingProvider,
    LocalChromaEmbeddingProvider,
)
from .vector_store import (
    VectorStore,
)
from .graph_retriever import (
    GraphRetriever,
)
from .structured_retriever import (
    StructuredRetriever,
)
from .hybrid_retriever import (
    HybridRetriever,
)
from .reranker import (
    Reranker,
    RerankerProvider,
    DeterministicFallbackRerankerProvider,
    LocalCrossEncoderProvider,
)
from .context_builder import (
    ContextBuilder,
)
from .prompt_builder import (
    PromptBuilder,
)
from .generator import (
    Generator,
    GeneratorProvider,
    DeterministicFallbackGeneratorProvider,
    OllamaGeneratorProvider,
    GeminiGeneratorProvider,
)
from .claim_verifier import (
    ClaimVerifier,
    ClaimExtractor,
)

__all__ = [
    "Citation",
    "CopilotQuery",
    "CopilotResponse",
    "RetrievedSnippet",
    "QueryIntentType",
    "QueryPlan",
    "ModalityType",
    "DocumentChunk",
    "GraphNodeSnippet",
    "GraphEdgeSnippet",
    "StructuredRecordSnippet",
    "StructuredRecordContext",
    "RetrievedItem",
    "FusedItem",
    "CaseContextSnapshot",
    "AssembledContext",
    "GenerationPrompt",
    "GenerationRequest",
    "GeneratedResponse",
    "Claim",
    "SpanGrounding",
    "StatutoryAuditItem",
    "VerificationReport",
    "ClaimVerificationReport",
    "VerifiedResponse",
    "CopilotConfig",
    "get_copilot_config",
    "QueryPlanner",
    "ForensicChunker",
    "EmbeddingService",
    "EmbeddingProvider",
    "DeterministicFallbackEmbeddingProvider",
    "LocalChromaEmbeddingProvider",
    "VectorStore",
    "GraphRetriever",
    "StructuredRetriever",
    "HybridRetriever",
    "Reranker",
    "RerankerProvider",
    "DeterministicFallbackRerankerProvider",
    "LocalCrossEncoderProvider",
    "ContextBuilder",
    "PromptBuilder",
    "Generator",
    "GeneratorProvider",
    "DeterministicFallbackGeneratorProvider",
    "OllamaGeneratorProvider",
    "GeminiGeneratorProvider",
    "ClaimVerifier",
    "ClaimExtractor",
]
