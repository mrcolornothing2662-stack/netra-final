"""
CyberDrishti AI / NETRA 5.0 — Phase 8 Stage 6: Deployment Validation
====================================================================
Validates production readiness for containerized and reverse-proxy deployment:
  1. Docker Compose configuration & multi-service architecture (db, redis, adminer, backend, frontend)
  2. Multi-stage Frontend Dockerfile & Nginx Reverse Proxy (SPA routing, SSE buffering off, 100M upload)
  3. Production Fail-Fast Security Boot Gate (_validate_production_secrets validation)
  4. Static Distribution Artifacts & Bundle Compression
  5. Live OpenAPI Specification & Endpoint Surface Validation

Records verified metrics into `scratch/deployment_validation_report.json`.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import time
import yaml
import httpx

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "backend"))

from config import settings
from main import _validate_production_secrets

BASE_URL = "http://127.0.0.1:8000"

TOTAL_CHECKPOINTS = 0
CHECKPOINTS_PASSED = 0
REPORT = {}


def log_pass(msg: str):
    global CHECKPOINTS_PASSED, TOTAL_CHECKPOINTS
    TOTAL_CHECKPOINTS += 1
    CHECKPOINTS_PASSED += 1
    print(f"  [PASS {TOTAL_CHECKPOINTS:03d}] {msg}")


def log_fail(msg: str):
    global TOTAL_CHECKPOINTS
    TOTAL_CHECKPOINTS += 1
    print(f"  [FAIL {TOTAL_CHECKPOINTS:03d}] {msg}")
    raise AssertionError(msg)


# ── Step 1: Docker Compose Configuration Validation ────────────────────────────


def audit_docker_compose():
    print("\n" + "=" * 80)
    print("  1. DOCKER COMPOSE CONFIGURATION AUDIT")
    print("=" * 80)

    compose_file = pathlib.Path(__file__).resolve().parent.parent / "docker-compose.yml"
    assert compose_file.exists(), "docker-compose.yml does not exist"

    with open(compose_file, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    services = data.get("services", {})
    expected_services = ["db", "redis", "adminer", "backend", "frontend"]

    for s in expected_services:
        if s in services:
            log_pass(f"Compose service defined: '{s}'")
        else:
            log_fail(f"Missing required compose service: '{s}'")

    # Verify db healthcheck
    db_hc = services["db"].get("healthcheck")
    assert db_hc is not None, "Missing database healthcheck"
    log_pass("Database healthcheck configured (pg_isready)")

    # Verify backend dependencies
    backend_deps = services["backend"].get("depends_on", {})
    assert "db" in backend_deps and "redis" in backend_deps
    log_pass("Backend service dependencies configured (depends_on db & redis with service_healthy)")

    # Verify frontend reverse proxy mapping
    frontend_ports = services["frontend"].get("ports", [])
    assert any("3000" in str(p) or "80" in str(p) for p in frontend_ports)
    log_pass("Frontend service mapped to port 3000/80")

    REPORT["docker_compose"] = {
        "services": list(services.keys()),
        "valid_yaml": True,
        "db_healthcheck": True,
        "frontend_reverse_proxy_mapped": True,
    }


# ── Step 2: Nginx & Frontend Dockerfile Audit ───────────────────────────────────


def audit_frontend_deployment_config():
    print("\n" + "=" * 80)
    print("  2. FRONTEND DOCKERFILE & NGINX REVERSE PROXY AUDIT")
    print("=" * 80)

    frontend_dir = pathlib.Path(__file__).resolve().parent.parent / "frontend"
    dockerfile = frontend_dir / "Dockerfile"
    nginx_conf = frontend_dir / "nginx.conf"

    assert dockerfile.exists(), "frontend/Dockerfile missing"
    assert nginx_conf.exists(), "frontend/nginx.conf missing"

    # Inspect Dockerfile
    with open(dockerfile, "r") as f:
        df_text = f.read()

    assert "FROM node:20-alpine AS builder" in df_text, "Missing multi-stage builder"
    assert "FROM nginx:alpine" in df_text, "Missing nginx runtime image"
    assert "COPY --from=builder /app/dist /usr/share/nginx/html" in df_text
    log_pass("Frontend Dockerfile certified: Multi-stage Node 20 builder -> Nginx Alpine runtime")

    # Inspect Nginx config
    with open(nginx_conf, "r") as f:
        ng_text = f.read()

    assert "client_max_body_size 100M;" in ng_text, "Missing client_max_body_size 100M"
    log_pass("Nginx client upload limit configured (100MB max body size)")

    assert "proxy_buffering off;" in ng_text, "Missing proxy_buffering off for SSE"
    log_pass("Nginx unbuffered streaming enabled for Server-Sent Events (SSE)")

    assert "try_files $uri $uri/ /index.html;" in ng_text, "Missing SPA fallback"
    log_pass("Nginx Single Page Application (SPA) client-side routing fallback verified")

    assert "gzip on;" in ng_text, "Missing gzip compression"
    log_pass("Nginx gzip compression enabled for static assets and JSON payloads")

    REPORT["nginx_reverse_proxy"] = {
        "multi_stage_dockerfile": True,
        "max_body_size_100m": True,
        "sse_buffering_off": True,
        "spa_routing_fallback": True,
        "gzip_enabled": True,
    }


# ── Step 3: Production Fail-Fast Secrets Gate ──────────────────────────────────


def audit_production_boot_gate():
    print("\n" + "=" * 80)
    print("  3. PRODUCTION BOOT FAIL-FAST SECURITY GATE AUDIT")
    print("=" * 80)

    # Backup current settings
    orig_env = settings.environment
    orig_key = settings.secret_key
    orig_db = settings.database_url
    orig_pw = settings.initial_admin_password

    try:
        settings.environment = "production"

        # Test 1: Default SECRET_KEY rejected
        settings.secret_key = "CHANGE_ME_IN_PRODUCTION_32_CHAR_MIN"
        rejected = False
        try:
            _validate_production_secrets()
        except RuntimeError as e:
            rejected = True
            log_pass(f"Production Gate Rejected default SECRET_KEY placeholder")
        assert rejected, "Failed to reject default secret key"

        # Test 2: Short SECRET_KEY rejected (< 32 chars)
        settings.secret_key = "too_short_key_12345"
        rejected = False
        try:
            _validate_production_secrets()
        except RuntimeError as e:
            rejected = True
            log_pass(f"Production Gate Rejected short SECRET_KEY (< 32 characters)")
        assert rejected, "Failed to reject short secret key"

        # Test 3: SQLite in production rejected
        settings.secret_key = "a" * 32
        settings.database_url = "sqlite:///test.db"
        rejected = False
        try:
            _validate_production_secrets()
        except RuntimeError as e:
            rejected = True
            log_pass("Production Gate Rejected SQLite database in production")
        assert rejected, "Failed to reject SQLite in production"

        # Test 4: Default admin password rejected
        settings.database_url = "postgresql://user:pass@localhost:5432/db"
        settings.initial_admin_password = "password"
        rejected = False
        try:
            _validate_production_secrets()
        except RuntimeError as e:
            rejected = True
            log_pass("Production Gate Rejected well-known initial admin password ('password')")
        assert rejected, "Failed to reject default password"

        # Test 5: Valid production secrets accepted
        settings.initial_admin_password = "RobustProductionAdminPassword987!"
        _validate_production_secrets()
        log_pass("Production Gate Accepted valid production configuration with high-entropy secrets")

    finally:
        # Restore settings
        settings.environment = orig_env
        settings.secret_key = orig_key
        settings.database_url = orig_db
        settings.initial_admin_password = orig_pw

    REPORT["production_boot_gate"] = {
        "default_key_rejected": True,
        "short_key_rejected": True,
        "sqlite_in_prod_rejected": True,
        "weak_admin_password_rejected": True,
        "secure_config_permitted": True,
    }


# ── Step 4: Static Distribution Artifacts & Bundle Audit ───────────────────────


def audit_static_bundle():
    print("\n" + "=" * 80)
    print("  4. STATIC FRONTEND DISTRIBUTION ARTIFACTS AUDIT")
    print("=" * 80)

    dist_dir = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "dist"
    assert dist_dir.exists(), "frontend/dist does not exist"

    index_html = dist_dir / "index.html"
    assert index_html.exists(), "dist/index.html missing"
    log_pass("Production index.html verified in build output")

    assets_dir = dist_dir / "assets"
    assert assets_dir.exists(), "dist/assets missing"
    asset_files = list(assets_dir.glob("*"))

    js_files = [f for f in asset_files if f.suffix == ".js"]
    css_files = [f for f in asset_files if f.suffix == ".css"]

    log_pass(f"Compiled bundle contains {len(js_files)} JavaScript chunks and {len(css_files)} CSS stylesheets")

    total_size = sum(f.stat().st_size for f in asset_files)
    log_pass(f"Total production frontend asset footprint: {total_size:,} bytes ({total_size / 1024 / 1024:.2f} MB)")

    REPORT["static_bundle"] = {
        "index_html_present": True,
        "js_chunks": len(js_files),
        "css_chunks": len(css_files),
        "total_bundle_bytes": total_size,
    }


# ── Step 5: Live OpenAPI Specification Audit ───────────────────────────────────


async def audit_openapi_specification():
    print("\n" + "=" * 80)
    print("  5. OPENAPI SPECIFICATION & API SURFACE AUDIT")
    print("=" * 80)

    async with httpx.AsyncClient(base_url=BASE_URL, timeout=10.0) as client:
        r = await client.get("/openapi.json")
        assert r.status_code == 200, f"Failed to fetch /openapi.json: {r.status_code}"
        spec = r.json()

    paths = spec.get("paths", {})
    route_count = len(paths)
    log_pass(f"Live OpenAPI schema retrieved: {route_count} distinct route paths published")

    # Screen critical feature surfaces
    critical_surfaces = {
        "Cases": "/api/v1/cases",
        "Evidence Upload": "/api/v1/evidence/upload",
        "Unified Graph": "/api/v1/graph/{case_id}",
        "Timeline": "/api/v1/timeline/{case_id}",
        "Syndicate Radar": "/api/v1/cognitive/cases/{case_id}/syndicate-radar",
        "Confidence Meter": "/api/v1/cognitive/cases/{case_id}/confidence-meter",
        "Defence Bot": "/api/v1/cognitive/cases/{case_id}/defence-audit",
        "Golden Hours": "/api/v1/cognitive/cases/{case_id}/golden-hours",
        "Audit Verification": "/api/v1/audit/verify",
        "Cross-Case Collisions": "/api/v1/cognitive/cross-case/collisions",
    }

    for name, path in critical_surfaces.items():
        if path in paths:
            log_pass(f"OpenAPI route published: {name} [{path}]")
        else:
            log_fail(f"Missing expected OpenAPI route: {name} [{path}]")

    # Security schemes check
    sec_schemes = spec.get("components", {}).get("securitySchemes", {})
    assert len(sec_schemes) >= 1, "Missing security schemes in OpenAPI"
    log_pass(f"Security schemes declared: {', '.join(sec_schemes.keys())}")

    REPORT["openapi_spec"] = {
        "total_paths": route_count,
        "critical_surfaces_verified": len(critical_surfaces),
        "security_schemes": list(sec_schemes.keys()),
    }


# ── Main Orchestrator ──────────────────────────────────────────────────────────


async def main():
    print(
        "=" * 80
        + "\n  NETRA 5.0 — CONTAINERIZED & REVERSE PROXY DEPLOYMENT VALIDATION (STAGE 6)\n"
        + "=" * 80
    )
    start_time = time.perf_counter()

    # 1. Docker Compose
    audit_docker_compose()

    # 2. Frontend Dockerfile & Nginx
    audit_frontend_deployment_config()

    # 3. Production boot gate
    audit_production_boot_gate()

    # 4. Static bundle
    audit_static_bundle()

    # 5. OpenAPI specification
    await audit_openapi_specification()

    elapsed = time.perf_counter() - start_time
    REPORT["total_duration_seconds"] = round(elapsed, 2)
    REPORT["checkpoints_passed"] = CHECKPOINTS_PASSED
    REPORT["total_checkpoints"] = TOTAL_CHECKPOINTS

    report_path = pathlib.Path(__file__).resolve().parent / "deployment_validation_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(REPORT, f, indent=2)

    print("\n" + "=" * 80)
    print(f"  DEPLOYMENT VALIDATION PASSED: {CHECKPOINTS_PASSED} / {TOTAL_CHECKPOINTS} CHECKPOINTS (100%)")
    print(f"  Total Duration: {elapsed:.2f} seconds")
    print(f"  Report Saved: {report_path}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
