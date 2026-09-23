from __future__ import annotations
"""
CyberDrishti AI / NETRA V5 — Forensic Lens Service
Central orchestration service providing read-only, cross-lens synchronized
projections over the shared Investigation Brain state.
"""
from datetime import datetime, timezone
from typing import Any, Optional
import uuid

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import Case, EvidenceEvent, InvestigationState
from forensic.contracts import (
    ForensicLensType,
    ForensicLensResponse,
    LensOverviewResponse,
    CrossLensSignal,
)
from forensic.money import build_money_lens
from forensic.communications import build_communications_lens
from forensic.geographic import build_geographic_lens, LOCATION_DISCLAIMER


class ForensicLensService:
    """Orchestrates forensic lens projections with cross-lens correlation."""

    @staticmethod
    async def get_forensic_lens(
        db: AsyncSession,
        case_id: str | uuid.UUID,
        lens_type: str | ForensicLensType,
        entity_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        state_version: Optional[int] = None,
    ) -> ForensicLensResponse:
        """
        Build a forensic lens projection.
        Strictly read-only; no database rows are mutated.
        """
        case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
        case = await db.get(Case, case_uuid)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        current_version = case.state_version or 1
        target_version = state_version or current_version

        if target_version < 1 or target_version > current_version:
            raise HTTPException(
                status_code=400,
                detail=f"Target version {target_version} must be between 1 and current case version {current_version}",
            )

        # 1. Determine checkpoint cutoff timestamp for historical replay (Invariant 13)
        cutoff_timestamp: Optional[datetime] = None
        is_historical = target_version < current_version
        if is_historical:
            ckpt_next_q = select(InvestigationState).where(
                InvestigationState.case_id == case_uuid,
                InvestigationState.version == target_version + 1,
            )
            ckpt_next = (await db.execute(ckpt_next_q)).scalars().first()
            if ckpt_next and ckpt_next.created_at:
                cutoff_timestamp = ckpt_next.created_at

        # Normalize lens type
        lens_clean = str(lens_type).upper().replace("FORENSICLENSTYPE.", "").strip()
        if "MONEY" in lens_clean or "FINANC" in lens_clean:
            lens_key = "MONEY"
        elif "COMM" in lens_clean:
            lens_key = "COMMUNICATION"
        elif "GEO" in lens_clean or "TRAVEL" in lens_clean or "LOC" in lens_clean:
            lens_key = "GEOGRAPHIC"
        else:
            lens_key = lens_clean

        # 2. Dispatch to domain builder
        if lens_key == "MONEY":
            lens_data = await build_money_lens(
                db=db,
                case=case,
                entity_id=entity_id,
                start_time=start_time,
                end_time=end_time,
                cutoff_timestamp=cutoff_timestamp,
            )
            disclaimer = None
        elif lens_key == "COMMUNICATION":
            lens_data = await build_communications_lens(
                db=db,
                case=case,
                entity_id=entity_id,
                start_time=start_time,
                end_time=end_time,
                cutoff_timestamp=cutoff_timestamp,
            )
            disclaimer = None
        elif lens_key == "GEOGRAPHIC":
            lens_data = await build_geographic_lens(
                db=db,
                case=case,
                entity_id=entity_id,
                start_time=start_time,
                end_time=end_time,
                cutoff_timestamp=cutoff_timestamp,
            )
            disclaimer = LOCATION_DISCLAIMER
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown lens type '{lens_type}'. Supported: MONEY, COMMUNICATION, GEOGRAPHIC",
            )

        # 3. Compute Cross-Lens Linked Coincidences
        cross_lens_signals = await ForensicLensService._detect_cross_lens_coincidences(
            db=db,
            case=case,
            entity_id=entity_id,
            start_time=start_time,
            end_time=end_time,
            cutoff_timestamp=cutoff_timestamp,
        )

        return ForensicLensResponse(
            id=lens_key,
            case_id=str(case.id),
            case_number=case.case_number,
            title=case.title,
            state_version=target_version,
            is_historical=is_historical,
            disclaimer=disclaimer,
            summary=lens_data["summary"],
            entities=lens_data["entities"],
            events=lens_data["events"],
            relationships=lens_data["relationships"],
            signals=lens_data["signals"],
            findings=lens_data["findings"],
            evidence_refs=lens_data["evidence_refs"],
            timeline=lens_data["timeline"],
            cross_lens_signals=cross_lens_signals,
        )

    @staticmethod
    async def get_lenses_overview(
        db: AsyncSession,
        case_id: str | uuid.UUID,
    ) -> LensOverviewResponse:
        """Overview summary across all three forensic lenses."""
        case_uuid = case_id if isinstance(case_id, uuid.UUID) else uuid.UUID(str(case_id))
        case = await db.get(Case, case_uuid)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")

        # Query counts by event type
        q = select(EvidenceEvent).where(EvidenceEvent.case_id == case_uuid)
        events = list((await db.execute(q)).scalars().all())

        money_evs = [e for e in events if e.event_type in ["bank_txn", "upi_txn", "financial"]]
        comms_evs = [e for e in events if e.event_type in ["call", "cdr", "whatsapp_msg", "sms"]]
        geo_evs = [e for e in events if e.event_type in ["location_timeline", "location", "cell_site"]]

        cross_coincidences = await ForensicLensService._detect_cross_lens_coincidences(
            db=db, case=case
        )

        active = []
        if money_evs:
            active.append("MONEY")
        if comms_evs:
            active.append("COMMUNICATION")
        if geo_evs:
            active.append("GEOGRAPHIC")

        return LensOverviewResponse(
            case_id=str(case.id),
            case_number=case.case_number,
            title=case.title,
            state_version=case.state_version or 1,
            money_summary={
                "transaction_count": len(money_evs),
                "has_data": len(money_evs) > 0,
            },
            communications_summary={
                "communication_count": len(comms_evs),
                "has_data": len(comms_evs) > 0,
            },
            geographic_summary={
                "observation_count": len(geo_evs),
                "has_data": len(geo_evs) > 0,
                "disclaimer": LOCATION_DISCLAIMER,
            },
            cross_lens_coincidences_count=len(cross_coincidences),
            active_lenses=active,
        )

    @staticmethod
    async def _detect_cross_lens_coincidences(
        db: AsyncSession,
        case: Case,
        entity_id: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        cutoff_timestamp: Optional[datetime] = None,
    ) -> list[CrossLensSignal]:
        """
        Detect cross-domain temporal overlaps:
        e.g., Financial transfer + Communication burst + Cell-site association in a 60-min window.
        """
        q = select(EvidenceEvent).where(
            EvidenceEvent.case_id == case.id,
            EvidenceEvent.event_timestamp.isnot(None),
        )
        if cutoff_timestamp:
            q = q.where(EvidenceEvent.created_at < cutoff_timestamp)

        events = list((await db.execute(q)).scalars().all())

        # Sort by event_timestamp
        timestamped = [e for e in events if e.event_timestamp]
        timestamped.sort(key=lambda x: x.event_timestamp)

        coincidences: list[CrossLensSignal] = []
        window_sec = 3600  # 60 minutes heuristic window

        i = 0
        while i < len(timestamped):
            j = i
            window_events = []
            types_present = set()
            while j < len(timestamped) and (timestamped[j].event_timestamp - timestamped[i].event_timestamp).total_seconds() <= window_sec:
                ev = timestamped[j]
                if ev.event_type in ["bank_txn", "upi_txn", "financial"]:
                    types_present.add("MONEY")
                elif ev.event_type in ["call", "cdr", "whatsapp_msg", "sms"]:
                    types_present.add("COMMUNICATION")
                elif ev.event_type in ["location_timeline", "location", "cell_site"]:
                    types_present.add("GEOGRAPHIC")
                window_events.append(ev)
                j += 1

            # If 2 or more distinct domains coincide in this 60-min window
            if len(types_present) >= 2 and len(window_events) >= 2:
                t_start = timestamped[i].event_timestamp
                t_end = timestamped[j - 1].event_timestamp
                entities_in_window = set()
                evidence_in_window = set()
                for wev in window_events:
                    wmeta = wev.event_metadata or {}
                    for k in ["phone", "caller", "callee", "sender", "account", "vpa"]:
                        if wmeta.get(k):
                            entities_in_window.add(str(wmeta[k]))
                    if wev.evidence_file_id:
                        evidence_in_window.add(str(wev.evidence_file_id))

                domains_str = " + ".join(sorted(types_present))
                coincidences.append(
                    CrossLensSignal(
                        id=str(uuid.uuid4()),
                        title=f"Heuristic Pattern Signal: Cross-Domain Coincidence ({domains_str})",
                        description=(
                            f"Analytical heuristic: {len(window_events)} events across {domains_str} observed within "
                            f"a {round((t_end - t_start).total_seconds() / 60, 1)} minute window "
                            f"({t_start.strftime('%H:%M')} - {t_end.strftime('%H:%M')})."
                        ),
                        lenses_involved=sorted(types_present),
                        time_window={
                            "start": t_start.isoformat(),
                            "end": t_end.isoformat(),
                        },
                        entities_involved=list(entities_in_window),
                        events_involved=[str(wev.id) for wev in window_events],
                        evidence_refs=list(evidence_in_window),
                        confidence=0.90 if len(types_present) >= 3 else 0.82,
                    )
                )
                i = j  # advance past window to prevent duplicates
            else:
                i += 1

        return coincidences[:10]
