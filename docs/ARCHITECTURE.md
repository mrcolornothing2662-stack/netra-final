# NETRA 5.0 — System Architecture Specification

**System Version**: 5.0.0-RC1 (Release Candidate 1)  
**Classification**: Law Enforcement & Forensic Enterprise Architecture  
**Governing Standards**: Bharatiya Sakshya Adhiniyam (BSA), 2023 (Section 63) & Bharatiya Nagarik Suraksha Sanhita (BNSS), 2023 (Sections 94 & 193)  
**Status**: Engineering Validation Complete / Architecture Frozen

---

## 1. Executive Full-Stack Topology

NETRA 5.0 is an enterprise cyber-investigation workstation and cognitive intelligence platform engineered for law enforcement agencies, cybercrime investigation cells, and forensic intelligence directorates.

```mermaid
graph TB
    subgraph ClientTier ["1. Presentation & Ingress Tier"]
        ClientBrowser["Investigator Workstation<br/>(Modern Web Browser)"]
        ReverseProxy["Nginx Alpine Reverse Proxy<br/>(:80 / :443)<br/>• 100MB Forensic Body Limit<br/>• Unbuffered SSE Streaming<br/>• WebSocket Upgrade Support<br/>• OWASP Security Headers"]
        StaticBundle["Compiled React / Vite Assets<br/>(2.17 MB Dist Bundle)<br/>• 5 JS Chunks + 1 CSS<br/>• SPA HTML5 Route Fallback"]
    end

    subgraph APITier ["2. High-Concurrency API & Security Gateway"]
        BackendAPI["FastAPI 0.115 / Uvicorn Server<br/>(:8000)<br/>• 81 Published Route Paths<br/>• Distributed Trace ID Engine<br/>• Multi-Tenant Anti-Enumeration<br/>• Fail-Fast Boot Security Gate"]
        
        subgraph Middlewares ["Middleware Stack"]
            OWASP["OWASP Headers Middleware<br/>(nosniff, DENY, XSS-block)"]
            TraceEngine["Trace ID Propagation<br/>(X-Request-ID, X-Trace-ID)"]
            AuthRBAC["JWT & RBAC Security Layer<br/>(Lockout after 5 failures)"]
        end
    end

    subgraph ForensicIngestion ["3. Forensic Multi-Modal Ingestion & Firewall"]
        IngestRouter["Evidence Ingestion Router<br/>(/api/v1/evidence/upload)"]
        
        subgraph Parsers ["12 Specialized Parsers"]
            BankParser["Bank CSV / PDF Parser"]
            CDRParser["CDR / Call Log Parser"]
            ChatParser["WhatsApp / Chat Parser"]
            NetParser["Network / IP Log Parser"]
            LocParser["Location Timeline Parser"]
            MemoParser["Seizure Memo (S.105 BNSS)"]
            DevParser["Device Extraction JSON"]
        end
        
        CanonicalFirewall["Canonical Entity Firewall<br/>• E.164 (+91) Telephone Normalizer<br/>• UPI VPA & Bank Acc Validator<br/>• Zero Synthetic Duplication Gate"]
    end

    subgraph CognitiveLayer ["4. Cognitive Investigation Layer (Roadmap F01-F11)"]
        CognitiveOrchestrator["Cognitive Investigation Orchestrator<br/>(Async Execution Pipeline)"]
        
        subgraph CognitiveEngines ["Investigation Capabilities"]
            F01["F01: Document Version Lineage"]
            F02A["F02: Behavioral Anomaly Profiler"]
            F02B["F02: Defence Bot Adversarial Audit"]
            F03["F03: Syndicate Radar & Cross-Case"]
            F04["F04: Hypothesis Investigation Board"]
            F05["F05: Confidence Meter (Bayesian)"]
            F06["F06: Golden Hours Action Center"]
            F07["F07: Crime Script Matcher (MO)"]
            F08["F08: What-If Freeze Simulator"]
            F09["F09: Legal Compliance Shield"]
            F10["F10: Crime Timeline Player"]
            F11["F11: Training Simulator"]
        end
    end

    subgraph PersistenceTier ["5. Resilient Storage & Cryptographic Provenance"]
        PG["PostgreSQL 16 Relational Engine<br/>• Connection Pool (25 base, 50 overflow)<br/>• pg_advisory_xact_lock (Audit Serialization)<br/>• 0 Orphaned Records Enforced<br/>• Deep Relational Foreign Key Indexing"]
        RedisStore["Redis 7.2 Engine<br/>• Task Queues & Caching<br/>• Session & Rate Limiting Storage"]
        ChromaStore["ChromaDB Vector Store<br/>• Case-Isolated Dense Embeddings"]
        AuditLedger["Cryptographic SHA-256 Hash Chain<br/>(1,472+ Tamper-Evident Entries)"]
    end

    ClientBrowser -->|HTTPS Requests| ReverseProxy
    ReverseProxy -->|Static Assets| StaticBundle
    ReverseProxy -->|API Proxy /api/*| BackendAPI
    ReverseProxy -->|SSE Stream /stream/*| BackendAPI
    ReverseProxy -->|WebSocket /ws/*| BackendAPI

    BackendAPI --> Middlewares
    Middlewares --> IngestRouter
    Middlewares --> CognitiveOrchestrator

    IngestRouter --> Parsers
    Parsers --> CanonicalFirewall
    CanonicalFirewall -->|Materialized Events & Entities| PG
    
    CognitiveOrchestrator --> CognitiveEngines
    CognitiveEngines -->|Read Ground Truth| PG
    CognitiveEngines -->|Persist Verified Findings| PG
    CognitiveEngines -->|Cryptographic Sealing| AuditLedger

    BackendAPI --> PG
    BackendAPI --> RedisStore
    BackendAPI --> ChromaStore
```

