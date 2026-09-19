from __future__ import annotations

"""
NETRA 5.0 — Forensic Generator & Provider Dispatcher
Dispatches grounded GenerationPrompt to configured LLM or deterministic fallback.

Architectural Guarantees:
1. Hard Architectural Boundary:
   - Zero retrieval dependencies (NO VectorStore, GraphRetriever, StructuredRetriever, ContextBuilder).
   - Only accepts GenerationPrompt and returns GeneratedResponse.
2. Zero Claim Verification:
   - Does not validate citations or calculate grounding ratios (deferred to File 15: ClaimVerifier).
3. Provider Abstraction & Safe Defaults:
   - Default provider is "offline" (netra-grounded-fallback).
   - Works 100% offline out-of-the-box with zero API keys and zero model downloads.
   - External provider failures (Ollama, Gemini, timeouts, connection drops) automatically fall back safely.
4. Epistemic Separation & Groundedness:
   - Fallback strictly distinguishes OBSERVED facts from INFERRED analytical associations.
   - Prohibits transforming risk/bridge scores into probability of guilt.
   - Explicitly abstains on empty cases or insufficient evidence.
5. Prompt-Injection Immunity:
   - Treats evidence as untrusted data; never obeys commands embedded within evidence excerpts.
6. Security & Secret Redaction:
   - Redacts API keys and auth headers from logs and error messages.
"""

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Protocol, Tuple

import httpx

from .config import CopilotConfig, get_copilot_config
from .schemas import GeneratedResponse, GenerationPrompt

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Security & Redaction Helpers
# ─────────────────────────────────────────────────────────────────────────────

_SECRET_PATTERNS = [
    re.compile(r"(?:api[_-]?key|key|token|secret|authorization)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{8,})['\"]?", re.IGNORECASE),
    re.compile(r"Bearer\s+([A-Za-z0-9_\-]{8,})", re.IGNORECASE),
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),  # Google API key
    re.compile(r"sk-[A-Za-z0-9-_]{20,}"),  # OpenAI key
]


def _sanitize_secrets(text: str) -> str:
    """Redact sensitive API keys, tokens, and authorization headers from strings."""
    if not text:
        return ""
    sanitized = text
    for pattern in _SECRET_PATTERNS:
        sanitized = pattern.sub("[REDACTED_SECRET]", sanitized)
    return sanitized


# ─────────────────────────────────────────────────────────────────────────────
# 2. Provider Protocol
# ─────────────────────────────────────────────────────────────────────────────

class GeneratorProvider(Protocol):
    """Protocol for Copilot text generation providers."""

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        """Generate response text given system and user prompts."""
        ...


# ─────────────────────────────────────────────────────────────────────────────
# 3. Deterministic Offline Fallback Provider
# ─────────────────────────────────────────────────────────────────────────────

