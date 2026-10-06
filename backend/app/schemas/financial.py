"""Pydantic schemas for Phase 6 & Phase 8 financial data models."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ----------------------------------------------------------------------------
# Financial Account Schemas
# ----------------------------------------------------------------------------
class FinancialAccountCreate(BaseModel):
    """Request schema for creating a financial account."""

    name: str = Field(..., max_length=100, description="Account display name")
    account_type: str = Field(
        ..., max_length=50, description="Type of account (e.g., bank, savings, credit_card, cash, investment)"
    )
    institution_name: Optional[str] = Field(None, max_length=100, description="Financial institution name")
    account_identifier_masked: Optional[str] = Field(None, max_length=50, description="Masked identifier e.g., '****1234'")
    currency: str = Field("USD", min_length=3, max_length=3, description="ISO 4217 currency code")
    opening_balance: Optional[Decimal] = Field(None, description="Opening balance if applicable")
    notes: Optional[str] = Field(None, description="User notes")
    metadata_json: Optional[Dict[str, Any]] = Field(None, description="Safe custom metadata")


class FinancialAccountResponse(BaseModel):
    """Safe response schema for a financial account."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    account_type: str
    institution_name: Optional[str] = None
    account_identifier_masked: Optional[str] = None
    currency: str
    opening_balance: Optional[Decimal] = None
    is_active: bool
    notes: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------------
# Transaction Schemas
# ----------------------------------------------------------------------------
VALID_TRANSACTION_TYPES = frozenset({"credit", "debit"})


class TransactionCreate(BaseModel):
    """Request schema for creating a transaction."""

    financial_account_id: uuid.UUID = Field(..., description="Target financial account ID")
    transaction_date: date = Field(..., description="Date transaction occurred")
    posted_at: Optional[datetime] = Field(None, description="Timestamp transaction posted")
    amount: Decimal = Field(..., gt=Decimal("0"), description="Transaction monetary amount (must be > 0)")
    currency: str = Field("USD", min_length=3, max_length=3, description="ISO 4217 currency code")
    transaction_type: str = Field(..., max_length=20, description="Transaction type: 'credit' (income) or 'debit' (expense)")
    merchant: Optional[str] = Field(None, max_length=255, description="Merchant name")
    description: Optional[str] = Field(None, max_length=1000, description="Transaction description")
    reference: Optional[str] = Field(None, max_length=100, description="Reference code")
    category: Optional[str] = Field(None, max_length=100, description="Transaction category")
    subcategory: Optional[str] = Field(None, max_length=100, description="Transaction subcategory")
    status: str = Field("posted", max_length=50, description="Transaction status e.g., posted, pending")
    source: str = Field("manual", max_length=50, description="Source of transaction e.g., manual, csv_import, pdf_import")
    notes: Optional[str] = Field(None, max_length=2000, description="Notes")
    metadata_json: Optional[Dict[str, Any]] = Field(None, description="Import metadata")

    @model_validator(mode="after")
    def validate_transaction(self) -> "TransactionCreate":
        """Cross-field validation for transaction creation."""
        # Normalize currency
        self.currency = self.currency.upper().strip()
        if not self.currency.isalpha():
            raise ValueError(f"Currency code '{self.currency}' must contain only alphabetic characters.")

        # Validate transaction type
        if self.transaction_type not in VALID_TRANSACTION_TYPES:
            raise ValueError(
                f"Invalid transaction_type '{self.transaction_type}'. "
                f"Valid values: {', '.join(sorted(VALID_TRANSACTION_TYPES))}."
            )

        return self


class TransactionResponse(BaseModel):
    """Safe response schema for a transaction."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    financial_account_id: uuid.UUID
    user_id: uuid.UUID
    transaction_fingerprint: Optional[str] = None
    transaction_date: date
    posted_at: Optional[datetime] = None
    amount: Decimal
    currency: str
    transaction_type: str
    merchant: Optional[str] = None
    description: Optional[str] = None
    reference: Optional[str] = None
    category: Optional[str] = None
    subcategory: Optional[str] = None
    status: str
    source: str
    notes: Optional[str] = None
    metadata_json: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------------
# Financial Document Schemas
# ----------------------------------------------------------------------------
class FinancialDocumentCreate(BaseModel):
    """Request schema for registering document metadata."""

    financial_account_id: Optional[uuid.UUID] = Field(None, description="Optional linked account ID")
    original_filename: str = Field(..., max_length=255, description="Original filename")
    document_type: str = Field("bank_statement", max_length=50, description="Document type e.g. bank_statement, pdf_statement, csv_export")
    mime_type: str = Field(..., max_length=100, description="MIME type e.g. application/pdf, text/csv")
    file_size: int = Field(..., ge=0, description="File size in bytes")
    file_hash: Optional[str] = Field(None, max_length=64, description="SHA-256 hash")
    storage_reference: str = Field(..., max_length=500, description="Internal storage reference")
    statement_start_date: Optional[date] = Field(None, description="Statement period start date")
    statement_end_date: Optional[date] = Field(None, description="Statement period end date")
    metadata_json: Optional[Dict[str, Any]] = Field(None, description="Metadata")


class FinancialDocumentResponse(BaseModel):
    """Safe response schema for a financial document metadata."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    financial_account_id: Optional[uuid.UUID] = None
    original_filename: str
    document_type: str
    mime_type: str
    file_size: int
    file_hash: Optional[str] = None
    processing_status: str
    processing_error: Optional[str] = None
    statement_start_date: Optional[date] = None
    statement_end_date: Optional[date] = None
    metadata_json: Optional[Dict[str, Any]] = None
    uploaded_at: datetime
    processed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ----------------------------------------------------------------------------
# Financial Event & Replay Schemas (Phase 8)
# ----------------------------------------------------------------------------
class FinancialEventResponse(BaseModel):
    """Safe response schema for immutable financial events."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    financial_account_id: uuid.UUID
    event_type: str
    transaction_id: Optional[uuid.UUID] = None
    source: str
    idempotency_key: str
    payload: Dict[str, Any]
    created_at: datetime


class ReplaySummaryResponse(BaseModel):
    """Response schema for replayed account balances."""

    financial_account_id: uuid.UUID
    user_id: uuid.UUID
    transaction_count: int
    financial_event_count: int
    total_credits: Decimal
    total_debits: Decimal
    net_balance_movement: Decimal


# ----------------------------------------------------------------------------
# Phase 9 – Double-Entry Ledger Schemas
# ----------------------------------------------------------------------------
class LedgerAccountResponse(BaseModel):
    """Safe response schema for a ledger account."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    financial_account_id: Optional[uuid.UUID] = None
    name: str
    account_type: str
    currency: str
    created_at: datetime


class LedgerEntryResponse(BaseModel):
    """Safe response schema for a ledger entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    ledger_account_id: uuid.UUID
    transaction_id: Optional[uuid.UUID] = None
    financial_event_id: Optional[uuid.UUID] = None
    debit_amount: Optional[Decimal] = None
    credit_amount: Optional[Decimal] = None
    currency: str
    description: Optional[str] = None
    created_at: datetime


class LedgerBalanceResponse(BaseModel):
    """Aggregate debit / credit balance for the authenticated user."""

    total_debit: Decimal
    total_credit: Decimal
    difference: Decimal
    is_balanced: bool
