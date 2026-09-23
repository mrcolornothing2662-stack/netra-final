"""
CyberDrishti AI — Hardened Authentication & Access Control Routes
Supports Argon2id password hashing (with transparent bcrypt migration),
TOTP Multi-Factor Authentication (MFA) for Admin & IO roles,
Short-lived access tokens (15m), Refresh token rotation (7d),
Redis token revocation blocklist, Account lockout, and Audit logging.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError
import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Query, Header, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import pyotp
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import User, UserSession
from db.session import get_db
from utils.audit import append_audit

try:
    import redis.asyncio as aioredis
except ImportError:
    aioredis = None

router = APIRouter()

oauth2 = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

# ── Password Hasher ──────────────────────────────────────────────────────────
_argon2_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
)

# ── Revocation / Lockout In-Memory Fallbacks ──────────────────────────────────
_REVOKED_JTIS: dict[str, datetime] = {}
_FAILED_ATTEMPTS: dict[str, list[datetime]] = {}
_ACTIVE_REFRESH_TOKENS: dict[str, str] = {}  # jti -> user_id

_redis_conn: Optional[Any] = None


async def _get_redis():
    global _redis_conn
    if aioredis is None:
        return None
    if _redis_conn is None:
        try:
            client = aioredis.from_url(settings.redis_url, decode_responses=True)
            await client.ping()
            _redis_conn = client
        except Exception:
            _redis_conn = None
    return _redis_conn


async def _revoke_jti(jti: str, ttl_seconds: int) -> None:
    now = datetime.now(timezone.utc)
    _REVOKED_JTIS[jti] = now + timedelta(seconds=ttl_seconds)
    r = await _get_redis()
    if r:
        try:
            await r.setex(f"revoked_jti:{jti}", max(1, ttl_seconds), "1")
        except Exception:
            pass


async def _is_jti_revoked(jti: str) -> bool:
    r = await _get_redis()
    if r:
        try:
            res = await r.get(f"revoked_jti:{jti}")
            if res:
                return True
        except Exception:
            pass
    now = datetime.now(timezone.utc)
    expiry = _REVOKED_JTIS.get(jti)
    if expiry:
        if now < expiry:
            return True
        else:
            _REVOKED_JTIS.pop(jti, None)
    return False


# ── Schemas ───────────────────────────────────────────────────────────────────

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    role: str
    full_name: str | None = None
    must_change_password: bool = False
    mfa_required: bool = False
    mfa_pending_token: str | None = None
    refresh_token: str | None = None


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: str
    username: str
    email: str
    full_name: str | None
    rank: str | None
    unit: str | None
    role: str
    is_active: bool
    must_change_password: bool = False
    totp_enabled: bool = False


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class TOTPVerifyRequest(BaseModel):
    secret: str
    code: str


class TOTPLoginRequest(BaseModel):
    mfa_pending_token: str
    code: str


class TOTPDisableRequest(BaseModel):
    current_password: str
    code: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _hash_password(plain: str) -> str:
    """Always hashes with memory-hard Argon2id."""
    return _argon2_hasher.hash(plain)


def _verify_password(plain: str, hashed: str) -> tuple[bool, bool]:
    """
    Verifies a password against Argon2id or legacy bcrypt.
    Returns: (is_valid, needs_rehash_to_argon2id)
    """
    if hashed.startswith(("$argon2id$", "$argon2i$", "$argon2d$")):
        try:
            is_valid = _argon2_hasher.verify(hashed, plain)
            needs_rehash = _argon2_hasher.check_needs_rehash(hashed)
            return is_valid, needs_rehash
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False, False
    elif hashed.startswith(("$2b$", "$2a$", "$2y$")):
        try:
            valid = bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
            return valid, True  # upgrade to argon2id on next save
        except Exception:
            return False, False
    return False, False


def _create_access_token(
    user_id: str,
    role: str,
    must_change_password: bool = False,
    session_id: Optional[str] = None,
    device_id: Optional[str] = None,
    authentication_level: str = "standard",
) -> tuple[str, int, str]:
    expire_delta = timedelta(minutes=settings.access_token_expire_minutes)
    expire = datetime.now(timezone.utc) + expire_delta
    expire_in = int(expire_delta.total_seconds())
    jti = uuid.uuid4().hex
    sid = session_id or jti
    did = device_id or "device-default"
    payload = {
        "sub": user_id,
        "role": role,
        "exp": expire,
        "jti": jti,
        "type": "access",
        "must_change_password": must_change_password,
        "sid": sid,
        "did": did,
        "lvl": authentication_level,
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    return token, expire_in, jti


async def _create_refresh_token(user_id: str) -> tuple[str, str]:
    expire_delta = timedelta(days=settings.refresh_token_expire_days)
    expire = datetime.now(timezone.utc) + expire_delta
    jti = uuid.uuid4().hex
    payload = {
        "sub": user_id,
        "exp": expire,
        "jti": jti,
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)
    ttl_seconds = int(expire_delta.total_seconds())
    r = await _get_redis()
    if r:
        try:
            await r.setex(f"refresh_token:{jti}", ttl_seconds, user_id)
        except Exception:
            _ACTIVE_REFRESH_TOKENS[jti] = user_id
    else:
        _ACTIVE_REFRESH_TOKENS[jti] = user_id
    return token, jti


def _create_mfa_pending_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "sub": user_id,
        "exp": expire,
        "jti": uuid.uuid4().hex,
        "type": "mfa_pending",
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


_create_token = _create_access_token


async def _resolve_user(token: str, db: AsyncSession) -> User:
    """Helper to decode and validate an access token directly against a DB session."""
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid, revoked, or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("sub")
        jti = payload.get("jti")
        if not user_id:
            raise cred_exc
        if jti and await _is_jti_revoked(jti):
            raise cred_exc
        uuid_obj = uuid.UUID(user_id)
    except (JWTError, ValueError, TypeError):
        raise cred_exc

    result = await db.execute(select(User).where(User.id == uuid_obj))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise cred_exc
    return user


# ── Dependency: get_current_user ──────────────────────────────────────────────

async def get_current_user(
    request: Request,
    token: str = Depends(oauth2),
    db: AsyncSession = Depends(get_db),
) -> User:
    cred_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid, revoked, or expired access token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        user_id = payload.get("sub")
        token_type = payload.get("type")
        jti = payload.get("jti")
        if not user_id or token_type != "access" or not jti:
            raise cred_exc

        sid = payload.get("sid")
        did = payload.get("did") or "device-default"
        lvl = payload.get("lvl") or "standard"

        if await _is_jti_revoked(jti) or (sid and await _is_jti_revoked(sid)):
            raise cred_exc

        uuid_obj = uuid.UUID(user_id)
    except (JWTError, ValueError, TypeError):
        raise cred_exc

    # Check database session revocation if sid exists
    if sid:
        sess_res = await db.execute(select(UserSession).where(UserSession.id == sid))
        active_sess = sess_res.scalar_one_or_none()
        if active_sess and active_sess.revoked:
            raise cred_exc
        if active_sess:
            active_sess.last_seen = datetime.now(timezone.utc)

    request.state.session_id = sid
    request.state.device_id = did
    request.state.auth_level = lvl

    result = await db.execute(select(User).where(User.id == uuid_obj))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise cred_exc

    now = datetime.now(timezone.utc)
    if user.locked_until and user.locked_until > now:
        remaining_mins = max(1, int((user.locked_until - now).total_seconds() / 60))
        raise HTTPException(
            status_code=status.HTTP_423_LOCKED,
            detail=f"Account temporarily locked due to failed attempts. Try again in {remaining_mins} minutes.",
        )

    # Enforce temporary password change before granting general access
    path = request.url.path
    allowed_unverified_paths = [
        "/api/v1/auth/change-password",
        "/api/v1/auth/me",
        "/api/v1/auth/logout",
    ]
    if user.must_change_password and not any(path.startswith(p) for p in allowed_unverified_paths):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Temporary password must be changed before accessing investigative workflows.",
            headers={"X-Require-Password-Change": "true"},
        )

    return user


async def get_current_user_token_or_header(
    request: Request,
    db: AsyncSession = Depends(get_db),
    token: str | None = Query(None),
    authorization: str | None = Header(None),
) -> User:
    tok = token
    if not tok and authorization and authorization.lower().startswith("bearer "):
        tok = authorization.split(" ", 1)[1].strip()
    if not tok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await get_current_user(request, token=tok, db=db)


def require_role(*roles: str):
    async def _check(current: User = Depends(get_current_user)):
        allowed = {r.strip().lower() for r in roles} | {r.strip().upper() for r in roles}
        # Transparent mapping between canonical and legacy roles
        if "investigator" in allowed or "INVESTIGATOR" in allowed:
            allowed.update({"io", "fiu_analyst"})
        if "manager" in allowed or "MANAGER" in allowed:
            allowed.update({"supervisor"})
        if "io" in allowed or "fiu_analyst" in allowed:
            allowed.update({"investigator", "INVESTIGATOR"})
        if "supervisor" in allowed:
            allowed.update({"manager", "MANAGER"})
        if current.role not in allowed:
            raise HTTPException(status_code=403, detail="Insufficient permissions for role")
        return current
    return _check


# ── Auth Endpoints ────────────────────────────────────────────────────────────

@router.post("/login", response_model=Token)
async def login(
    request: Request,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)
    username = form.username.strip().lower()
    client_ip = request.client.host if request.client else "unknown"

    # 1. Clean stale in-memory failed attempts and enforce sliding-window lockout
    cutoff = now - timedelta(minutes=settings.login_lockout_minutes)
    if username in _FAILED_ATTEMPTS:
        _FAILED_ATTEMPTS[username] = [t for t in _FAILED_ATTEMPTS[username] if t > cutoff]
        if len(_FAILED_ATTEMPTS[username]) >= settings.login_max_failed_attempts:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Account temporarily locked for {settings.login_lockout_minutes} minutes for security.",
            )

    # 2. Check DB lockout
    result = await db.execute(select(User).where(func.lower(User.username) == username))
    user = result.scalar_one_or_none()

    if user and user.locked_until and user.locked_until > now:
        rem = max(1, int((user.locked_until - now).total_seconds() / 60))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account temporarily locked due to excessive failed attempts. Please try again after {rem} minutes.",
        )

    # 3. Verify credentials
    valid, needs_rehash = False, False
    if user:
        valid, needs_rehash = _verify_password(form.password, user.hashed_password)

    if not user or not valid:
        _FAILED_ATTEMPTS.setdefault(username, []).append(now)
        failures = len(_FAILED_ATTEMPTS[username])

        if user:
            user.failed_login_attempts += 1
            if user.failed_login_attempts >= settings.login_max_failed_attempts or failures >= settings.login_max_failed_attempts:
                user.locked_until = now + timedelta(minutes=settings.login_lockout_minutes)
                await append_audit(
                    db,
                    action="ACCOUNT_LOCKED",
                    user_id=user.id,
                    resource_type="user",
                    resource_id=str(user.id),
                    details={"ip": client_ip, "reason": "excessive_failed_logins"},
                )
            else:
                await append_audit(
                    db,
                    action="LOGIN_FAILED",
                    user_id=user.id,
                    resource_type="user",
                    resource_id=str(user.id),
                    details={"ip": client_ip, "attempt": user.failed_login_attempts},
                )
            await db.commit()

        remaining = max(0, settings.login_max_failed_attempts - failures)
        detail = "Incorrect username or password"
        if 0 < remaining <= 2:
            detail += f" ({remaining} attempt{'s' if remaining > 1 else ''} remaining before temporary lockout)"
        raise HTTPException(status_code=401, detail=detail)

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled by system administrator")

    # Reset failure counters
    _FAILED_ATTEMPTS.pop(username, None)
    user.failed_login_attempts = 0
    user.locked_until = None

    # Transparent upgrade to Argon2id if was legacy bcrypt
    if needs_rehash:
        user.hashed_password = _hash_password(form.password)
    await db.commit()

    # 4. MFA Check for Admin and IO roles
    if user.role in ("admin", "io") and user.totp_enabled:
        pending_token = _create_mfa_pending_token(str(user.id))
        return Token(
            access_token="",
            token_type="mfa_pending",
            expires_in=300,
            role=user.role,
            full_name=user.full_name,
            must_change_password=user.must_change_password,
            mfa_required=True,
            mfa_pending_token=pending_token,
        )

    # 5. Issue standard access + refresh tokens bound to device session
    dev_id = request.headers.get("X-Device-ID") or f"dev-{uuid.uuid4().hex[:12]}"
    session_id = uuid.uuid4().hex

    new_session = UserSession(
        id=session_id,
        user_id=user.id,
        device_id=dev_id,
        expires_at=now + timedelta(days=settings.refresh_token_expire_days),
        authentication_level="standard",
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent", "")[:250],
    )
    db.add(new_session)

    access_token, expires_in, _ = _create_access_token(
        str(user.id),
        user.role,
        must_change_password=user.must_change_password,
        session_id=session_id,
        device_id=dev_id,
        authentication_level="standard",
    )
    refresh_token, _ = await _create_refresh_token(str(user.id))

    await append_audit(
        db,
        action="LOGIN_SUCCESS",
        user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        details={"ip": client_ip, "device_id": dev_id, "session_id": session_id, "mfa_verified": False},
    )
    await db.commit()

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        role=user.role,
        full_name=user.full_name,
        must_change_password=user.must_change_password,
        mfa_required=False,
    )


@router.post("/totp/login", response_model=Token)
async def totp_login(
    body: TOTPLoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Complete login using TOTP code and pending MFA token."""
    try:
        payload = jwt.decode(body.mfa_pending_token, settings.secret_key, algorithms=[settings.algorithm])
        if payload.get("type") != "mfa_pending":
            raise HTTPException(401, "Invalid MFA token type")
        user_id = payload.get("sub")
        uuid_obj = uuid.UUID(user_id)
    except Exception:
        raise HTTPException(401, "Invalid or expired MFA pending token")

    user = await db.get(User, uuid_obj)
    if not user or not user.is_active or not user.totp_enabled or not user.totp_secret:
        raise HTTPException(401, "MFA authentication failed")

    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(body.code.strip(), valid_window=1):
        await append_audit(
            db,
            action="MFA_FAILED",
            user_id=user.id,
            resource_type="user",
            resource_id=str(user.id),
            details={"ip": request.client.host if request.client else "unknown"},
        )
        await db.commit()
        raise HTTPException(401, "Invalid TOTP verification code")

    access_token, expires_in, _ = _create_access_token(
        str(user.id), user.role, must_change_password=user.must_change_password
    )
    refresh_token, _ = await _create_refresh_token(str(user.id))

    await append_audit(
        db,
        action="LOGIN_SUCCESS_MFA",
        user_id=user.id,
        resource_type="user",
        resource_id=str(user.id),
        details={"ip": request.client.host if request.client else "unknown"},
    )
    await db.commit()

    return Token(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
        role=user.role,
        full_name=user.full_name,
        must_change_password=user.must_change_password,
        mfa_required=False,
    )


