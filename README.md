# 👁️ NETRA 5.0 — Cognitive Cyber Crime Intelligence & Forensic Workstation

<p align="center">
  <img src="https://img.shields.io/badge/Release-NETRA--5.0--RC1-00B4D8?style=for-the-badge&logo=shield" alt="NETRA 5.0 RC1" />
  <img src="https://img.shields.io/badge/Engineering_Validation-100%25_PASS-success?style=for-the-badge" alt="100% Pass" />
  <img src="https://img.shields.io/badge/Statutory_Standard-BSA_S.63_%7C_BNSS_S.193-gold?style=for-the-badge" alt="BSA S.63 / BNSS S.193" />
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Frontend-React_18_%7C_Vite-61DAFB?style=for-the-badge&logo=react&logoColor=black" alt="React 18" />
  <img src="https://img.shields.io/badge/PostgreSQL-16_Alpine-4169E1?style=for-the-badge&logo=postgresql&logoColor=white" alt="PostgreSQL 16" />
  <img src="https://img.shields.io/badge/Redis-7.2_Alpine-DC382D?style=for-the-badge&logo=redis&logoColor=white" alt="Redis 7.2" />
  <img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white" alt="Docker Ready" />
</p>

> **Empowering Law Enforcement & State Cyber Crime Directorates** with automated multi-modal evidence ingestion, epistemic graph reasoning, behavioral anomaly profiling, adversarial courtroom defense modeling, zero-knowledge cross-case intelligence, and tamper-evident statutory dossiers under the Bharatiya Sakshya Adhiniyam, 2023.

---

## 📌 Executive Summary

**NETRA 5.0** is an enterprise-grade, on-premise cognitive cyber-investigation workstation engineered for law enforcement agencies, cybercrime investigation divisions, and intelligence directorates.

In complex financial fraud and extortion schemes (such as "Digital Arrest" scams, multi-layer mule account syndicates, loan app extortion, and illegal payment gateway laundering), investigators are inundated with thousands of pages of unstructured evidence: Call Detail Records (CDRs), bank statements, WhatsApp chat exports, IPDR logs, and seizure memos. Manually analyzing these disparate streams takes weeks, allowing syndicates to drain accounts and vanish.

**NETRA 5.0 automates the entire investigative lifecycle**: from rapid 82-second ingestion of 18,000+ events to real-time Golden Hours asset freezing, behavioral velocity anomaly detection, cross-case syndicate clustering, adversarial trial vulnerability auditing, and automated Section 63 BSA court-ready charge sheet generation.

---

## 🚀 The 11 Canonical Investigation Capabilities (Roadmap F01–F11)

| Feature ID | Capability Name | Investigative Role | Statutory / Standard Grounding |
|:---:|---|---|---|
| **F01** | **Document Version Timeline** | Forensic lineage tracking, structural diffing, and alteration detection for forged KYC IDs and notices. | Section 63 BSA (Original vs Variant) |
| **F02** | **Behavioral Anomaly Profiler** | Detects rapid pass-through velocity (< 30m turnaround), dormant-to-burst spikes, and off-hour ATM cash drains. | RBI Master Directions on Mule Accounts |
| **F02** | **Defence Bot Adversarial Audit** | Simulates adversarial defense counsel attacks, flagging missing panchnama video timestamps and procedural gaps before trial. | Section 105 BNSS & Section 63 BSA |
| **F03** | **Syndicate Radar** | Discovers organized criminal networks across 50+ cases using Zero-Knowledge HMAC-SHA256 Blind Indexing without exposing raw citizen PII. | Section 94 BNSS Privacy Protection |
| **F04** | **Hypothesis Investigation Board** | Mathematically evaluates competing attribution hypotheses (Mule Syndicate vs Identity Theft) via Bayesian posterior ranking. | Section 173/193 BNSS Charge Sheet Drafting |
| **F05** | **Confidence Meter** | Calibrated Bayesian evidentiary health score and conformal prediction uncertainty intervals guaranteeing factual grounding. | Proof Beyond Reasonable Doubt Standard |
| **F06** | **Golden Hours Action Center** | Time-critical emergency response during the first 24–48 hours; auto-generates 9 immediate bank freeze and tower preservation orders. | NCRP 1930 / MHA Golden Hours SOP |
| **F07** | **Crime Script Matcher** | Modus Operandi (MO) fingerprinting against 6 formal cybercrime playbooks (Digital Arrest, KYC Phishing, Mule Layering, etc.). | BNS 2023 (Impersonation & Cheating) |
| **F08** | **What-If Freeze Simulator** | Counterfactual graph sandbox simulating node freezes to forecast financial bleed reduction and cut off laundering exit routes. | Section 106 BNSS (Attachment of Proceeds) |
| **F09** | **Legal Compliance Shield** | End-to-end statutory checklist validator generating exportable Section 63 BSA certificates and Section 193 BNSS charge sheet annexures. | Bharatiya Sakshya Adhiniyam, 2023 |
| **F10** | **Crime Timeline Player** | Dynamic step-by-step temporal graph replay ($\tau$-windowing) synchronizing phone calls, chat threats, and bank debits. | Courtroom Visual Evidence & IO Briefing |
| **F11** | **Training Simulator** | Interactive scenario training drills evaluating junior cyber officers on speed, accuracy, legal compliance, and action urgency. | National Police Academy Cyber Curriculum |

