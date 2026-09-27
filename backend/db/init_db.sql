-- CyberDrishti AI — Database Schema (PostgreSQL 16)
-- 8 tables: cases, evidence_files, evidence_events, entities,
--           entity_mentions, correlations, users, audit_log

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ── Users / Officers ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username    VARCHAR(64)  NOT NULL UNIQUE,
    email       VARCHAR(256) NOT NULL UNIQUE,
    hashed_password VARCHAR(256) NOT NULL,
    full_name   VARCHAR(128),
    rank        VARCHAR(64),
    unit        VARCHAR(128),
    role        VARCHAR(32) NOT NULL DEFAULT 'constable'
                  CHECK (role IN ('constable','io','fiu_analyst','admin','supervisor','INVESTIGATOR','MANAGER','ADMIN','investigator','manager')),
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Cases ────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cases (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_number     VARCHAR(64) NOT NULL UNIQUE,
    title           VARCHAR(256) NOT NULL,
    description     TEXT,
    crime_type      VARCHAR(64),
    fir_number      VARCHAR(64),
    police_station  VARCHAR(128),
    priority        VARCHAR(16) NOT NULL DEFAULT 'medium'
                      CHECK (priority IN ('high','medium','low')),
    status          VARCHAR(32) NOT NULL DEFAULT 'open'
                      CHECK (status IN ('open','in_progress','under_review','closed','on_hold')),
    assigned_officer_id UUID REFERENCES users(id) ON DELETE SET NULL,
    tags            TEXT[],
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at       TIMESTAMPTZ
);
CREATE INDEX idx_cases_status    ON cases(status);
CREATE INDEX idx_cases_priority  ON cases(priority);
CREATE INDEX idx_cases_officer   ON cases(assigned_officer_id);

-- ── Evidence Files ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence_files (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id         UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    filename        VARCHAR(512) NOT NULL,
    original_name   VARCHAR(512) NOT NULL,
    file_type       VARCHAR(64)  NOT NULL,
    source_type     VARCHAR(32),
    file_size_bytes BIGINT,
    sha256_hash     CHAR(64) NOT NULL,
    storage_path    TEXT NOT NULL,
    upload_status   VARCHAR(32) NOT NULL DEFAULT 'pending'
                      CHECK (upload_status IN ('pending','processing','processed','failed')),
    parse_error     TEXT,
    uploaded_by     UUID REFERENCES users(id) ON DELETE SET NULL,
    uploaded_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at    TIMESTAMPTZ
);
CREATE INDEX idx_evfiles_case ON evidence_files(case_id);
CREATE INDEX idx_evfiles_hash ON evidence_files(sha256_hash);
CREATE UNIQUE INDEX uq_evidence_case_sha256 ON evidence_files(case_id, sha256_hash);
CREATE UNIQUE INDEX uq_evidence_storage_path ON evidence_files(storage_path);

-- ── Evidence Events ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence_events (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id         UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    evidence_file_id UUID REFERENCES evidence_files(id) ON DELETE SET NULL,
    event_timestamp TIMESTAMPTZ,
    event_type      VARCHAR(32),   -- whatsapp_msg | bank_txn | call | ocr_text | sms
    text_content    TEXT,
    source_line     INTEGER,
    source_page     INTEGER,
    metadata        JSONB DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_evevents_case      ON evidence_events(case_id);
CREATE INDEX idx_evevents_timestamp ON evidence_events(event_timestamp);

-- ── Entities ─────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS entities (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id         UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    canonical_value VARCHAR(512) NOT NULL,
    entity_type     VARCHAR(32) NOT NULL,
                    -- PER | PHONE | UPI | ACCOUNT | AMOUNT | BANK | OTP |
                    -- EMAIL | URL | IFSC | LOCATION | KEYWORD | IP | DEVICE
    node_metadata   JSONB DEFAULT '{}'::jsonb,
    degree_centrality FLOAT,
    community_id    INTEGER,
    bridge_score    FLOAT DEFAULT 0.0,
    first_seen      TIMESTAMPTZ,
    last_seen       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_entities_case ON entities(case_id);
CREATE INDEX idx_entities_type ON entities(entity_type);
CREATE INDEX idx_entities_value ON entities USING gin(canonical_value gin_trgm_ops);

-- ── Entity Mentions (raw extractions before canonical merge) ─────────────────
CREATE TABLE IF NOT EXISTS entity_mentions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    entity_id       UUID REFERENCES entities(id) ON DELETE CASCADE,
    evidence_event_id UUID REFERENCES evidence_events(id) ON DELETE CASCADE,
    raw_value       VARCHAR(512) NOT NULL,
    entity_type     VARCHAR(32) NOT NULL,
    confidence      FLOAT DEFAULT 1.0,
    extractor       VARCHAR(32),  -- regex | cyberdrishtilm | hingbert | crf
    span_start      INTEGER,
    span_end        INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_mentions_entity ON entity_mentions(entity_id);
CREATE INDEX idx_mentions_event  ON entity_mentions(evidence_event_id);

-- ── Correlations / Hidden Links ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS correlations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id             UUID NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
    entity_a_id         UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    entity_b_id         UUID NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    link_type           VARCHAR(32) DEFAULT 'hidden_link',
    final_score         FLOAT NOT NULL,
    threshold           FLOAT NOT NULL,
    decision            VARCHAR(16) NOT NULL CHECK (decision IN ('flagged','not_flagged')),
    component_scores    JSONB NOT NULL DEFAULT '{}'::jsonb,
    model_weights       JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_citations    JSONB DEFAULT '[]'::jsonb,
    verified_by         UUID REFERENCES users(id) ON DELETE SET NULL,
    verified_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(case_id, entity_a_id, entity_b_id)
);
CREATE INDEX idx_correlations_case ON correlations(case_id);

-- ── Audit Log (tamper-evident blockchain-style chain) ────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id              BIGSERIAL PRIMARY KEY,
    prev_hash       CHAR(64) NOT NULL,
    entry_hash      CHAR(64) NOT NULL UNIQUE,
    event_timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    user_id         UUID REFERENCES users(id) ON DELETE SET NULL,
    action          VARCHAR(64) NOT NULL,
    resource_type   VARCHAR(64),
    resource_id     TEXT,
    details_json    JSONB DEFAULT '{}'::jsonb
);
CREATE INDEX idx_audit_resource ON audit_log(resource_type, resource_id);
CREATE INDEX idx_audit_user     ON audit_log(user_id);

-- ── Users / Administrator ──────────────────────────────────────────────────
-- Zero default users are created by SQL scripts. Administrators must be
-- explicitly provisioned via cli.py bootstrap-admin or authenticated seed scripts.

-- ── Audit genesis entry ────────────────────────────────────────────────────
-- Inserted by the application on first startup (audit chain setup in main.py)
