# 🚀 CyberDrishti AI — Quick Command Reference

## 📋 Daily Commands

### **Start Everything**
```powershell
# Automated setup (first time only)
.\quickstart.ps1

# Start infrastructure
docker-compose up -d

# Terminal 1: Backend
cd backend
.\venv\Scripts\Activate.ps1
uvicorn main:app --reload

# Terminal 2: Frontend
cd frontend
npm run dev
```

### **Stop Everything**
```powershell
# Stop containers
docker-compose down

# Stop backend: Ctrl+C in Terminal 1
# Stop frontend: Ctrl+C in Terminal 2
```

---

## 🧪 ML Training Commands

### **Generate Synthetic Data**
```powershell
cd backend
python nlp/generate_ner_training_data.py --output_dir training_data --n_sentences 8000
```

### **Train All Models (Full Pipeline)**
```powershell
# With GPU (recommended)
python train_all.py --synthetic 8000 --epochs 10 --gpu

# Without GPU (CPU only, slower)
python train_all.py --synthetic 8000 --epochs 5
```

### **Train Individual Models**
```powershell
# CyberDrishtiLM only
python nlp/cyberdrishtilm/train.py --data_dir training_data --output_dir artifacts/cdlm --epochs 10

# HingBERT only
python nlp/hingbert_finetune.py --data_dir training_data --output_dir artifacts/hingbert --epochs 10

# CRF only
python nlp/train_crf.py --data_dir training_data --output_path artifacts/crf/model.pkl
```

### **Validate on Real Data**
```powershell
python nlp/validate_real_data.py \
    --real_data ./real_data/test.txt \
    --cdlm_model artifacts/cyberdrishtilm \
    --hingbert_model artifacts/hingbert \
    --crf_model artifacts/crf/crf_model.pkl \
    --output_report artifacts/validation.json
```

### **Compare Models**
```powershell
python nlp/compare_models.py \
    --cdlm_metrics artifacts/cyberdrishtilm/eval_metrics.json \
    --hingbert_metrics artifacts/hingbert/eval_metrics.json \
    --crf_metrics artifacts/crf/eval_metrics.json \
    --output_report artifacts/comparison.json \
    --output_table artifacts/comparison.txt
```

---

## 🗄️ Database Commands

### **Initialize Database**
```powershell
cd backend
python database/init_db.py
```

### **Connect to PostgreSQL**
```powershell
# Via Adminer (web UI)
# http://localhost:8080
# System: PostgreSQL
# Server: postgres
# Username: cd_user
# Password: cd_secure_password
# Database: cyberdrishti

# Via psql (command line)
docker exec -it cyberdrishti-postgres psql -U cd_user -d cyberdrishti
```

### **Connect to Redis**
```powershell
docker exec -it cyberdrishti-redis redis-cli
```

---

## 📦 Package Management

### **Backend Dependencies**
```powershell
cd backend

# Install
pip install -r requirements.txt

# Add new package
pip install <package-name>
pip freeze > requirements.txt

# Update all
pip install --upgrade -r requirements.txt
```

### **Frontend Dependencies**
```powershell
cd frontend

# Install
npm install

# Add new package
npm install <package-name>

# Update all
npm update
```

---

## 🧹 Cleanup Commands

### **Clean Python Cache**
```powershell
cd backend
Get-ChildItem -Recurse -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Recurse -Filter "*.pyc" | Remove-Item -Force
```

### **Clean Frontend Build**
```powershell
cd frontend
Remove-Item -Recurse -Force .next
npm run build
```

### **Clean Docker Volumes**
```powershell
docker-compose down -v  # ⚠️ This will delete all data!
```

### **Reset Everything**
```powershell
# Stop containers
docker-compose down -v

# Remove virtual environment
Remove-Item -Recurse -Force backend/venv

# Remove node modules
Remove-Item -Recurse -Force frontend/node_modules

# Start fresh with quickstart.ps1
.\quickstart.ps1
```

---

## 🐛 Debugging Commands

### **Backend Logs**
```powershell
# Live logs
uvicorn main:app --reload --log-level debug

# Docker logs
docker-compose logs -f backend
docker-compose logs -f postgres
docker-compose logs -f redis
```

### **Frontend Logs**
```powershell
# Development mode shows logs in terminal
npm run dev

# Production build logs
npm run build
npm start
```

### **Database Query Logs**
```python
# In database/session.py, enable SQL echo:
engine = create_engine(DATABASE_URL, echo=True)
```

---

## 🔧 Utility Commands

### **Format Code**
```powershell
# Backend (Black)
cd backend
pip install black
black .

# Frontend (Prettier)
cd frontend
npm install --save-dev prettier
npx prettier --write "src/**/*.{ts,tsx}"
```

### **Type Check**
```powershell
# Backend (mypy)
cd backend
pip install mypy
mypy .

# Frontend (TypeScript)
cd frontend
npm run type-check
```

### **Lint**
```powershell
# Backend (flake8)
cd backend
pip install flake8
flake8 .

# Frontend (ESLint)
cd frontend
npm run lint
```

---