---

## 📊 Scale & Engineering Validation Scorecard

NETRA 5.0 has undergone a 6-stage engineering validation pass with **100% certified checkpoints**:

```
╔═══════════════════════════════════════════════════════════════════════════════════════╗
║                 NETRA 5.0 RELEASE CANDIDATE (RC1) VALIDATION METRICS                  ║
╠══════════════════════════════════════════════════╦═══════════════╦════════════════════╣
║ Benchmark Dimension                              ║ Measured Telemetry            ║ Certified Status   ║
╠══════════════════════════════════════════════════╬═══════════════╬════════════════════╣
║ Large-Case Stress Ingestion (12 Files)           ║ 18,363 Events / 1,739 Entities║ ✅ 82.14s (Pass)   ║
║ Canonical Entity Firewall Precision              ║ 0 Fabricated / Duplicates     ║ ✅ 100% Precision  ║
║ Sustained API Throughput (25 Concurrent Workers) ║ 81.68 req/s (250 Requests)    ║ ✅ 0.00% 5xx Errors║
║ Cross-Case Blind Index Search (50 Active Cases)  ║ 61.48ms (8 Syndicates Clustered)║ ✅ 0 Deadlocks   ║
║ Database Orphan Records Audit (8 Child Tables)   ║ 0 Orphaned Records Found      ║ ✅ ACID Safe       ║
║ Global Audit Chain Recomputation (1,472 Entries) ║ 27.66ms Verification Time     ║ ✅ Cryptographically Sealed║
║ Automated Test Suite                             ║ 294 / 294 Test Items Passing  ║ ✅ 100% Green      ║
╚══════════════════════════════════════════════════╩═══════════════╩════════════════════╝
```

---

## 🤖 Real Local LLM Copilot (Ollama Grounded Generation)

NETRA 5.0 integrates a local LLM generation layer over its deterministic Hybrid RAG pipeline.

```
INVESTIGATOR QUERY → HYBRID RETRIEVAL (Vector + Graph + Structured + Timeline) → RRF → RERANKER
  → CONTEXT BUILDER (Epistemic Partitioning) → PROMPT SHIELD → OLLAMA (llama3.2:1b)
  → CLAIM VERIFICATION GATE → GROUNDED ANSWER + EVIDENCE CITATIONS
```

- **Local Inference:** Runs 100% locally via Ollama with `llama3.2:1b` (`http://localhost:11434`). Zero cloud data leakage.
- **Epistemic Boundaries:** Strict separation between **Observed Facts** (directly in evidence) and **Inferred Correlations** (heuristic graph hypotheses).
- **Prompt Injection Defense:** Evidence content is wrapped inside `<untrusted_case_evidence>` and parsed by a forensic shield; adversarial instructions in evidence are quarantined.
- **Deterministic Offline Fallback:** If Ollama is unavailable, the copilot immediately falls back to `netra-grounded-fallback` with full citation grounding.
- **Claim Verification Gate:** Every claim is verified against case facts; hallucinated claims are quarantined under *"The available context does not establish"*.