@router.post("/refresh", response_model=Token)
async def refresh_tokens(
    body: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    """Rotates refresh token and issues a fresh 15-minute access token."""
    cred_exc = HTTPException(401, "Invalid or expired refresh token")
    try:
        payload = jwt.decode(body.refresh_token, settings.secret_key, algorithms=[settings.algorithm])
        if payload.get("type") != "refresh":
            raise cred_exc
        user_id = payload.get("sub")
        old_jti = payload.get("jti")
        if not user_id or not old_jti:
            raise cred_exc
        if await _is_jti_revoked(old_jti):
            raise cred_exc
        uuid_obj = uuid.UUID(user_id)
    except Exception:
        raise cred_exc

    user = await db.get(User, uuid_obj)
    if not user or not user.is_active:
        raise cred_exc

    # 1. Revoke the old refresh token (Strict rotation)
    await _revoke_jti(old_jti, ttl_seconds=settings.refresh_token_expire_days * 86400)

    # 2. Issue new pair
    access_token, expires_in, _ = _create_access_token(str(user.id), user.role, user.must_change_password)
    new_refresh_token, _ = await _create_refresh_token(str(user.id))

    return Token(
        access_token=access_token,
        refresh_token=new_refresh_token,
        expires_in=expires_in,
        role=user.role,
        full_name=user.full_name,
        must_change_password=user.must_change_password,
        mfa_required=False,
    )


@router.post("/logout")
async def logout(
    request: Request,
    token: str = Depends(oauth2),
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Revokes the current JWT access token and logs out the session."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
        jti = payload.get("jti")
        if jti:
            await _revoke_jti(jti, ttl_seconds=settings.access_token_expire_minutes * 60)
    except Exception:
        pass

    await append_audit(
        db,
        action="USER_LOGOUT",
        user_id=current.id,
        resource_type="user",
        resource_id=str(current.id),
        details={"ip": request.client.host if request.client else "unknown"},
    )
    await db.commit()
    return {"status": "ok", "message": "Successfully logged out and session revoked"}


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
        totp_enabled=current.totp_enabled,
    )


@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Change current password. Enforces length, difference, and clears must_change_password."""
    valid, _ = _verify_password(body.current_password, current.hashed_password)
    if not valid:
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(body.new_password) < 12:
        raise HTTPException(status_code=400, detail="New password must be at least 12 characters")
    if body.new_password == body.current_password:
        raise HTTPException(status_code=400, detail="New password must differ from current password")

    current.hashed_password = _hash_password(body.new_password)
    current.must_change_password = False

    await append_audit(
        db,
        action="PASSWORD_CHANGED",
        user_id=current.id,
        resource_type="user",
        resource_id=str(current.id),
        details={"hasher": "argon2id"},
    )
    await db.commit()
    return {"status": "ok", "message": "Password changed successfully"}


# ── TOTP MFA Management Endpoints ─────────────────────────────────────────────

@router.get("/totp/setup")
async def totp_setup(current: User = Depends(get_current_user)):
    """Generate a new TOTP secret and provisioning URI for MFA enrollment."""
    secret = pyotp.random_base32()
    totp = pyotp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=current.email,
        issuer_name="CyberDrishti AI",
    )
    return {
        "secret": secret,
        "provisioning_uri": provisioning_uri,
        "message": "Scan the provisioning URI in an authenticator app (Google Authenticator, Aegis) and submit a code to /totp/verify",
    }


@router.post("/totp/verify")
async def totp_verify(
    body: TOTPVerifyRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Verify code against secret and activate TOTP MFA on account."""
    totp = pyotp.TOTP(body.secret.strip())
    if not totp.verify(body.code.strip(), valid_window=1):
        raise HTTPException(status_code=400, detail="Invalid verification code. Please try again.")

    current.totp_secret = body.secret.strip()
    current.totp_enabled = True

    await append_audit(
        db,
        action="TOTP_MFA_ENABLED",
        user_id=current.id,
        resource_type="user",
        resource_id=str(current.id),
        details={"email": current.email},
    )
    await db.commit()
    return {"status": "ok", "message": "TOTP Multi-Factor Authentication successfully enabled."}


@router.post("/totp/disable")
async def totp_disable(
    body: TOTPDisableRequest,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Disable TOTP MFA on account (requires current password and valid code)."""
    valid, _ = _verify_password(body.current_password, current.hashed_password)
    if not valid:
        raise HTTPException(400, "Current password is incorrect")
    if not current.totp_enabled or not current.totp_secret:
        raise HTTPException(400, "TOTP MFA is not enabled")

    totp = pyotp.TOTP(current.totp_secret)
    if not totp.verify(body.code.strip(), valid_window=1):
        raise HTTPException(400, "Invalid TOTP code")

    current.totp_enabled = False
    current.totp_secret = None

    await append_audit(
        db,
        action="TOTP_MFA_DISABLED",
        user_id=current.id,
        resource_type="user",
        resource_id=str(current.id),
        details={},
    )
    await db.commit()
    return {"status": "ok", "message": "TOTP Multi-Factor Authentication disabled."}


# ── Milestone 9: Device & Session Trust Endpoints ────────────────────────────

class SessionRevokeRequest(BaseModel):
    session_id: Optional[str] = None
    reason: Optional[str] = "User requested signout"


class SessionElevateRequest(BaseModel):
    password: str
    target_level: str = "elevated"  # "elevated" | "supervisor"


@router.get("/sessions")
async def list_active_sessions(
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """List active device sessions for current authenticated user."""
    res = await db.execute(
        select(UserSession)
        .where(UserSession.user_id == current.id)
        .order_by(UserSession.last_seen.desc())
    )
    sessions = res.scalars().all()
    return [
        {
            "session_id": s.id,
            "device_id": s.device_id,
            "issued_at": s.issued_at.isoformat() if s.issued_at else None,
            "expires_at": s.expires_at.isoformat() if s.expires_at else None,
            "last_seen": s.last_seen.isoformat() if s.last_seen else None,
            "authentication_level": s.authentication_level,
            "revoked": s.revoked,
            "ip_address": s.ip_address,
            "user_agent": s.user_agent,
        }
        for s in sessions
    ]


@router.post("/sessions/revoke")
async def revoke_session(
    body: Optional[SessionRevokeRequest] = None,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """Revoke an active session. If no session_id is provided, revokes current session."""
    target_sid = (body.session_id if body and body.session_id else None) or getattr(request.state, "session_id", None)
    if not target_sid:
        raise HTTPException(status_code=400, detail="No session identified to revoke")

    res = await db.execute(select(UserSession).where(UserSession.id == target_sid))
    sess = res.scalar_one_or_none()
    if sess:
        if sess.user_id != current.id and current.role.lower() != "admin":
            raise HTTPException(status_code=403, detail="Cannot revoke another user's session")
        sess.revoked = True
        sess.revoked_reason = (body.reason if body else None) or "Revoked"

    # Invalidate in-memory/redis cache
    await _revoke_jti(target_sid, 86400 * 7)

    await append_audit(
        db,
        action="SESSION_REVOKED",
        user_id=current.id,
        resource_type="user_session",
        resource_id=target_sid,
        details={"reason": (body.reason if body else None) or "User signout"},
    )
    await db.commit()
    return {"status": "ok", "message": f"Session '{target_sid}' successfully revoked."}


@router.post("/sessions/elevate", response_model=Token)
async def elevate_session(
    body: SessionElevateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current: User = Depends(get_current_user),
):
    """
    Step-up authentication: Re-verifies credentials to elevate session trust level
    to 'elevated' or 'supervisor' for sensitive operations.
    """
    valid, _ = _verify_password(body.password, current.hashed_password)
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid password for session elevation")

    sid = getattr(request.state, "session_id", None) or uuid.uuid4().hex
    did = getattr(request.state, "device_id", None) or "device-default"

    target_lvl = body.target_level.strip().lower()
    if target_lvl not in ("elevated", "supervisor"):
        target_lvl = "elevated"

    # Only supervisor/manager or admin can obtain supervisor trust level
    if target_lvl == "supervisor" and current.role.lower() not in ("manager", "supervisor", "admin"):
        raise HTTPException(status_code=403, detail="Supervisor authentication level requires Manager or Admin role")

    sess_res = await db.execute(select(UserSession).where(UserSession.id == sid))
    active_sess = sess_res.scalar_one_or_none()
    if active_sess:
        active_sess.authentication_level = target_lvl

    token, expires_in, _ = _create_access_token(
        str(current.id),
        current.role,
        session_id=sid,
        device_id=did,
        authentication_level=target_lvl,
    )

    await append_audit(
        db,
        action="SESSION_ELEVATED",
        user_id=current.id,
        resource_type="user_session",
        resource_id=sid,
        details={"new_level": target_lvl, "device_id": did},
    )
    await db.commit()

    return Token(
        access_token=token,
        expires_in=expires_in,
        role=current.role,
        full_name=current.full_name,
        mfa_required=False,
    )
