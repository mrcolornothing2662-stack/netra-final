from __future__ import annotations

"""
CyberDrishti AI / NETRA V5 — Observability & Telemetry Collector
Provides in-memory, thread-safe operational metrics without logging sensitive evidence content:
- Request correlation (correlation_id propagation)
- Latency percentiles (p50, p95, p99)
- Operational failure counters (commands, sync conflicts, evidence, reports, audits)
"""

import math
import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List


class TelemetryCollector:
    """In-memory telemetry collector for system health and operational metrics."""

    def __init__(self, max_latencies: int = 5000) -> None:
        self._lock = threading.Lock()
        self._start_time: float = time.time()
        self._latencies_ms: deque[float] = deque(maxlen=max_latencies)

        # Counters
        self._total_requests: int = 0
        self._status_counts: Dict[int, int] = {}
        self._failed_commands_count: int = 0
        self._sync_conflicts_count: int = 0
        self._evidence_failures_count: int = 0
        self._report_failures_count: int = 0
        self._audit_verification_failures_count: int = 0
        self._background_job_failures_count: int = 0

        # Category breakdowns (non-sensitive)
        self._failed_commands_by_type: Dict[str, int] = {}
        self._failed_jobs_by_type: Dict[str, int] = {}

    def record_request(self, duration_ms: float, status_code: int) -> None:
        """Record an incoming HTTP request completion."""
        with self._lock:
            self._total_requests += 1
            self._latencies_ms.append(duration_ms)
            self._status_counts[status_code] = self._status_counts.get(status_code, 0) + 1

    def record_failed_command(self, command_type: str) -> None:
        """Record a rejected or failed investigation command."""
        with self._lock:
            self._failed_commands_count += 1
            cmd_norm = command_type or "unknown"
            self._failed_commands_by_type[cmd_norm] = (
                self._failed_commands_by_type.get(cmd_norm, 0) + 1
            )

    def record_sync_conflict(self) -> None:
        """Record an offline sync conflict occurrence."""
        with self._lock:
            self._sync_conflicts_count += 1

    def record_evidence_failure(self) -> None:
        """Record an evidence ingestion or extraction failure."""
        with self._lock:
            self._evidence_failures_count += 1

    def record_report_failure(self) -> None:
        """Record a report generation or export failure."""
        with self._lock:
            self._report_failures_count += 1

    def record_audit_verification_failure(self) -> None:
        """Record an audit chain tamper/verification failure."""
        with self._lock:
            self._audit_verification_failures_count += 1

    def record_background_job_failure(self, job_type: str) -> None:
        """Record a background task failure."""
        with self._lock:
            self._background_job_failures_count += 1
            j_norm = job_type or "unknown"
            self._failed_jobs_by_type[j_norm] = (
                self._failed_jobs_by_type.get(j_norm, 0) + 1
            )

    def get_metrics(self) -> Dict[str, Any]:
        """Compute snapshot of system telemetry."""
        with self._lock:
            uptime_seconds = round(time.time() - self._start_time, 2)
            latencies = sorted(self._latencies_ms)
            count = len(latencies)

            if count > 0:
                avg_latency = round(sum(latencies) / count, 2)
                p50 = round(latencies[int(math.floor(count * 0.50))], 2)
                p95 = round(latencies[min(int(math.floor(count * 0.95)), count - 1)], 2)
                p99 = round(latencies[min(int(math.floor(count * 0.99)), count - 1)], 2)
            else:
                avg_latency = 0.0
                p50 = 0.0
                p95 = 0.0
                p99 = 0.0

            return {
                "system": {
                    "uptime_seconds": uptime_seconds,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "healthy",
                },
                "http_traffic": {
                    "total_requests": self._total_requests,
                    "status_distribution": dict(self._status_counts),
                    "latency_ms": {
                        "avg": avg_latency,
                        "p50": p50,
                        "p95": p95,
                        "p99": p99,
                        "sample_size": count,
                    },
                },
                "subsystem_failures": {
                    "failed_commands": self._failed_commands_count,
                    "failed_commands_by_type": dict(self._failed_commands_by_type),
                    "sync_conflicts": self._sync_conflicts_count,
                    "evidence_processing_failures": self._evidence_failures_count,
                    "report_generation_failures": self._report_failures_count,
                    "audit_verification_failures": self._audit_verification_failures_count,
                    "background_job_failures": self._background_job_failures_count,
                    "background_job_failures_by_type": dict(self._failed_jobs_by_type),
                },
            }


# Singleton global telemetry instance
telemetry = TelemetryCollector()
