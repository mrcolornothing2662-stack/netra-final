# CyberDrishti AI / Netra 5.0 — Completion Plan

**Companion to** [`DELIVERY_REQUIREMENTS.md`](../DELIVERY_REQUIREMENTS.md) — turns that checklist
into an ordered, file-grounded execution plan, updated with the defects proved by the
baseline re-run on **both** database dialects (2026-09-14).

**Baseline facts this plan is built on** (re-verified, no repo changes made to establish it):

| Suite | SQLite | PostgreSQL 16 | Defect class |
|---|---|---|---|
| `backend/_feature_audit.py` | 48/49 | 48/49 | harness bug (illegal status value) |
| `backend/_shadow_mule_e2e.py` | 19/19 | **18/19** | 🚨 real dialect divergence in counterfactual freeze |
| `backend/tests` (pytest) | 23/23 | 23/23 | — |
| Frontend build | **not verifiable** | — | `frontend/node_modules` absent (`npm ci` needed) |

---

## 0. Verified starting point (repro commands)

```bash
P='<python-3.12 venv with backend/requirements.txt>'
cd backend
"$P" _feature_audit.py      # 48/49 on SQLite (temp DB)
"$P" _shadow_mule_e2e.py    # 19/19 on SQLite
"$P" -m pytest tests -v     # 23/23 (unit=SQLite; live tests hit :8000 server → Postgres prod DB)

# Postgres harness copies (env-honoring DATABASE_URL variant lives in /tmp, repo untouched)
"$P" /tmp/netra_prepare_run_pg.py   # → 48/49 and 18/19 against fresh DB cyberdrishti_audit_dev
```

**Three baseline findings that change the plan:**

1. **Counterfactual freeze diverges on PostgreSQL** (`_shadow_mule_e2e` 18/19 on PG).
   `EvidenceEvent.event_timestamp` is `DateTime(timezone=True)` (→ Postgres `timestamptz`).
   The bank parser emits *naive IST wall-clock* strings; Postgres interprets them in the session
   TZ (`Asia/Kolkata`) and returns offset-aware datetimes, but `cognitive/counterfactual.py::_ts`
   interprets the naive API `freeze_time` as **UTC** → the freeze lands ~5.5 h "after" every IST
   transfer → `preserved ₹0`. On SQLite naive→naive wall-clock works. **Fix is §1.1.**
2. **The single feature-audit failure is a harness bug**: `backend/_feature_audit.py:201` sends
   `{"status":"active"}`; `ck_cases_status` permits only
   `open, in_progress, under_review, closed, on_hold` → constraint violation → HTTP 500.
   **Fix is §1.2.**
3. **Schema drift**: prod `cyberdrishti` has 18 tables; a fresh `Base.metadata.create_all`
   produces 12. The 6 extras (`intelligence_assessments`, `intelligence_signals`,
   `investigation_questions`, `investigator_entities`, `investigator_relationships`,
   `relationship_explanations`) come from `db/init_db.sql` and have **zero references in current
   Python code** — legacy orphans to be handled by §2.1 (Alembic), not carried forever.

---

## 1. Fix what the baseline proved broken (correctness — do first)

### 1.1 Counterfactual freeze — PostgreSQL timezone frame  🔴 BLOCKER

- **Goal:** identical freeze results (₹275,000 preserved, 2 blocked debits for the Shadow Mule
  scenario) on both dialects.
- **Root cause chain (evidence):**
  1. `backend/parsers/bank_csv_parser.py::_parse_dt` emits **naive** ISO
     (`2026-08-18T09:50:03` — IST wall-clock from `timestamp_ist`).
  2. `backend/db/models.py` `EvidenceEvent.event_timestamp = Column(DateTime(timezone=True))`
     → on PG a naive literal is bound as `timestamptz`, interpreted in the session
     timezone (`Asia/Kolkata`), stored/read back offset-aware (`09:50:03+05:30`).
  3. `backend/routes/cognitive.py::_iso` / `_get_bank_events` pass that through.
  4. `backend/cognitive/counterfactual.py::_ts` treats a naive `freeze_time` as **UTC**,
     so on PG every IST transfer precedes the UTC-anchored freeze → nothing blocks.