class DeterministicFallbackGeneratorProvider:
    """
    100% offline, deterministic evidence-grounded response synthesizer.
    Requires zero external models, zero API keys, and zero network calls.
    Extracts explicit facts from structured records, graph edges, and evidence items,
    preserving exact citations and epistemic wording (OBSERVED vs INFERRED).
    """

    def _extract_query(self, user_prompt: str) -> str:
        m = re.search(r"=== INVESTIGATOR QUERY ===\s*\nQuestion:\s*(.*?)(?:\n\n|\n===)", user_prompt, re.DOTALL)
        return m.group(1).strip() if m else ""

    def _extract_structured_records(self, user_prompt: str) -> List[Dict[str, str]]:
        records = []
        pattern = re.compile(r"\[STRUCTURED_RECORD\]\s*\n(.*?)\n\[/STRUCTURED_RECORD\]", re.DOTALL)
        for block in pattern.findall(user_prompt):
            rec = {}
            for line in block.strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    rec[k.strip().lower()] = v.strip()
            records.append(rec)
        return records

    def _extract_graph_relationships(self, user_prompt: str) -> List[Dict[str, str]]:
        edges = []
        pattern = re.compile(r"\[GRAPH_RELATIONSHIP\]\s*\n(.*?)\n\[/GRAPH_RELATIONSHIP\]", re.DOTALL)
        for block in pattern.findall(user_prompt):
            edge = {}
            for line in block.strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    edge[k.strip().lower()] = v.strip()
            edges.append(edge)
        return edges

    def _extract_evidence_items(self, user_prompt: str) -> List[Dict[str, str]]:
        items = []
        pattern = re.compile(r"\[EVIDENCE_ITEM\]\s*\n(.*?)\n\[/EVIDENCE_ITEM\]", re.DOTALL)
        for block in pattern.findall(user_prompt):
            it = {}
            header_part, _, content_part = block.partition("content:\n")
            for line in header_part.strip().split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    it[k.strip().lower()] = v.strip()
            it["content"] = content_part.strip()
            items.append(it)
        return items

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        # 1. Empty Case Handling
        if "[EMPTY CASE NOTICE]" in user_prompt or "is_empty_case=True" in user_prompt:
            return (
                "The seized case file contains no evidence files, events, or corroborated records. "
                "Based strictly on the available case context, there is insufficient evidence to answer this inquiry.\n\n"
                "The supplied evidence does not establish any facts regarding this query."
            )

        query = self._extract_query(user_prompt)
        query_lower = query.lower()

        records = self._extract_structured_records(user_prompt)
        edges = self._extract_graph_relationships(user_prompt)
        items = self._extract_evidence_items(user_prompt)

        # 2. Amount / Transaction Inquiry
        amount_query = any(kw in query_lower for kw in ("amount", "transferred", "transfer", "paid", "rupees", "inr", "₹", "txn"))
        if amount_query:
            matching_rec = None
            for rec in records:
                summary = rec.get("summary", "")
                if ("amount" in summary.lower() or "₹" in summary or "inr" in summary.lower() or "transferred" in summary.lower()):
                    matching_rec = rec
                    break

            matching_item = None
            if not matching_rec and items:
                for it in items:
                    c = it.get("content", "")
                    if any(k in c.lower() for k in ("amount", "₹", "inr", "transferred")):
                        matching_item = it
                        break

            if matching_rec:
                summary = matching_rec.get("summary", "")
                src = matching_rec.get("source", "Evidence Record")
                cite_src = src.split("(")[0].strip()
                page_match = re.search(r"page=([^\s,\)]+)", src)
                page_str = f", page {page_match.group(1)}" if page_match else ""
                line_match = re.search(r"line=([^\s,\)]+)", src)
                line_str = f", line {line_match.group(1)}" if (line_match and not page_str) else ""

                amt_match = re.search(r"(?:₹|Rs\.?|INR)\s?([0-9][\d,]*(?:\.\d{1,2})?)", summary, re.IGNORECASE)
                amt_text = f"an amount of ₹{amt_match.group(1)}" if amt_match else "a recorded transfer"

                acc_match = re.search(r"(ACC-[0-9A-Za-z_\-]+)", summary)
                acc_text = f" associated with {acc_match.group(1)}" if acc_match else ""

                to_match = re.search(r"To:\s*([^\s\|]+)", summary)
                to_text = f" transferred to {to_match.group(1)}" if to_match else ""

                return (
                    f"Based on the supplied case evidence, the transaction record shows {amt_text}{acc_text}{to_text}.\n\n"
                    f"[Evidence: {cite_src}{page_str}{line_str}]\n\n"
                    f"The supplied evidence does not establish any additional conclusion beyond this recorded transaction."
                )

            if matching_item:
                content = matching_item.get("content", "")
                amt_match = re.search(r"(?:₹|Rs\.?|INR)\s?([0-9][\d,]*(?:\.\d{1,2})?)", content, re.IGNORECASE)
                amt_text = f"an amount of ₹{amt_match.group(1)}" if amt_match else "a recorded transfer"
                acc_match = re.search(r"(ACC-[0-9A-Za-z_\-]+)", content)
                acc_text = f" associated with {acc_match.group(1)}" if acc_match else ""
                s_file = matching_item.get("source_file", "evidence_document.pdf").split("(")[0].strip()
                return (
                    f"Based on the supplied case evidence, the transaction record shows {amt_text}{acc_text}.\n\n"
                    f"[Evidence: {s_file}]\n\n"
                    f"The supplied evidence does not establish any additional conclusion beyond this recorded transaction."
                )

            # An amount query with no amount/transaction evidence must abstain, avoiding hallucination
            return (
                "Based on the supplied case evidence, there are no recorded transactions or transfer amounts "
                "matching the specified query.\n\n"
                "The supplied evidence does not establish any transfer amount regarding this inquiry."
            )

        # 3. Relational Inquiry
        relational_query = any(kw in query_lower for kw in ("relationship", "relationships", "connect", "connected", "connects", "link", "between"))
        if relational_query:
            if edges:
                lines = ["Based on the case evidence and investigative graph, the following relationships are established:"]
                for edge in edges[:5]:
                    src = edge.get("source", "Unknown")
                    tgt = edge.get("target", "Unknown")
                    rel = edge.get("relationship", "ASSOCIATED_WITH")
                    status = edge.get("epistemic_status", "OBSERVED").upper()
                    conf = edge.get("confidence", "1.00")

                    if status == "INFERRED":
                        lines.append(f"- NETRA inferred an analytical association: {src} -> {rel} -> {tgt} (confidence={conf}).")
                    else:
                        lines.append(f"- The evidence records an observed relationship: {src} -> {rel} -> {tgt}.")

                lines.append("")
                if items:
                    primary_item = items[0]
                    s_file = primary_item.get("source_file", "Case Graph")
                    cite_file = s_file.split("(")[0].strip()
                    lines.append(f"[Evidence: {cite_file}]")
                elif records:
                    s_file = records[0].get("source", "Case Graph").split("(")[0].strip()
                    lines.append(f"[Evidence: {s_file}]")

                lines.append("\nThe supplied evidence does not establish any additional direct relationship beyond these recorded entries.")
                return "\n".join(lines)
            else:
                return (
                    "Based on the supplied case evidence and investigative graph, there are no recorded "
                    "relationships connecting the entities in this query.\n\n"
                    "The supplied evidence does not establish any direct or inferred relationship."
                )

        # 4. General Grounded Evidence Response
        if items:
            top_item = items[0]
            content = top_item.get("content", "").strip()
            # Clean content snippet
            snippet = content[:200] + ("..." if len(content) > 200 else "")
            s_file = top_item.get("source_file", "seized_evidence.pdf")
            cite_file = s_file.split("(")[0].strip()
            loc_match = re.search(r"\((.*?)\)", s_file)
            loc_str = f", {loc_match.group(1)}" if (loc_match and "N/A" not in loc_match.group(1)) else ""

            ep_status = top_item.get("epistemic_status", "OBSERVED").upper()
            ep_prefix = "The evidence records the following excerpt:" if ep_status == "OBSERVED" else "NETRA analytical records indicate the following excerpt:"

            return (
                f"Based on the seized case evidence, {ep_prefix} \"{snippet}\"\n\n"
                f"[Evidence: {cite_file}{loc_str}]\n\n"
                f"The supplied evidence does not establish any additional facts regarding this query."
            )

        if records:
            top_rec = records[0]
            summary = top_rec.get("summary", "")
            src = top_rec.get("source", "Database Record").split("(")[0].strip()
            return (
                f"Based on the supplied case evidence, the record indicates: {summary}\n\n"
                f"[Evidence: {src}]\n\n"
                f"The supplied evidence does not establish any additional conclusions."
            )

        # 5. Abstention
        return (
            f"The seized case evidence contains insufficient records to determine {query or 'this inquiry'}. "
            f"No corroborating records were found in the provided evidence."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. Remote Providers (Ollama & Gemini)
# ─────────────────────────────────────────────────────────────────────────────

class OllamaGeneratorProvider:
    """Local Ollama model provider via HTTP API."""

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "llama3.2:1b",
        timeout_seconds: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout_seconds

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": user_prompt,
            "system": system_prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama returned HTTP status {resp.status_code}: {resp.text[:200]}")
            data = resp.json()
            response_text = data.get("response", "").strip()
            if not response_text:
                raise ValueError("Ollama returned empty response string")
            return response_text


class GeminiGeneratorProvider:
    """Cloud Google Gemini provider with credential redaction."""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        timeout_seconds: float = 30.0,
    ):
        self.api_key = api_key
        self.model = model
        self.timeout = timeout_seconds

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 2000,
    ) -> str:
        # Clean model name if prefixed
        model_name = self.model.replace("models/", "")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={self.api_key}"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        headers = {"Content-Type": "application/json"}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                sanitized_msg = _sanitize_secrets(resp.text[:200])
                raise RuntimeError(f"Gemini API error (status {resp.status_code}): {sanitized_msg}")
            data = resp.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise ValueError("Gemini returned zero candidates")
            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts or "text" not in parts[0]:
                raise ValueError("Gemini response missing text parts")
            return parts[0]["text"].strip()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Core Generator Dispatcher
