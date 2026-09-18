# NETRA 5.0 — Production Deployment & Operations Runbook

**Document Version**: 5.0.0-PROD  
**Classification**: Law Enforcement & Enterprise Sensitive (Forensic Grade)  
**Governing Standards**: Bharatiya Sakshya Adhiniyam, 2023 (Section 63) & Bharatiya Nagarik Suraksha Sanhita, 2023 (Sections 94 & 193)  
**Status**: Certified & Production Ready

---

## 1. System Architecture & Topology

NETRA 5.0 is an enterprise-grade cyber-investigation workstation and cognitive intelligence platform engineered for law enforcement agencies, cybercrime investigation divisions, and intelligence directorates.

The production deployment consists of five isolated containerized micro-services managed via Docker Compose or Kubernetes:

```
                  ┌──────────────────────────────────────────────┐
                  │          External Ingress (HTTPS / 443)      │
                  └──────────────────────┬───────────────────────┘
                                         │
                                         ▼
                 ┌─────────────────────────────────────────────────┐
                 │       Frontend Service (Port 3000 -> 80)        │
                 │      Nginx Reverse Proxy & Alpine Linux         │
                 │  - Client Body Limit: 100MB                     │
                 │  - Unbuffered SSE (proxy_buffering off)         │
                 │  - WebSocket Upgrades (Connection "upgrade")    │
                 │  - Gzip & Brotli Static Asset Caching           │
                 │  - Single Page Application (SPA) HTML5 Fallback │
                 └───────────────┬─────────────────┬───────────────┘
                                 │                 │
              Static UI Assets   │                 │ API Proxy (/api/*)
             (Compiled React/Vite)│                │ WebSocket (/ws/*)
                                 ▼                 ▼
                       [ Browser Client ]  ┌─────────────────────────────────┐
                                           │    Backend Service (Port 8000)   │
                                           │    FastAPI + Uvicorn Async API  │
                                           │  - Distributed Trace ID Engine  │
                                           │  - OWASP Security Middlewares   │
                                           │  - 10 Cognitive AI Engines      │
                                           │  - Zero-Knowledge Blind Index   │
                                           └───────────┬────────────┬────────┘
                                                       │            │
                           SQL Transactions & Locking   │            │ Redis Pub/Sub
                         (SQLAlchemy Connection Pool)  │            │ & Task Queue
                                                       ▼            ▼
                         ┌─────────────────────────────────┐ ┌───────────────┐
                         │   Database Service (PostgreSQL) │ │ Redis Engine  │
                         │   PostgreSQL 16-Alpine          │ │ Redis 7.2     │
                         │  - pg_advisory_xact_lock        │ │ Cache & Tasks │
                         │  - Foreign Key Cascade Safety   │ └───────────────┘
                         │  - Persistent NVMe Volume       │
                         └─────────────────────────────────┘
```

---

## 2. Hardware & Infrastructure Prerequisites

### 2.1 Compute & Storage Sizing

| Sizing Tier | Active Cases | Concurrent Officers | Min CPU (vCPU) | Min RAM | NVMe SSD Storage | IOPS Threshold |
|---|---|---|---|---|---|---|
| **Departmental / Lab** | 1 – 25 | Up to 10 | 4 Cores | 16 GB | 250 GB NVMe | 3,000 IOPS |
| **State / Bureau Standard** | 25 – 100 | Up to 50 | 8 Cores | 32 GB | 1.0 TB NVMe | 10,000 IOPS |
| **National Command Center** | 100 – 500+ | 100+ | 16 Cores | 64 GB | 4.0 TB NVMe RAID-10 | 25,000+ IOPS |

### 2.2 Host Operating System & Kernel Tuning

NETRA 5.0 is supported on **Ubuntu 22.04 LTS / 24.04 LTS**, **RHEL 9 / Rocky Linux 9**, and **Debian 12**.

Configure OS limits in `/etc/security/limits.conf`:
```text
* soft nofile 65535
* hard nofile 65535
* soft nproc 32768
* hard nproc 32768
```

