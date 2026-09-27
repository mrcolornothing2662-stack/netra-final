"""
CyberDrishti × ArmorIQ — Autonomous Agent API Routes

Endpoints:
  POST /api/v1/agent/{case_id}/run          Start autonomous investigation
  GET  /api/v1/agent/{case_id}/status       Agent status + action timeline
  GET  /api/v1/agent/{case_id}/actions      All agent actions with ArmorIQ state
  POST /api/v1/agent/holds/{hold_id}/approve Human approves a blocked action
  POST /api/v1/agent/holds/{hold_id}/reject  Human rejects a blocked action
  GET  /api/v1/agent/holds                  All pending holds (cross-case)
  GET  /api/v1/agent/{case_id}/audit-trail  ArmorIQ-enhanced audit trail
  GET  /api/v1/agent/sandbox/rules          Sandbox firewall rules (for demo)
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import AgentAction, AgentHold, AgentSession, AuditLog, User
from db.session import get_db
from routes.auth import get_current_user, require_role
from routes.case_access import require_case_access

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory agent registry (session_id → agent instance)
# For production: replace with Redis/DB-backed agent state
_active_agents: dict = {}


# ── Schemas ───────────────────────────────────────────────────────────────────

class HoldDecision(BaseModel):
    reason: Optional[str] = "Human authorized"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/{case_id}/run")
async def run_autonomous_investigation(
    case_id:          str,
    background_tasks: BackgroundTasks,
    db:               AsyncSession = Depends(get_db),
    current:          User = Depends(require_role("io", "fiu_analyst", "admin")),
):
    """
    Launch an autonomous investigation for the given case.
    The agent runs in the background; poll /status for progress.
    Returns immediately with the session_id.

    The case is resolved and access-checked BEFORE the agent is created, so an
    unknown/inaccessible case returns 404 and no investigation is launched.
    """
    # Resolve + authorize the case first — never launch an agent for a case that
    # cannot be loaded. This is the route-level half of the agent's hard stop.
    case = await require_case_access(db, current, case_id, write=True)
    canonical_case_id = str(case.id)

    from armoriq.sandbox import ensure_sandbox_rules
    await ensure_sandbox_rules(db)

    from armoriq.agent import AutonomousInvestigationAgent

    agent = AutonomousInvestigationAgent(
        case_id=canonical_case_id,
        triggered_by=current.username,
        db=db,
    )

    session_id = agent.session_id
    _active_agents[session_id] = agent

    # Run the investigation in the background
    background_tasks.add_task(_run_agent_background, agent, session_id)

    return {
        "session_id": session_id,
        "case_id": canonical_case_id,
        "case_number": case.case_number,
        "status": "investigating",
        "message": "Autonomous investigation started. Poll /status for progress.",
        "poll_url": f"/api/v1/agent/{canonical_case_id}/status?session_id={session_id}",
    }


async def _run_agent_background(agent, session_id: str):
    """Background task wrapper for agent.run()"""
    from db.session import db_context
    try:
        async with db_context() as session:
            agent.db = session
            result = await agent.run()
            status = (result or {}).get("status", getattr(agent, "status", "unknown"))
            logger.info(f"[Agent] Session {session_id} state: {status}")
    except Exception as exc:
        logger.error(f"[Agent] Session {session_id} error: {exc}")


@router.get("/{case_id}/status")
async def get_agent_status(
    case_id:    str,
    session_id: Optional[str] = None,
    db:         AsyncSession = Depends(get_db),
    current:    User = Depends(get_current_user),
):
    """
    Get current agent status, action timeline, and pending holds.
    If session_id is provided, return that specific session.
    Otherwise return the most recent session for the case.
    """
    case = await require_case_access(db, current, case_id)
    canonical_case_id = str(case.id)

    # Try in-memory first (live agent)
    if session_id and session_id in _active_agents:
        agent = _active_agents[session_id]
        return {
            "session_id": agent.session_id,
            "case_id": canonical_case_id,
            "status": agent.status,
            "actions": agent.actions,
            "pending_hold": agent.pending_hold,
            "action_count": len(agent.actions),
            "case_snapshot": getattr(agent, "case_snapshot", {}),
            "investigation_plan": getattr(agent, "investigation_plan", []),
            "final_report": getattr(agent, "final_report", None),
        }

    # Fall back to DB
    query = (
        select(AgentSession)
        .where(AgentSession.case_id == case.id)
        .order_by(AgentSession.started_at.desc())
        .limit(1)
    )
    if session_id:
        query = select(AgentSession).where(AgentSession.id == session_id)

    result = await db.execute(query)
    session = result.scalar_one_or_none()

    if not session:
        return {
            "session_id": None,
            "case_id": canonical_case_id,
            "status": "idle",
            "actions": [],
            "pending_hold": None,
            "message": "No investigation session found for this case.",
        }

    # Get pending hold if any
    hold_result = await db.execute(
        select(AgentHold)
        .where(
            AgentHold.session_id == session.id,
            AgentHold.status == "awaiting_approval",
        )
        .limit(1)
    )
    hold = hold_result.scalar_one_or_none()
    hold_dict = None
    if hold:
        hold_dict = {
            "hold_id": hold.id,
            "action": hold.action,
            "description": hold.description,
            "ai_reasoning": hold.ai_reasoning,
            "authorization_boundary": hold.authorization_boundary,
            "risk_level": hold.risk_level,
            "affected_resource": hold.affected_resource_json,
            "armoriq_reason": hold.armoriq_reason,
            "governance_outcome": "blocked_by_design",
            "status": hold.status,
            "requested_at": hold.created_at.isoformat() if hold.created_at else None,
        }

    actions = session.actions_json or []
    # Reconstruct the plan/snapshot/report from the persisted action ledger so
    # the UI keeps them after the in-memory agent session ends.
    plan_entry = next(
        (a for a in actions if a.get("action_type") == "INVESTIGATION_PLAN" and a.get("details")),
        None,
    )
    summary_entry = next(
        (a for a in actions if a.get("action_type") == "INVESTIGATION_SUMMARY" and a.get("details")),
        None,
    )

    return {
        "session_id": session.id,
        "case_id": canonical_case_id,
        "status": session.status,
        "actions": actions,
        "pending_hold": hold_dict,
        "action_count": len(actions),
        "case_snapshot": (plan_entry or {}).get("details", {}).get("case_snapshot", {}) if plan_entry else {},
        "investigation_plan": (plan_entry or {}).get("details", {}).get("plan", []) if plan_entry else [],
        "final_report": summary_entry.get("details") if summary_entry else None,
        "started_at": session.started_at.isoformat() if session.started_at else None,
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


@router.get("/{case_id}/actions")
async def list_agent_actions(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """List all agent actions for a case with ArmorIQ enforcement states."""
    case = await require_case_access(db, current, case_id)
    result = await db.execute(
        select(AgentAction)
        .where(AgentAction.case_id == case.id)
        .order_by(AgentAction.created_at.asc())
    )
    actions = result.scalars().all()

    return {
        "case_id": str(case.id),
        "actions": [
            {
                "id": a.id,
                "action_type": a.action_type,
                "description": a.description,
                "status": a.status,
                "details": a.details_json,
                "timestamp": a.created_at.isoformat() if a.created_at else None,
            }
            for a in actions
        ],
        "total": len(actions),
        "executed": sum(1 for a in actions if a.status == "executed"),
        "blocked": sum(1 for a in actions if a.status == "blocked"),
        "approved": sum(1 for a in actions if a.status == "approved"),
        "rejected": sum(1 for a in actions if a.status == "rejected"),
    }


@router.post("/holds/{hold_id}/approve")
async def approve_hold(
    hold_id:  str,
    body:     HoldDecision = HoldDecision(),
    db:       AsyncSession = Depends(get_db),
    current:  User = Depends(require_role("io", "fiu_analyst", "admin")),
):
    """
    Human approves a blocked action.
    The action executes and the investigation continues.
    """
    # Find the session with this hold
    hold_result = await db.execute(
        select(AgentHold).where(AgentHold.id == hold_id)
    )
    hold_row = hold_result.scalar_one_or_none()
    if not hold_row:
        raise HTTPException(404, f"Hold {hold_id} not found")
    if hold_row.status != "awaiting_approval":
        raise HTTPException(400, f"Hold {hold_id} is already {hold_row.status}")

    session_id = hold_row.session_id

    # Try live agent first
    if session_id in _active_agents:
        agent = _active_agents[session_id]
        result = await agent.approve_hold(approved_by=current.username)

        # Update hold in DB
        await db.execute(
            text("""
                UPDATE agent_holds
                SET status = 'approved', approved_by = :approved_by, resolved_at = :resolved_at
                WHERE id = :hold_id
            """),
            {"hold_id": hold_id, "approved_by": current.username, "resolved_at": datetime.now(timezone.utc)}
        )
        await db.commit()
        return result

    # No live agent — update DB and return confirmation
    await db.execute(
        text("""
            UPDATE agent_holds
            SET status = 'approved', approved_by = :approved_by, resolved_at = :resolved_at
            WHERE id = :hold_id
        """),
        {"hold_id": hold_id, "approved_by": current.username, "resolved_at": datetime.now(timezone.utc)}
    )
    await db.commit()

    return {
        "hold_id": hold_id,
        "status": "approved",
        "approved_by": current.username,
        "message": (
            "Hold approved. Action has been authorized. "
            "Note: Live agent session has ended; the action record has been approved in the audit trail."
        ),
    }


@router.post("/holds/{hold_id}/reject")
async def reject_hold(
    hold_id:  str,
    body:     HoldDecision = HoldDecision(),
    db:       AsyncSession = Depends(get_db),
    current:  User = Depends(require_role("io", "fiu_analyst", "admin")),
):
    """
    Human rejects a blocked action.
    The investigation completes without the blocked action.
    """
    hold_result = await db.execute(
        select(AgentHold).where(AgentHold.id == hold_id)
    )
    hold_row = hold_result.scalar_one_or_none()
    if not hold_row:
        raise HTTPException(404, f"Hold {hold_id} not found")
    if hold_row.status != "awaiting_approval":
        raise HTTPException(400, f"Hold {hold_id} is already {hold_row.status}")

    session_id = hold_row.session_id

    if session_id in _active_agents:
        agent = _active_agents[session_id]
        result = await agent.reject_hold(
            rejected_by=current.username,
            reason=body.reason or "Rejected by human reviewer",
        )

    await db.execute(
        text("""
            UPDATE agent_holds
            SET status = 'rejected',
                rejected_by = :rejected_by,
                rejection_reason = :reason,
                resolved_at = :resolved_at
            WHERE id = :hold_id
        """),
        {
            "hold_id": hold_id,
            "rejected_by": current.username,
            "reason": body.reason or "Rejected by human reviewer",
            "resolved_at": datetime.now(timezone.utc),
        }
    )
    await db.commit()

    return {
        "hold_id": hold_id,
        "status": "rejected",
        "rejected_by": current.username,
        "reason": body.reason,
        "message": "Action rejected. Investigation will complete without this action.",
    }


@router.get("/holds")
async def list_pending_holds(
    db: AsyncSession = Depends(get_db),
    _:  User = Depends(get_current_user),
):
    """List all holds awaiting human approval (across all cases)."""
    result = await db.execute(
        select(AgentHold)
        .where(AgentHold.status == "awaiting_approval")
        .order_by(AgentHold.created_at.desc())
    )
    holds = result.scalars().all()

    return {
        "pending_holds": [
            {
                "hold_id": h.id,
                "case_id": str(h.case_id),
                "action": h.action,
                "description": h.description,
                "ai_reasoning": h.ai_reasoning,
                "authorization_boundary": h.authorization_boundary,
                "risk_level": h.risk_level,
                "affected_resource": h.affected_resource_json,
                "governance_outcome": "blocked_by_design",
                "requested_at": h.created_at.isoformat() if h.created_at else None,
            }
            for h in holds
        ],
        "total": len(holds),
    }


@router.get("/{case_id}/audit-trail")
async def get_armoriq_audit_trail(
    case_id: str,
    db:      AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Return the complete ArmorIQ-enhanced audit trail for a case.
    Includes both agent actions and the SHA-256 chain entries.
    """
    case = await require_case_access(db, current, case_id)
    canonical_case_id = str(case.id)

    # Agent actions (case_id is a UUID column — coerce; resource_id below is Text)
    actions_result = await db.execute(
        select(AgentAction)
        .where(AgentAction.case_id == case.id)
        .order_by(AgentAction.created_at.asc())
    )
    actions = actions_result.scalars().all()

    # ArmorIQ entries from the SHA-256 audit chain
    chain_result = await db.execute(
        select(AuditLog)
        .where(
            AuditLog.resource_id == canonical_case_id,
            AuditLog.action.like("ARMORIQ_%"),
        )
        .order_by(AuditLog.id.asc())
    )
    chain_entries = chain_result.scalars().all()

    return {
        "case_id": canonical_case_id,
        "agent_actions": [
            {
                "id": a.id,
                "action_type": a.action_type,
                "description": a.description,
                "status": a.status,
                "details": a.details_json,
                "timestamp": a.created_at.isoformat() if a.created_at else None,
                "source": "agent_runtime",
            }
            for a in actions
        ],
        "sha256_chain_entries": [
            {
                "id": e.id,
                "action": e.action,
                "entry_hash": e.entry_hash,
                "prev_hash": e.prev_hash,
                "details": e.details_json,
                "timestamp": e.event_timestamp.isoformat() if e.event_timestamp else None,
                "source": "sha256_chain",
            }
            for e in chain_entries
        ],
        "totals": {
            "agent_actions": len(actions),
            "sha256_chain_entries": len(chain_entries),
            "executed": sum(1 for a in actions if a.status == "executed"),
            "blocked": sum(1 for a in actions if a.status == "blocked"),
            "approved": sum(1 for a in actions if a.status == "approved"),
            "rejected": sum(1 for a in actions if a.status == "rejected"),
        },
    }


@router.get("/sandbox/rules")
async def get_sandbox_rules(
    db: AsyncSession = Depends(get_db),
    _:  User = Depends(get_current_user),
):
    """Return sandbox firewall rules (for demo / UI display)."""
    from armoriq.sandbox import ensure_sandbox_rules
    await ensure_sandbox_rules(db)

    result = await db.execute(
        text("SELECT * FROM sandbox_firewall_rules ORDER BY priority ASC")
    )
    rows = result.fetchall()
    return {
        "rules": [dict(row._mapping) for row in rows],
        "note": "These are sandboxed test resources. No real infrastructure is affected.",
    }
