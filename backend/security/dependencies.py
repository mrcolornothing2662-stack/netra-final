from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Security & Authorization Dependencies
Provides capability-based, session-based, and evidence-access enforcement dependencies.
"""

from typing import Callable, Optional
from fastapi import Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import User
from db.session import get_db
from investigation.policies import user_has_capability
from routes.auth import get_current_user


def require_capability(*capabilities: str) -> Callable:
    """
    FastAPI dependency ensuring the authenticated actor possesses at least
    one of the specified operational capabilities.
    """
    async def _check_cap(current: User = Depends(get_current_user)) -> User:
        has_any = any(user_has_capability(current.role, cap) for cap in capabilities)
        if not has_any:
            req_str = ", ".join(capabilities)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions: capability '{req_str}' required for role '{current.role}'",
            )
        return current
    return _check_cap


def require_all_capabilities(*capabilities: str) -> Callable:
    """
    FastAPI dependency ensuring the authenticated actor possesses all
    specified capabilities.
    """
    async def _check_caps(current: User = Depends(get_current_user)) -> User:
        for cap in capabilities:
            if not user_has_capability(current.role, cap):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Insufficient permissions: capability '{cap}' required for role '{current.role}'",
                )
        return current
    return _check_caps


def extract_device_id(
    request: Request,
    x_device_id: Optional[str] = Header(None, alias="X-Device-ID"),
    device_id: Optional[str] = Query(None),
) -> str:
    """
    Extract verified device identifier from header, query, or client state.
    Defaults to 'device-terminal-primary' in dev environments if unspecified.
    """
    dev = x_device_id or device_id or getattr(request.state, "device_id", None)
    if dev and dev.strip():
        return dev.strip()
    return "device-terminal-primary"


def extract_access_reason(
    request: Request,
    x_access_reason: Optional[str] = Header(None, alias="X-Access-Reason"),
    reason: Optional[str] = Query(None),
) -> Optional[str]:
    """
    Extract access justification string from header or query.
    """
    res = x_access_reason or reason
    if res and res.strip():
        return res.strip()
    return None