Configure TCP and memory virtual tuning in `/etc/sysctl.d/99-netra.conf`:
```ini
net.core.somaxconn = 4096
net.ipv4.tcp_max_syn_backlog = 4096
net.ipv4.ip_local_port_range = 1024 65535
fs.file-max = 2097152
vm.overcommit_memory = 1
vm.swappiness = 10
```
Apply immediately:
```bash
sudo sysctl --system
```

---

## 3. Environment Variables & Security Gate

NETRA 5.0 enforces a **Production Boot Fail-Fast Security Gate**. If `ENVIRONMENT=production` is declared, the server will intentionally abort boot with an unrecoverable exception if insecure secrets or development fallbacks are detected.

### 3.1 Required Production Variables

Create a strictly protected `.env.production` file (permissions `600`):

```bash
# ==============================================================================
# NETRA 5.0 PRODUCTION ENVIRONMENT SPECIFICATION
# ==============================================================================

# Core System
ENVIRONMENT=production
DEBUG=false
PROJECT_NAME="NETRA 5.0 — Cognitive Intelligence Platform"

# Cryptographic Token Authentication (MUST be >= 32 high-entropy characters)
# Generate via: openssl rand -hex 32
SECRET_KEY=c4f91b7d5e82a901f4c3b6d2e8a1f7c9b0e2d4a6f8c1b3e5a7d9f0e2b4a6c8d0
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=480

# Relational Database (PostgreSQL 16)
POSTGRES_USER=netra_admin
POSTGRES_PASSWORD=YOUR_STRONG_PG_PASSWORD_HERE
POSTGRES_DB=netra
POSTGRES_HOST=db
POSTGRES_PORT=5432
DATABASE_URL=postgresql://netra_admin:YOUR_STRONG_PG_PASSWORD_HERE@db:5432/netra

# Database Connection Pool Tuning
DB_POOL_SIZE=25
DB_MAX_OVERFLOW=50
DB_POOL_TIMEOUT=30
DB_POOL_RECYCLE=1800

# Redis Cache & Asynchronous Broker
REDIS_URL=redis://redis:6379/0

# Ingestion Constraints & File Quotas
MAX_FILE_SIZE_MB=100
MAX_ARCHIVE_FILES=500
INGESTION_TEMP_DIR=/tmp/netra_ingest

# Privacy & Zero-Knowledge Cross-Case Correlation
# Generate via: openssl rand -hex 32
BLIND_INDEX_HMAC_PEPPER=8f1c3b5a7e9d0f2a4b6c8d0e1f3a5c7e9b0d2f4a6c8e0b1d3f5a7c9e1b3d5f7
```

### 3.2 Production Gate Verification Rules

The boot gate validates the following conditions at startup:
1. `SECRET_KEY` is not the default fallback (`"cyberdrishti_super_secret_jwt_key_2026"` or `"netra_secret"`).
2. `SECRET_KEY` length is $\ge 32$ characters.
3. `DATABASE_URL` does not use SQLite in production (`sqlite://`).
4. Initial administrative password is not `"password"`, `"admin"`, or `"123456"`.

---

## 4. Containerized Deployment Steps

### 4.1 Step 1: Clone and Stage Configuration
```bash
git clone https://github.com/police-department/netra5.0.git /opt/netra5.0
cd /opt/netra5.0
cp .env.example .env.production
chmod 600 .env.production
# Edit .env.production with production credentials
```

### 4.2 Step 2: Build Multi-Stage Containers
```bash
docker compose -f docker-compose.yml build --no-cache
```

The frontend container executes a 2-stage build:
1. **Stage 1 (Node 20 Alpine)**: Installs dependencies with clean caching, executes `npm run build` compiling React/Vite assets into optimized chunks in `/app/dist`.
2. **Stage 2 (Nginx Alpine)**: Copies static artifacts to `/usr/share/nginx/html` and mounts the hardened `frontend/nginx.conf` reverse proxy.

