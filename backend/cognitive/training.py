"""
CyberDrishti AI / NETRA 5.0 — Feature 11: Training Simulator
Synthetic Benchmark & Evaluation Layer over Cognitive Engines

Architecture:
  Seeded Synthetic Evidence -> Controlled Noise / Gaps -> Investigator Task
  -> NETRA Engine Analysis -> Expected-Answer Comparison -> Scoring & Debrief

Statutory & Pedagogical Standards:
  - DPDP Act 2023: Purely synthetic entities, zero real citizen PII.
  - Section 193 BNSS / Section 63 BSA / BNS 2023: Exercises digital chain of custody,
    evidentiary admissibility, defense cross-examination, and golden hours actions.
  - Strict Isolation: Training cases are demarcated and never pollute production cases.
"""
from __future__ import annotations

import copy
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from cognitive import data_path
from cognitive.benchmark import BenchmarkGenerator, load_json

logger = logging.getLogger(__name__)

# Standard statutory and pedagogical constants
STATUTORY_TRAINING_NOTICE = (
    "NETRA TRAINING SIMULATOR — SYNTHETIC BENCHMARK ENVIRONMENT. "
    "All scenarios, names, phone numbers, accounts, and artifacts are synthetically "
    "generated pursuant to the Digital Personal Data Protection (DPDP) Act, 2023. "
    "Not real evidence. For law-enforcement training & engine benchmark evaluation only."
)

READINESS_TIERS = {
    "MASTER_INVESTIGATOR": {
        "min_score": 90,
        "title": "Master Cyber Investigator",
        "description": "Court-ready chargesheet quality. Exceptional evidentiary rigor, acute identification of BSA Section 63 vulnerabilities, and optimal golden hours response.",
        "badge": "🎖️ MASTER INVESTIGATOR",
    },
    "LEAD_CYBER_INVESTIGATOR": {
        "min_score": 75,
        "title": "Lead Cyber Investigator",
        "description": "High investigative competency. Thorough evidence extraction, strong suspect attribution, and sound legal understanding with minor procedural omissions.",
        "badge": "⭐ LEAD INVESTIGATOR",
    },
    "PROFICIENT_OFFICER": {
        "min_score": 50,
        "title": "Proficient Investigating Officer",
        "description": "Solid operational grasp of basic cyber-fraud mechanics. Requires strengthening on defense cross-examination angles and Section 63 BSA hash certification.",
        "badge": "🔷 PROFICIENT OFFICER",
    },
    "NOVICE_IN_TRAINING": {
        "min_score": 0,
        "title": "Investigator in Training",
        "description": "Foundational comprehension. Critical gaps in distinguishing pass-through mules from kingpins, identifying planted hidden links, or executing immediate asset freeze.",
        "badge": "🔰 IN TRAINING",
    },
}


