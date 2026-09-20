from __future__ import annotations

"""
NETRA 5.0 — Forensic Multi-Modal Candidate Reranker
Post-RRF candidate reranking layer executing:
1. Cross-Encoder / Local Semantic Scoring (with Deterministic Fallback)
2. Exact Structured Fact Signal (ACCOUNT, PHONE, EMAIL, UPI, IP, AMOUNT, TIMESTAMP, etc.)
3. Epistemic Status Preservation (strictly preserves OBSERVED vs INFERRED)
4. Provenance Preservation (evidence files, lines, citations, payloads)
5. Deterministic Tie-Breaking (-final_score, -fused_score, original_rank, item_id)
6. Budget Enforcement (evaluates top candidate_k, returns final_k)

Safety Invariants:
- Preserves original RRF `fused_score` untouched.
- Adds `rerank_score` and `final_score` to FusedItem.
- Never transforms risk_score / bridge_score / finding confidence into guilt probability.
- 100% offline-safe; never silently downloads models during Copilot request.
- Graceful fallback on any provider error.
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Protocol, Sequence, Set, Tuple, Union

from .config import CopilotConfig, get_copilot_config
from .query_planner import QueryPlanner
from .schemas import FusedItem, ModalityType, QueryPlan, QueryIntentType

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Provider Protocol & Implementations
# ─────────────────────────────────────────────────────────────────────────────

class RerankerProvider(Protocol):
    """Protocol for reranker scoring models."""

    async def score(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        """
        Score query-document pairs.
        Returns a list of relevance scores (0.0 to 1.0) corresponding to each document.
        """
        ...


class DeterministicFallbackRerankerProvider:
    """
    Offline, deterministic lexical/semantic relevance scorer.
    Zero external model downloads.
    Evaluates:
    - Term frequency saturation (BM25-like tf / (tf + 1.2))
    - Distinct query keyword coverage
    - Exact phrase / identifier match boosts
    - Normalized to [0.0, 1.0]
    """

    STOPWORDS: Set[str] = {
        "a", "an", "the", "and", "or", "in", "on", "at", "to", "for",
        "of", "with", "by", "from", "is", "are", "was", "were", "be",
        "been", "being", "this", "that", "these", "those", "what",
        "which", "who", "whom", "whose", "why", "where", "how", "all",
        "any", "both", "each", "few", "more", "most", "other", "some",
        "such", "no", "nor", "not", "only", "own", "same", "so", "than",
        "too", "very", "can", "will", "just", "don", "should", "now",
    }

    def _tokenize(self, text: str) -> List[str]:
        if not text:
            return []
        # Retain alphanumeric, hyphens, colons, underscores for forensic identifiers
        return re.findall(r"[A-Za-z0-9_\-.:@/]+", text.lower())

    def _extract_keywords(self, text: str) -> List[str]:
        tokens = self._tokenize(text)
        return [t for t in tokens if t not in self.STOPWORDS and len(t) > 1]

    async def score(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        if not documents:
            return []

        query_keywords = self._extract_keywords(query)
        query_text_lower = query.lower().strip()

        scores: List[float] = []
        for doc in documents:
            if not doc:
                scores.append(0.0)
                continue

            doc_lower = doc.lower()
            doc_tokens = self._tokenize(doc)

            if not query_keywords:
                q_all = self._tokenize(query)
                if not q_all:
                    scores.append(0.0)
                    continue
                overlap = sum(1 for t in q_all if t in doc_lower)
                scores.append(round(min(1.0, overlap / len(q_all)), 6))
                continue

            # 1. Term frequency saturation for keywords: tf / (tf + 1.2)
            tf_score = 0.0
            matched_keywords = 0
            for kw in query_keywords:
                count = doc_tokens.count(kw)
                if count > 0:
                    tf_score += count / (count + 1.2)
                    matched_keywords += 1

            normalized_tf = tf_score / len(query_keywords)
            coverage = matched_keywords / len(query_keywords)

            # 2. Exact phrase boost
            phrase_boost = 0.0
            if len(query_text_lower) > 3 and query_text_lower in doc_lower:
                phrase_boost = 0.3
            elif any(kw in doc_lower for kw in query_keywords if len(kw) >= 4):
                phrase_boost = 0.1

            # Combined score bounded [0.0, 1.0]
            raw_score = 0.45 * normalized_tf + 0.40 * coverage + 0.15 * phrase_boost
            scores.append(round(min(1.0, max(0.0, raw_score)), 6))

        return scores


class LocalCrossEncoderProvider:
    """
    Local Cross-Encoder provider using transformers AutoModelForSequenceClassification.
    Offline safety:
    - Never triggers remote HuggingFace network downloads (local_files_only=True).
    - If model is not found or fails to load, gracefully delegates to fallback provider.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-base",
        fallback_provider: Optional[RerankerProvider] = None,
    ):
        self.model_name = model_name
        self.fallback_provider = fallback_provider or DeterministicFallbackRerankerProvider()
        self._tokenizer = None
        self._model = None
        self._initialized = False
        self._load_error: Optional[str] = None

    def _ensure_loaded(self) -> bool:
        if self._initialized:
            return self._model is not None
        self._initialized = True
        try:
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            # IMPORTANT: local_files_only=True strictly prevents network downloads
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_name,
                local_files_only=True,
            )
            self._model = AutoModelForSequenceClassification.from_pretrained(
                self.model_name,
                local_files_only=True,
            )
            self._model.eval()
            logger.info("Successfully loaded local cross-encoder model '%s'", self.model_name)
            return True
        except Exception as e:
            self._load_error = str(e)
            logger.warning(
                "Local cross-encoder '%s' cannot be loaded locally (%s). Falling back to deterministic reranker.",
                self.model_name,
                e,
            )
            self._model = None
            self._tokenizer = None
            return False

    async def score(
        self,
        query: str,
        documents: list[str],
    ) -> list[float]:
        if not documents:
            return []

        if not self._ensure_loaded():
            return await self.fallback_provider.score(query, documents)

        def _predict() -> List[float]:
            import torch

            pairs = [[query, doc] for doc in documents]
            inputs = self._tokenizer(
                pairs,
                padding=True,
                truncation=True,
                max_length=512,
                return_tensors="pt",
            )
            with torch.no_grad():
                outputs = self._model(**inputs)
                logits = outputs.logits
                if logits.shape[-1] == 1:
                    probs = torch.sigmoid(logits).squeeze(-1)
                else:
                    probs = torch.softmax(logits, dim=-1)[:, 1]
                scores = probs.cpu().tolist()
                if isinstance(scores, float):
                    scores = [scores]
                return [round(float(s), 6) for s in scores]

        try:
            return await asyncio.to_thread(_predict)
        except Exception as e:
            logger.warning("Cross-encoder inference failed: %s; falling back to deterministic scorer.", e)
            return await self.fallback_provider.score(query, documents)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Main Reranker Class
