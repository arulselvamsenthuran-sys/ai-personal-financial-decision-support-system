# AI Security Architecture & Safety Policy (Phase 16)

This document specifies the security architecture, trust boundaries, tool authorization layer, and safety guardrails governing the AI layer of the **AI-Powered Personal Financial Decision Support System**.

---

## 1. Core Architectural Principle

> **"The LLM is NOT the financial calculation engine."**

The deterministic backend engine (`DecisionSupportEngine`, `AnalyticsService`, `LedgerService`) is the sole source of truth for all financial numbers, balances, ratios, risk indicators, and cash flow projections.

The AI layer serves exclusively to explain, clarify, and summarize deterministic facts in natural language. It cannot execute financial actions, alter backend numbers, or override risk severities.

---

## 2. AI Trust Boundary

The system maintains a strict operational trust boundary separating **Trusted System Instructions & Data** from **Untrusted External Content**:

| Content Type | Classification | Treatment |
| :--- | :--- | :--- |
| System Prompts & Safety Invariants | **TRUSTED** | Highest priority. Defines model permissions and output constraints. |
| Deterministic Engine Output | **TRUSTED** | Authoritative facts provided directly by backend financial services. |
| User Chat Questions | **UNTRUSTED** | Sanitized and enclosed in `<untrusted_user_question>` XML tags. |
| User Descriptions / Notes | **UNTRUSTED** | Sanitized and enclosed in `<untrusted_user_input>` XML tags. |
| Uploaded Files (CSV, PDF, OCR text) | **UNTRUSTED** | Treated as raw data ONLY. Enclosed in `<untrusted_document_data>` tags. |

### XML Trust Boundary Isolation
All untrusted text is wrapped in strict XML delimiters before context construction. System instructions mandate that text within these tags is processed purely as literal string data. Instructions embedded inside user text or uploaded files (e.g., *"Ignore previous instructions"*) cannot override system safety policy.

---

## 3. Prompt Injection Defense

Prompt injection defense is enforced across three distinct layers:

1. **Pre-LLM Injection Pattern Scanner**: Inputs are scanned for known override signatures (`detect_prompt_injection()`). Detected attempts trigger a security audit log (`AI_PROMPT_INJECTION_ATTEMPT`).
2. **XML Tag Isolation**: Untrusted content is HTML-escaped and isolated within XML tags.
3. **System Policy Invariants**: System prompts explicitly instruct the model to reject user commands contained inside data tags.

---

## 4. Tool Authorization Layer & Allowlist

The LLM has **NO direct access** to PostgreSQL, SQLAlchemy sessions, raw SQL queries, system filesystems, arbitrary URLs, or backend functions.

All tool executions flow through the **Tool Authorization Layer**:

```text
User Request
     ↓
FastAPI Session Auth (current_user.id)
     ↓
LLM Provider
     ↓
Tool Execution Request
     ↓
Allowlist Verification (TOOL_ALLOWLIST)
     ↓
Pydantic Argument Validation
     ↓
IDOR Ownership Enforcement (session user_id)
     ↓
Backend Deterministic Domain Service
     ↓
Output Size Truncation & Audit Logging
     ↓
LLM Response
```

### Approved Tool Allowlist (`TOOL_ALLOWLIST`)

- `get_financial_state`: Retrieve financial account balances and summary state for authenticated user.
- `get_income_and_expenses`: Retrieve total income, expenses, and net cash flow by currency.
- `get_cash_flow`: Retrieve baseline net cash flow and savings rate summary.
- `get_recurring_expenses`: Retrieve detected recurring expense patterns.
- `simulate_decision_scenario`: Deterministically evaluate hypothetical financial scenarios.

---

## 5. IDOR & Authorization Protection

- **Session Authority**: User identity is derived strictly from the authenticated HttpOnly session cookie (`session_id`).
- **Parameter Stripping**: Any `user_id` parameter passed within LLM prompts, tool arguments, or request payloads is stripped and ignored.
- **Account Ownership Verification**: Financial tools verify that target account IDs belong to `current_user.id` before returning data.

---

## 6. Data Minimization & Redaction

- Passwords, hashes, session tokens, API keys, full account numbers, and credit card numbers are stripped and redacted (`[REDACTED]`) prior to model context generation.
- The AI receives aggregated metrics (e.g., monthly income, total expenses, net cash flow) rather than raw sensitive transaction logs.

---

## 7. Rate Limiting & Input Bounds

| Parameter | Configurable Limit | Action on Exceeded |
| :--- | :--- | :--- |
| **Max Question Length** | `ai_max_question_length` (1000 chars) | HTTP 422 Unprocessable Entity |
| **Max Conversation History** | `ai_max_chat_history_messages` (10 msgs) | HTTP 422 Unprocessable Entity |
| **Max Document Context** | `ai_max_document_context_size` (10000 chars) | HTTP 422 Unprocessable Entity |
| **AI Endpoint Frequency** | `ai_rate_limit_per_minute` (10 req/min) | HTTP 429 Too Many Requests |

---

## 8. Audit Logging & Correlation ID Tracing

Every AI interaction is tagged with a unique correlation ID (`req_...`) and logged to the security audit stream:

- `AI_REQUEST`: Logged upon receiving a valid AI request.
- `AI_TOOL_ALLOWED`: Logged when an authorized tool is executed.
- `AI_TOOL_DENIED`: Logged when an unauthorized or invalid tool request is rejected.
- `AI_PROMPT_INJECTION_ATTEMPT`: Logged when prompt injection signatures are detected.
- `AI_FALLBACK`: Logged when graceful fallback responses are returned due to LLM provider timeouts or errors.

Audit logs never record passwords, session tokens, or raw sensitive file contents.

---

## 9. Known Limitations

1. **Persistent Memory**: Phase 16 does not maintain persistent vector database memory across user sessions (Phase 17 scope).
2. **Standing Autonomous Actions**: The AI layer cannot perform standing automated bank transfers, investments, or payments. All financial decisions remain under human control.