---

## 🛠️ Quickstart Deployment Guide

### System Requirements
- **OS:** Linux (Ubuntu 22.04 / 24.04, Debian 12, RHEL 9) or macOS (Apple Silicon / Intel)
- **Runtime:** Python 3.10+ (Python 3.12 recommended), Node.js 18+, PostgreSQL 16+ with `pgvector`
- **LLM Engine:** Ollama with `llama3.2:1b` (Optional: offline fallback is built-in)

---

### Option A: Local Bare-Metal Development Setup

#### 1. Clone & Configure Environment
```bash
git clone https://github.com/shubhamrana2662/netra-final.git
cd netra-final
cp .env.example backend/.env
```

#### 2. Start PostgreSQL & Ollama
```bash
# Ensure PostgreSQL with pgvector is running and created database 'cyberdrishti'
# Start Ollama service and pull the lightweight model:
ollama serve &
ollama pull llama3.2:1b
```

#### 3. Backend Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

#### 4. Frontend Setup
```bash
cd ../frontend
npm install
npm run dev
```
Access the application at `http://localhost:5173` (or `http://localhost:3000`).

---

### Option B: Docker Compose Deployment

```bash
cp .env.example .env
docker compose up -d --build
```
Verify running services:
```bash
docker compose ps
curl -s http://localhost:8000/health
```

---

### 🧪 Running the Verification & Test Suites

NETRA 5.0 includes comprehensive automated test suites:

```bash
# 1. Pytest Unit & Forensic Integrity Regression Suite (18 tests)
cd backend
.venv/bin/pytest tests/test_evidence_prehash_preview.py tests/test_evidence_batch_preview.py tests/test_evidence_integrity.py tests/test_contracts_pipeline.py

# 2. Evidence Ingestion Hardening Suite (25 checks)
.venv/bin/python scratch/test_ingestion_hardening_suite.py

# 3. LLM Copilot & Ollama Verification Suite (10 checks)
.venv/bin/python scratch/test_copilot_verification_suite.py

# 4. Frontend Production Build
cd ../frontend
npm run build
```

---

## 📚 Technical Documentation & Resources

- 📖 **Operations Runbook**: [docs/DEPLOYMENT_RUNBOOK.md](docs/DEPLOYMENT_RUNBOOK.md) — Production setup, OS kernel tuning, hot backups, and disaster recovery.
- 📈 **Scale Benchmark Report**: [docs/SCALE_BENCHMARK_REPORT.md](docs/SCALE_BENCHMARK_REPORT.md) — Empirical telemetry from large-case stress tests and 50-case concurrency matrix.
- 🏛️ **System Architecture**: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — Full-stack topology, Nginx reverse proxy, and multi-tenant security boundaries.
- 🧠 **Cognitive Architecture**: [docs/COGNITIVE_ARCHITECTURE.md](docs/COGNITIVE_ARCHITECTURE.md) — Deep dive into the 11 investigation capabilities, probabilistic models, and epistemic guarantees.
- 🕵️ **Investigator's Journey**: [docs/INVESTIGATOR_JOURNEY_LARGE_CASE.md](docs/INVESTIGATOR_JOURNEY_LARGE_CASE.md) — Step-by-step case study of Inspector Sen solving "Operation Meridian" (18,363 events).
- 🎙️ **Demo Narrative & Pitch Script**: [docs/DEMO_NARRATIVE.md](docs/DEMO_NARRATIVE.md) — Timed 4-minute presentation script and Q&A defense sheet for evaluations.

---

## ⚖️ Legal & Statutory Compliance Notice

NETRA 5.0 is designed strictly to assist certified law enforcement personnel. **NETRA produces evidence-grounded, provenance-preserving investigative outputs and statutory verification artifacts; final legal admissibility and investigative decisions remain with the authorized investigator and applicable judicial process.**

All analytical outputs, behavioral anomaly alerts, and crime script matches are evidentiary drafts requiring physical Investigating Officer (IO) verification, attestation, and signature prior to court submission in compliance with Section 63 of the Bharatiya Sakshya Adhiniyam, 2023.

