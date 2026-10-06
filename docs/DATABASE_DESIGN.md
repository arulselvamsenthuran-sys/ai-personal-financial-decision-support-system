# Database Architecture & Design (Phase 6)

AI-Powered Personal Financial Decision Support System  
PostgreSQL 16 · SQLAlchemy 2.0 · Alembic

---

## 1. Overview & Architectural Principles

The database architecture is designed to support a deterministic personal finance decision support system. PostgreSQL serves as the single source of truth for user identities, authentication sessions, third-party OAuth links, multi-currency financial accounts, ledger transactions, and document ingestion metadata.

### Architectural Tiers

```
   ┌──────────────────────────────────────────────┐
   │             FastAPI Application              │
   └──────────────────────┬───────────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────────┐
   │        SQLAlchemy 2.0 ORM & Core             │
   │  (DeclarativeBase, Mapped types, Session)    │
   └──────────────────────┬───────────────────────┘
                          │
                          ▼
   ┌──────────────────────────────────────────────┐
   │             PostgreSQL 16 Engine             │
   │  (UUID PKs, NUMERIC(18,4), Strict FK & Idx)  │
   └──────────────────────────────────────────────┘
```

### Why PostgreSQL?
- **Transactional Integrity (ACID)**: Absolute consistency is required for financial balances and transaction ledgers.
- **Rich Data Types**: Native support for `UUID`, high-precision `NUMERIC`, timezone-aware `TIMESTAMPTZ`, `JSONB`, and indexed structured metadata.
- **Robust Constraint Enforcement**: Enforces referential integrity, compound unique constraints, and foreign key cascades at the database engine level.

### Why SQLAlchemy 2.0?
- **Type-Safe Declarative Mapping**: Modern SQLAlchemy 2.0 `Mapped` and `mapped_column` type annotations integrate cleanly with Python type checkers and IDEs.
- **Separation of Concerns**: Modular models mapped across dedicated files (`user.py`, `profile.py`, `session.py`, `financial_account.py`, `transaction.py`, `financial_document.py`).
- **Query Precision & Security**: Parameterised queries by default protect against SQL injection vulnerabilities.

### Why Alembic?
- **Auditable Version Control**: Every change to database structure is tracked as a version-controlled migration script in `backend/migrations/versions/`.
- **Reproducible Environments**: Production, staging, and local development environments share an identical schema through `alembic upgrade head`.

---

## 2. Entity-Relationship Diagram

```mermaid
erDiagram
    USERS ||--|| USER_PROFILES : "has profile (1:1)"
    USERS ||--o{ SESSIONS : "has active sessions (1:N)"
    USERS ||--o{ OAUTH_ACCOUNTS : "links external accounts (1:N)"
    USERS ||--o{ FINANCIAL_ACCOUNTS : "owns (1:N)"
    USERS ||--o{ TRANSACTIONS : "owns (1:N)"
    FINANCIAL_ACCOUNTS ||--o{ TRANSACTIONS : "records ledger (1:N)"
    USERS ||--o{ FINANCIAL_DOCUMENTS : "uploads (1:N)"
    FINANCIAL_ACCOUNTS ||--o{ FINANCIAL_DOCUMENTS : "categorizes (optional 1:N)"

    USERS {
        uuid id PK
        string email UK
        string password_hash
        boolean is_active
        boolean is_verified
        timestamp created_at
        timestamp updated_at
    }

    USER_PROFILES {
        uuid id PK
        uuid user_id FK,UK
        string display_name
        string preferred_currency
        string timezone
        timestamp created_at
        timestamp updated_at
    }

    SESSIONS {
        uuid id PK
        uuid user_id FK
        string session_token_hash UK
        timestamp expires_at
        timestamp created_at
        timestamp revoked_at
    }

    OAUTH_ACCOUNTS {
        uuid id PK
        uuid user_id FK
        string provider
        string provider_user_id
        timestamp created_at
        timestamp updated_at
    }

    FINANCIAL_ACCOUNTS {
        uuid id PK
        uuid user_id FK
        string name
        string account_type
        string institution_name
        string account_identifier_masked
        string currency
        numeric opening_balance
        boolean is_active
        text notes
        jsonb metadata_json
        timestamp created_at
        timestamp updated_at
    }

    TRANSACTIONS {
        uuid id PK
        uuid user_id FK
        uuid financial_account_id FK
        date transaction_date
        timestamp posted_at
        numeric amount
        string currency
        string transaction_type
        string merchant
        text description
        string reference
        string category
        string subcategory
        string status
        string source
        text notes
        jsonb metadata_json
        timestamp created_at
        timestamp updated_at
    }

    FINANCIAL_DOCUMENTS {
        uuid id PK
        uuid user_id FK
        uuid financial_account_id FK
        string original_filename
        string document_type
        string mime_type
        bigint file_size
        string file_hash
        string storage_reference
        string processing_status
        text processing_error
        date statement_start_date
        date statement_end_date
        jsonb metadata_json
        timestamp uploaded_at
        timestamp processed_at
        timestamp created_at
        timestamp updated_at
    }
```