class TrainingSession:
    """Represents an isolated, active training session."""

    def __init__(
        self,
        session_id: str,
        drill_id: str,
        title: str,
        typology: str,
        difficulty: str,
        incident_brief: str,
        seed: int,
        case_data: dict[str, Any],
        tasks: list[dict[str, Any]],
        full_tasks: list[dict[str, Any]],
    ) -> None:
        self.session_id = session_id
        self.drill_id = drill_id
        self.title = title
        self.typology = typology
        self.difficulty = difficulty
        self.incident_brief = incident_brief
        self.seed = seed
        self.case_data = case_data
        self.tasks = tasks                  # Redacted tasks (no correct_option exposed)
        self._full_tasks = full_tasks        # Complete tasks with correct_option & notes
        self.created_at = datetime.now(timezone.utc).isoformat()
        self.engine_analysis: dict[str, Any] | None = None
        self.submission: dict[str, Any] | None = None
        self.evaluation: dict[str, Any] | None = None

    def to_dict(self, include_ground_truth: bool = False) -> dict[str, Any]:
        """Convert session to API-safe dict."""
        artifacts_summary = {}
        for k, v in self.case_data.get("artifacts", {}).items():
            if isinstance(v, list):
                artifacts_summary[k] = {
                    "type": "table",
                    "rows_count": len(v),
                    "preview": v[:5],
                    "raw": v,
                }
            else:
                text_content = str(v)
                artifacts_summary[k] = {
                    "type": "text",
                    "length_chars": len(text_content),
                    "lines_count": len(text_content.splitlines()),
                    "preview": text_content[:400],
                    "raw": text_content,
                }

        out = {
            "session_id": self.session_id,
            "drill_id": self.drill_id,
            "title": self.title,
            "typology": self.typology,
            "difficulty": self.difficulty,
            "incident_brief": self.incident_brief,
            "seed": self.seed,
            "created_at": self.created_at,
            "has_hints": self.engine_analysis is not None,
            "is_evaluated": self.evaluation is not None,
            "tasks": self.tasks,
            "artifacts": artifacts_summary,
            "statutory_notice": STATUTORY_TRAINING_NOTICE,
        }

        if self.evaluation:
            out["evaluation"] = self.evaluation

        if include_ground_truth:
            out["ground_truth"] = self.case_data.get("ground_truth", {})
            out["solution_tasks"] = self._full_tasks

        return out


