# Finance Support — Architecture

> Phase 1 — Full-Stack Foundation

## Current Architecture (Phase 1)

```
┌─────────────────────┐
│   React Frontend    │
│  (Vite + TypeScript) │
│   localhost:5173     │
└────────┬────────────┘
         │ HTTP / JSON
         ▼
┌─────────────────────┐
│   FastAPI Backend    │
│   (Python + async)   │
│   localhost:8000     │
└────────┬────────────┘
         │ asyncpg
         ▼
┌─────────────────────┐
│    PostgreSQL 16     │
│   (Docker Compose)   │
│   localhost:5432     │
└─────────────────────┘
```

### Frontend → Backend

The React frontend calls the FastAPI backend through standard HTTP `fetch()` requests.
The API base URL is configurable via the `VITE_API_URL` environment variable.
During development, the frontend runs on port **5173** (Vite) and the backend on port **8000** (Uvicorn).

### Backend → Database

The backend uses **async SQLAlchemy** with the `asyncpg` driver to communicate with PostgreSQL.
Database configuration is loaded from the `DATABASE_URL` environment variable via Pydantic Settings.
**Alembic** manages all schema migrations — the app does not auto-create tables.

### Phase 1 Endpoints

| Method | Path             | Purpose                          |
| ------ | ---------------- | -------------------------------- |
| GET    | `/api/health`    | Application liveness check       |
| GET    | `/api/health/db` | Database connectivity check      |

---

## Future Architecture (Not Yet Implemented)

The following layers are planned for future phases. **None of this is built yet.**

```
Financial Data (uploads: CSV, PDF, bank statements)
   ↓
Financial State (normalised, validated data)
   ↓
Deterministic Financial Engine (calculations, metrics)
   ↓
Structured Insights (computed results, ratios)
   ↓
Decision Engine (rule-based recommendations)
   ↓
Scenario Engine (what-if simulations)
   ↓
AI Tool Layer (structured context for LLM)
   ↓
LLM (explanation, Q&A — NOT the calculation engine)
   ↓
User Interface
```

### Key Principle

> The AI/LLM must **NOT** become the financial calculation engine.
> Financial calculations are deterministic and live in a dedicated engine.
> The LLM receives structured, pre-computed insights and provides explanations.

### Planned Future Modules

| Module                  | Purpose                                         | Phase |
| ----------------------- | ----------------------------------------------- | ----- |
| Authentication          | User accounts, OAuth                            | 2     |
| Document Processing     | PDF/CSV parsing, normalization                   | 3     |
| Financial Engine        | Deterministic calculations, metrics              | 3     |
| Transaction Models      | Full database schema                             | 2-3   |
| AI Tool Layer           | LLM integration with structured context          | 4+    |
| Scenario Simulation     | What-if analysis                                 | 4+    |
| Notifications           | Alerts, scheduled reports                        | 5+    |
| Production Deployment   | CI/CD, monitoring, cloud infrastructure          | 5+    |

---

## Technology Stack

| Layer     | Technology                              |
| --------- | --------------------------------------- |
| Frontend  | React, Vite, TypeScript                 |
| Backend   | Python, FastAPI, Pydantic, Uvicorn      |
| Database  | PostgreSQL 16, SQLAlchemy (async), Alembic |
| DevOps    | Docker Compose (PostgreSQL only)        |
| Testing   | pytest, httpx, pytest-asyncio           |
