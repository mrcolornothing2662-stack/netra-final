from __future__ import annotations
"""
CyberDrishti AI — Master Hybrid Extraction & Inference Manager
Combines:
  1. Deterministic regex (authoritative for PHONE, UPI, ACCOUNT, AMOUNT, EMAIL, IP, IFSC, URL)
  2. Real ML model inference (CRF / HingBERT / CyberDrishtiLM) for contextual entities
  3. Built-in Hinglish NER fallback (PERSON, ORG, LOCATION, DATE) — always runs
"""
import time
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from correlation.regex_extractors import extract as extract_regex
from ml.registry import get_model_registry
from nlp.entity_validation import validate_entity_candidate

logger = logging.getLogger(__name__)


@dataclass
class ExtractedMention:
    entity_type: str
    raw_value: str
    canonical_value: str
    span_start: int
    span_end: int
    confidence: float
    extractor: str          # "regex" | "crf" | "hingbert" | "cyberdrishtilm" | "spacy_ner" | "hinglish_ner"
    is_hard_id: bool = False


@dataclass
class HybridExtractionResult:
    mentions: List[ExtractedMention] = field(default_factory=list)
    primary_model: str = "none"
    inference_time_ms: float = 0.0
    ml_entity_count: int = 0
    regex_entity_count: int = 0
    model_agreement: str = "SINGLE_MODEL"
    all_predictions_by_model: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)


def _spans_overlap(a_start: int, a_end: int, seen: set) -> bool:
    return any(a_start < e and a_end > s for s, e in seen)


def run_hybrid_extraction(text: str) -> HybridExtractionResult:
    """
    Full hybrid extraction pipeline:
    1. Regex → hard IDs (authoritative, confidence=1.0)
    2. ML models → contextual entities (PERSON, ORG, LOCATION, DATE)
    3. Hinglish NER fallback → fills gaps when ML model returns nothing
    4. Compute model agreement across loaded models
    """
    result = HybridExtractionResult()
    if not text or not text.strip():
        return result

    start_time = time.perf_counter()

    # ── Step 1: Deterministic Regex (Hard IDs) ────────────────────────────────
    regex_matches = extract_regex(text)
    seen_spans: set[Tuple[int, int]] = set()

    for m in regex_matches:
        canon = str(m.norm_value if m.norm_value is not None else m.raw_value).strip()
        if not canon:
            continue
        seen_spans.add((m.span_start, m.span_end))
        result.mentions.append(ExtractedMention(
            entity_type=m.entity_type,
            raw_value=m.raw_value,
            canonical_value=canon,
            span_start=m.span_start,
            span_end=m.span_end,
            confidence=1.0,
            extractor="regex",
            is_hard_id=True,
        ))
        result.regex_entity_count += 1

    # ── Step 2: ML Model Inference ────────────────────────────────────────────
    registry = get_model_registry()
    primary_engine, primary_name = registry.get_primary_engine()
    result.primary_model = primary_name

    ml_predictions_map: Dict[str, List[Any]] = {}

    if primary_engine and primary_engine.loaded:
        try:
            preds = primary_engine.predict(text)
            if preds:
                ml_predictions_map[primary_name] = preds
        except Exception as exc:
            logger.error("[ML] Primary model %s error: %s", primary_name, exc)

    # Secondary models for agreement computation
    for engine_name, engine in [
        ("crf", registry.crf_engine),
        ("hingbert", registry.hingbert_engine),
    ]:
        if engine.loaded and engine_name not in ml_predictions_map:
            try:
                preds = engine.predict(text)
                if preds:
                    ml_predictions_map[engine_name] = preds
            except Exception:
                pass

    # Record predictions per model for UI
    for mname, mpreds in ml_predictions_map.items():
        result.all_predictions_by_model[mname] = [
            {
                "entity_type": p.entity_type,
                "raw_value": p.raw_value,
                "span_start": p.span_start,
                "span_end": p.span_end,
                "confidence": p.confidence,
                "model_name": mname,
            }
            for p in mpreds
        ]

    # Add primary model predictions to mentions (skip hard-ID overlaps and invalid entities)
    primary_preds = ml_predictions_map.get(primary_name, [])
    for p in primary_preds:
        if _spans_overlap(p.span_start, p.span_end, seen_spans):
            continue
        if not validate_entity_candidate(p.entity_type, p.raw_value):
            logger.debug("[Hybrid] Rejected ML candidate: type=%s value=%r", p.entity_type, p.raw_value)
            continue
        result.mentions.append(ExtractedMention(
            entity_type=p.entity_type,
            raw_value=p.raw_value,
            canonical_value=p.canonical_value,
            span_start=p.span_start,
            span_end=p.span_end,
            confidence=p.confidence,
            extractor=primary_name,
            is_hard_id=False,
        ))
        result.ml_entity_count += 1
        seen_spans.add((p.span_start, p.span_end))

    # ── Step 3: Hinglish NER Fallback ────────────────────────────────────────
    # Always run — fills PERSON/ORG/LOCATION/DATE that ML missed
    from nlp.ner import extract_entities as extract_ner
    ner_results = extract_ner(text)
    for ner in ner_results:
        if _spans_overlap(ner.span_start, ner.span_end, seen_spans):
            continue
        if not validate_entity_candidate(ner.entity_type, ner.raw_value):
            logger.debug("[Hybrid] Rejected NER candidate: type=%s value=%r", ner.entity_type, ner.raw_value)
            continue
        result.mentions.append(ExtractedMention(
            entity_type=ner.entity_type,
            raw_value=ner.raw_value,
            canonical_value=ner.canonical_value,
            span_start=ner.span_start,
            span_end=ner.span_end,
            confidence=ner.confidence,
            extractor=ner.extractor,
            is_hard_id=False,
        ))
        result.ml_entity_count += 1
        seen_spans.add((ner.span_start, ner.span_end))

    # ── Step 4: Model Agreement ───────────────────────────────────────────────
    if len(ml_predictions_map) >= 2:
        model_names = list(ml_predictions_map.keys())
        p_set = {(p.entity_type, p.raw_value.lower()) for p in ml_predictions_map[model_names[0]]}
        s_set = {(p.entity_type, p.raw_value.lower()) for p in ml_predictions_map[model_names[1]]}
        if p_set == s_set:
            result.model_agreement = "HIGH"
        elif p_set & s_set:
            result.model_agreement = "MEDIUM"
        else:
            result.model_agreement = "DISAGREEMENT"
    else:
        result.model_agreement = "SINGLE_MODEL"

    result.inference_time_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

    logger.info(
        "[Hybrid] Done in %.1fms | Primary: %s | ML+NER: %d | Regex: %d | Agreement: %s",
        result.inference_time_ms, result.primary_model,
        result.ml_entity_count, result.regex_entity_count, result.model_agreement,
    )

    return result