### 4.3 Step 3: Launch Services with Healthchecks
```bash
docker compose -f docker-compose.yml up -d
```

### 4.4 Step 4: Verify Deployment Health
```bash
docker compose ps
```
Ensure all 5 services report `Up (healthy)` or `Up`:
- `netra-db` (PostgreSQL 16)
- `netra-redis` (Redis 7.2)
- `netra-backend` (FastAPI / Uvicorn)
- `netra-frontend` (Nginx Reverse Proxy & UI)
- `netra-adminer` (Optional DBA management console)

Probe backend health:
```bash
curl -f http://127.0.0.1:8000/health
```
Expected output:
```json
{
  "status": "healthy",
  "version": "5.0.0",
  "dependencies": {
    "postgresql": "connected",
    "chromadb": "active",
    "disk_free_gb": 250.48
  }
}
```

---

## 5. Nginx Reverse Proxy & Network Hardening

The frontend Nginx reverse proxy mediates all traffic on port 80 (or 443 with TLS).

### 5.1 Critical Reverse Proxy Directives

1. **Client Body Limit (Forensic Uploads)**:
   ```nginx
   client_max_body_size 100M;
   ```
   Ensures forensic archives (ZIP, CDR, PCAP, Cellebrite extractions) up to 100MB are accepted without `HTTP 413 Payload Too Large`.

2. **Unbuffered Server-Sent Events (SSE)**:
   ```nginx
   location /api/v1/cognitive/stream/ {
       proxy_pass http://backend:8000;
       proxy_http_version 1.1;
       proxy_set_header Connection '';
       proxy_buffering off;
       proxy_cache off;
       chunked_transfer_encoding on;
       proxy_read_timeout 86400s;
   }
   ```
   Guarantees real-time streaming updates for AI analysis without buffer stagnation.

3. **WebSocket Upgrades**:
   ```nginx
   location /ws/ {
       proxy_pass http://backend:8000;
       proxy_http_version 1.1;
       proxy_set_header Upgrade $http_upgrade;
       proxy_set_header Connection "upgrade";
       proxy_read_timeout 86400s;
   }
   ```

4. **OWASP HTTP Security Headers**:
   - `X-Content-Type-Options: nosniff`
   - `X-Frame-Options: DENY`
   - `X-XSS-Protection: 1; mode=block`
   - `Referrer-Policy: strict-origin-when-cross-origin`
   - `Permissions-Policy: geolocation=(), camera=(), microphone=()`

5. **Distributed Correlation Trace ID Passing**:
   ```nginx
   proxy_set_header X-Request-ID $request_id;
   proxy_set_header X-Trace-ID $request_id;
   ```

---

## 6. Database Operations & Resilience

### 6.1 Connection Pooling Configuration
NETRA 5.0 utilizes an enterprise SQLAlchemy pool configured in `backend/database/connection.py`:
- `pool_size`: 25 active connections
- `max_overflow`: 50 bursting connections
- `pool_pre_ping`: `True` (automatically purges stale or dropped connections before query dispatch)
- `pool_recycle`: 1800s (prevents long-lived connection drift)

### 6.2 Hot Backup Procedure
Run automated backups daily during low-traffic windows:
```bash
#!/bin/bash
set -euo pipefail
BACKUP_DIR="/var/backups/netra"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/netra5_backup_${TIMESTAMP}.sql.gz"
mkdir -p "${BACKUP_DIR}"

# Execute streaming compressed pg_dump
docker exec netra-db pg_dump -U netra_admin -d netra | gzip -9 > "${BACKUP_FILE}"

# Generate SHA-256 integrity seal
sha256sum "${BACKUP_FILE}" > "${BACKUP_FILE}.sha256"

# Retain backups for 90 days
find "${BACKUP_DIR}" -type f -name "*.sql.gz" -mtime +90 -delete
echo "Backup successfully sealed: ${BACKUP_FILE}"
```

