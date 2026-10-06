# Finance Support — Architecture

> Phase 9 — Double-Entry Financial Ledger Engine

## Current Architecture (Phase 9)

```
┌─────────────────────┐
│   React Frontend    │
│  (Vite + TypeScript) │
│   localhost:5173     │
└────────┬────────────┘
         │ HTTP / JSON (HttpOnly Session Cookies) / Multipart File Upload
         ▼
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                        │
│   (Python + Uvicorn)                                        │
│   localhost:8000                                            │
│                                                             │
│   ┌───────────────────────┐   ┌─────────────────────────┐  │
│   │   Document Storage    │   │    Statement Parsers    │  │
│   │   (Local Disk / S3)   │   │  (CSV / PDF Extractor)  │  │
│   └───────────────────────┘   └────────────┬────────────┘  │
│                                            │                │
│                                            ▼                │
│   ┌─────────────────────────────────────────────────────┐   │
│   │  Fingerprint Service (SHA-256 Canonicalization)     │   │
│   └────────────────────────┬────────────────────────────┘   │
│                            │                                │
│                            ▼                                │
│   ┌─────────────────────────────────────────────────────┐   │
│   │  Deduplication + Atomic Transaction & Event System  │   │
│   └────────────────────────┬────────────────────────────┘   │
│                            │                                │
│                            ▼                                │
│   ┌─────────────────────────────────────────────────────┐   │
│   │   Double-Entry Ledger Posting Engine (Phase 9)      │   │
│   │   LedgerService → LedgerAccount + LedgerEntry       │   │
│   └─────────────────────────────────────────────────────┘   │
└────────┬────────────────────────────────────────────────────┘
         │ psycopg (SQLAlchemy 2.0 Sync Engine)
         ▼
┌─────────────────────┐
│    PostgreSQL 16     │
│   (Docker Compose)   │
│   localhost:5432     │
└─────────────────────┘
```

### Data Hierarchy & Ownership

```
User
 ├──> UserProfile (1:1)
 ├──> Sessions (1:N)
 ├──> OAuthAccounts (1:N)
 ├──> FinancialAccounts (1:N)
 │      ├──> Transactions (1:N)
 │      └──> FinancialEvents (1:N)
 ├──> Transactions (1:N direct ownership link)
 ├──> FinancialEvents (1:N direct ownership link)
 ├──> FinancialDocuments (1:N, FK -> FinancialAccount)
 ├──> LedgerAccounts (1:N, chart-of-accounts per user)     ← Phase 9
 └──> LedgerEntries (1:N, debit/credit postings)           ← Phase 9
```

---

## Processing Pipeline

```
Parser
  ↓
Normalized Transaction
  ↓
Centralized Fingerprint (SHA-256)
  ↓
Deduplication Check (Batch & DB)
  ↓
[Savepoint]
  Transaction INSERT
  FinancialEvent INSERT  (TRANSACTION_IMPORTED, immutable)
  LedgerEntry×2 INSERT   (one Debit + one Credit)          ← Phase 9
[Savepoint Commit / Rollback on any failure]
```

---

## Phase 8 System Design

### 1. Transaction Fingerprint (`generate_transaction_fingerprint`)
- Centralized deterministic SHA-256 calculation.
- **Identity Fields Only**: `financial_account_id`, `transaction_date`, `amount`, `transaction_type`, `merchant`, `reference`.
- **Exclusions**: Never includes database UUIDs, timestamps, document IDs, category, notes, or raw metadata.
- **Canonicalization Rules**:
  - Whitespace: trimmed and internal multiple spaces collapsed.
  - Case: normalized to lowercase strings.
  - Decimal: formatted deterministically to 4 decimal places (`0.0001` scale).
  - Null/Empty values: represented as empty string `""` consistently.
  - SHA-256 hash: 64-character lowercase hex digest.

### 2. Database Deduplication Uniqueness
- Unique constraint `uq_account_transaction_fingerprint` on `(financial_account_id, transaction_fingerprint)`.
- Prevents duplicate transactions within the same financial account while allowing identical transactions across different financial accounts.
- Distinguishes document-level SHA-256 deduplication (Phase 7 file hash) from line-item transaction fingerprint deduplication (Phase 8).