- **Recommended fix (surgical):** make the engine treat *naive* timestamps as **IST** (the
  source clock of Indian bank evidence) and keep aware datetimes as-is:

  ```python
  # cognitive/counterfactual.py::_ts
  IST = timezone(timedelta(hours=5, minutes=30))
  if dt.tzinfo is None:
      dt = dt.replace(tzinfo=IST)   # naive == evidence wall-clock (IST)
  ```
  - PG reads: aware `+05:30` → compared directly against IST-anchored freeze → correct.
  - SQLite reads: naive → now explicitly IST → identical result to today.
  - Freeze-path only; `_ts` is not used by cross-stream engines. Document the new contract
    in the engine docstring: *"`freeze_time` and naive event timestamps are Indian Standard Time"*.
- **Add regression coverage:**
  - `backend/tests/test_regression_cognitive.py`: unit test that the freeze result is identical
    when the same transfer is passed with a naive timestamp vs the equivalent `+05:30`-aware
    timestamp.
  - Re-run `_shadow_mule_e2e.py` **on Postgres** (§3 harness) → must be 19/19.
- **Done when:** shadow mule 19/19 on **both** dialects; new unit test green.
- **Structural follow-up (optional, separate task):** store all event timestamps as UTC-aware
  instants at parse time (bank IST → UTC, CDR already UTC) so absolute cross-stream analytics
  are unambiguous. Requires a decision on the `freeze_time` API contract (interpret as IST).

### 1.2 Feature-audit harness — legal `status` value  🟢 trivial

- `backend/_feature_audit.py:201`: change the PATCH body from `{"status": "active"}` to a
  constraint-legal value, e.g. `{"status": "in_progress"}`; strengthen the check to assert the
  echoed status (`r.json().get("status") == "in_progress"`).
- **Done when:** `_feature_audit.py` prints **49/49** on SQLite **and** on Postgres.

---

## 2. Production safety (§3.1–3.3 of DELIVERY_REQUIREMENTS.md)

"Cheap, high-risk-if-skipped." Do these immediately after §1.

### 2.1 Database migrations — Alembic  🔴

- **Goal:** fresh DB and existing DB both converge via `alembic upgrade head`; model changes
  require a migration.
- **What:**
  1. Stand up `backend/alembic.ini` + `backend/alembic/env.py`. Use a **synchronous** engine for
     migration runs (psycopg for PG, SQLite for dev) pointed at `DATABASE_URL`; keep `asyncpg`
     out of Alembic's run path (it needs a sync driver).
  2. Baseline revision: autogenerate against `db.models.Base.metadata`, then **hand-review** —
     must match the 12 tables the app creates. Do **not** autogenerate against the prod DB or it
     will absorb the 6 legacy orphans.
  3. Second revision, `existing_db_bridge`: makes the current prod 18-table DB reach the same
     head. Decide (recommend **drop**): the 6 orphan tables have no code references; either
     `DROP TABLE` them in the migration or leave documented as out-of-band. Confirm the
     `evidence_events.metadata` rename (already applied in prod) has no-op guards.
  4. Startup wiring: keep `Base.metadata.create_all` for dev-only no-op convenience, but add
     `alembic upgrade head` as the canonical release step in `start.sh`, `docker-compose.yml`,
     and the Dockerfile CMD. Optionally call `alembic upgrade head` from `main.py` lifespan when
     `ENVIRONMENT=production`.
  5. CI guard (repo script `backend/scripts/check_migrations.py`): fail if any
     `db/models.py` change has no corresponding revision file (compare `alembic check` /
     autogenerate diff with `--autogenerate --sql`).
