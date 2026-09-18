from __future__ import annotations
"""
CyberDrishti AI — CRF Model Inference + Training Service
Uses sklearn-crfsuite to perform sequence labeling for contextual NER.
Supports: load(), predict(), train(), evaluate() — fully trainable.
"""
import logging
import pickle
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Graceful import
_crfsuite_available = False
try:
    import sklearn_crfsuite
    from sklearn_crfsuite import metrics as crf_metrics
    _crfsuite_available = True
except ImportError:
    logger.warning("[CRF] sklearn-crfsuite not installed. Run: pip3 install sklearn-crfsuite")


@dataclass
class MLPrediction:
    entity_type: str
    raw_value: str
    canonical_value: str
    span_start: int
    span_end: int
    confidence: float
    model_name: str = "crf"


# ── Feature extraction ────────────────────────────────────────────────────────

def _word2features(tokens: List[str], i: int) -> Dict[str, Any]:
    """Rich feature set for CRF token classification."""
    word = tokens[i]
    feat = {
        "bias": 1.0,
        "word.lower()": word.lower(),
        "word[-3:]": word[-3:],
        "word[-2:]": word[-2:],
        "word[:3]": word[:3],
        "word[:2]": word[:2],
        "word.isupper()": word.isupper(),
        "word.istitle()": word.istitle(),
        "word.isdigit()": word.isdigit(),
        "word.has_digit": any(c.isdigit() for c in word),
        "word.has_hyphen": "-" in word,
        "word.has_at": "@" in word,
        "word.len": len(word),
        "word.len_bucket": min(len(word) // 3, 5),  # 0-5
    }
    if i > 0:
        w1 = tokens[i - 1]
        feat.update({
            "-1:word.lower()": w1.lower(),
            "-1:word.istitle()": w1.istitle(),
            "-1:word.isupper()": w1.isupper(),
        })
        if i > 1:
            w2 = tokens[i - 2]
            feat["-2:word.lower()"] = w2.lower()
    else:
        feat["BOS"] = True

    if i < len(tokens) - 1:
        w1 = tokens[i + 1]
        feat.update({
            "+1:word.lower()": w1.lower(),
            "+1:word.istitle()": w1.istitle(),
            "+1:word.isupper()": w1.isupper(),
        })
        if i < len(tokens) - 2:
            w2 = tokens[i + 2]
            feat["+2:word.lower()"] = w2.lower()
    else:
        feat["EOS"] = True

    return feat


def _sent2features(tokens: List[str]) -> List[Dict[str, Any]]:
    return [_word2features(tokens, i) for i in range(len(tokens))]


def _sent2labels(labels: List[str]) -> List[str]:
    return labels


# ── Inference Engine ──────────────────────────────────────────────────────────

class CRFInferenceEngine:
    """CRF Model Inference and Training Service."""

    def __init__(self, model_path: Optional[str | Path] = None):
        self.model = None
        self.loaded = False
        if model_path:
            self.load(model_path)

    # ── Load ─────────────────────────────────────────────────────────────────

    def load(self, model_path: str | Path) -> bool:
        path = Path(model_path)
        if not path.exists():
            logger.warning("[CRF] Checkpoint not found at %s", path)
            self.loaded = False
            return False

        try:
            with open(path, "rb") as f:
                obj = pickle.load(f)

            # Handle both raw CRF objects and dict-wrapped checkpoints
            if isinstance(obj, dict) and "model" in obj:
                self.model = obj["model"]
            else:
                self.model = obj

            # Verify the model has a predict method
            if not hasattr(self.model, "predict"):
                logger.warning("[CRF] Loaded object has no predict() — rebuilding fallback.")
                self.model = _build_fallback_crf()

            self.loaded = True
            logger.info("[CRF] Loaded checkpoint from %s", path)
            return True

        except Exception as exc:
            logger.warning("[CRF] Failed to unpickle (%s) — using feature-based fallback.", exc)
            self.model = _build_fallback_crf()
            self.loaded = True
            return True

    # ── Predict ──────────────────────────────────────────────────────────────

    def predict(self, text: str) -> List[MLPrediction]:
        """Tokenize, extract features, run CRF, decode BIO tags → MLPrediction list."""
        if not self.loaded or not self.model or not text.strip():
            return []

        tokens_with_offsets: List[Tuple[str, int, int]] = []
        for m in re.finditer(r'\S+', text):
            tokens_with_offsets.append((m.group(), m.start(), m.end()))

        if not tokens_with_offsets:
            return []

        tokens = [t[0] for t in tokens_with_offsets]
        features = _sent2features(tokens)

        try:
            tags: List[str] = self.model.predict([features])[0]
        except Exception as exc:
            logger.error("[CRF] Inference error: %s", exc)
            return []

        return _decode_bio(tags, tokens_with_offsets, text)

    # ── Train ─────────────────────────────────────────────────────────────────

    def train(
        self,
        train_sentences: List[List[str]],
        train_labels: List[List[str]],
        save_path: Optional[str | Path] = None,
        c1: float = 0.1,
        c2: float = 0.1,
        max_iterations: int = 200,
    ) -> Dict[str, Any]:
        """
        Train CRF on labelled sentence data.

        Args:
            train_sentences: List of token lists e.g. [["Rohit", "transferred", "50000"]]
            train_labels:    List of BIO tag lists  e.g. [["B-PERSON", "O", "B-AMOUNT"]]
            save_path:       Path to save trained model pickle.
            c1:              L1 regularisation coefficient.
            c2:              L2 regularisation coefficient.
            max_iterations:  Maximum LBFGS iterations.

        Returns:
            Dict with training summary (n_train, model_type, save_path).
        """
        if not _crfsuite_available:
            raise RuntimeError("sklearn-crfsuite is required for training. Run: pip3 install sklearn-crfsuite")

        logger.info("[CRF] Starting training on %d sentences...", len(train_sentences))

        X_train = [_sent2features(s) for s in train_sentences]
        y_train = [_sent2labels(l) for l in train_labels]

        crf = sklearn_crfsuite.CRF(
            algorithm="lbfgs",
            c1=c1,
            c2=c2,
            max_iterations=max_iterations,
            all_possible_transitions=True,
        )
        crf.fit(X_train, y_train)
        self.model = crf
        self.loaded = True

        result = {
            "n_train": len(train_sentences),
            "model_type": "sklearn_crfsuite.CRF",
            "classes": list(crf.classes_),
        }

        if save_path:
            sp = Path(save_path)
            sp.parent.mkdir(parents=True, exist_ok=True)
            with open(sp, "wb") as f:
                pickle.dump({"model": crf, "classes": list(crf.classes_)}, f)
            result["save_path"] = str(sp)
            logger.info("[CRF] Trained model saved to %s", sp)

        return result

    # ── Evaluate ─────────────────────────────────────────────────────────────

    def evaluate(
        self,
        test_sentences: List[List[str]],
        test_labels: List[List[str]],
    ) -> Dict[str, Any]:
        """
        Evaluate trained CRF on test data using seqeval-style classification report.

        Returns:
            Dict with per-class and macro F1, precision, recall.
        """
        if not self.loaded or not self.model:
            raise RuntimeError("Model must be loaded before evaluation.")

        X_test = [_sent2features(s) for s in test_sentences]
        y_pred = self.model.predict(X_test)
        y_true = test_labels

        try:
            from seqeval.metrics import classification_report, f1_score, precision_score, recall_score
            report = classification_report(y_true, y_pred, output_dict=True)
            return {
                "macro_f1": f1_score(y_true, y_pred, average="macro"),
                "macro_precision": precision_score(y_true, y_pred, average="macro"),
                "macro_recall": recall_score(y_true, y_pred, average="macro"),
                "per_class": report,
            }
        except ImportError:
            # Fallback: basic token accuracy
            correct = sum(
                p == t
                for pred_seq, true_seq in zip(y_pred, y_true)
                for p, t in zip(pred_seq, true_seq)
            )
            total = sum(len(s) for s in y_true)
            return {"token_accuracy": correct / total if total else 0.0}


# ── BIO decoder ──────────────────────────────────────────────────────────────

def _normalize_label(label: str) -> str:
    """Normalize BIO entity type labels to canonical names."""
    _MAP = {
        "PER": "PERSON",
        "PERSON": "PERSON",
        "GPE": "LOCATION",
        "LOC": "LOCATION",
        "LOCATION": "LOCATION",
        "ORG": "ORG",
        "ORGANIZATION": "ORG",
        "NORP": "ORG",
        "DATE": "DATE",
        "TIME": "DATE",
        "AMOUNT": "AMOUNT",
        "PHONE": "PHONE",
        "UPI": "UPI",
        "ACCOUNT": "ACCOUNT",
        "EMAIL": "EMAIL",
        "IP": "IP",
        "IFSC": "IFSC",
        "URL": "URL",
    }
    return _MAP.get(label, label)


def _decode_bio(
    tags: List[str],
    tokens_with_offsets: List[Tuple[str, int, int]],
    text: str,
) -> List[MLPrediction]:
    """Convert BIO tag sequence into entity span predictions."""
    predictions: List[MLPrediction] = []
    current_type = None
    current_start = -1
    current_end = -1

    for idx, (token, start, end) in enumerate(tokens_with_offsets):
        tag = tags[idx]

        if tag.startswith("B-"):
            # Flush previous entity
            if current_type:
                val = text[current_start:current_end].strip()
                if val and len(val) >= 2:
                    predictions.append(MLPrediction(
                        entity_type=_normalize_label(current_type),
                        raw_value=val,
                        canonical_value=val,
                        span_start=current_start,
                        span_end=current_end,
                        confidence=0.88,
                        model_name="crf",
                    ))
            current_type = tag[2:]
            current_start = start
            current_end = end

        elif tag.startswith("I-") and current_type and current_type == tag[2:]:
            current_end = end  # extend span

        else:
            if current_type:
                val = text[current_start:current_end].strip()
                if val and len(val) >= 2:
                    predictions.append(MLPrediction(
                        entity_type=_normalize_label(current_type),
                        raw_value=val,
                        canonical_value=val,
                        span_start=current_start,
                        span_end=current_end,
                        confidence=0.88,
                        model_name="crf",
                    ))
            current_type = None
            current_start = -1
            current_end = -1

    if current_type:
        val = text[current_start:current_end].strip()
        if val and len(val) >= 2:
            predictions.append(MLPrediction(
                entity_type=_normalize_label(current_type),
                raw_value=val,
                canonical_value=val,
                span_start=current_start,
                span_end=current_end,
                confidence=0.88,
                model_name="crf",
            ))

    return predictions


# ── Fallback heuristic CRF (when real model fails to unpickle) ───────────────

class _FallbackCRF:
    """Simple feature-rule CRF fallback — used only when checkpoint cannot be loaded."""

    def predict(self, X: List[List[Dict[str, Any]]]) -> List[List[str]]:
        tags_batch = []
        for feats in X:
            sent_tags = []
            for f in feats:
                word = f.get("word.lower()", "")
                istitle = f.get("word.istitle()", False)
                isupper = f.get("word.isupper()", False)
                has_at = f.get("word.has_at", False)
                has_digit = f.get("word.has_digit", False)
                length = f.get("word.len", 0)

                if has_at and not has_digit:
                    sent_tags.append("B-UPI")
                elif has_digit and length == 10:
                    sent_tags.append("B-PHONE")
                elif (
                    istitle
                    and not has_digit
                    and length >= 3
                    and word not in {
                        "the", "and", "for", "with", "from", "to", "in", "on", "at", "by",
                        "received", "sent", "confirmed", "conversation", "participants",
                        "participant", "communication", "network", "analysis", "message",
                        "messages", "transaction", "transactions", "evidence", "document",
                        "summary", "details", "status", "unknown", "system", "bank",
                        "field", "value", "platform", "android", "observed", "record",
                        "records", "timestamp", "activity", "outgoing", "incoming",
                        "application", "extraction", "integrity", "method", "custody",
                        "examiner", "tooling", "device", "reference",
                    }
                ):
                    sent_tags.append("B-PERSON")
                elif isupper and length >= 3 and not has_digit:
                    sent_tags.append("B-ORG")
                else:
                    sent_tags.append("O")
            tags_batch.append(sent_tags)
        return tags_batch


def _build_fallback_crf() -> _FallbackCRF:
    return _FallbackCRF()
