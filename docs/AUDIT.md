# 🛡️ NETRA 5.0 (CyberDrishti AI) — Security & Engineering Hardening Audit
**Document:** `docs/AUDIT.md`  
**Author:** Senior Backend & Security Hardening Engineer  
**Branch:** `hardening/phase-0-audit`  
**Target Audience:** Smart India Hackathon Police & Security Evaluation Panel  
**Evaluation Standard:** Absolute honesty, evidence-grounded metrics, statutory precision, and hardened security.

---

## 1. Executive Summary & Audit Baseline

An exhaustive technical audit of the NETRA 5.0 codebase was conducted on September 19, 2026. 

### Core Audit Findings
1. **Algorithmic Substance**: The mathematical foundations of several analytical engines are genuinely implemented in pure Python (discrete-event counterfactual simulation, Continuous-Time Dynamic Graph slicing, Levenshtein sequence alignment, MinHash document diffing, and split-conformal prediction sets).
2. **Security Deficits**: The codebase currently exhibits critical security hygiene flaws: default hardcoded credentials (`admin/admin123`), lack of MFA, unencrypted file storage on disk, overly long JWT expiration (8 hours) with no revocation blocklist, and coarse RBAC where any admin can read any case.
3. **Audit Ledger Limitations**: The current cryptographic audit chain in `AuditLog` is only tamper-evident against unauthorized DB updates; a malicious DBA can mutate a row and recalculate the subsequent hash chain in-place because no external signed checkpoints exist.
4. **Legal & Epistemic Inflation**: Documentation and UI strings use inflated legal and cryptographic claims (e.g., claiming HMAC-SHA256 is "Zero-Knowledge", citing repealed Section 65B of the Evidence Act, misattributing Section 94 BNSS as a "privacy protection" law, and citing "court-admissible" rather than "designed to support admissibility").

---

## 2. Capability Completeness Assessment: Engines F01–F11

Every engine was audited strictly from **active code**, ignoring documentation claims.

