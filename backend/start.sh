#!/usr/bin/env bash
set -e

echo "==> Running database migrations via Alembic..."
python -m alembic upgrade head

echo "==> Starting CyberDrishti API server..."
exec uvicorn main:app --host 0.0.0.0 --port 8000