### 3. Immutable Financial Event Ledger (`FinancialEvent`)
- Append-only `financial_events` table.
- Event types (initial: `TRANSACTION_IMPORTED`).
- **Fields**: `id`, `user_id`, `financial_account_id`, `event_type`, `transaction_id`, `created_at`, `source`, `idempotency_key`, `payload`.
- **Immutability Enforcement**: SQLAlchemy ORM event listeners (`before_update`, `before_delete`) prevent direct updating or deletion of event records by application services.

### 4. Database Atomicity & Event Idempotency
- **Atomic Operations**: Newly imported transaction `INSERT`, corresponding `TRANSACTION_IMPORTED` event `INSERT`, and Phase 9 ledger entries all execute inside a **SQLAlchemy savepoint** (nested transaction). If any step fails, all three roll back atomically.
- **Idempotency Strategy**: Unique constraint `uq_financial_events_idempotency_key` on `idempotency_key = f"import:{account_id}:{fingerprint}"` prevents duplicate event generation.

### 5. Replay Foundation (`ReplayService`)
- Replays financial events and transactions to calculate total counts, total credits, total debits, and net balance movement.
- Uses Python `Decimal` arithmetic exclusively for precision.

---

## Phase 9: Double-Entry Ledger Architecture

### Fundamental Accounting Rule

```
TOTAL DEBITS == TOTAL CREDITS
```

Every imported transaction produces **exactly two** `LedgerEntry` rows — one debit and one credit — that always balance each other.

### Data Model

#### `LedgerAccount` — Chart of Accounts
| Field                  | Type         | Notes                                    |
|------------------------|--------------|------------------------------------------|
| `id`                   | UUID PK      |                                          |
| `user_id`              | UUID FK      | Enforces per-user isolation              |
| `financial_account_id` | UUID FK (nullable) | Links to real bank account if applicable |
| `name`                 | String(150)  | e.g. "Bank Account", "Salary Income"     |
| `account_type`         | String(20)   | ASSET / LIABILITY / INCOME / EXPENSE / EQUITY |
| `currency`             | String(3)    | ISO 4217                                 |
| `created_at`           | DateTime(tz) |                                          |

#### `LedgerEntry` — Debit / Credit Postings
| Field                  | Type             | Notes                                    |
|------------------------|------------------|------------------------------------------|
| `id`                   | UUID PK          |                                          |
| `user_id`              | UUID FK          | Enforces per-user isolation              |
| `ledger_account_id`    | UUID FK          | References `LedgerAccount`               |
| `transaction_id`       | UUID FK (nullable) | References `Transaction`               |
| `financial_event_id`   | UUID FK (nullable) | References `FinancialEvent`            |
| `debit_amount`         | Decimal(18,4)    | NULL if this is a credit entry           |
| `credit_amount`        | Decimal(18,4)    | NULL if this is a debit entry            |
| `currency`             | String(3)        |                                          |
| `description`          | Text             |                                          |
| `created_at`           | DateTime(tz)     |                                          |

**Invariants**:
- Exactly one of (`debit_amount`, `credit_amount`) is non-NULL per row.
- Neither field may be negative.

### Posting Flow

```
Salary / Credit Transaction (money IN):
  → Debit  "Bank Account"  (ASSET)   +80,000
  → Credit "Salary Income" (INCOME)  +80,000
  ✓ balanced

Expense / Debit Transaction (money OUT):
  → Debit  "General Expenses" (EXPENSE)  +3,500
  → Credit "Bank Account"     (ASSET)    +3,500
  ✓ balanced
```

### Default Chart of Accounts (Auto-Created per User)

| Name               | Account Type | Created When                          |
|--------------------|--------------|---------------------------------------|
| Bank Account       | ASSET        | First import for the user             |
| Salary Income      | INCOME       | First import for the user             |
| General Expenses   | EXPENSE      | First import for the user             |