# ─────────────────────────────────────────────────────────────────────────────

class Generator:
    """
    Forensic Generator Dispatcher.
    Dispatches GenerationPrompt to configured provider with deterministic fallback on failure.
    Enforces strict isolation from retrieval layers.
    """

    def __init__(
        self,
        config: Optional[CopilotConfig] = None,
        provider: Optional[GeneratorProvider] = None,
        fallback_provider: Optional[GeneratorProvider] = None,
    ):
        self.config = config or get_copilot_config()
        self.fallback_provider = fallback_provider or DeterministicFallbackGeneratorProvider()

        if provider is not None:
            self.provider = provider
        else:
            self.provider = self._init_provider()

    def _init_provider(self) -> GeneratorProvider:
        """Initialize provider based on CopilotConfig; defaults to offline fallback."""
        provider_name = (self.config.llm_provider or "offline").lower()

        if provider_name == "ollama":
            return OllamaGeneratorProvider(
                base_url="http://localhost:11434",
                model=self.config.llm_model or "llama3.2:1b",
                timeout_seconds=self.config.generation_timeout_seconds,
            )
        elif provider_name == "gemini":
            from config import settings
            api_key = getattr(settings, "gemini_api_key", "") or ""
            if not api_key:
                logger.warning("Gemini provider configured but GEMINI_API_KEY is missing. Using deterministic fallback.")
                return self.fallback_provider
            return GeminiGeneratorProvider(
                api_key=api_key,
                model=self.config.llm_model or "gemini-1.5-flash",
                timeout_seconds=self.config.generation_timeout_seconds,
            )
        else:
            return self.fallback_provider

    async def generate(
        self,
        prompt: GenerationPrompt,
    ) -> GeneratedResponse:
        """
        Executes generation for the supplied GenerationPrompt.
        If the primary provider fails, gracefully falls back to the deterministic offline synthesizer.
        """
        start_time = time.perf_counter()
        configured_provider = self.config.llm_provider or "offline"
        active_provider_name = configured_provider
        model_name = self.config.llm_model or "netra-grounded-fallback"
        used_fallback = False

        # Route offline directly without trying network if provider is the fallback provider
        if self.provider is self.fallback_provider:
            text = await self.fallback_provider.generate(
                system_prompt=prompt.system_prompt,
                user_prompt=prompt.user_prompt,
                temperature=self.config.temperature,
                max_tokens=self.config.max_output_tokens,
            )
            used_fallback = False
            active_provider_name = "offline"
            model_name = "netra-grounded-fallback"
        else:
            try:
                text = await asyncio.wait_for(
                    self.provider.generate(
                        system_prompt=prompt.system_prompt,
                        user_prompt=prompt.user_prompt,
                        temperature=self.config.temperature,
                        max_tokens=self.config.max_output_tokens,
                    ),
                    timeout=self.config.generation_timeout_seconds,
                )
                if not text or not text.strip():
                    raise ValueError("Provider returned empty or whitespace response")
            except Exception as e:
                sanitized_err = _sanitize_secrets(str(e))
                logger.warning(
                    "LLM provider '%s' failed (%s); falling back to deterministic grounded fallback.",
                    configured_provider,
                    sanitized_err,
                )
                text = await self.fallback_provider.generate(
                    system_prompt=prompt.system_prompt,
                    user_prompt=prompt.user_prompt,
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_output_tokens,
                )
                used_fallback = True
                active_provider_name = "offline"
                model_name = "netra-grounded-fallback"

        latency_ms = round((time.perf_counter() - start_time) * 1000.0, 2)

        return GeneratedResponse(
            text=text,
            provider=active_provider_name,
            model=model_name,
            used_fallback=used_fallback,
            latency_ms=latency_ms,
        )