---

## 3. Table Specifications & Schema Details

### 1. `users`
- **Purpose**: Core application identity entity.
- **Columns**:
  - `id` (`UUID`, PK): Random UUID v4 identifier.
  - `email` (`VARCHAR(255)`, NOT NULL, UNIQUE, INDEX): Normalized user email address.
  - `password_hash` (`VARCHAR(255)`, NULLABLE): Nullable to support OAuth-only accounts that authenticate without local passwords.
  - `is_active` (`BOOLEAN`, NOT NULL, default `true`): Account state switch.
  - `is_verified` (`BOOLEAN`, NOT NULL, default `false`): Verification state (email verification).
  - `created_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`): Creation audit timestamp.
  - `updated_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`): Modification audit timestamp.

### 2. `user_profiles`
- **Purpose**: Stores profile preferences separately from credentials and authentication identities.
- **Columns**:
  - `id` (`UUID`, PK): Random UUID v4 identifier.
  - `user_id` (`UUID`, NOT NULL, UNIQUE, INDEX, FK → `users.id` `ON DELETE CASCADE`): Enforces a strict 1:1 relationship with the user identity.
  - `display_name` (`VARCHAR(100)`, NULLABLE): User's selected display name.
  - `preferred_currency` (`VARCHAR(3)`, NOT NULL, default `'USD'`): ISO 4217 currency code for dashboard aggregation.
  - `timezone` (`VARCHAR(50)`, NOT NULL, default `'UTC'`): IANA timezone identifier for presentation.
  - `created_at` / `updated_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`).

### 3. `sessions`
- **Purpose**: Server-side authentication session management for secure revocation and activity tracking.
- **Columns**:
  - `id` (`UUID`, PK): Session record ID.
  - `user_id` (`UUID`, NOT NULL, INDEX, FK → `users.id` `ON DELETE CASCADE`): Owning user.
  - `session_token_hash` (`VARCHAR(255)`, NOT NULL, UNIQUE, INDEX): Cryptographic hash (e.g. SHA-256) of the bearer token. Raw tokens are never stored.
  - `expires_at` (`TIMESTAMPTZ`, NOT NULL, INDEX): Session expiration boundary for fast cleanup queries.
  - `created_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`).
  - `revoked_at` (`TIMESTAMPTZ`, NULLABLE): Timestamp of explicit logout or revocation (`NULL` while active).

### 4. `oauth_accounts`
- **Purpose**: Connects third-party identity providers (Google, Facebook, GitHub, etc.) to internal user identities.
- **Columns**:
  - `id` (`UUID`, PK): Record identifier.
  - `user_id` (`UUID`, NOT NULL, INDEX, FK → `users.id` `ON DELETE CASCADE`).
  - `provider` (`VARCHAR(50)`, NOT NULL): Provider name (`google`, `facebook`, etc.).
  - `provider_user_id` (`VARCHAR(255)`, NOT NULL): Provider's persistent unique user identifier.
  - `created_at` / `updated_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`).
  - **Constraint**: `uq_oauth_provider_user_id` on `(provider, provider_user_id)`.

