# Finance Support

**AI-Powered Personal Financial Decision Support System**

> Phase 1 — Full-stack foundation: React ↔ FastAPI ↔ PostgreSQL (Completed)
> Phase 2 — Production Database Architecture: SQLAlchemy 2.0 & Alembic (Completed)

---

## What Is This?

A financial decision support system that will eventually allow users to upload financial data (bank statements, CSVs, PDFs), analyse their financial state, and receive AI-assisted explanations — with all calculations performed by a deterministic engine, not the AI.

**Phase 1** establishes the development environment and proves end-to-end communication between the three layers.

---

## Technology Stack

| Layer     | Technology                                  |
| --------- | ------------------------------------------- |
| Frontend  | React 19, Vite, TypeScript                  |
| Backend   | Python 3.11+, FastAPI, Pydantic, Uvicorn    |
| Database  | PostgreSQL 16, SQLAlchemy 2.0 (async), Alembic |
| Container | Docker Compose (PostgreSQL only)            |
| Testing   | pytest, httpx, pytest-asyncio               |

---

## Prerequisites

Install the following before starting:

| Software          | Version  | Link                                      |
| ----------------- | -------- | ----------------------------------------- |
| Python            | 3.11+    | https://www.python.org/downloads/         |
| Node.js           | 18+      | https://nodejs.org/                       |
| Docker Desktop    | Latest   | https://www.docker.com/products/docker-desktop |
| Git               | Latest   | https://git-scm.com/downloads             |

---

## Project Structure

```
finance-support/
├── frontend/              # React + Vite + TypeScript
│   ├── src/
│   │   ├── api/           # API client functions
│   │   ├── components/    # Reusable UI components
│   │   ├── App.tsx        # Main dashboard page
│   │   ├── App.css        # Styling
│   │   └── config.ts      # API base URL configuration
│   └── ...
├── backend/               # FastAPI + SQLAlchemy
│   ├── app/
│   │   ├── api/           # Route handlers
│   │   ├── core/          # Config, logging, error handling
│   │   ├── db/            # Database engine and base model
│   │   ├── models/        # ORM models (empty in Phase 1)
│   │   ├── schemas/       # Pydantic response models
│   │   ├── services/      # Business logic (empty in Phase 1)
│   │   └── main.py        # FastAPI application entry point
│   ├── migrations/        # Alembic migrations
│   ├── alembic.ini
│   └── requirements.txt
├── tests/                 # pytest test suite
├── docs/                  # Architecture documentation
├── docker-compose.yml     # PostgreSQL container
├── .env.example           # Environment variable template
├── .gitignore
└── README.md              # ← You are here
```

---

## Environment Setup

### 1. Clone & configure environment

```bash
# Copy the environment template
cp .env.example .env

# Edit .env if you need to change ports or credentials
```

The defaults work out of the box for local development.

### 2. Start PostgreSQL

```bash
docker compose up -d
```

Verify it's running:

```bash
docker compose ps
```

You should see `finance_support_db` with status **healthy**.

### 3. Start the Backend

```bash
# Create a Python virtual environment
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS / Linux

# Install dependencies
pip install -r requirements.txt

# Start the dev server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API is now running at **http://localhost:8000**.

### 4. Start the Frontend

```bash
# Open a new terminal
cd frontend
npm install       # only needed once
npm run dev
```

The frontend is now running at **http://localhost:5173**.

---

## Verifying Everything Works

### Backend Health

```bash
# Application health
curl http://localhost:8000/api/health
# → {"status":"ok"}

# Database connectivity
curl http://localhost:8000/api/health/db
# → {"status":"ok","database":"connected"}
```

### Frontend

Open **http://localhost:5173** in your browser. You should see:

- The Finance Support dashboard
- Two status cards showing **Connected** for both FastAPI and PostgreSQL

### API Documentation

FastAPI auto-generates interactive API docs:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

---

## Running Tests

```bash
# From the project root, with the backend venv activated
pytest tests/ -v
```

Tests verify:
1. FastAPI application starts correctly
2. `GET /api/health` returns HTTP 200 with `{"status": "ok"}`
3. `GET /api/health/db` returns HTTP 200 with a valid response
4. Unknown routes return 404 (not 500)

> **Note:** The database health test accepts both "connected" and "disconnected" states,
> so tests pass even if PostgreSQL is not running.

---

## How Communication Works

### Frontend → Backend

1. React calls `fetch("http://localhost:8000/api/health")` from the browser
2. The API base URL comes from `VITE_API_URL` (environment variable)
3. FastAPI receives the request and returns JSON
4. The frontend renders the response in the HealthStatus component

### Backend → PostgreSQL

1. FastAPI uses **async SQLAlchemy** with the `asyncpg` driver
2. The `DATABASE_URL` is loaded from `.env` via Pydantic Settings
3. The `/api/health/db` endpoint runs `SELECT 1` to verify connectivity
4. **Alembic** manages schema migrations — tables are never auto-created

---

## Alembic (Database Migrations)

Phase 2 migration has been generated and applied to PostgreSQL.
For full schema design and ER diagrams, see [docs/DATABASE_DESIGN.md](docs/DATABASE_DESIGN.md).

```bash
# From backend/ directory
cd backend

# Check current migration state (should show bc0f37696ec2 (head))
alembic current

# View migration history
alembic history

# Apply migrations:
alembic upgrade head
```

---

## Security Notes (Phase 1)

- ✅ No secrets committed (`.env` is gitignored)
- ✅ Database credentials loaded from environment
- ✅ CORS configured explicitly (no wildcard with credentials)
- ✅ Stack traces never exposed to API clients
- ✅ SQLAlchemy uses parameterised queries
- ❌ Authentication is **not implemented** (planned for Phase 2)