# ─────────────────────────────────────────────────────────────────────────────

class Reranker:
    """
    Post-RRF candidate reranker for NETRA 5.0.
    Combines:
    1. Reciprocal Rank Fusion score (fused_score preserved intact)
    2. Semantic / Cross-encoder relevance score (rerank_score)
    3. Forensic Priority Signals:
       - Exact identifier alignment (ACCOUNT, PHONE, EMAIL, UPI, IP, etc.)
       - Query intent-guided exact fact alignment (AMOUNT/TRANSACTION, GRAPH/RELATIONAL, TIMELINE/TEMPORAL)
       - Provenance grounding bonus
    4. Epistemic preservation (OBSERVED vs INFERRED preserved strictly)
    5. Deterministic budget enforcement (candidate_k -> final_k)
    6. Deterministic tie-breaking (-final_score, -fused_score, original_rank, item_id)
    """

    def __init__(
        self,
        config: Optional[CopilotConfig] = None,
        provider: Optional[RerankerProvider] = None,
        query_planner: Optional[QueryPlanner] = None,
    ):
        self.config = config or get_copilot_config()
        self.query_planner = query_planner or QueryPlanner()
        self.fallback_provider = DeterministicFallbackRerankerProvider()

        if provider is not None:
            self.provider = provider
        elif self.config.reranker_enabled and self.config.reranker_provider == "local":
            self.provider = LocalCrossEncoderProvider(
                model_name=self.config.reranker_model,
                fallback_provider=self.fallback_provider,
            )
        else:
            self.provider = self.fallback_provider

    def _calculate_forensic_signals(
        self,
        plan: QueryPlan,
        item: FusedItem,
    ) -> float:
        """
        Calculate deterministic forensic priority signals for an evidence item.
        Dynamically adapts to query intent and extracted investigative entities.
        Does NOT treat risk scores or bridge scores as evidence of guilt.
        """
        signal = 0.0
        query_lower = plan.original_query.lower()
        payload = item.raw_payload or {}
        item_text_lower = item.text.lower()
        payload_str_lower = str(payload).lower()

        # ─────────────────────────────────────────────────────────────────────
        # A. Exact Identifier Alignment
        # Matches accounts, phones, emails, upis, ips, and named entities
        # ─────────────────────────────────────────────────────────────────────
        matched_ids = 0
        all_query_ids: List[str] = []

        # From target_entities (format "TYPE:VALUE" or raw string)
        for entity_str in (plan.target_entities or []):
            if ":" in entity_str:
                _, val = entity_str.split(":", 1)
                all_query_ids.append(val.strip())
            else:
                all_query_ids.append(entity_str.strip())

        # Also extract any identifiers from query text directly (e.g. ACC-001, phone numbers)
        for token in re.findall(r"\b[A-Za-z0-9_\-+.:@/]{3,}\b", plan.original_query):
            if any(char.isdigit() for char in token):
                all_query_ids.append(token.strip())

        seen_matched: Set[str] = set()
        for q_id in all_query_ids:
            q_clean = q_id.strip().lower()
            if not q_clean or q_clean in seen_matched:
                continue
            if (
                q_clean in item_text_lower
                or q_clean in payload_str_lower
                or q_clean in item.id.lower()
            ):
                matched_ids += 1
                seen_matched.add(q_clean)

        if matched_ids > 0:
            # +0.25 per matched identifier, capped at +0.50
            signal += min(0.50, matched_ids * 0.25)

        # ─────────────────────────────────────────────────────────────────────
        # B. Intent-Guided Exact Fact Alignment
        # ─────────────────────────────────────────────────────────────────────
        intent_val = plan.intent.value if hasattr(plan.intent, "value") else str(plan.intent or "general")
        intent = intent_val.lower()

        # 1. Amount & Transaction Intent
        amount_keywords = (
            "amount", "transferred", "transfer", "paid", "received",
            "inr", "rupees", "balance", "sum", "total", "money", "$"
        )
        query_amounts = re.findall(r"(?:₹|Rs\.?|INR|\$)\s?([0-9][\d,]*(?:\.\d{1,2})?)", plan.original_query, re.IGNORECASE)
        is_amount_query = (
            intent == "factual"
            or any(kw in query_lower for kw in amount_keywords)
            or bool(query_amounts)
        )
        if is_amount_query:
            is_transaction = (
                payload.get("event_type") == "TRANSACTION"
                or "amount" in payload
                or "[structured transaction]" in item_text_lower
                or "amount=" in item_text_lower
                or "inr" in item_text_lower
            )
            if is_transaction:
                signal += 0.40

            # Match exact requested amount if present
            if query_amounts:
                for amt in query_amounts:
                    amt_clean = amt.replace(",", "").strip()
                    if amt_clean and (amt_clean in item_text_lower or amt_clean in payload_str_lower):
                        signal += 0.15
                        break

        # 2. Temporal & Timeline Intent
        temporal_keywords = (
            "timeline", "chronology", "sequence", "happened", "between", "when",
            "after", "before", "august", "january", "february", "march",
            "april", "may", "june", "july", "september", "october", "november", "december"
        )
        is_temporal_query = (
            intent == "temporal"
            or plan.time_window_start is not None
            or any(kw in query_lower for kw in temporal_keywords)
        )
        if is_temporal_query:
            is_timeline_event = (
                ModalityType.TIMELINE in item.modalities
                or "[timeline]" in item_text_lower
                or "timestamp" in payload
                or "event_timestamp" in payload
            )
            if is_timeline_event:
                signal += 0.40
                ev_type = str(payload.get("event_type") or "").lower()
                if any(k in ev_type for k in ("bank", "call", "location", "network", "seizure", "document")):
                    signal += 0.25

        # 3. Relational & Graph Intent
        relational_keywords = (
            "relationship", "relationships", "connect", "connected", "connects",
            "connection", "link", "links", "linked", "network", "associate", "associated"
        )
        is_relational_query = (
            intent == "relational"
            or (not is_temporal_query and "between" in query_lower)
            or any(kw in query_lower for kw in relational_keywords)
        )
        if is_relational_query:
            is_graph_relational = (
                ModalityType.GRAPH in item.modalities
                or "[graph" in item_text_lower
                or "relationship_type" in payload
                or ("source" in payload and "target" in payload)
            )
            if is_graph_relational:
                signal += 0.35

        # 4. Communication Intent
        comm_keywords = ("call", "calls", "message", "messages", "sms", "chat", "email", "cdr")
        if any(kw in query_lower for kw in comm_keywords):
            is_communication = (
                payload.get("event_type") == "COMMUNICATION"
                or "call" in item_text_lower
                or "message" in item_text_lower
                or "cdr" in item_text_lower
            )
            if is_communication:
                signal += 0.35

        # ─────────────────────────────────────────────────────────────────────
        # C. Provenance Grounding Bonus
        # ─────────────────────────────────────────────────────────────────────
        has_verified_source = bool(
            item.source_file
            and item.source_file not in ("Unknown", "Case Graph (Entities)")
        )
        has_exact_location = bool(
            item.source_line is not None
            or item.source_page is not None
            or item.citations
            or payload.get("event_id")
            or payload.get("finding_id")
        )
        if has_verified_source and has_exact_location:
            signal += 0.05

        return round(min(1.0, max(0.0, signal)), 6)

    async def rerank(
        self,
        query: Union[str, QueryPlan],
        candidates: List[FusedItem],
        plan: Optional[QueryPlan] = None,
        limit: Optional[int] = None,
    ) -> List[FusedItem]:
        """
        Reranks candidates post-RRF.
        - Evaluates up to `config.reranker_candidate_k` candidates (budget limit).
        - Preserves `fused_score` untouched.
        - Computes `rerank_score` (semantic/cross-encoder) and `final_score`.
        - Enforces deterministic tie-breaking: (-final_score, -fused_score, original_rank, item_id).
        - Returns up to `limit` or `config.reranker_final_k` items.
        """
        if not candidates:
            return []

        # Resolve query string and QueryPlan
        if isinstance(query, QueryPlan):
            active_plan = query
            query_text = active_plan.original_query
        elif plan is not None:
            active_plan = plan
            query_text = str(query)
        else:
            query_text = str(query)
            active_plan = self.query_planner.plan(query_text)

        # Budget limits
        candidate_budget = self.config.reranker_candidate_k
        final_budget = limit or self.config.reranker_final_k
        if (
            active_plan.intent in (QueryIntentType.TEMPORAL, "temporal")
            or active_plan.time_window_start is not None
            or "happened" in active_plan.original_query.lower()
        ):
            candidate_budget = max(candidate_budget, 50)
            final_budget = max(final_budget, 25)

        # Truncate candidates to evaluation budget
        eval_candidates = candidates[:candidate_budget]
        doc_texts = [item.text for item in eval_candidates]

        # Score documents via provider with safe fallback
        try:
            rerank_scores = await self.provider.score(query_text, doc_texts)
            if not isinstance(rerank_scores, list) or len(rerank_scores) != len(doc_texts):
                raise ValueError(f"Provider returned invalid scores shape: expected {len(doc_texts)}")
        except Exception as e:
            logger.warning("Reranker provider scoring failed: %s; falling back to deterministic scorer", e)
            rerank_scores = await self.fallback_provider.score(query_text, doc_texts)

        # Combine scores and evaluate forensic signals
        scored_entries: List[Tuple[FusedItem, float, float, int]] = []
        for orig_idx, (item, r_score) in enumerate(zip(eval_candidates, rerank_scores), start=1):
            r_score_val = round(float(r_score), 6)
            forensic_signal = self._calculate_forensic_signals(active_plan, item)

            # Combined final score:
            # FusedItem.fused_score + reranker score + forensic priority signals
            final_score = round(item.fused_score + r_score_val + forensic_signal, 6)
            scored_entries.append((item, final_score, r_score_val, orig_idx))

        # Deterministic tie-breaking:
        # 1. -final_score (descending)
        # 2. -fused_score (descending)
        # 3. orig_rank (ascending)
        # 4. item_id (ascending lexicographical string)
        def sort_key(entry: Tuple[FusedItem, float, float, int]) -> Tuple[float, float, int, str]:
            it, fin_score, _, orig_rank = entry
            return (-fin_score, -it.fused_score, orig_rank, str(it.id))

        sorted_entries = sorted(scored_entries, key=sort_key)
        final_selection = sorted_entries[:final_budget]

        # Assemble reranked items with full provenance and epistemic preservation
        reranked_items: List[FusedItem] = []
        for new_rank, (item, fin_score, r_score, _) in enumerate(final_selection, start=1):
            reranked_items.append(
                FusedItem(
                    id=item.id,
                    rank=new_rank,
                    fused_score=item.fused_score,  # PRESERVED ORIGINAL RRF SCORE
                    text=item.text,
                    source_file=item.source_file,
                    source_line=item.source_line,
                    source_page=item.source_page,
                    modalities=list(item.modalities),
                    raw_payload=dict(item.raw_payload or {}),
                    epistemic_status=item.epistemic_status,  # STRICTLY PRESERVED
                    citations=list(item.citations or []),
                    rerank_score=r_score,
                    final_score=fin_score,
                )
            )

        return reranked_items