- **Files:** `backend/alembic.ini`, `backend/alembic/env.py`, `backend/alembic/versions/*`,
  `backend/scripts/check_migrations.py`, `backend/start.sh`, `docker-compose.yml`,
  `backend/Dockerfile`, `backend/main.py`.
- **Done when:** `alembic upgrade head` converges a fresh DB and the existing `cyberdrishti`
  prod DB (test on a copy) to identical schemas; CI guard blocks an un-migrated model change.

### 2.2 Credentials — no default/backdoor admin  🔴

- **Goal:** no guessable accounts; forced first-login password change.
- **What:**
  1. Delete the dev-authenticated backdoor in `backend/routes/auth.py:140–170`: no lazy seeding
     from `username == 'rana'`, no acceptance of plaintext `admin123` / `rana123` / `admin`.
     Login verifies **only** the bcrypt hash (`$2b$` …).
  2. Remove the `rana` user from any seeding path (grep `rana` across `backend/`).
  3. `backend/config.py`: default `initial_admin_password` must be **empty** when
     `ENVIRONMENT=production`; seeding (`backend/main.py::_ensure_admin_seed`) refuses to run
     with an empty/weak value in prod (fail-fast — see §2.3).
  4. Forced first-login change: add `users.must_change_password BOOLEAN NOT NULL DEFAULT …`
     (migration §2.1, set `TRUE` for the seeded initial admin), an endpoint
     `POST /api/v1/auth/change-password`, and a frontend redirect to a change-password screen when
     the JWT carries `must_change_password: true` (include the flag in the token claims or `/me`).
- **Files:** `backend/routes/auth.py`, `backend/db/models.py`, `backend/config.py`,
  `backend/main.py`, `backend/routes/officers.py` (password rules), frontend `src/screens/auth/`.
- **Done when:** a production boot with no explicit admin secret creates **no** account and
  refuses to start (§2.3); first login forces a password change before any case work.

### 2.3 Secrets & environment — fail-fast boot  🔴

- **Goal:** one documented env contract; the app refuses to start in prod with missing/weak
  secrets.
- **What:**
  1. Create `backend/.env.example` documenting every var from `backend/config.py` (DB URL,
     `SECRET_KEY`, `INITIAL_ADMIN_USERNAME/PASSWORD`, `ARMORIQ_API_KEY`, `OLLAMA_BASE_URL`,
     `ALLOW_CLOUD_AI`, `UPLOAD_DIR`, `CHROMA_PERSIST_DIR`, `CORS_ORIGINS`, …).
  2. Boot validation in `backend/main.py` lifespan (before tables are created): when
     `ENVIRONMENT=production`, require `DATABASE_URL`, `SECRET_KEY` ≥ 32 chars and ≠
     `CHANGE_ME_IN_PRODUCTION_32_CHAR_MIN`, `INITIAL_ADMIN_PASSWORD` set; print the missing list
     and `raise RuntimeError`. Generate a strong dev secret via `openssl rand -hex 32`.
  3. Rotate the JWT `algorithm`/key handling: keep `HS256`, keyed off `SECRET_KEY`.
- **Files:** `backend/.env.example`, `backend/main.py`, `backend/config.py`.
- **Done when:** `ENVIRONMENT=production` boot with a missing/weak secret exits non-zero with an
  explicit list; dev boots unchanged.

---

## 3. Postgres verification lock-in (§3.4)

- **Goal:** the full feature audit + regression suites are green **on Postgres**, not just SQLite.
- **What:**
  1. Institutionalize the env-honoring harness: change `backend/_feature_audit.py` and
     `backend/_shadow_mule_e2e.py` from hard-setting `DATABASE_URL` to
     `os.environ.setdefault("DATABASE_URL", "<temp sqlite>")` (this is the only repo source change
     required — the /tmp copies proved it works).
  2. Update `backend/tests/test_regression_correlations.py` which currently hard-sets SQLite, so
     it also honors an external `DATABASE_URL` for its import-guard engine.
  3. Document the two canonical runs (SQLite temp; `postgresql+asyncpg://…/cyberdrishti_audit_dev`)
     in `docs/COMMANDS.md`, including creating the isolated PG database
     (`CREATE DATABASE cyberdrishti_audit_dev; ALTER DATABASE … OWNER TO cyberdrishti;`).