class TrainingSimulator:
    """
    Core engine managing drill catalogs, seeded case generation,
    cognitive engine execution over synthetic evidence, and grading.
    """

    def __init__(self) -> None:
        self._pools = load_json(data_path("pools.json"))
        self._typologies = load_json(data_path("typologies.json"))
        self._drills_data = load_json(data_path("training_drills.json"))
        self._generator = BenchmarkGenerator(self._pools, self._typologies)
        self._sessions: dict[str, TrainingSession] = {}

    # ------------------------------------------------------------------ Catalog
    def list_drills(self) -> list[dict[str, Any]]:
        """List all available training drill missions."""
        drills = []
        for d in self._drills_data.get("drills", []):
            drills.append({
                "id": d["id"],
                "title": d["title"],
                "typology": d["typology"],
                "difficulty": d.get("difficulty", "INTERMEDIATE"),
                "incident_brief": d["incident_brief"],
                "default_seed": d.get("default_seed", 100),
                "tasks_count": len(d.get("tasks", [])),
                "planted_defects": d.get("planted_defects", []),
            })
        return drills

    def get_drill(self, drill_id: str) -> dict[str, Any] | None:
        """Find a drill definition by ID."""
        for d in self._drills_data.get("drills", []):
            if d["id"] == drill_id:
                return d
        return None

    # ----------------------------------------------------------- Session Mgmt
    def start_session(
        self,
        drill_id: str | None = None,
        seed: int | None = None,
        difficulty: str | None = None,
    ) -> TrainingSession:
        """
        Instantiate a fresh training session.
        If drill_id is omitted, defaults to the first available drill.
        """
        drills = self._drills_data.get("drills", [])
        if not drills:
            raise RuntimeError("No training drills configured in training_drills.json")

        drill = None
        if drill_id:
            drill = self.get_drill(drill_id)
        if not drill and difficulty:
            drill = next((d for d in drills if d.get("difficulty") == difficulty.upper()), None)
        if not drill:
            drill = drills[0]

        actual_seed = seed if seed is not None else drill.get("default_seed", 101)
        typology_key = drill["typology"]

        # Generate deterministic synthetic case
        case_data = self._generator.generate_case(typology_key, actual_seed)

        # Build redacted task set for student view
        redacted_tasks = []
        full_tasks = []
        for t in drill.get("tasks", []):
            full_tasks.append(copy.deepcopy(t))
            redacted_tasks.append({
                "task_id": t["task_id"],
                "pillar": t["pillar"],
                "prompt": t["prompt"],
                "points": t.get("points", 25),
                "options": copy.deepcopy(t.get("options", [])),
            })

        session_id = str(uuid.uuid4())
        session = TrainingSession(
            session_id=session_id,
            drill_id=drill["id"],
            title=drill["title"],
            typology=typology_key,
            difficulty=drill.get("difficulty", "INTERMEDIATE"),
            incident_brief=drill["incident_brief"],
            seed=actual_seed,
            case_data=case_data,
            tasks=redacted_tasks,
            full_tasks=full_tasks,
        )

        # Keep session store bounded
        if len(self._sessions) >= 64:
            oldest_key = next(iter(self._sessions))
            self._sessions.pop(oldest_key, None)

        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> TrainingSession | None:
        """Retrieve active session by ID."""
        return self._sessions.get(session_id)

    # ---------------------------------------------------- Cognitive Engine Run
    def run_netra_engines_on_case(self, session: TrainingSession) -> dict[str, Any]:
        """
        Execute NETRA's actual cognitive reasoning engines over the synthetic
        case artifacts, providing expected benchmark findings and officer hints.
        """
        if session.engine_analysis:
            return session.engine_analysis

        artifacts = session.case_data.get("artifacts", {})
        ground_truth = session.case_data.get("ground_truth", {})

        # 1. Prepare evidence items for cognitive engines
        chat_text = artifacts.get("whatsapp_export.txt", "")
        bank_rows = artifacts.get("bank_statement_noisy.csv") or artifacts.get("bank_statement.csv", [])
        cdr_rows = artifacts.get("cdr.csv", [])

        # Parse chat into evidence items
        from parsers.whatsapp_parser import _PIPE_DELIMITED_RE, _MSG_PATTERNS
        chat_items = []
        for line_no, line in enumerate(chat_text.splitlines(), start=1):
            if not line.strip():
                continue
            m = _PIPE_DELIMITED_RE.match(line)
            if m:
                ts, sender, text = m.group(1), m.group(2), m.group(3)
            else:
                sender = "Accused"
                text = line
                ts = ""
            chat_items.append({
                "type": "whatsapp_msg",
                "line_no": line_no,
                "sender": sender,
                "text": text,
                "timestamp": ts,
                "filename": "whatsapp_export.txt",
            })

        evidence_items = list(chat_items)
        for idx, br in enumerate(bank_rows, start=len(evidence_items) + 1):
            evidence_items.append({
                "type": "bank_txn",
                "line_no": idx,
                "account": br.get("account"),
                "narration": br.get("narration", ""),
                "amount": br.get("credit") or br.get("debit"),
                "timestamp": br.get("timestamp"),
                "filename": "bank_statement.csv",
            })
        for idx, cr in enumerate(cdr_rows, start=len(evidence_items) + 1):
            evidence_items.append({
                "type": "call",
                "line_no": idx,
                "caller": cr.get("caller"),
                "callee": cr.get("callee"),
                "duration_sec": cr.get("duration_sec"),
                "timestamp": cr.get("timestamp"),
                "filename": "cdr.csv",
            })

        # 2. Run MO Fingerprint Engine
        from cognitive.mo import classify_case_evidence, load_playbooks
        playbooks = load_playbooks(data_path("playbooks.json"))
        mo_result = classify_case_evidence(evidence_items, playbooks, {"match_threshold": 0.60})

        # 3. Run Contradiction & Ledger Audit
        from cognitive.contradiction import ledger_audit
        ledger_findings = []
        accounts = {r.get("account") for r in bank_rows if r.get("account")}
        for acct in accounts:
            acct_rows = [r for r in bank_rows if r.get("account") == acct]
            f = ledger_audit(acct_rows)
            if f:
                ledger_findings.extend(f)

        # 4. Run Defence Bot Audit
        from cognitive.defence import audit_case_defensibility
        synth_files = [
            {"filename": "whatsapp_export.txt", "sha256_hash": "a" * 64},
            {"filename": "bank_statement.csv", "sha256_hash": "b" * 64},
            {"filename": "cdr.csv", "sha256_hash": "c" * 64},
            {"filename": "evidence_seizure_memo.txt", "sha256_hash": "d" * 64},
        ]
        defence_audit = audit_case_defensibility(
            case_id=session.session_id,
            evidence_files=synth_files,
            events=evidence_items,
            findings=[],
            entity_profiles={},
        )

        # 5. Run Next-Best Golden Hours Engine
        from cognitive.nextbest import rank_actions, load_catalog
        action_cat = load_catalog(data_path("action_catalog.json"))
        case_state = {
            "elapsed_hours_since_first_credit": 1.2,
            "complaint_ref": f"NCRP-2026-{session.seed}",
            "accounts_at_risk": [
                {
                    "account": br.get("account", "MULE_ACCT"),
                    "bank": br.get("bank", "Bank"),
                    "amount_unwithdrawn": float(br.get("credit") or 100000),
                }
                for br in bank_rows[:2]
            ],
            "unresolved_phones": [
                {"phone": cr.get("caller", "9876543210"), "carrier": "Carrier"}
                for cr in cdr_rows[:2]
            ],
        }
        nb_result = rank_actions(
            case_state=case_state,
            catalog=action_cat,
        )

        analysis = {
            "mo_engine": {
                "verdict": mo_result.get("verdict"),
                "best_playbook": mo_result.get("best_match", {}).get("playbook") if mo_result.get("best_match") else None,
                "similarity": mo_result.get("best_match", {}).get("similarity") if mo_result.get("best_match") else 0.0,
                "observed_stages": mo_result.get("observed_sequence", []),
            },
            "contradiction_engine": {
                "ledger_anomalies_count": len(ledger_findings),
                "findings": ledger_findings[:3],
            },
            "defence_bot_engine": {
                "defensibility_score": defence_audit.defensibility_score,
                "risk_level": defence_audit.risk_level,
                "bsa_status": defence_audit.bsa_compliance_status.get("status", "NON_COMPLIANT") if isinstance(defence_audit.bsa_compliance_status, dict) else str(defence_audit.bsa_compliance_status),
                "challenges_count": len(defence_audit.challenges),
                "top_challenge": {
                    "counter_hypothesis": defence_audit.challenges[0].defense_counter_hypothesis if defence_audit.challenges else None,
                    "target_entity": defence_audit.challenges[0].target_entity if defence_audit.challenges else None,
                },
            },
            "nextbest_engine": {
                "top_action": (
                    nb_result.get("ranked_actions", [{}])[0].get("description")
                    or nb_result.get("ranked_actions", [{}])[0].get("action_code")
                ) if nb_result.get("ranked_actions") else None,
                "statutory_basis": (
                    nb_result.get("ranked_actions", [{}])[0].get("statutory_basis")
                ) if nb_result.get("ranked_actions") else None,
            },
        }

        session.engine_analysis = analysis
        return analysis

    # ---------------------------------------------------- Scoring & Evaluation
    def evaluate_submission(
        self,
        session_id: str,
        answers: dict[str, str],
    ) -> dict[str, Any]:
        """
        Grades investigator's submission against Ground Truth and NETRA analysis.
        Computes 4-pillar scores, overall readiness tier, and pedagogical debrief.
        """
        session = self.get_session(session_id)
        if not session:
            raise KeyError(f"Training session '{session_id}' not found")

        # Run cognitive engines if not already run
        engine_insights = self.run_netra_engines_on_case(session)

        task_evaluations = []
        pillar_scores = {
            "typology": {"earned": 0, "max": 25},
            "hidden_links": {"earned": 0, "max": 25},
            "legal_rigor": {"earned": 0, "max": 25},
            "action_priority": {"earned": 0, "max": 25},
        }

        for t in session._full_tasks:
            t_id = t["task_id"]
            pillar = t.get("pillar", "typology")
            correct_opt = t.get("correct_option")
            max_pts = t.get("points", 25)
            selected_opt = answers.get(t_id)

            is_correct = bool(selected_opt and selected_opt.strip().upper() == str(correct_opt).strip().upper())
            pts_earned = max_pts if is_correct else 0

            pillar_scores[pillar]["earned"] += pts_earned
            pillar_scores[pillar]["max"] = max(pillar_scores[pillar]["max"], max_pts)

            # Map correct label
            correct_label = correct_opt
            selected_label = selected_opt or "Unanswered"
            for opt in t.get("options", []):
                if opt.get("id") == correct_opt:
                    correct_label = opt.get("label", correct_opt)
                if opt.get("id") == selected_opt:
                    selected_label = opt.get("label", selected_opt)

            # Correlate with NETRA cognitive engine finding
            engine_finding = ""
            if pillar == "typology":
                engine_finding = f"MO Engine matched: {engine_insights['mo_engine']['best_playbook']} ({engine_insights['mo_engine']['similarity']*100:.0f}%)"
            elif pillar == "hidden_links":
                engine_finding = f"Ground truth hidden link: {session.case_data.get('ground_truth', {}).get('planted_hidden_links', [{}])[0].get('note', '')}"
            elif pillar == "legal_rigor":
                engine_finding = f"Defence Bot audit: {engine_insights['defence_bot_engine']['bsa_status']} ({engine_insights['defence_bot_engine']['risk_level']})"
            elif pillar == "action_priority":
                engine_finding = f"Golden Hours VoI rank #1: {engine_insights['nextbest_engine']['top_action']} ({engine_insights['nextbest_engine']['statutory_basis']})"

            task_evaluations.append({
                "task_id": t_id,
                "pillar": pillar,
                "prompt": t.get("prompt"),
                "selected_option": selected_opt,
                "selected_label": selected_label,
                "correct_option": correct_opt,
                "correct_label": correct_label,
                "is_correct": is_correct,
                "points_earned": pts_earned,
                "max_points": max_pts,
                "pedagogical_lesson": t.get("pedagogical_lesson", ""),
                "netra_engine_finding": engine_finding,
            })

        total_earned = sum(p["earned"] for p in pillar_scores.values())
        total_max = sum(p["max"] for p in pillar_scores.values()) or 100
        score_pct = round((total_earned / total_max) * 100)

        # Determine readiness tier
        assigned_tier = "NOVICE_IN_TRAINING"
        for tier_key, tier_info in sorted(READINESS_TIERS.items(), key=lambda x: -x[1]["min_score"]):
            if score_pct >= tier_info["min_score"]:
                assigned_tier = tier_key
                break

        tier_meta = READINESS_TIERS[assigned_tier]

        evaluation = {
            "score_pct": score_pct,
            "total_points_earned": total_earned,
            "total_points_possible": total_max,
            "readiness_tier": assigned_tier,
            "tier_title": tier_meta["title"],
            "tier_badge": tier_meta["badge"],
            "tier_description": tier_meta["description"],
            "pillar_breakdown": pillar_scores,
            "task_evaluations": task_evaluations,
            "statutory_recap": [
                "Section 193 BNSS: Rigorous investigation report preparation and trial court evidence scrutiny.",
                "Section 63 BSA: Mandatory certificate requirement for secondary electronic evidence admissibility.",
                "Section 105 BNSS: Compulsory audio-video electronic recording of search and seizure operations.",
                "Section 318(4) BNS: Cheating and fraudulent intent requirement (mens rea proof).",
            ],
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

        session.submission = answers
        session.evaluation = evaluation
        return evaluation


# Singleton instance for route handlers
_simulator_instance: TrainingSimulator | None = None


def get_training_simulator() -> TrainingSimulator:
    global _simulator_instance
    if _simulator_instance is None:
        _simulator_instance = TrainingSimulator()
    return _simulator_instance