### 5. `financial_accounts`
- **Purpose**: Represents financial accounts owned by users (checking, savings, credit cards, loans, cash, investment portfolios).
- **Columns**:
  - `id` (`UUID`, PK): Account ID.
  - `user_id` (`UUID`, NOT NULL, INDEX, FK → `users.id` `ON DELETE CASCADE`): Account owner.
  - `name` (`VARCHAR(100)`, NOT NULL): Friendly account label (e.g. "Chase Freedom Flex").
  - `account_type` (`VARCHAR(50)`, NOT NULL): Extensible type (`bank`, `savings`, `credit_card`, `cash`, `investment`, `other`).
  - `institution_name` (`VARCHAR(100)`, NULLABLE): Financial institution (e.g. "Vanguard", "Barclays").
  - `account_identifier_masked` (`VARCHAR(50)`, NULLABLE): Safe masked identifier (e.g. `****1234`). Full account numbers are NEVER stored.
  - `currency` (`VARCHAR(3)`, NOT NULL, default `'USD'`): Native currency for the account (ISO 4217).
  - `opening_balance` (`NUMERIC(18, 4)`, NULLABLE): Baseline opening balance if provided.
  - `is_active` (`BOOLEAN`, NOT NULL, default `true`).
  - `notes` (`TEXT`, NULLABLE): User notes.
  - `metadata_json` (`JSONB`, NULLABLE): Extensible metadata storage for provider attributes.
  - `created_at` / `updated_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`).

### 6. `transactions`
- **Purpose**: Normalized financial ledger records. Serves as the authoritative source of truth for financial history and balance derivation.
- **Columns**:
  - `id` (`UUID`, PK): Transaction ID.
  - `user_id` (`UUID`, NOT NULL, INDEX, FK → `users.id` `ON DELETE CASCADE`): Owning user for explicit ownership queries and performance.
  - `financial_account_id` (`UUID`, NOT NULL, INDEX, FK → `financial_accounts.id` `ON DELETE CASCADE`): Associated account.
  - `transaction_date` (`DATE`, NOT NULL, INDEX): Value or occurrence date.
  - `posted_at` (`TIMESTAMPTZ`, NULLABLE): Timestamp when transaction posted to bank statement.
  - `amount` (`NUMERIC(18, 4)`, NOT NULL): Exact financial decimal value (positive for credit/debit depending on type).
  - `currency` (`VARCHAR(3)`, NOT NULL): Original transaction currency (ISO 4217). Exchange rate conversions are NOT performed silently.
  - `transaction_type` (`VARCHAR(20)`, NOT NULL): Extensible type (`debit`, `credit`, `transfer`).
  - `merchant` (`VARCHAR(255)`, NULLABLE): Counterparty name.
  - `description` (`TEXT`, NULLABLE): Full statement description or memo.
  - `reference` (`VARCHAR(100)`, NULLABLE): Statement reference or check number.
  - `category` (`VARCHAR(100)`, NULLABLE): Primary category tag.
  - `subcategory` (`VARCHAR(100)`, NULLABLE): Detailed subcategory tag.
  - `status` (`VARCHAR(50)`, NOT NULL, default `'posted'`): State (`posted`, `pending`, `cleared`).
  - `source` (`VARCHAR(50)`, NOT NULL, default `'manual'`): Origin (`manual`, `csv_import`, `pdf_import`, `bank_import`, `system`).
  - `notes` (`TEXT`, NULLABLE): User notes.
  - `metadata_json` (`JSONB`, NULLABLE): Raw import payload metadata.
  - `created_at` / `updated_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`).
  - **Composite Indexes**: 
    - `ix_transactions_account_date` on `(financial_account_id, transaction_date)`
    - `ix_transactions_user_date` on `(user_id, transaction_date)`

