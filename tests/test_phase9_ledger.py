"""Comprehensive tests for Phase 9: Double-Entry Financial Ledger Engine.

Covers:
1.  Ledger account auto-creation (ensure_default_accounts is idempotent)
2.  Salary (credit) transaction creates Debit Bank + Credit Income
3.  Expense (debit) transaction creates Debit Expense + Credit Bank
4.  Debit equals Credit for every posting
5.  Unbalanced entry rejection (service-layer ValueError)
6.  Cross-user isolation (user B cannot see user A's data)
7.  Transaction rollback when ledger posting fails
8.  All Phase 1-8 tests still pass (implicitly – this file only adds Phase 9)
9.  Balance summary returns correct aggregates
10. Per-transaction ledger entry query
"""

from datetime import date
from decimal import Decimal
import io
from typing import Generator
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.financial_account import FinancialAccount
from app.models.ledger import AccountType, LedgerAccount, LedgerEntry
from app.models.transaction import Transaction
from app.models.user import User
from app.services.document_service import document_ingestion_service
from app.services.ledger_service import LedgerService, ledger_service
from app.services.ledger_validation import (
    LedgerValidationError,
    LedgerValidationService,
    ledger_validation_service,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------
class DummyUploadFile:
    def __init__(self, filename: str, content: bytes, content_type: str = "text/csv"):
        self.filename = filename
        self.file = io.BytesIO(content)
        self.content_type = content_type


@pytest.fixture
def db() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def test_user(db: Session) -> User:
    user = User(email=f"ledger_user_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture
def test_account(db: Session, test_user: User) -> FinancialAccount:
    acc = FinancialAccount(
        user_id=test_user.id,
        name="Primary Checking",
        account_type="bank",
        currency="LKR",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


@pytest.fixture
def other_user(db: Session) -> User:
    """A second, independent user (user B)."""
    user = User(email=f"other_ledger_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# 1. Default ledger account creation
# ---------------------------------------------------------------------------
def test_ensure_default_accounts_creates_three_accounts(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """ensure_default_accounts must create ASSET, INCOME, and EXPENSE accounts."""
    accounts = ledger_service.ensure_default_accounts(
        db=db,
        user_id=test_user.id,
        currency="LKR",
        financial_account_id=test_account.id,
    )

    assert AccountType.ASSET in accounts
    assert AccountType.INCOME in accounts
    assert AccountType.EXPENSE in accounts

    db_count = (
        db.query(LedgerAccount)
        .filter(LedgerAccount.user_id == test_user.id)
        .count()
    )
    assert db_count == 3


def test_ensure_default_accounts_is_idempotent(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """Calling ensure_default_accounts twice must NOT create duplicate rows."""
    ledger_service.ensure_default_accounts(
        db=db, user_id=test_user.id, currency="LKR",
        financial_account_id=test_account.id,
    )
    ledger_service.ensure_default_accounts(
        db=db, user_id=test_user.id, currency="LKR",
        financial_account_id=test_account.id,
    )

    db_count = (
        db.query(LedgerAccount)
        .filter(LedgerAccount.user_id == test_user.id)
        .count()
    )
    assert db_count == 3, "Duplicate ledger accounts were created (non-idempotent)"


# ---------------------------------------------------------------------------
# 2. Salary (credit) transaction creates Debit Bank + Credit Income
# ---------------------------------------------------------------------------
def test_salary_credit_transaction_ledger_entries(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """A credit transaction must produce Debit=Bank, Credit=Income."""
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-04-01,80000.00,Employer Salary,credit,SAL001\n"
    )
    file = DummyUploadFile("salary.csv", csv_content)
    doc = document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )
    assert doc.processing_status == "completed"

    # Fetch the transaction
    tx = (
        db.query(Transaction)
        .filter(Transaction.financial_account_id == test_account.id)
        .first()
    )
    assert tx is not None

    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.transaction_id == tx.id)
        .all()
    )
    assert len(entries) == 2, "Expected exactly 2 ledger entries for this transaction"

    debit_entries = [e for e in entries if e.debit_amount is not None]
    credit_entries = [e for e in entries if e.credit_amount is not None]
    assert len(debit_entries) == 1
    assert len(credit_entries) == 1

    # Debit must be on Bank Account (ASSET)
    debit_acct = db.get(LedgerAccount, debit_entries[0].ledger_account_id)
    assert debit_acct.account_type == AccountType.ASSET.value, (
        f"Salary debit should hit ASSET, got {debit_acct.account_type}"
    )

    # Credit must be on Income account
    credit_acct = db.get(LedgerAccount, credit_entries[0].ledger_account_id)
    assert credit_acct.account_type == AccountType.INCOME.value, (
        f"Salary credit should hit INCOME, got {credit_acct.account_type}"
    )

    # Amounts
    assert debit_entries[0].debit_amount == Decimal("80000.0000")
    assert credit_entries[0].credit_amount == Decimal("80000.0000")


# ---------------------------------------------------------------------------
# 3. Expense (debit) transaction creates Debit Expense + Credit Bank
# ---------------------------------------------------------------------------
def test_expense_debit_transaction_ledger_entries(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """A debit transaction must produce Debit=Expense, Credit=Bank."""
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-04-05,3500.00,Ceylon Electricity Board,debit,UTIL001\n"
    )
    file = DummyUploadFile("electricity.csv", csv_content)
    doc = document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )
    assert doc.processing_status == "completed"

    tx = (
        db.query(Transaction)
        .filter(Transaction.financial_account_id == test_account.id)
        .first()
    )
    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.transaction_id == tx.id)
        .all()
    )
    assert len(entries) == 2

    debit_entries = [e for e in entries if e.debit_amount is not None]
    credit_entries = [e for e in entries if e.credit_amount is not None]

    # Debit must be on Expense account
    debit_acct = db.get(LedgerAccount, debit_entries[0].ledger_account_id)
    assert debit_acct.account_type == AccountType.EXPENSE.value

    # Credit must be on Bank Account (ASSET)
    credit_acct = db.get(LedgerAccount, credit_entries[0].ledger_account_id)
    assert credit_acct.account_type == AccountType.ASSET.value

    assert debit_entries[0].debit_amount == Decimal("3500.0000")
    assert credit_entries[0].credit_amount == Decimal("3500.0000")