- **Done when:** `_feature_audit.py` = 49/49 and `_shadow_mule_e2e.py` = 19/19 on
  **PostgreSQL 16**, with the isolation commands documented.

---

## 4. Fiction → honest (§2 of DELIVERY_REQUIREMENTS.md)

These need a product decision ("build vs badge"). With no government API credentials available,
the plan defaults to **honest badge**; every indicator must reflect a real backend-reported state
or be unambiguously labelled simulated.

### 4.1 Settings → Integrations tab (NCRP / DoT / FIU-IND + AI engine)  🟠

- **Problem (verified):** `frontend/src/screens/settings/Settings.tsx:525–610` renders badges
  `CONNECTED / READY / ONLINE / RUNNING` for NCRP 1930, DoT CMS/CDR&IPDR, FIU-IND Finnet 2.0,
  and an "AI Neural Inference Engine" — none of these connections or runtime claims exist
  (health shows `cyberdrishtilm: false, hingbert: false`).
- **What (badge path):**
  1. New endpoint `GET /api/v1/settings/integrations` returning a real, honest status per
     connector: `{"id": "ncrp", "status": "simulated", "simulated": true,
     "detail": "No live credentials configured"}`; drive the AI card's runtime flags from
     `/api/v1/ml/models` (the real registry).
  2. Frontend: render a prominent **"SIMULATED / DEMO — not connected to live services"** banner,
     replace green badges with grey `SIMULATED` chips, disable action controls (title tooltip:
     "Requires production credentials"), and add the provenance tag `SYNTHETIC_DEMO` per the
     project standard.
- **Done when:** every indicator on the tab comes from a real endpoint response; nothing
  on the tab can be mistaken for a live connection.

### 4.2 Section 65B certificate — remove HSM/"hardware-signing" claims  🟠

- **Problem (verified):** `frontend/src/screens/settings/Settings.tsx:~412–418` advertises a
  "PKCS#11 Cryptographic Hardware Security Module" enclave; the PDF may carry signing language
  (`backend/report/templates/*`).
- **What (honest output path):** grep `backend/report/` + `frontend/src` for
  `HSM|PKCS|hardware sign|digital certificate`; replace with the established "analysis aid"
  language — the artifact is an **evidentiary draft** whose court admissibility requires IO
  verification (already mandated by Phase 7 for BSA 2023 §63) — and state that cryptographic
  signing is **not applied** in this build.
- **Done when:** no reachable UI or generated PDF implies a hardware signature that the build
  does not produce.

### 4.3 ML model claims  🟠

- `README.md` / UI copy claiming a "~2.3M param CyberDrishtiLM" / "HingBERT fine-tune" being
  *active* are currently fiction: `backend/artifacts/cyberdrishtilm` and `hingbert` are absent
  and `/health` reports them unloaded. Either provision real artifacts (§5.3) or scope the copy
  to "deterministic extraction, ML-ready with fallback". Keep the honest fallback path intact.

---

## 5. Feature completion (§4 of DELIVERY_REQUIREMENTS.md)

### 5.1 Live event streaming (SSE)  🟠

- **Current (verified):** `backend/routes/analytics.py:822–847` (`events_router`) emits only a
  connection ack + 5 s heartbeats; the frontend has **no** SSE consumer
  (`frontend/src/api/` has no events module).
