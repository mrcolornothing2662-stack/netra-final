"""
CyberDrishti × ArmorIQ — SDK Client Wrapper

Uses the verified ArmorIQ SDK API:
  pip install armoriq-sdk

Real API surface (from docs.armoriq.ai):
  - ArmorIQClient(api_key=...)                  → client
  - client.capture_plan(llm, prompt, plan)      → PlanCapture
  - client.get_intent_token(plan_capture, policy, validity_seconds) → IntentToken
  - client.invoke(mcp, action, intent_token, params) → MCPInvocationResult
  - IntentMismatchException  → raised when action not in declared plan
  - PolicyBlockedException   → raised when policy blocks the action

The boundary enforcement is REAL:
  - Authorized actions are listed in the plan passed to capture_plan()
  - ArmorIQ's cryptographic Merkle-proof verifies each invoke() call
  - Any action NOT in the declared plan raises IntentMismatchException
  - We catch this and record it as a BLOCKED hold awaiting human approval
"""
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ── Try to import the real SDK; fall back to a local stub if not installed ────

try:
    from armoriq_sdk import ArmorIQClient as _RealArmorIQClient          # type: ignore
    from armoriq_sdk import IntentMismatchException, PolicyBlockedException  # type: ignore
    _SDK_AVAILABLE = True
    logger.info("[ArmorIQ] Real armoriq-sdk loaded successfully.")
except ImportError:
    _SDK_AVAILABLE = False
    _RealArmorIQClient = None
    IntentMismatchException = None
    PolicyBlockedException = None
    logger.warning(
        "[ArmorIQ] armoriq-sdk not installed. "
        "Run: pip install armoriq-sdk  "
        "Falling back to local enforcement stub for development."
    )


# ── Local stub (development / demo without a live ArmorIQ account) ────────────

class StubIntentMismatch(Exception):
    """Raised by the local stub when an action was not declared in the plan.

    This must be a *dedicated* type. Returning base `Exception` from
    `get_intent_mismatch_exception()` previously made the agent treat every
    tool failure as a fabricated "ArmorIQ governance block".
    """


class StubPolicyBlocked(Exception):
    """Raised by the local stub when a declared action is policy-blocked."""