# ---------------------------------------------------------------------------
# 4. Debit equals Credit (accounting equation)
# ---------------------------------------------------------------------------
def test_debit_equals_credit_for_multiple_transactions(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """For every imported transaction, sum(debit) must equal sum(credit)."""
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-05-01,100000.00,Employer,credit,SAL002\n"
        b"2026-05-02,25000.00,Rent,debit,RENT001\n"
        b"2026-05-03,5000.00,Groceries,debit,GRC001\n"
    )
    file = DummyUploadFile("stmt.csv", csv_content)
    doc = document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )
    assert doc.processing_status == "completed"
    assert doc.metadata_json["imported_transaction_count"] == 3

    transactions = (
        db.query(Transaction)
        .filter(Transaction.financial_account_id == test_account.id)
        .all()
    )
    for tx in transactions:
        result = ledger_validation_service.validate_double_entry(
            db=db, transaction_id=tx.id, user_id=test_user.id
        )
        assert result["is_balanced"], (
            f"Transaction {tx.id} ledger is unbalanced: {result}"
        )


# ---------------------------------------------------------------------------
# 5. Unbalanced entry rejection
# ---------------------------------------------------------------------------
def test_unbalanced_entry_rejected_by_validation_service(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """Manually inserting an unbalanced pair of entries raises LedgerValidationError."""
    # Get or create ledger accounts
    ledger_service.ensure_default_accounts(
        db=db, user_id=test_user.id, currency="LKR",
        financial_account_id=test_account.id,
    )
    bank_acct = (
        db.query(LedgerAccount)
        .filter(
            LedgerAccount.user_id == test_user.id,
            LedgerAccount.account_type == AccountType.ASSET.value,
        )
        .first()
    )

    # Create a dummy transaction
    tx = Transaction(
        user_id=test_user.id,
        financial_account_id=test_account.id,
        transaction_fingerprint=f"test_unbalanced_{uuid.uuid4().hex}",
        transaction_date=date(2026, 6, 1),
        amount=Decimal("1000.00"),
        currency="LKR",
        transaction_type="debit",
        source="test",
    )
    db.add(tx)
    db.flush()

    # Deliberately create ONLY a debit entry (no matching credit → imbalanced)
    bad_entry = LedgerEntry(
        user_id=test_user.id,
        ledger_account_id=bank_acct.id,
        transaction_id=tx.id,
        debit_amount=Decimal("1000.00"),
        credit_amount=None,
        currency="LKR",
        description="Unbalanced test entry",
    )
    db.add(bad_entry)
    db.flush()

    with pytest.raises(LedgerValidationError, match="imbalance"):
        ledger_validation_service.validate_double_entry(
            db=db, transaction_id=tx.id, user_id=test_user.id
        )


# ---------------------------------------------------------------------------
# 6. Cross-user isolation
# ---------------------------------------------------------------------------
def test_cross_user_ledger_isolation(
    db: Session,
    test_user: User,
    test_account: FinancialAccount,
    other_user: User,
):
    """User B must not be able to see User A's ledger entries."""
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-07-01,50000.00,Payroll,credit,PAY001\n"
    )
    file = DummyUploadFile("payroll.csv", csv_content)
    document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )

    # User B queries ledger entries
    other_user_entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.user_id == other_user.id)
        .count()
    )
    assert other_user_entries == 0, (
        "Cross-user IDOR: User B can see User A's ledger entries"
    )

    # User B queries ledger accounts
    other_user_accounts = (
        db.query(LedgerAccount)
        .filter(LedgerAccount.user_id == other_user.id)
        .count()
    )
    assert other_user_accounts == 0