## 🔑 API Testing Commands

### **Login and Get Token**
```powershell
# Using curl
$response = Invoke-RestMethod -Method POST -Uri "http://localhost:8000/api/v1/auth/login" -ContentType "multipart/form-data" -Form @{username="admin"; password="admin123"}
$token = $response.access_token

# Using Invoke-RestMethod
$headers = @{Authorization = "Bearer $token"}
Invoke-RestMethod -Uri "http://localhost:8000/api/v1/cases" -Headers $headers
```

### **Create a Case**
```powershell
$body = @{
    case_number = "FIR/2025/001"
    title = "Investment Fraud Case"
    priority = "high"
    status = "in_progress"
    crime_type = "Investment Fraud"
} | ConvertTo-Json

Invoke-RestMethod -Method POST -Uri "http://localhost:8000/api/v1/cases" -Headers $headers -Body $body -ContentType "application/json"
```

---

## 🌐 URLs Reference

| Service | URL | Credentials |
|---------|-----|-------------|
| Frontend | http://localhost:3000 | (after user creation) |
| Backend API | http://localhost:8000 | - |
| API Docs (Swagger) | http://localhost:8000/docs | - |
| Adminer (DB UI) | http://localhost:8080 | User: cd_user / Pass: cd_secure_password |
| Postgres | localhost:5432 | User: cd_user / DB: cyberdrishti |
| Redis | localhost:6379 | No auth |

---

## 🔥 Emergency Commands

### **Kill All Running Processes**
```powershell
# Kill Python processes
Get-Process python | Stop-Process -Force

# Kill Node processes
Get-Process node | Stop-Process -Force

# Stop all Docker containers
docker stop $(docker ps -aq)
```

### **Free Up Ports**
```powershell
# Find process on port 8000
netstat -ano | findstr :8000

# Kill process by PID
Stop-Process -Id <PID> -Force
```

---

## 📊 Monitoring Commands

### **Check Docker Status**
```powershell
docker-compose ps
docker stats
```

### **Check Database Size**
```sql
-- Connect to psql first
SELECT pg_size_pretty(pg_database_size('cyberdrishti'));
```

### **Check Model Artifacts**
```powershell
Get-ChildItem artifacts -Recurse | Measure-Object -Property Length -Sum
```

---

## 💾 Backup Commands

### **Backup Database**
```powershell
docker exec cyberdrishti-postgres pg_dump -U cd_user cyberdrishti > backup_$(Get-Date -Format 'yyyyMMdd_HHmmss').sql
```

### **Restore Database**
```powershell
Get-Content backup_20260808_120000.sql | docker exec -i cyberdrishti-postgres psql -U cd_user -d cyberdrishti
```

---

## 🎓 Learning Commands

### **Interactive Python Shell (with DB access)**
```powershell
cd backend
.\venv\Scripts\Activate.ps1
python

>>> from database.session import SessionLocal
>>> from database.models import Case
>>> db = SessionLocal()
>>> cases = db.query(Case).all()
>>> print(cases)
```

### **Test Individual Parser**
```powershell
cd backend
python -c "from parsers.whatsapp_parser import parse_whatsapp; print(parse_whatsapp('test.txt'))"
```

---

## 🧪 Canonical Verification & Audit Harnesses

Both SQLite and PostgreSQL 16 dialect runs are verified and fully supported.

### 1. SQLite In-Memory / Temp Database (Self-cleaning)
```bash
cd backend
python _feature_audit.py        # 49/49 features passed
python _shadow_mule_e2e.py      # 19/19 checks passed
pytest tests -v                 # 24/24 passed
python scripts/check_migrations.py # Migration sync guard
```

### 2. PostgreSQL 16 Canonical Verification (Dedicated Audit DB)
```bash
# A. Provision isolated audit database (one-time setup):
PGPASSWORD=cyberdrishti_secret psql -h 127.0.0.1 -U cyberdrishti -d postgres -c "CREATE DATABASE cyberdrishti_audit_dev OWNER cyberdrishti;"

# B. Run database migrations on PostgreSQL:
DATABASE_URL="postgresql+asyncpg://cyberdrishti:cyberdrishti_secret@127.0.0.1:5432/cyberdrishti_audit_dev" python -m alembic upgrade head

# C. Run Operation Shadow Mule forensic acceptance test:
DATABASE_URL="postgresql+asyncpg://cyberdrishti:cyberdrishti_secret@127.0.0.1:5432/cyberdrishti_audit_dev" python _shadow_mule_e2e.py

# D. Run full surface feature audit:
DATABASE_URL="postgresql+asyncpg://cyberdrishti:cyberdrishti_secret@127.0.0.1:5432/cyberdrishti_audit_dev" python _feature_audit.py
```

### 3. Database Migration Management (Alembic)
```bash
cd backend
python -m alembic upgrade head           # Apply all migrations to head
python -m alembic revision --autogenerate -m "<name>"  # Generate new migration
python scripts/check_migrations.py       # CI guard: verifies models match migrations
```

---

**📝 Tip:** Bookmark this file for quick reference during development!
