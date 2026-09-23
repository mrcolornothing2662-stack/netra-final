from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Offline Synchronization Contracts
Strict Pydantic models for offline mutation queueing, conflict detection,
and projection deltas.
"""
from datetime import datetime, timezone
from typing import Any, Optional
from pydantic import BaseModel, Field


class OfflineMutationEnvelope(BaseModel):
    mutation_id: str
    device_id: str
    actor_id: str
    case_id: str
    base_state_version: int
    client_created_at: str
    command_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    local_sequence: int = 1
    sync_status: str = "PENDING"
    server_state_version: Optional[int] = None
    error_code: Optional[str] = None


class SyncConflict(BaseModel):
    conflict_id: str
    mutation_id: str
    command_type: str
    conflict_type: str
    client_payload: dict[str, Any] = Field(default_factory=dict)
    server_current_state: dict[str, Any] = Field(default_factory=dict)
    message: str
    status: str = "PENDING_REVIEW"
    created_at: Optional[str] = None


class SyncRejection(BaseModel):
    mutation_id: str
    error_code: str  # UNAUTHORIZED | MALFORMED_PAYLOAD | INVALID_COMMAND | TARGET_NOT_FOUND
    detail: str


class SyncProjectionDelta(BaseModel):
    from_version: int
    to_version: int
    entities: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    identity_candidates: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    activities: list[dict[str, Any]] = Field(default_factory=list)


class SyncBatchRequest(BaseModel):
    device_id: str
    client_state_version: int
    mutations: list[OfflineMutationEnvelope] = Field(default_factory=list)


class SyncBatchResponse(BaseModel):
    case_id: str
    server_state_version: int
    accepted: list[str] = Field(default_factory=list)
    rebased: list[str] = Field(default_factory=list)
    conflicts: list[SyncConflict] = Field(default_factory=list)
    rejected: list[SyncRejection] = Field(default_factory=list)
    projection_delta: SyncProjectionDelta


class OfflineBundleResponse(BaseModel):
    case: dict[str, Any]
    server_state_version: int
    entities: list[dict[str, Any]] = Field(default_factory=list)
    evidence_metadata: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    findings: list[dict[str, Any]] = Field(default_factory=list)
    timeline_activity: list[dict[str, Any]] = Field(default_factory=list)
    identity_candidates: list[dict[str, Any]] = Field(default_factory=list)
    replay_index: list[dict[str, Any]] = Field(default_factory=list)
    generated_at: str


class ConflictResolutionRequest(BaseModel):
    resolution: str  # KEEP_SERVER | APPLY_OFFLINE | CREATE_NEW_REVIEW
    rationale: str


class ConflictResolutionResponse(BaseModel):
    success: bool
    conflict_id: str
    status: str
    server_state_version: int
    message: str