def test_validate_double_entry_cross_user_returns_zero(
    db: Session,
    test_user: User,
    test_account: FinancialAccount,
    other_user: User,
):
    """validate_double_entry for other_user on user_a's tx must show no entries (balanced 0==0)."""
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-07-02,20000.00,Freelance,credit,FREE001\n"
    )
    file = DummyUploadFile("freelance.csv", csv_content)
    document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )
    tx = (
        db.query(Transaction)
        .filter(Transaction.financial_account_id == test_account.id)
        .first()
    )

    # Passing other_user's ID should find zero entries → balanced (0 == 0) but
    # importantly it MUST NOT return user A's entries.
    result = ledger_validation_service.validate_double_entry(
        db=db, transaction_id=tx.id, user_id=other_user.id
    )
    assert result["total_debit"] == Decimal("0")
    assert result["total_credit"] == Decimal("0")


# ---------------------------------------------------------------------------
# 7. Transaction rollback when ledger posting fails
# ---------------------------------------------------------------------------
def test_ledger_failure_rolls_back_transaction_and_event(
    db: Session, test_user: User, test_account: FinancialAccount, monkeypatch
):
    """When post_transaction_to_ledger raises, the entire DB tx must rollback."""
    # Patch the ledger service to simulate a failure
    def _boom(db, transaction, financial_event_id=None):
        raise RuntimeError("Simulated ledger failure")

    monkeypatch.setattr(
        "app.services.document_service.ledger_service.post_transaction_to_ledger",
        _boom,
    )

    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-08-01,15000.00,Bonus,credit,BONUS001\n"
    )
    file = DummyUploadFile("bonus.csv", csv_content)
    doc = document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )

    # Document itself is updated to completed (outer try/except catches and marks completed
    # when ledger failure is caught as Exception — but NO transaction must be persisted)
    tx_count = (
        db.query(Transaction)
        .filter(Transaction.financial_account_id == test_account.id)
        .count()
    )
    assert tx_count == 0, (
        f"Expected 0 transactions after ledger failure rollback, got {tx_count}"
    )


# ---------------------------------------------------------------------------
# 8. Balance summary
# ---------------------------------------------------------------------------
def test_balance_summary_reflects_all_transactions(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """get_user_balance_summary must return total_debit == total_credit across all postings."""
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-09-01,200000.00,Company,credit,SAL003\n"
        b"2026-09-02,50000.00,Rent,debit,RENT002\n"
        b"2026-09-03,10000.00,Phone,debit,PHONE001\n"
    )
    file = DummyUploadFile("multi.csv", csv_content)
    doc = document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )
    assert doc.metadata_json["imported_transaction_count"] == 3

    summary = ledger_validation_service.get_user_balance_summary(
        db=db, user_id=test_user.id
    )

    # 3 transactions × 2 entries each = 6 entries
    # Total debit posted = 200000 (bank dr) + 50000 (expense dr) + 10000 (expense dr) = 260000
    # Total credit posted = 200000 (income cr) + 50000 (bank cr) + 10000 (bank cr) = 260000
    assert summary["total_debit"] == Decimal("260000.0000")
    assert summary["total_credit"] == Decimal("260000.0000")
    assert summary["is_balanced"] is True
    assert summary["difference"] == Decimal("0")


# ---------------------------------------------------------------------------
# 9. Per-transaction ledger entry queries
# ---------------------------------------------------------------------------
def test_per_transaction_ledger_entry_query(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """Each transaction must have exactly 2 ledger entries."""
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-10-01,7500.00,Office Supplies,debit,OFFICE001\n"
        b"2026-10-02,45000.00,Client Invoice,credit,INV001\n"
    )
    file = DummyUploadFile("per_tx.csv", csv_content)
    document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )

    transactions = (
        db.query(Transaction)
        .filter(Transaction.financial_account_id == test_account.id)
        .all()
    )
    assert len(transactions) == 2
    for tx in transactions:
        entries = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.transaction_id == tx.id)
            .all()
        )
        assert len(entries) == 2, (
            f"Transaction {tx.id} has {len(entries)} ledger entries, expected 2"
        )


# ---------------------------------------------------------------------------
# 10. Ledger entry integrity: debit XOR credit, never both, never negative
# ---------------------------------------------------------------------------
def test_ledger_entries_are_debit_xor_credit(
    db: Session, test_user: User, test_account: FinancialAccount
):
    """Every ledger entry must have exactly one of debit_amount or credit_amount set."""
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-11-01,30000.00,Consulting,credit,CONS001\n"
        b"2026-11-02,5000.00,Transport,debit,TRN001\n"
    )
    file = DummyUploadFile("xor_test.csv", csv_content)
    document_ingestion_service.process_document_upload(
        db, test_user, test_account.id, file
    )

    entries = (
        db.query(LedgerEntry)
        .filter(LedgerEntry.user_id == test_user.id)
        .all()
    )
    assert len(entries) > 0
    for entry in entries:
        has_debit = entry.debit_amount is not None
        has_credit = entry.credit_amount is not None
        # Exactly one must be set (XOR)
        assert has_debit != has_credit, (
            f"Entry {entry.id} violates debit XOR credit invariant: "
            f"debit={entry.debit_amount}, credit={entry.credit_amount}"
        )
        # No negative values
        if has_debit:
            assert entry.debit_amount >= Decimal("0")
        if has_credit:
            assert entry.credit_amount >= Decimal("0")