### 7. `financial_documents`
- **Purpose**: Metadata and state tracking for user-uploaded statements and financial receipts (PDF, CSV, OFX). Stores storage references only (no raw binary in Postgres).
- **Columns**:
  - `id` (`UUID`, PK): Document ID.
  - `user_id` (`UUID`, NOT NULL, INDEX, FK → `users.id` `ON DELETE CASCADE`): Uploader identity.
  - `financial_account_id` (`UUID`, NULLABLE, INDEX, FK → `financial_accounts.id` `ON DELETE SET NULL`): Optional linked financial account.
  - `original_filename` (`VARCHAR(255)`, NOT NULL): Uploaded file name.
  - `document_type` (`VARCHAR(50)`, NOT NULL, default `'bank_statement'`): Document classification (`bank_statement`, `credit_card_statement`, `csv_export`, `pdf_statement`).
  - `mime_type` (`VARCHAR(100)`, NOT NULL): Content type e.g., `application/pdf`, `text/csv`.
  - `file_size` (`BIGINT`, NOT NULL): Size in bytes.
  - `file_hash` (`VARCHAR(64)`, NULLABLE, INDEX): SHA-256 hash for future duplicate document detection.
  - `storage_reference` (`VARCHAR(500)`, NOT NULL): Safe internal file storage path / S3 key. Never exposed directly in API outputs.
  - `processing_status` (`VARCHAR(50)`, NOT NULL, default `'uploaded'`, INDEX): Ingestion state (`uploaded`, `processing`, `processed`, `failed`).
  - `processing_error` (`TEXT`, NULLABLE): Error message if processing failed.
  - `statement_start_date` (`DATE`, NULLABLE): Statement period start date.
  - `statement_end_date` (`DATE`, NULLABLE): Statement period end date.
  - `metadata_json` (`JSONB`, NULLABLE): Custom document metadata.
  - `uploaded_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`).
  - `processed_at` (`TIMESTAMPTZ`, NULLABLE): Completion timestamp.
  - `created_at` / `updated_at` (`TIMESTAMPTZ`, NOT NULL, default `now()`).

---

## 4. Key Design Decisions

### Monetary Precision
- **Never use floating-point types (`FLOAT`, `REAL`, `DOUBLE PRECISION`) for money**: Floating-point representations introduce binary rounding inaccuracies (e.g. `100.10` becomes `100.09999999999999`).
- **PostgreSQL `NUMERIC(18, 4)` mapped to Python `decimal.Decimal`**: Preserves up to 14 integer digits and 4 fractional decimal places (supporting fractional cents and cryptocurrency precision where relevant).

### Authoritative Ledger vs Cached Balances
- `current_balance` is **NOT** stored as an authoritative column on `financial_accounts`. Transactions remain the ultimate source of truth for all calculations and balance derivations.

### Primary Keys & UUIDs
- UUID v4 (`sa.Uuid(as_uuid=True)`) prevents sequential enumeration attacks, enables distributed or client-side ID generation, and obscures internal business volume from external observers.

### Timestamps & Timezones
- All stored timestamps use `TIMESTAMP WITH TIME ZONE` (`TIMESTAMPTZ` / `DateTime(timezone=True)`) in UTC.
- Display conversion to the user's local timezone is handled at the presentation layer using the `user_profiles.timezone` setting.

### Referential Integrity & `ON DELETE` Behaviors
- **`ON DELETE CASCADE`**:
  - `users` → `user_profiles`, `sessions`, `oauth_accounts`, `financial_accounts`, `transactions`, `financial_documents`.
  - `financial_accounts` → `transactions`: Deleting an account removes its ledger entries cleanly, ensuring no orphaned transactions exist.
- **`ON DELETE SET NULL`**:
  - `financial_accounts` → `financial_documents`: If an individual account is closed or deleted, uploaded financial statements remain preserved for the user's overall financial history and audit trail.