Account creation is **idempotent** — calling `ensure_default_accounts()` multiple times never creates duplicates (enforced by `uq_ledger_account_user_name_type` DB constraint + get-or-create logic).

### Ledger Consistency Rules

1. **Balanced**: `sum(debit_amount) == sum(credit_amount)` for every transaction.
2. **Non-negative**: Amounts must be `>= 0`; negative values are rejected at the service layer.
3. **Debit XOR Credit**: Each `LedgerEntry` carries exactly one of the two amounts (never both, never neither).
4. **User Isolation**: All queries filter on `user_id`; no IDOR possible.
5. **Atomic Savepoint**: The trio (Transaction + FinancialEvent + LedgerEntries) is wrapped in a SQLAlchemy nested transaction (savepoint). Any failure rolls back all three atomically.

### Validation Service (`ledger_validation.py`)

- `validate_double_entry(db, transaction_id, user_id)` — asserts balance for a single transaction; raises `LedgerValidationError` on mismatch.
- `get_user_balance_summary(db, user_id)` — aggregates all debit/credit totals for a user; returns `is_balanced` flag.

---

## Phase 10 & 11 Endpoints

| Method | Path                                         | Purpose                                                |
| ------ | -------------------------------------------- | ------------------------------------------------------ |
| GET    | `/api/health`                                | Application liveness check                             |
| GET    | `/api/health/db`                             | Database connectivity check                            |
| POST   | `/api/auth/register`                         | Local email/password registration                      |
| POST   | `/api/auth/login`                            | Local email/password authentication (session cookie)   |
| POST   | `/api/auth/logout`                           | Revoke session cookie                                  |
| GET    | `/api/auth/me`                               | Current authenticated user identity                    |
| GET    | `/api/auth/oauth/google/url`                 | Google OAuth authorization URL                         |
| POST   | `/api/auth/oauth/google/callback`            | Exchange OAuth code for session                        |
| GET    | `/api/financial/accounts`                    | List authenticated user's financial accounts           |
| GET    | `/api/financial/transactions`                | List authenticated user's transactions                 |
| GET    | `/api/financial/documents`                   | List authenticated user's financial documents          |
| POST   | `/api/financial/documents`                   | Upload and ingest financial document (CSV / PDF)       |
| GET    | `/api/financial/events`                      | List authenticated user's immutable financial events   |
| GET    | `/api/financial/replay`                      | Replay financial events and derive account balances    |
| GET    | `/api/financial/ledger/accounts`             | List user's ledger accounts (chart of accounts)        |
| GET    | `/api/financial/ledger/entries`              | List user's ledger entries (with optional tx filter)   |
| GET    | `/api/financial/ledger/balance`              | Aggregate debit/credit balance + is_balanced flag      |
| GET    | `/api/financial/ledger/transaction/{id}`     | All debit/credit entries for a specific transaction    |
| GET    | `/api/financial/analytics/summary`           | Phase 10: Financial health & period summary           |
| GET    | `/api/financial/analytics/monthly`           | Phase 10: Monthly time-series analytics               |
| GET    | `/api/financial/analytics/categories`        | Phase 10: Category-level spending breakdown            |
| GET    | `/api/financial/insights`                    | Phase 10: Rule-based deterministic insights            |
| POST   | `/api/financial/scenarios/simulate`          | Phase 11: Deterministic scenario simulation engine     |

---

## Technology Stack

| Layer     | Technology                                      |
| --------- | ----------------------------------------------- |
| Frontend  | React, Vite, TypeScript                         |
| Backend   | Python, FastAPI, Pydantic, Uvicorn              |
| Auth      | Argon2id, Session Cookies, Google OAuth 2.0     |
| Ingestion | pdfplumber, python-multipart, hashlib           |
| Database  | PostgreSQL 16, SQLAlchemy 2.0, Alembic          |
| Ledger    | Double-Entry, Decimal arithmetic, Savepoints    |
| Analytics | Rule-Based Insights, Deterministic Scenarios    |
| DevOps    | Docker Compose (PostgreSQL only)                |
| Testing   | pytest, httpx, anyio                            |