---

## 2. End-to-End Forensic Data Lifecycle

The NETRA 5.0 data lifecycle ensures complete bit-for-bit evidentiary integrity under Section 63 of the Bharatiya Sakshya Adhiniyam (BSA), 2023:

```mermaid
sequenceDiagram
    autonumber
    actor IO as Investigating Officer
    participant Proxy as Nginx Reverse Proxy
    participant API as FastAPI Backend
    participant Ingest as Forensic Ingestion & Firewall
    participant DB as PostgreSQL 16
    participant Cognitive as Cognitive Layer (F01-F11)
    participant Audit as Cryptographic Hash Chain

    IO->>Proxy: Upload Evidence ZIP / Files (multipart/form-data)
    Proxy->>API: Route to /api/v1/evidence/upload (X-Request-ID generated)
    API->>API: Compute SHA-256 digest at byte boundary
    API->>Ingest: Stream to specialized parsers (Bank, CDR, Chat, Seizure Memo)
    Ingest->>Ingest: Canonicalize entities (Phone, UPI, Account, Device)
    Ingest->>DB: Atomically persist EvidenceFiles, Events, Entities, Mentions
    Ingest->>Audit: Append EVIDENCE_UPLOADED (Advisory Lock + SHA-256 seal)
    
    IO->>Proxy: Trigger Investigation Run (/api/v1/intelligence/cases/{id}/analyze)
    Proxy->>API: Forward analysis dispatch
    API->>Cognitive: Orchestrate active capabilities
    Note over Cognitive: F02 Anomaly, F06 Golden Hours, F07 Crime Script, F05 Confidence, F02 Defence Bot
    Cognitive->>DB: Fetch case graph, timeline, and entity relationships
    Cognitive->>DB: Persist typed InvestigationFindings (severity, citations, scores)
    Cognitive->>Audit: Append COGNITIVE_ANALYSIS_RUN with parameter snapshot
    
    API-->>IO: Real-time findings & radar telemetry via unbuffered SSE
    IO->>API: Request Court-Admissible Dossier (/api/v1/report/{case_id})
    API->>DB: Gather verified findings, evidence digests, panchnama memos
    API->>Audit: Verify unbroken SHA-256 chain from genesis
    API-->>IO: Export Section 63 BSA & Section 193 BNSS PDF Dossier
```