- **What:**
  1. In-process `asyncio` hub, `backend/utils/event_bus.py`: per-case `case_id` subscriber sets
     with `Queue`s; `publish(case_id, event)` / `subscribe(case_id)`.
  2. Wire `event_generator()` in `routes/analytics.py` to the hub (ack + heartbeat stay), and
     **publish real domain events only** from the exact mutation points:
     - evidence finished processing → `backend/routes/evidence.py` background parse task
       (`ingestion.file_processed`, payload = real status + hash prefix),
     - correlation flagged → `backend/routes/correlations.py` when a decision row is created,
     - agent action executed / hold raised → `backend/armoriq/agent.py` +
       `backend/routes/agent.py` (`agent.action`, `agent.hold_created`).
  3. Frontend `frontend/src/api/events.ts`: connect via `EventSource` (sends no headers —
     authorize via a short-lived `?token=` minted from the login JWT) + auto-reconnect; case
     screen renders a live activity feed. No fabricated activity — the hub only forwards what
     producers publish.
- **Done when:** uploading evidence or running the agent yields visible, real-time events in a
  connected browser tab consistent with audit-log records; ack/heartbeat unchanged.

### 5.2 Autonomous agent — run to completion & hold approval  🟡

- **Decision point (docs §4.2):** recommend keeping `modify_network_control_config` **out of**
  **scope** — it is the entire governance demo
  (`backend/armoriq/agent.py:89–98` declares the plan; ArmorIQ blocks by design).
- **What (option b — governance block as success):**
  1. When a run ends after a governance block, expose a terminal status `governance_blocked`
     from `backend/routes/agent.py` `GET /agent/{case_id}/status`.
  2. Frontend: render the block as **"CONTROL FIRED — perimeter change blocked (governance)"** —
     an intended/success outcome with a deep link to the holds queue; never a red "failed".
  3. Exercise the human **approve / reject hold** flow end-to-end: verify
     `backend/routes/agent.py` has approve/reject endpoints (add if missing, with audit entries;
     approval performs the real sandbox write via `armoriq/sandbox.py`), and add the flow as an
     E2E check in `_shadow_mule_e2e.py`.
- **Done when:** a default agent run terminates in a state the UI frames as success (completed
  or governance-blocked), and an approved hold performs the real sandbox write.

### 5.3 Externally-provisioned capabilities (fallback-honest until provisioned)  ⚪

- **ArmorIQ real SDK** (`ARMORIQ_API_KEY`): the stub is correct and safe; provision the key and
  verify intent-verification against the real SDK, else keep the stub and label it
  (`backend/armoriq/`).
- **ML artifacts** (CyberDrishtiLM/HingBERT): place real checkpoints at
  `backend/artifacts/{cyberdrishtilm,hingbert}`; confirm the loader picks them up and measure
  extraction vs the deterministic fallback. Until then, keep the honest fallback (§4.3).
- **Copilot / LLM provider:** choose Ollama (`llama3.2:1b`, currently offline on this machine)
  or another provider; run the CRAG verify-draft firewall against the real model.

---

## 6. Cross-cutting — "coordinating as intended" (§5 of DELIVERY_REQUIREMENTS.md)

### 6.1 End-to-end investigator journey  🟠

- **What:** a scripted walkthrough (the Shadow Mule E2E is the pipeline backbone — add the
  missing UI-level steps): login → create case → upload evidence → **live** processing feed (§5.1)
  → timeline & graph → cognitive analysis → agent run → **approve a hold** (§5.2) → generate 65B
  PDF → verify audit chain — every screen fed by the previous step's real output.
- **Deliverable:** `docs/WALKTHROUGH.md` + the E2E additions to `backend/_shadow_mule_e2e.py`.

### 6.2 Frontend ↔ backend contract integrity  🟠

- Re-audit for mocked/derived fallbacks (e.g., any remaining `DEMO_TRANSACTION_DATA`-style data;
  Phase 7 removed the transactions/communications ones — verify nothing regressed), confirm every
  screen consumes a real endpoint (`frontend/src/api/`), and that disconnecting the backend
  produces graceful error/empty/loading states, not blank screens. Covers §5.2 of the
  requirements doc.