### 6.3 Disaster Recovery & Restore Runbook
To restore a snapshot into a fresh or recovered database:
```bash
# 1. Verify SHA-256 seal integrity
sha256sum -c netra5_backup_20260918.sql.gz.sha256

# 2. Stop application backend to prevent concurrent writes
docker compose stop backend frontend

# 3. Decompress and restore into PostgreSQL
gunzip -c netra5_backup_20260918.sql.gz | docker exec -i netra-db psql -U netra_admin -d netra

# 4. Execute cryptographic audit chain verification
docker compose start backend
docker exec netra-backend python3 -c "
from database.connection import SessionLocal
from utils.audit import verify_audit_chain
db = SessionLocal()
res = verify_audit_chain(db)
print('Audit Chain Integrity:', res['status'])
db.close()
"

# 5. Bring services back online
docker compose start frontend
```

---

## 7. Statutory Evidentiary Compliance & Audit Trail

### 7.1 Legal Standards

NETRA 5.0 implements end-to-end statutory compliance under Indian criminal jurisprudence:
- **Bharatiya Sakshya Adhiniyam, 2023 (BSA S.63)**: Cryptographic electronic evidence certification, replacing the repealed Indian Evidence Act S.65B.
- **Bharatiya Nagarik Suraksha Sanhita, 2023 (BNSS S.193 & S.94)**: Tamper-evident charge sheet dossiers and zero-knowledge blind indexing for privacy preservation.

### 7.2 Cryptographic Audit Chain Mechanics
Every write operation (evidence upload, entity creation, note addition, role assignment) appends to a global cryptographically chained ledger (`audit_log` table).
- Each entry calculates:
  $$\text{Hash}_i = \text{SHA256}(\text{Hash}_{i-1} + \text{SerializedRecord}_i)$$
- Appends are serialized using PostgreSQL transaction-level advisory locking:
  `SELECT pg_advisory_xact_lock(hashtext('cyberdrishti:audit-chain'))`
- Ensures zero fork hazards or race conditions under extreme concurrency.

### 7.3 Auditing System Integrity
To verify the global audit log via API:
```bash
curl -H "Authorization: Bearer <ADMIN_TOKEN>" http://localhost:8000/api/v1/audit/verify
```
Expected response:
```json
{
  "total_records": 1472,
  "status": "VERIFIED",
  "broken_at": null,
  "tamper_detected": false
}
```

---

## 8. Incident Response & Troubleshooting Runbook

| Symptom / Alert | Root Cause | Immediate Remediation |
|---|---|---|
| **HTTP 429 Too Many Requests** | Brute force threshold triggered (5 consecutive bad logins) | Wait 15 minutes for sliding window expiry, or admin unlocks user via `DELETE /api/v1/auth/lockout/{username}`. |
| **HTTP 404 on Existing Case** | Anti-enumeration multi-tenant security barrier | Verify officer is assigned to `case_id` or authenticate using Supervisor/Admin role (`admin` role bypasses tenant boundary). |
| **HTTP 413 Payload Too Large** | Evidence archive exceeds Nginx upload boundary | Ensure `client_max_body_size 100M;` is active in Nginx configuration. |
| **DB Pool Timeout (Queue Full)** | Long-running queries or sudden traffic spike | Check active sessions in PostgreSQL (`SELECT * FROM pg_stat_activity`). Increase `DB_MAX_OVERFLOW` in `.env.production`. |
| **Audit Chain "TAMPER_DETECTED"** | Record in `audit_log` was modified directly in SQL | Isolate database node immediately; run `backend/utils/audit.py` forensic audit tool to pinpoint corrupted row ID and timestamp. |
| **Broken SSE Streaming Updates** | Intermediary proxy buffering SSE responses | Confirm `proxy_buffering off;` and `chunked_transfer_encoding on;` in Nginx upstream block. |

---

## 9. Sign-off & Maintenance Contacts

- **Operations Lead**: Cyber Operations Directorate
- **Forensic Admissibility Attestation**: S.63 BSA Certified System
- **Next Audit Review Date**: Annual or Major Release