---

## 3. Trust Boundaries & Multi-Tenant Security

NETRA 5.0 enforces defense-in-depth across 5 operational security boundaries:

```mermaid
graph LR
    subgraph PublicUntrusted ["Boundary 0: Public / Network"]
        Attacker["Adversary / Prober"]
    end

    subgraph SecurityPerimeter ["Boundary 1: Ingress Gateway"]
        NginxShield["Nginx Reverse Proxy<br/>• Request Size Gate (100MB)<br/>• Anti-Clickjacking (DENY)<br/>• MIME-Type Sniffing Shield<br/>• Static Asset Isolation"]
    end

    subgraph ApplicationSecurity ["Boundary 2: Application Core"]
        RateLimiter["Rate Limiting & Lockout<br/>(5 failed logins -> HTTP 429)"]
        JWTValidator["Cryptographic JWT Verifier<br/>(HMAC-SHA256, Exp, Foreign Key block)"]
        AntiEnum["Anti-Enumeration Multi-Tenant Gate<br/>(Cross-case access returns strict 404)"]
        SQLSanitizer["SQLAlchemy Parameterization<br/>(Zero string-interpolated SQL)"]
    end

    subgraph PrivacyShield ["Boundary 3: Cross-Case Intelligence"]
        BlindIndex["Zero-Knowledge Blind Indexing<br/>(HMAC-SHA256 Salted Hash Token)<br/>• Cross-match syndicates without PII exposure<br/>• Section 94 BNSS Privacy Compliant"]
    end

    subgraph DataIntegrity ["Boundary 4: Evidence & Audit"]
        AdvisoryLock["PostgreSQL Advisory Lock<br/>(Serialized Hash Chain Ledger)"]
        SHASeal["Bit-for-Bit SHA-256 File Ledger"]
    end

    Attacker -->|Brute Force Attempt| RateLimiter
    Attacker -->|Forged JWT / alg:none| JWTValidator
    Attacker -->|Case ID Probe / IDOR| AntiEnum
    Attacker -->|SQLi Injection Payloads| SQLSanitizer
    
    AntiEnum --> BlindIndex
    BlindIndex --> AdvisoryLock
    AdvisoryLock --> SHASeal
```

---

## 4. Containerized Micro-Services Topology

The production stack is deployed using Docker Compose or Kubernetes:

| Service Name | Container Image | Host Port | Internal Port | Health Check | Storage Mount |
|---|---|---|---|---|---|
| `frontend` | Multi-Stage (Node 20 $\to$ Nginx Alpine) | `3000` | `80` | `GET /` $\to$ 200 OK | Read-only static assets |
| `backend` | Python 3.10 / FastAPI Alpine | `8000` | `8000` | `GET /health` $\to$ healthy | `/app/uploads` persistent volume |
| `db` | PostgreSQL 16 Alpine | `5432` | `5432` | `pg_isready -U netra_admin` | `/var/lib/postgresql/data` NVMe |
| `redis` | Redis 7.2 Alpine | `6379` | `6379` | `redis-cli ping` | Ephemeral / AOF volume |
| `adminer` | Adminer 4.8 (Optional DBA) | `8080` | `8080` | Native HTTP | None |

---

## 5. Architectural Verification & Guarantees

1. **High Concurrency Throughput**: Evaluated across 25 concurrent workers sustaining 81.68 req/s across 250 requests with 0.00% error rate.
2. **Deterministic Database ACID Rollover**: Transaction rollbacks verified under check-constraint fault injections, guaranteeing zero orphaned records across 8 relational tables.
3. **Continuous Cryptographic Auditability**: Recomputes and validates 1,472 global audit entries in 27.66ms using PostgreSQL transactional advisory locking (`pg_advisory_xact_lock`).
4. **Statutory Admissibility**: Every evidence artifact is immutably anchored with a SHA-256 digest at ingestion, enabling verifiable certificate generation under Section 63 of Bharatiya Sakshya Adhiniyam, 2023.