| Engine ID | Name | Code Completeness | Active Code Locations | Actual Mechanism in Code | Gaps, Heuristics & Grounding Reality |
|:---:|---|:---:|---|---|---|
| **F01** | **Document Version Timeline** | **REAL** | [`backend/cognitive/fingerprint.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/fingerprint.py), [`version_impact.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/version_impact.py) | 3-tier fingerprinting: Tier 1 SHA-256 byte exact; Tier 2 optional TLSH binary fuzzy; Tier 3 MinHash (128 permutations) over normalized canonical tuples with Jaccard containment and structural diff. | Real implementation. Optional TLSH requires native C-lib `py-tlsh` (falls back cleanly to MinHash if absent). |
| **F02 (A)** | **Behavioral Anomaly Profiler** | **REAL** | [`backend/cognitive/anomaly.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/anomaly.py), [`contradiction.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/contradiction.py) | Computes empirical baselines (Mean, StdDev, Median, MAD); detects rapid pass-through velocity (<30m), circadian surges (00:00–05:00), and spatial velocity (Haversine distance vs time drift). | Real implementation. Features honest epistemic abstention when $N < 3$ transactions. |
| **F02 (B)** | **Defence Bot Adversarial Audit** | **PARTIAL** | [`backend/cognitive/defence.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/defence.py) | Deterministic rule-based critic auditing panchnama compliance, missing CAF/KYC, and Section 63 BSA certificate presence. Computes a defensibility score. | **Not an LLM or autonomous adversarial agent.** It is a structured rule-based heuristic checklist. Highly useful for standardizing police objections, but should not be marketed as AI red-teaming. |
| **F03** | **Syndicate Radar** | **REAL** *(Misnamed)* | [`backend/cognitive/crosscase.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/crosscase.py), [`routes/cognitive.py`](file:///Users/shubhamrana/netra5.0/backend/routes/cognitive.py) | Hard identifier canonicalization + deterministic `HMAC-SHA256(val, secret_key)` matching; bipartite graph clustering with polar radar coordinate generation. | **NOT Zero-Knowledge.** HMAC-SHA256 is a keyed PRF / deterministic MAC. Low-entropy values (10-digit phone numbers) can be brute-forced if a key leaks. Must be renamed "Keyed Blind Index". |
| **F04** | **Hypothesis Investigation Board** | **PARTIAL** | [`backend/cognitive/hypothesis.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/hypothesis.py), [`cognitive/data/hypothesis_model.json`](file:///Users/shubhamrana/netra5.0/backend/cognitive/data/hypothesis_model.json) | Evaluates competing theories under Heuer's Analysis of Competing Hypotheses (ACH) using Bayesian likelihood updates over a discrete likelihood matrix. | Static JSON likelihoods and hardcoded priors. Must move priors to configurable settings and clearly label outputs as investigative decision-support. |
| **F05** | **Confidence Meter (Lead Score)** | **REAL** *(Misleading Framing)* | [`backend/cognitive/uncertainty.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/uncertainty.py) | Distribution-free split-conformal prediction sets (Vovk / Angelopoulos & Bates) computing quantile $\hat{q}$ for coverage $P(Y \in C(X)) \ge 1 - \epsilon$. | Mathematical core is genuine. However, documentation falsely cited "statutory proof beyond reasonable doubt" (which is a common-law judicial standard, not a statute). Must be renamed "Evidence Strength / Lead Score". |
| **F06** | **Golden Hours Action Center** | **REAL** | [`backend/cognitive/nextbest.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/nextbest.py), [`cognitive/data/action_catalog.json`](file:///Users/shubhamrana/netra5.0/backend/cognitive/data/action_catalog.json) | Multi-window urgency decay ($U(t) = \exp(-t / T_{half})$) for assets (2h), CCTV/panchnama (24h), telecom (48h); auto-renders pre-filled statutory notice drafts with mandatory DRAFT banner. | Real heuristic ranking engine. Correctly blocks notice generation if mandatory fields are missing. |
| **F07** | **Crime Script Matcher** | **REAL** | [`backend/cognitive/mo.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/mo.py), [`cognitive/data/crime_scripts.json`](file:///Users/shubhamrana/netra5.0/backend/cognitive/data/crime_scripts.json) | Extracts ordered stage tokens from multi-modal events and matches against 6 crime playbooks (Digital Arrest, Phishing, Mule Ring, etc.) via normalized Levenshtein edit distance. | Real implementation. Cites stage-by-stage evidence; issues `NO_CONFIDENT_MATCH` if below threshold. |
| **F08** | **What-If Freeze Simulator** | **REAL** | [`backend/cognitive/counterfactual.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/counterfactual.py) | 4-stage discrete-event network flow replay. Blocks debit attempts on frozen accounts, calculates cascade starvation of downstream mules, and computes lower-bound ₹ preserved. | Real simulation. Uses single-pool balance tracking (implicit FIFO). Needs user-selectable accounting tracing assumptions (FIFO / LIFO / Proportional) and must cite BNSS s.107 instead of s.106. |
| **F09** | **Legal Compliance Shield** | **REAL** | [`backend/cognitive/verifier.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/verifier.py), [`cognitive/data/statutory_db.json`](file:///Users/shubhamrana/netra5.0/backend/cognitive/data/statutory_db.json) | Deterministic AST statutory citation parser (BNS/BNSS/BSA transition, struck-down laws), regex multi-entity span grounding, and SHA-256 custody checks. | Real deterministic verification engine. Sits directly between copilots and investigators. |
| **F10** | **Crime Timeline Player** | **REAL** | [`backend/cognitive/replay.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/replay.py) | Continuous-Time Dynamic Graph (CTDG) discrete sampler. Computes active nodes, edges, exponential decay opacity, and communication burst frames. | Real implementation. Pure function converting chronological events into playback frames. |
| **F11** | **Training Simulator** | **REAL** | [`backend/cognitive/training.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/training.py), [`benchmark.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/benchmark.py) | Procedural synthetic case generator with planted ground truth, evaluation against cadet actions, and 4-pillar scoring (Speed, Accuracy, Compliance, Action). | Real implementation. Strictly isolates synthetic training data from real case databases. |

---

## 3. Phase-by-Phase Technical Audit & Action Plans

---

### Phase 1 — Security Hygiene

#### Item 1.1: Default Hardcoded Credentials & Password Security
* **Current State:**
  * `backend/config.py:88` defines default `initial_admin_password: str = "admin123"`.
  * `backend/seed_demo_case.py`, `_feature_audit.py`, `quickstart.ps1`, `docs/COMMANDS.md`, and numerous test files explicitly pass and print `admin / admin123`.
  * Password hashing in `backend/routes/auth.py` uses legacy `bcrypt` instead of memory-hard `argon2id`.
  * `main.py` blocks startup in production if `admin123` is used, but development allows it to persist indefinitely.
* **Files Involved:**
  * [`backend/config.py`](file:///Users/shubhamrana/netra5.0/backend/config.py)
  * [`backend/routes/auth.py`](file:///Users/shubhamrana/netra5.0/backend/routes/auth.py)
  * [`backend/main.py`](file:///Users/shubhamrana/netra5.0/backend/main.py)
  * [`backend/seed_demo_case.py`](file:///Users/shubhamrana/netra5.0/backend/seed_demo_case.py)
  * [`quickstart.ps1`](file:///Users/shubhamrana/netra5.0/quickstart.ps1)
  * Documentation files: `README.md`, `docs/GETTING_STARTED.md`, `docs/COMMANDS.md`.
* **Fix Plan:**
  1. Remove `initial_admin_password = "admin123"` fallback from `config.py`.
  2. Implement a dedicated CLI bootstrap command: `python -m backend.cli bootstrap-admin` (or read from mandatory `INITIAL_ADMIN_PASSWORD` env var with min 14 chars).
  3. Set `must_change_password = True` on initial admin creation; block all API endpoints except `/auth/change-password` until changed.
  4. Replace `bcrypt` with `argon2id` (via `passlib.context.CryptContext(schemes=["argon2"], ...)`).
  5. Update all tests and documentation to use dynamic credentials or test fixtures.

#### Item 1.2: Absolute Local Paths and `file://` Scrubbing
* **Current State:**
  * Absolute paths containing `/Users/shubhamrana/...` are present in `test_fresh_case_pipeline.py`, `scratch/*.py`, `backend/tests/test_seizure_memo.py`, `test_location_timeline.py`, `test_upi_transaction_report.py`, `test_network_log.py`, and `scratch/netra5_backup_snapshot.sql`.
  * Hardcoded `/Users/shubhamrana/Downloads/...` causes tests to fail on any other developer's or evaluator's workstation.
* **Files Involved:**
  * [`backend/test_fresh_case_pipeline.py`](file:///Users/shubhamrana/netra5.0/backend/test_fresh_case_pipeline.py)
  * [`backend/tests/test_seizure_memo.py`](file:///Users/shubhamrana/netra5.0/backend/tests/test_seizure_memo.py)
  * [`backend/tests/test_location_timeline.py`](file:///Users/shubhamrana/netra5.0/backend/tests/test_location_timeline.py)
  * [`backend/tests/test_network_log.py`](file:///Users/shubhamrana/netra5.0/backend/tests/test_network_log.py)
  * [`backend/tests/test_bank_pdf_and_device_extraction.py`](file:///Users/shubhamrana/netra5.0/backend/tests/test_bank_pdf_and_device_extraction.py)
  * All scripts in `scratch/`.
* **Fix Plan:**
  1. Replace all hardcoded absolute paths with `pathlib.Path(__file__).resolve().parents[...]` or environment variables (`TEST_DATA_DIR`).
  2. For evidence storage paths in the database, store paths relative to `UPLOAD_DIR`, resolving them dynamically at runtime.
  3. Ensure zero instances of `/Users/` or `file:///Users/` remain in tracked repository files.

#### Item 1.3: Secrets Scan & Pre-Commit Hook
* **Current State:**
  * `.gitignore` ignores `.env` and `*.env`, but mistakenly ignored `backend/.env.example` due to `.env.*` glob.
  * No automated pre-commit hook currently blocks commits containing private keys, high-entropy tokens, or passwords.
* **Files Involved:**
  * [`.gitignore`](file:///Users/shubhamrana/netra5.0/.gitignore)
  * `.pre-commit-config.yaml` (new file)
* **Fix Plan:**
  1. Fix `.gitignore` to allow `.env.example` (`!.env.example`).
  2. Integrate `gitleaks` / `detect-secrets` into a `.pre-commit-config.yaml` hook.
  3. Run a repository-wide history and tree scan to guarantee no live API keys exist.

#### Item 1.4: TOTP Multi-Factor Authentication (MFA)
* **Current State:**
  * `backend/routes/auth.py` and `backend/db/models.py:User` have no MFA or TOTP support whatsoever.
* **Files Involved:**
  * [`backend/db/models.py`](file:///Users/shubhamrana/netra5.0/backend/db/models.py)
  * [`backend/routes/auth.py`](file:///Users/shubhamrana/netra5.0/backend/routes/auth.py)
  * New migration in `backend/alembic/versions/`
  * [`frontend/src/screens/auth/Login.tsx`](file:///Users/shubhamrana/netra5.0/frontend/src/screens/auth/Login.tsx)
* **Fix Plan:**
  1. Add Alembic migration adding `totp_secret: String(64)`, `totp_enabled: Boolean(default=False)` to `users` table.
  2. Implement TOTP enrollment endpoints: `/api/v1/auth/totp/setup` (emits standard `otpauth://` URI / QR) and `/api/v1/auth/totp/verify` (verifies initial token before enabling).
  3. Update `/api/v1/auth/login`: If user role is `admin` or `io`, check `totp_enabled`. If enabled, return a short-lived `mfa_pending_token`; require `/api/v1/auth/totp/login` with code to issue the final JWT.
  4. Update frontend login view to support the 2-step TOTP code prompt.

#### Item 1.5: Per-Case Access Control & Audit-Logged Denials
* **Current State:**
  * In [`backend/routes/case_access.py`](file:///Users/shubhamrana/netra5.0/backend/routes/case_access.py#L36), admins bypass all case boundaries: `if current.role != "admin" and not assigned: raise HTTPException(404)`.
  * Access decisions (both grants and denials) are not recorded in the audit ledger.
  * No supervisor approval workflow exists for report/dossier export.
* **Files Involved:**
  * [`backend/routes/case_access.py`](file:///Users/shubhamrana/netra5.0/backend/routes/case_access.py)
  * [`backend/routes/reports.py`](file:///Users/shubhamrana/netra5.0/backend/routes/reports.py)
  * [`backend/db/models.py`](file:///Users/shubhamrana/netra5.0/backend/db/models.py)
* **Fix Plan:**
  1. Refactor `require_case_access`: Admin cannot read case contents by default unless explicitly added as a case collaborator or during an emergency audit mode.
  2. Explicitly write every authorization success AND authorization failure (`403`/`404`) to `AuditLog` (`action="CASE_ACCESS_ALLOWED" | "CASE_ACCESS_DENIED"`).
  3. Add a `dossier_export_approvals` table: Exporting a Section 63 BSA dossier requires a supervisor approval record (`status="APPROVED"`, signed by `approver_id`).

#### Item 1.6: JWT Hardening, Rotation, Revocation List & Rate Limiting
* **Current State:**
  * Access tokens expire in 480 minutes (8 hours) with no refresh mechanism.
  * Logging out only deletes the token client-side; leaked JWTs remain valid until natural expiry.
  * No login attempt rate limiting or account lockout after failed attempts.
* **Files Involved:**
  * [`backend/routes/auth.py`](file:///Users/shubhamrana/netra5.0/backend/routes/auth.py)
  * [`backend/config.py`](file:///Users/shubhamrana/netra5.0/backend/config.py)
* **Fix Plan:**
  1. Reduce access token TTL to 15 minutes.
  2. Implement refresh tokens (stored in Redis or HTTP-only cookies) with rotation (one-time use).
  3. Implement Redis-backed token revocation list (`jti` blocklist) checked on every authenticated request.
  4. Implement sliding-window rate limiting on `/auth/login` (5 attempts per 5 minutes per IP/username), locking the account for 15 minutes after 5 consecutive failures and logging to `AuditLog`.

#### Item 1.7: File Vault Envelope Encryption at Rest
* **Current State:**
  * In [`backend/routes/evidence.py#L115-L126`](file:///Users/shubhamrana/netra5.0/backend/routes/evidence.py#L115-L126), seized files are written as raw plaintext directly to disk.
* **Files Involved:**
  * [`backend/routes/evidence.py`](file:///Users/shubhamrana/netra5.0/backend/routes/evidence.py)
  * `backend/utils/encryption.py` (new file)
* **Fix Plan:**
  1. Implement an envelope encryption provider: generate a random per-file DEK (Data Encryption Key, 256-bit AES-GCM); encrypt file contents on disk using DEK; encrypt DEK using the KEK (Key Encryption Key) from a KeyProvider interface.
  2. Store encrypted file as `<uuid>.enc` with prepended IV and encrypted DEK header.
  3. Build pluggable `KeyProvider`: `EnvKeyProvider` (dev/testing) and interface for `KMSKeyProvider` / `PKCS11KeyProvider` (production on-prem).

---

### Phase 2 — Audit Ledger Integrity

#### Item 2.1: Signed Periodic Checkpoints (Ed25519)
* **Current State:**
  * The hash chain in `AuditLog` connects each row to `prev_hash`. However, because the chain lives solely in PostgreSQL, anyone with SQL access (`UPDATE audit_logs SET ...`) can tamper with an entry and recompute all downstream hashes without detection.
* **Files Involved:**
  * [`backend/db/models.py`](file:///Users/shubhamrana/netra5.0/backend/db/models.py)
  * `backend/services/audit_checkpoint.py` (new file)
  * [`backend/main.py`](file:///Users/shubhamrana/netra5.0/backend/main.py)
* **Fix Plan:**
  1. Implement an out-of-database signed checkpoint daemon/scheduler: every $N$ entries (e.g. 50) or $T$ minutes (e.g. 15m), reads the latest `entry_hash`, signs it using a private Ed25519 key (stored outside PostgreSQL on a separate read-only mount / environment), and appends to an append-only file `audit_checkpoints.jsonl`.
  2. Support an optional RFC 3161 Timestamping Authority (TSA) HTTP hook interface.

#### Item 2.2: `verify_ledger` Service, API & CLI Command
* **Current State:**
  * Only an HTTP endpoint `GET /api/v1/audit/verify` exists. It checks hash chain continuity, but has no concept of external checkpoint verification.
* **Files Involved:**
  * [`backend/routes/audit.py`](file:///Users/shubhamrana/netra5.0/backend/routes/audit.py)
  * `backend/cli.py` (new file)
* **Fix Plan:**
  1. Refactor ledger verification into a core service `backend/services/audit_verifier.py`.
  2. Verify two layers:
     * **Layer 1 (Internal):** Hash chain continuity ($\text{Hash}_n = \text{SHA256}(\text{prev} \,\|\, \text{entry})$).
     * **Layer 2 (External):** Verification of head hashes against signed Ed25519 checkpoints in `audit_checkpoints.jsonl`.
  3. Expose via both REST API (`GET /api/v1/audit/verify`) and CLI: `python -m backend.cli verify-ledger`. Report exact index of any discrepancy.

#### Item 2.3: Ledger Tamper Detection Tests
* **Current State:**
  * Existing tests only test that an unmanipulated chain returns intact. There are no tests verifying that mutating a row and recomputing all hashes is detected.
* **Files Involved:**
  * `backend/tests/test_audit_tamper_detection.py` (new test file)
* **Fix Plan:**
  1. Test A: Mutate a single historical audit row $\to$ verify chain fails on hash mismatch.
  2. Test B: Mutate a historical audit row AND recompute all subsequent row hashes in Postgres $\to$ verify that external checkpoint signature verification detects the forgery.

#### Item 2.4: Terminology Scrub: "Immutable" $\to$ "Tamper-Evident"
* **Current State:**
  * Code and docs claim "Immutable Audit Ledger" (e.g., `AUDIT_GENESIS_SEED = CYBERDRISHTI_GENESIS # Immutable Audit Ledger Anchor`).
* **Files Involved:**
  * [`backend/config.py`](file:///Users/shubhamrana/netra5.0/backend/config.py)
  * `docs/*.md`, frontend UI labels.
* **Fix Plan:**
  * Replace the word "immutable" with "tamper-evident" across all code, API responses, UI components, and documentation.

#### Item 2.5: Ingestion Hash vs. Original Seizure Hash Clarification
* **Current State:**
  * The system computes SHA-256 upon file receipt (`evidence_files.sha256_hash`). Documentation conflates this with evidence integrity from the moment of physical device seizure.
* **Files Involved:**
  * [`backend/db/models.py:EvidenceFile`](file:///Users/shubhamrana/netra5.0/backend/db/models.py)
  * [`backend/report/section_65b.py`](file:///Users/shubhamrana/netra5.0/backend/report/section_65b.py)
  * New Alembic migration
* **Fix Plan:**
  1. Add fields to `EvidenceFile`: `source_device_hash: Optional[str]`, `acquisition_tool: Optional[str]`, `acquisition_timestamp: Optional[datetime]`, `officer_notes: Optional[str]`.
  2. Clearly document in the generated Section 63 BSA certificate that ingestion SHA-256 verifies integrity from the moment of workstation upload, while `source_device_hash` certifies the original physical forensic extraction.

---

### Phase 3 — "Zero-Knowledge" Blind Index Hardening

#### Item 3.1: Rename "Zero-Knowledge" $\to$ "Keyed Blind Index"
* **Current State:**
  * Code (`backend/cognitive/crosscase.py:11`, `routes/cognitive.py:1474`), docs, and UI brand the feature as "Zero-Knowledge HMAC-SHA256 Blind Indexing".
* **Files Involved:**
  * [`backend/cognitive/crosscase.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/crosscase.py)
  * [`backend/routes/cognitive.py`](file:///Users/shubhamrana/netra5.0/backend/routes/cognitive.py)
  * Frontend UI components: `frontend/src/screens/case/tabs/CognitiveTab.tsx`
* **Fix Plan:**
  * Systematically rename "Zero-Knowledge" to "Keyed Blind Index" across all classes, docstrings, API schemas, and UI badges.

#### Item 3.2: Domain Separation & Secret Key Rotation
* **Current State:**
  * `crosscase.py` uses a single department secret key across all data types. If an HMAC output leaks, an attacker can test all entity types uniformly.
* **Files Involved:**
  * [`backend/cognitive/crosscase.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/crosscase.py)
* **Fix Plan:**
  1. Implement per-field-type domain separation:
     $$\text{Token} = \text{HMAC-SHA256}\Big(\text{Key}_{\text{agency}}, \;\; \text{"NETRA-v1:"} \,\|\, \text{Type} \,\|\, \text{":"} \,\|\, \text{Value}\Big)$$
     where $\text{Type} \in \{\text{PHONE}, \text{ACCOUNT}, \text{UPI}, \text{IMEI}\}$.
  2. Implement key versioning (`key_id`) to support periodic key rotation.
  3. Rate-limit cross-case query requests in `routes/cognitive.py` and write every cross-case collision check to `AuditLog`.

#### Item 3.3: Comprehensive Threat Model Documentation
* **Current State:**
  * No threat model document exists.
* **Files Involved:**
  * `docs/THREAT_MODEL.md` (new file)
* **Fix Plan:**
  * Create `docs/THREAT_MODEL.md` detailing:
    * Key compromise scenarios.
    * Offline dictionary attacks against low-entropy 10-digit Indian phone numbers ($10^{10}$ space).
    * Malicious insider risks.
    * Cross-jurisdictional leakage limits.
    * Future work: Private Set Intersection (PSI) and Oblivious Pseudorandom Functions (OPRF).

---

### Phase 4 — Statutory & Legal References

#### Item 4.1: Centralized Legal Reference Source of Truth
* **Current State:**
  * Statutory section numbers are hardcoded as string literals across dozens of files (`verifier.py`, `copilot.py`, `nextbest.py`, `counterfactual.py`, `section_65b.py`, tests).
* **Files Involved:**
  * `backend/report/legal_refs.py` (new file)
* **Fix Plan:**
  1. Create `backend/report/legal_refs.py` as the authoritative dictionary mapping every legal reference.
  2. Refactor all backend routes, cognitive engines, report generators, and tests to import from `legal_refs.py`.

#### Item 4.2: Statutory Verification & Misattribution Fixes
* **Current State:**
  * **BNSS s.94:** Misattributed in F03 as "Cross-Case Privacy Protection". Actual statute: Summons to produce documents or things.
  * **BNSS s.106 vs s.107:** F08 What-If Freeze cites s.106 ("Seizure of Property"). The actual statute for attachment/freezing of proceeds of crime is **Section 107 BNSS**.
  * **F05 Grounding:** Cited "proof beyond reasonable doubt" as a statutory grounding.
* **Files Involved:**
  * [`backend/cognitive/crosscase.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/crosscase.py)
  * [`backend/cognitive/counterfactual.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/counterfactual.py)
  * [`backend/cognitive/uncertainty.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/uncertainty.py)
  * [`backend/report/legal_refs.py`](file:///Users/shubhamrana/netra5.0/backend/report/legal_refs.py)
* **Fix Plan:**
  1. Correct F03: Cite Section 94 BNSS accurately as the authority for inter-agency document requisitions; clarify that privacy protection is a cryptographic design feature.
  2. Correct F08: Cite Section 107 BNSS (attachment of proceeds) and Section 106(3) BNSS (report to Magistrate).
  3. Correct F05: Remove statutory claim for "proof beyond reasonable doubt"; classify as an investigative evidentiary lead scoring tool.

#### Item 4.3: Unverified Legal Item Tracking
* **Current State:**
  * Items needing judicial review are scattered.
* **Files Involved:**
  * [`docs/NEEDS_HUMAN.md`](file:///Users/shubhamrana/netra5.0/docs/NEEDS_HUMAN.md)
* **Fix Plan:**
  * Log all unverified legal assumptions with `TODO(VERIFY)` in `docs/NEEDS_HUMAN.md` for human legal review.

#### Item 4.4 & 4.6: Migration from Section 65B to Section 63 BSA Schedule
* **Current State:**
  * File is named `backend/report/section_65b.py` and emits repealed Section 65B Indian Evidence Act certificates.
  * Does not follow the two-part structure (Part A / Part B) mandated by the Schedule to the Bharatiya Sakshya Adhiniyam, 2023.
* **Files Involved:**
  * [`backend/report/section_65b.py`](file:///Users/shubhamrana/netra5.0/backend/report/section_65b.py) $\to$ rename to `backend/report/section_63_bsa.py`
  * [`backend/routes/reports.py`](file:///Users/shubhamrana/netra5.0/backend/routes/reports.py)
* **Fix Plan:**
  1. Rename module to `backend/report/section_63_bsa.py` and update all imports.
  2. Rebuild HTML/PDF template to strictly mirror the official Schedule under Section 63 BSA:
     * **Part A:** Certificate by the person in lawful control of the device/system.
     * **Part B:** Certificate by an authorized digital forensics expert / analyst.
  3. Include cryptographic hash value declarations and device identifiers.

#### Item 4.5: Admissibility Language Scrub
* **Current State:**
  * UI and documentation frequently state "Court-Admissible Dossier" or "Admissible Evidence".
* **Files Involved:**
  * `README.md`, `docs/*.md`, report templates.
* **Fix Plan:**
  * Systematically replace with: *"Designed to support admissibility under Section 63 BSA (subject to judicial determination)"*.
  * Add a permanent disclaimer banner on all generated PDF and JSON dossiers.

---

### Phase 5 — Entity Resolution Safety

#### Item 5.1 & 5.2: Soft-ID Proposed Merges & Transitive Closure Prevention
* **Current State:**
  * In [`backend/graph/graph_builder.py#L101-L105`](file:///Users/shubhamrana/netra5.0/backend/graph/graph_builder.py#L101-L105), any soft pair with similarity $\ge 0.85$ is merged via `UnionFind.union(ids[i], ids[j])`.
  * Allows transitive chaining: $A \sim B$ (0.86) and $B \sim C$ (0.86) merges $A$ and $C$ even if $A \not\approx C$.
  * Merges happen automatically without officer knowledge or confirmation.
* **Files Involved:**
  * [`backend/graph/graph_builder.py`](file:///Users/shubhamrana/netra5.0/backend/graph/graph_builder.py)
  * [`backend/routes/evidence.py`](file:///Users/shubhamrana/netra5.0/backend/routes/evidence.py)
  * [`backend/db/models.py`](file:///Users/shubhamrana/netra5.0/backend/db/models.py)
* **Fix Plan:**
  1. Hard-ID matches (phone, account, UPI, IMEI) continue to merge automatically.
  2. Soft-ID matches (names, locations) are marked as `PROPOSED_MERGE` with similarity score and reasoning; they do not merge canonical entities in the database until an officer confirms.
  3. Replace pure Union-Find transitive closure with **average-linkage** or **complete-linkage (all-pairs)** clustering.
  4. Enforce a maximum cluster size (default: 5) and flag oversized clusters for manual inspection.

#### Item 5.3: Reversible Merges & Split Operation
* **Current State:**
  * No entity split mechanism exists. Once merged, decoupling requires manual SQL updates.
* **Files Involved:**
  * [`backend/db/models.py`](file:///Users/shubhamrana/netra5.0/backend/db/models.py)
  * `backend/routes/entities.py` (new endpoints)
* **Fix Plan:**
  1. Add `EntityMergeHistory` table tracking merged entities, proposing officer, confirming officer, and previous canonical states.
  2. Implement `POST /api/v1/entities/{id}/split` endpoint allowing officers to reverse any merge, restoring original entity nodes and re-assigning mentions.

#### Item 5.4: Comprehensive Resolution Safety Tests
* **Current State:**
  * Existing tests do not evaluate near-duplicate chaining or common Indian name collisions.
* **Files Involved:**
  * `backend/tests/test_entity_resolution_safety.py` (new test file)
* **Fix Plan:**
  * Add unit tests verifying:
    1. Transitive chain prevention ($A \sim B$, $B \sim C$, but $A \ne C$).
    2. Distinction between common Indian name variants (e.g. "Rahul Kumar" vs "Rahul Kumari", "Amit Sharma" vs "Anil Sharma").
    3. Proper split operation and audit ledger trail.

---

### Phase 6 — Honest Confidence & Inferred Links

#### Item 6.1: Rename Confidence Meter $\to$ "Evidence Strength / Lead Score"
* **Current State:**
  * F05 is branded as "Confidence Meter", implying definitive judicial confidence.
* **Files Involved:**
  * [`backend/cognitive/uncertainty.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/uncertainty.py)
  * [`backend/routes/cognitive.py`](file:///Users/shubhamrana/netra5.0/backend/routes/cognitive.py)
  * Frontend UI tabs and components.
* **Fix Plan:**
  1. Rename F05 to "Evidence Strength / Lead Score" in code, APIs, and UI.
  2. Clearly display the underlying components (direct observation vs heuristic rule vs conformal set).
  3. Add explicit label to every inferred edge and posterior score: *"Investigative lead — not evidence"*.

#### Item 6.2: Strict Exclusion of Inferred Leads from Section 63 Dossiers
* **Current State:**
  * Inferred relationships and findings can appear in generated reports if not filtered.
* **Files Involved:**
  * [`backend/report/section_63_bsa.py`](file:///Users/shubhamrana/netra5.0/backend/report/section_65b.py)
  * [`backend/routes/reports.py`](file:///Users/shubhamrana/netra5.0/backend/routes/reports.py)
* **Fix Plan:**
  1. Enforce strict filtering in Section 63 BSA dossiers: include **`OBSERVED`** relationships only by default.
  2. Provide an explicit, audit-logged opt-in switch (`include_investigative_leads=True`) that renders inferred leads in a separate, clearly demarcated annexure.

#### Item 6.3: Precision Gate Reading from Stored Validation Report
* **Current State:**
  * In [`backend/graph/hidden_link_engine.py:27`](file:///Users/shubhamrana/netra5.0/backend/graph/hidden_link_engine.py#L27), `MIN_PRECISION = 0.90` is hardcoded, and the engine defaults to threshold `0.5` if unfitted.
* **Files Involved:**
  * [`backend/graph/hidden_link_engine.py`](file:///Users/shubhamrana/netra5.0/backend/graph/hidden_link_engine.py)
* **Fix Plan:**
  1. Refactor `HiddenLinkEngine` to load its operational threshold from a verified `validation_report.json` generated by Phase 7 evaluation.
  2. If no valid report is found, the engine refuses to emit inferred links and reports `status="unvalidated"`.

#### Item 6.4: Configurable Bayesian Priors for F04
* **Current State:**
  * F04 priors are embedded in static JSON without documented justification or UI visibility.
* **Files Involved:**
  * [`backend/cognitive/hypothesis.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/hypothesis.py)
  * [`backend/cognitive/data/hypothesis_model.json`](file:///Users/shubhamrana/netra5.0/backend/cognitive/data/hypothesis_model.json)
* **Fix Plan:**
  1. Move Bayesian hypothesis priors into configurable settings with documented empirical baselines.
  2. Expose the prior distribution and update formula in the UI.

#### Item 6.5: Parameterized Fund Tracing in F08
* **Current State:**
  * F08 What-If Freeze Simulator tracks account balances in a single pool, assuming greedy/implicit FIFO.
* **Files Involved:**
  * [`backend/cognitive/counterfactual.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/counterfactual.py)
* **Fix Plan:**
  1. Expose `tracing_method` parameter: `FIFO` (First-In First-Out), `LIFO` (Last-In First-Out), or `PROPORTIONAL`.
  2. Document in the UI and report outputs that results are mathematical simulations dependent on the chosen accounting assumption.

---

### Phase 7 — Validation Harness

#### Item 7.1: Synthetic Data Generator (`tools/synth/`)
* **Current State:**
  * No standalone synthetic generator exists in a dedicated tools directory. Existing benchmarks rely on ad-hoc files or pre-baked zip archives.
* **Files Involved:**
  * `tools/synth/generator.py` (new directory and file)
  * `tools/synth/bank_formats.py` (new file)
* **Fix Plan:**
  1. Build a reproducible, seeded generator capable of producing:
     * CDR/tower dumps ($\ge 1\text{M}$ rows).
     * Multi-bank statement variants (at least 4 distinct format variations across SBI, HDFC, ICICI, Axis).
     * WhatsApp / Telegram chat transcripts with Hinglish slang.
     * Planted ground truth: known mule chains, rapid pass-throughs, circadian bursts, ATM cash-outs, and benign decoys.
  2. Save ground-truth labels in a separate, isolated JSON file.

#### Item 7.2: Automated Evaluation Harness (`tools/eval/run_eval.py`)
* **Current State:**
  * No unified evaluation script generates tracked JSON telemetry.
* **Files Involved:**
  * `tools/eval/run_eval.py` (new file)
  * `docs/metrics/latest.json` (new file)
  * `docs/METRICS.md` (new file)
* **Fix Plan:**
  1. Build `tools/eval/run_eval.py` to evaluate:
     * Mule / Anomaly detection Precision / Recall / F1 (F02).
     * Parser success rate across all bank and telecom format variants.
     * NER Precision / Recall / F1 by entity type.
     * Entity resolution pairwise Precision / Recall.
     * Link prediction precision at threshold.
     * Crime Script Matcher accuracy (F07).
     * Ingestion throughput (rows/sec, wall time, peak memory) at 18k, 100k, and 1M rows.
  2. Export results to `docs/metrics/latest.json` and generate human-readable `docs/METRICS.md`. Clearly label all metrics as **SYNTHETIC-DATA EVALUATION**.

#### Item 7.3: Dynamic Metric Injection into Documentation
* **Current State:**
  * Benchmark numbers in `README.md` and `docs/SCALE_BENCHMARK_REPORT.md` were manually typed.
* **Files Involved:**
  * `tools/eval/inject_metrics.py` (new file)
  * `README.md`
* **Fix Plan:**
  * Build a script that reads `docs/metrics/latest.json` and programmatically updates documentation markdown tables.

---

### Phase 8 — Scalability & Architecture

#### Item 8.1: Ingestion Hotspots & Bulk COPY Optimization
* **Current State:**
  * Ingestion in `backend/routes/evidence.py` iterates row-by-row with individual `db.add(EvidenceEvent(...))` calls.
* **Files Involved:**
  * [`backend/routes/evidence.py`](file:///Users/shubhamrana/netra5.0/backend/routes/evidence.py)
* **Fix Plan:**
  1. Refactor event and mention ingestion to use PostgreSQL `asyncpg` bulk COPY or batched `db.execute(insert(EvidenceEvent).values([...]))` in chunks of 5,000 rows.
  2. Add composite indexes on `(case_id, event_timestamp)` and evaluate partitioning for `evidence_events`.

#### Item 8.2: Bounded In-Memory NetworkX Graph Loading
* **Current State:**
  * `backend/routes/graph.py` queries all case entities and relationships into memory before calling `select_relevant_subgraph`.
* **Files Involved:**
  * [`backend/routes/graph.py`](file:///Users/shubhamrana/netra5.0/backend/routes/graph.py)
  * [`backend/graph/graph_builder.py`](file:///Users/shubhamrana/netra5.0/backend/graph/graph_builder.py)
* **Fix Plan:**
  1. Push subgraph filtering down to PostgreSQL using recursive Common Table Expressions (CTEs) or parameterized $k$-hop SQL queries.
  2. Strictly bound in-memory NetworkX construction to requested node limits with clear UI notices when views are truncated.

#### Item 8.3: Real Background Job Queue (Arq / Redis)
* **Current State:**
  * Long-running analytical tasks run unmanaged in standard asyncio request loops without job persistence or retry guarantees.
* **Files Involved:**
  * `backend/worker.py` (new file)
  * `backend/services/job_queue.py` (new file)
* **Fix Plan:**
  1. Integrate **Arq** (async Redis-based job queue) for heavy analytical tasks (F02 scans, large-case graph builds, synthetic generation).
  2. Stream task progress, status, and completion to the frontend over Server-Sent Events (SSE).

#### Item 8.4: Comparative Benchmark Recording
* **Current State:**
  * No before/after performance comparison.
* **Files Involved:**
  * `docs/METRICS.md`
* **Fix Plan:**
  * Re-run evaluation harness post-optimization and record before/after speedups and memory footprints in `docs/METRICS.md`.

---

### Phase 9 — Demo Focus & Human-in-the-Loop

#### Item 9.1: Guided 5-Minute Demo Flow Script
* **Current State:**
  * No single script guides an evaluator through the core workflow end-to-end.
* **Files Involved:**
  * `tools/demo/run_demo.py` (new file)
  * `docs/DEMO_GUIDE.md` (new file)
* **Fix Plan:**
  * Create `tools/demo/run_demo.py`: seeds a clean case $\to$ ingests synthetic evidence $\to$ identifies mule ring $\to$ executes What-If freeze simulation $\to$ exports signed Section 63 BSA dossier in under 5 minutes on a standard laptop.

#### Item 9.2: "Labs" Feature Flag for Non-Core Engines
* **Current State:**
  * All 11 engines are displayed simultaneously in navigation, overwhelming users and reviewers.
* **Files Involved:**
  * `frontend/src/screens/case/CaseView.tsx`
  * `frontend/src/config/features.ts` (new file)
* **Fix Plan:**
  1. Establish a clear core investigation path in the primary UI:
     * **Core Path:** Behavioral Anomaly (F02), Syndicate Radar (F03), Golden Hours (F06), What-If Freeze (F08), Section 63 Compliance Shield (F09), plus Interactive Graph & Timeline.
  2. Move experimental engines (F01, F04, F07, F10, F11) behind an explicit "Labs / Experimental" toggle.

#### Item 9.3: Click-Through Evidence Citations & Anti-Hallucination Validator
* **Current State:**
  * LLM copilot responses sometimes state factual amounts without explicit record references.
* **Files Involved:**
  * [`backend/cognitive/verifier.py`](file:///Users/shubhamrana/netra5.0/backend/cognitive/verifier.py)
  * [`backend/copilot/`](file:///Users/shubhamrana/netra5.0/backend/copilot/)
* **Fix Plan:**
  1. Integrate the `verifier.py` output verifier into the copilot response stream.
  2. Every entity or amount mention in generated text must link to an underlying `event_id` or `evidence_file_id`.
  3. Flag any uncited claim with a visible warning and require officer sign-off before report export.

---

### Phase 10 — Documentation Rewrite & Reality Alignment

#### Item 10.1: Engineering Report Rewrite
* **Current State:**
  * Documentation contains promotional adjectives ("enterprise-grade", "5.0 cognitive workstation", "cryptographically sealed", "court-admissible").
* **Files Involved:**
  * `README.md`
  * [`docs/ARCHITECTURE.md`](file:///Users/shubhamrana/netra5.0/docs/ARCHITECTURE.md)
* **Fix Plan:**
  * Rewrite `README.md` and `ARCHITECTURE.md` as an objective engineering report detailing architecture, threat models, assumptions, technical limitations, and synthetic benchmark results.

#### Item 10.2: Clarification of "CyberDrishtiLM"
* **Current State:**
  * Marketing documents imply CyberDrishtiLM is a sovereign LLM.
* **Files Involved:**
  * `README.md`
  * [`docs/COGNITIVE_ARCHITECTURE.md`](file:///Users/shubhamrana/netra5.0/docs/COGNITIVE_ARCHITECTURE.md)
  * [`docs/NEEDS_HUMAN.md`](file:///Users/shubhamrana/netra5.0/docs/NEEDS_HUMAN.md)
* **Fix Plan:**
  * Explicitly state that **CyberDrishtiLM is a 2.3M parameter custom transformer encoder** built for token classification (Named Entity Recognition) and binary fraud sentence classification on Hinglish text. Document that generative co-pilot capabilities rely on local Ollama models (e.g. Llama-3.2) or external APIs.

#### Item 10.3: Roadmap & Unimplemented Scope Section
* **Current State:**
  * Unclear boundaries between what works today and future aspirations.
* **Files Involved:**
  * `README.md`
* **Fix Plan:**
  * Add a dedicated "Roadmap / Not Implemented" section explicitly listing:
    * Blockchain / Cryptocurrency / USDT-TRC20 tracing.
    * True Private Set Intersection (PSI) for cross-agency sharing.
    * Regional Indian language user interfaces.
    * Direct API integration with NCRP / CFCFRMS and bank nodal-officer portals.
    * Formal DPDP Act data retention and purging policies.

#### Item 10.4: Tool Comparison Placeholder
* **Current State:**
  * No structured comparison with industry standard tools.
* **Files Involved:**
  * `README.md`
* **Fix Plan:**
  * Add a dedicated comparison placeholder section comparing NETRA with IBM i2 Analyst's Notebook, Maltego, and official I4C platforms, left ready for user input.

---

## 4. Phase 0 Completion & Approval Gate

* **Branch:** `hardening/phase-0-audit`
* **Deliverable Files:**
  * [`docs/AUDIT.md`](file:///Users/shubhamrana/netra5.0/docs/AUDIT.md) (this document)
  * [`docs/NEEDS_HUMAN.md`](file:///Users/shubhamrana/netra5.0/docs/NEEDS_HUMAN.md) (decisions and verification items)
* **Status:** **PHASE 0 AUDIT COMPLETE.** No code changes made. Awaiting user review and formal approval before commencing **Phase 1 (Security Hygiene)**.