### 6.3 Role-based access across the full surface  🟠

- Extend the existing IDOR checks (`backend/tests/test_live_integration.py`) beyond
  cases/evidence/correlations to: `intel/cross-match` (the CURRENT_STATE_AUDIT flagged it exposes
  all cases to any authenticated officer — add case-scope/jurisdiction filtering to
  `backend/routes/analytics.py` cross-match query), `intelligence/*`, `agent/*`, `report/*`,
  `cognitive/*`. Verifies a non-owner IO cannot read/mutate another officer's case through any
  endpoint or screen.

### 6.4 Deployment topology  🟡

- Decide: Vercel (`vercel.json` multi-service routing) or self-hosted. Document the env contract
  (§2.3) for the target; confirm CORS origins include the real origin; DB must be reachable from
  the deployed backend; `/api/v1` proxying must behave exactly as local. Deliverable:
  `docs/PRODUCTION_DEPLOYMENT.md` with the verified deploy steps + smoke test.

---

## 7. Definition of Done — master gate checklist

Maps to the quality gates in DELIVERY_REQUIREMENTS §6. A box is only ticked when **re-verified
after the last code change**.

- [ ] `_feature_audit.py` **49/49 on Postgres** (was 48/49 — §1.2 fixes the harness)
- [ ] `_feature_audit.py` **49/49 on SQLite**
- [ ] `_shadow_mule_e2e.py` **19/19 on Postgres** (was 18/19 — §1.1 fixes the freeze)
- [ ] `_shadow_mule_e2e.py` **19/19 on SQLite**
- [ ] pytest regression + contract suites **green on both dialects** (23/23 + new tests)
- [ ] Frontend build green (`npm ci && npm run build` once deps are installed) + no console
      errors on the core journey
- [ ] No reachable fiction without a "SIMULATED/DEMO" badge (§4)
- [ ] Migrations exist and apply cleanly to a fresh **and** an existing DB (§2.1)
- [ ] No default/guessable credentials in prod; first-login password change works (§2.2)
- [ ] Required secrets validated at boot; prod refuses to start otherwise (§2.3)
- [ ] End-to-end investigator journey passes manually (§6.1)
- [ ] Role/IDOR checks pass across the full surface (§6.3)
- [ ] Deployed URL behaves as local (§6.4)

---

## 8. Suggested execution order & effort

| Step | Workstream | Why this order | Effort |
|---|---|---|---|
| 1 | **§1.1 freeze fix** + regression test | Baseline-proven defect; correctness gate | S (hours) |
| 2 | **§1.2 audit harness status** | Unblocks 49/49 on PG | XS |
| 3 | **§2.2–2.3 credentials & secrets** | High-risk, cheap | S–M |
| 4 | **§2.1 Alembic** + orphan-table bridge | Unblocks clean schema evolution; do before any new column work | M |
| 5 | **§3 Postgres verification lock-in** | Proves 49/49/19/19 on PG after 1–4 | S |
| 6 | **§4 fiction badges** (integrations, 65B, ML copy) | Product-honesty gate before demo | S–M |
| 7 | **§6.2–6.3 contract + RBAC** | Cross-cutting; cheaper before 5.1 lands on top | M |
| 8 | **§5.1 SSE real events** + frontend feed | Demo-critical "watch it process live" | M–L |
| 9 | **§5.2 agent completion + holds UI** | Demo-critical governance outcome | M |
| 10 | **§6.1 walkthrough, §6.4 deploy, §7 gate** | Final proof + production | M–L |
| 11 | **§5.3 external provisioning** (SDK/ML/LLM) | Requires external credentials/artifacts | on demand |

Legend: 🔴 = blocks delivery · 🟠 = required for an honest demo · 🟡 = required for prod ·
⚪ = conditional on external provisioning.