class _LocalStubClient:
    """
    Minimal local stub that mimics ArmorIQ's authorization model without
    requiring a live API key.  Used ONLY when armoriq-sdk is not installed.

    Authorization logic: an action is AUTHORIZED if and only if its 'action'
    name appears in the declared plan steps.  This is NOT keyword filtering —
    it mirrors how ArmorIQ works: if the action wasn't in the signed plan it
    is blocked.
    """

    def __init__(self):
        self._plan_steps: dict[str, dict] = {}  # plan_hash → {action → step}
        self._plan_hashes: dict = {}

    def capture_plan(self, llm: str, prompt: str, plan: dict, metadata: dict = None):
        """Validate plan structure and store declared steps."""
        if "goal" not in plan:
            raise ValueError("plan.goal is required")
        if "steps" not in plan or not plan["steps"]:
            raise ValueError("plan.steps is required and must be non-empty")
        for step in plan["steps"]:
            if "action" not in step or "mcp" not in step:
                raise ValueError("Each step requires 'action' and 'mcp'")

        # Build a simple hash from the declared action names
        import hashlib, json
        canonical = json.dumps(
            {"goal": plan["goal"], "steps": [s["action"] for s in plan["steps"]]},
            sort_keys=True
        )
        plan_hash = hashlib.sha256(canonical.encode()).hexdigest()

        # Index by plan_hash
        self._plan_steps[plan_hash] = {
            step["action"]: step for step in plan["steps"]
        }

        class _PlanCapture:
            pass

        pc = _PlanCapture()
        pc.plan = plan
        pc.llm = llm
        pc.prompt = prompt
        pc.metadata = metadata or {}
        pc._plan_hash = plan_hash
        return pc

    def get_intent_token(self, plan_capture, policy: dict = None, validity_seconds: float = 3600.0):
        """Return a stub token that references the plan hash. Explicitly labelled simulated."""
        import time
        return {
            "success": True,
            "simulated": True,  # NOT a real Ed25519/Merkle-signed ArmorIQ token
            "token": f"SIMULATED_stub_token_{plan_capture._plan_hash[:16]}",
            "plan_hash": plan_capture._plan_hash,
            "merkle_root": f"SIMULATED_merkle_{plan_capture._plan_hash[:16]}",
            "expires_at": int(time.time()) + int(validity_seconds),
            "issued_at": int(time.time()),
            "_plan_hash": plan_capture._plan_hash,  # internal
        }

    def invoke(self, mcp: str, action: str, intent_token, params: dict = None):
        """
        Check whether 'action' was declared in the plan.
        If not → raise a stub IntentMismatchException.
        If yes → return a simulated success result.
        """
        plan_hash = (
            intent_token.get("_plan_hash") if isinstance(intent_token, dict)
            else getattr(intent_token, "_plan_hash", None)
        )
        declared = self._plan_steps.get(plan_hash, {})

        if action not in declared:
            # Action not in declared plan → blocked, exactly like ArmorIQ
            raise StubIntentMismatch(
                f"IntentMismatchException: action '{action}' on MCP '{mcp}' "
                f"was not declared in the authorization plan. "
                f"Declared actions: {list(declared.keys())}"
            )

        # Authorized — return a result explicitly labelled as simulated. This is
        # the local stub, not a real ArmorIQ invocation; callers/audit must not
        # record this as a cryptographically verified action.
        return {
            "success": True,
            "simulated": True,
            "data": {"stub": True, "simulated": True, "action": action, "mcp": mcp, "params": params},
            "error": None,
            "execution_time_ms": 0,
            "mcp": mcp,
            "action": action,
        }


# ── Public client factory ─────────────────────────────────────────────────────

def get_armoriq_client():
    """
    Return an ArmorIQ client.
    Uses the real SDK if installed + ARMORIQ_API_KEY is set.
    Falls back to the local stub for development.
    """
    api_key = os.environ.get("ARMORIQ_API_KEY", "")

    if _SDK_AVAILABLE and api_key:
        logger.info("[ArmorIQ] Using real ArmorIQ SDK with live API key.")
        return _RealArmorIQClient(api_key=api_key)
    else:
        if _SDK_AVAILABLE and not api_key:
            logger.warning(
                "[ArmorIQ] armoriq-sdk installed but ARMORIQ_API_KEY not set. "
                "Using local stub."
            )
        return _LocalStubClient()


def get_intent_mismatch_exception(client=None):
    """Return the exception class raised when an action is outside the plan.

    This must match the *active* client. When the local stub is in use it raises
    ``StubIntentMismatch``; when the real SDK client is active it raises
    ArmorIQ's ``IntentMismatchException``. Never return the base ``Exception`` —
    that would swallow ordinary tool errors and mislabel them as governance
    blocks.
    """
    active = client if client is not None else armoriq()
    if isinstance(active, _LocalStubClient):
        return StubIntentMismatch
    if _SDK_AVAILABLE and IntentMismatchException is not None:
        return IntentMismatchException
    return StubIntentMismatch


def get_policy_blocked_exception(client=None):
    """Return the exception class raised when a declared action is policy-blocked."""
    active = client if client is not None else armoriq()
    if isinstance(active, _LocalStubClient):
        return StubPolicyBlocked
    if _SDK_AVAILABLE and PolicyBlockedException is not None:
        return PolicyBlockedException
    return StubPolicyBlocked


# ── Singleton ────────────────────────────────────────────────────────────────

_client_singleton = None


def armoriq():
    """Return the singleton ArmorIQ client."""
    global _client_singleton
    if _client_singleton is None:
        _client_singleton = get_armoriq_client()
    return _client_singleton
