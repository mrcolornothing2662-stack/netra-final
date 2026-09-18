"""
CyberDrishti AI — Authentication & RBAC Routes
"""
from __future__ import annotations

"""
CyberDrishti AI — Auth Routes (JWT login/logout, current user)
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Header, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import User
from db.session import get_db

import bcrypt

router = APIRouter()

oauth2    = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


# ── Schemas ───────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    expires_in:   int
    role:         str
    full_name:    str | None
    must_change_password: bool = False


class UserOut(BaseModel):
    id:        str
    username:  str
    email:     str
    full_name: str | None
    rank:      str | None
    unit:      str | None
    role:      str
    is_active: bool
    must_change_password: bool = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode('utf-8'), hashed.encode('utf-8'))
    except Exception:
        return False


def _hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')


def _create_token(user_id: str, role: str, must_change_password: bool = False) -> tuple[str, int]:
    expire    = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    expire_in = settings.access_token_expire_minutes * 60
    payload   = {"sub": user_id, "role": role, "exp": expire, "must_change_password": must_change_password}
    token     = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token, expire_in


async def get_current_user(
    token: str = Depends(oauth2),
    db: AsyncSession = Depends(get_db),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("sub")
        if not user_id:
            raise cred_exc
        
        # Validate that the token is a valid UUID, otherwise it's a legacy mock token
        import uuid
        try:
            uuid_obj = uuid.UUID(user_id, version=4)
        except ValueError:
            raise cred_exc
            
    except JWTError:
        raise cred_exc

    result = await db.execute(select(User).where(User.id == uuid_obj))
    user   = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise cred_exc
    return user


async def _resolve_user(token: str, db: AsyncSession) -> User:
    """Shared JWT verification — decode, load the active user, else raise 401."""
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    import uuid
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("sub")
        if not user_id:
            raise cred_exc
        try:
            uuid_obj = uuid.UUID(user_id, version=4)
        except ValueError:
            raise cred_exc
    except JWTError:
        raise cred_exc

    result = await db.execute(select(User).where(User.id == uuid_obj))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise cred_exc
    return user


async def get_current_user_token_or_header(
    db:            AsyncSession = Depends(get_db),
    token:         str | None = Query(None),
    authorization: str | None = Header(None),
) -> User:
    """Auth dependency for clients that cannot send headers.

    Browser ``EventSource`` cannot set an ``Authorization`` header, so the SSE
    endpoints accept the JWT either from the ``token`` query parameter OR from
    the standard bearer header. Scoped to streaming endpoints only.
    """
    tok = token
    if not tok and authorization and authorization.lower().startswith("bearer "):
        tok = authorization.split(" ", 1)[1].strip()
    if not tok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _resolve_user(tok, db)


def require_role(*roles: str):
    """Dependency factory — raises 403 if user role not in `roles`."""
    async def _check(current: User = Depends(get_current_user)):
        if current.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current
    return _check


# ── Rate Limiter & Account Lockout Store ──────────────────────────────────────
_FAILED_ATTEMPTS: dict[str, list[datetime]] = {}
LOCKOUT_THRESHOLD = 5
LOCKOUT_DURATION_MINUTES = 15


@router.post("/login", response_model=Token)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    username = form.username.strip().lower()

    # Clean stale failed attempts
    if username in _FAILED_ATTEMPTS:
        cutoff = now - timedelta(minutes=LOCKOUT_DURATION_MINUTES)
        _FAILED_ATTEMPTS[username] = [t for t in _FAILED_ATTEMPTS[username] if t > cutoff]
        if len(_FAILED_ATTEMPTS[username]) >= LOCKOUT_THRESHOLD:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Account temporarily locked for {LOCKOUT_DURATION_MINUTES} minutes for security.",
            )

    result = await db.execute(select(User).where(func.lower(User.username) == username))
    user = result.scalar_one_or_none()

    # Authenticate ONLY via bcrypt hash verification — no backdoor, no
    # plaintext fallback, no auto-seeding at login time.
    valid = False
    if user:
        valid = _verify_password(form.password, user.hashed_password)

    if not user or not valid:
        # Record failed attempt
        _FAILED_ATTEMPTS.setdefault(username, []).append(now)
        remaining = max(0, LOCKOUT_THRESHOLD - len(_FAILED_ATTEMPTS[username]))
        detail = "Incorrect username or password"
        if remaining <= 2 and remaining > 0:
            detail += f" ({remaining} attempt{'s' if remaining > 1 else ''} remaining before lockout)"
        raise HTTPException(status_code=401, detail=detail)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")

    # Clear failed attempts on successful login
    _FAILED_ATTEMPTS.pop(username, None)

    token, expires_in = _create_token(str(user.id), user.role, must_change_password=user.must_change_password)
    return Token(
        access_token=token,
        expires_in=expires_in,
        role=user.role,
        full_name=user.full_name,
        must_change_password=user.must_change_password,
    )


@router.get("/me", response_model=UserOut)
async def me(current: User = Depends(get_current_user)):
    return UserOut(
        id=str(current.id),
        username=current.username,
        email=current.email,
        full_name=current.full_name,
        rank=current.rank,
        unit=current.unit,
        role=current.role,
        is_active=current.is_active,
        must_change_password=current.must_change_password,
    )


# ── Change Password ──────────────────────────────────────────────────────────

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Change the current user's password.  Clears ``must_change_password``."""
    if not _verify_password(body.current_password, current.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must differ from current password")
    current.hashed_password = _hash_password(body.new_password)
    current.must_change_password = False
    await db.commit()
    return {"status": "ok", "message": "Password changed successfully"}

