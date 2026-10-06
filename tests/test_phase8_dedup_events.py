"""Comprehensive unit & integration tests for Phase 8.

Covers:
- Transaction Fingerprinting
- Database Deduplication
- Document vs Transaction Deduplication Isolation
- Immutable Financial Events
- Atomicity and Event Idempotency
- Replay Foundation
- Security & Cross-User Isolation
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
from app.models.financial_document import FinancialDocument
from app.models.financial_event import FinancialEvent
from app.models.transaction import Transaction
from app.models.user import User
from app.services.document_service import document_ingestion_service
from app.services.fingerprint import generate_transaction_fingerprint
from app.services.replay_service import replay_service


# ----------------------------------------------------------------------------
# 1. Fingerprint Tests
# ----------------------------------------------------------------------------
def test_fingerprint_deterministic():
    fp1 = generate_transaction_fingerprint(
        financial_account_id="11111111-1111-1111-1111-111111111111",
        transaction_date=date(2026, 1, 15),
        amount=Decimal("120.50"),
        transaction_type="debit",
        merchant="Starbucks Coffee",
        reference="REF12345",
    )
    fp2 = generate_transaction_fingerprint(
        financial_account_id="11111111-1111-1111-1111-111111111111",
        transaction_date=date(2026, 1, 15),
        amount=Decimal("120.5000"),
        transaction_type="debit",
        merchant="Starbucks Coffee",
        reference="REF12345",
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_fingerprint_normalization_whitespace_and_case():
    fp1 = generate_transaction_fingerprint(
        financial_account_id="11111111-1111-1111-1111-111111111111",
        transaction_date="2026-01-15",
        amount=120.5,
        transaction_type="DEBIT ",
        merchant="  STARBUCKS   COFFEE  ",
        reference=" Ref12345 ",
    )
    fp2 = generate_transaction_fingerprint(
        financial_account_id="11111111-1111-1111-1111-111111111111",
        transaction_date=date(2026, 1, 15),
        amount=Decimal("120.5000"),
        transaction_type="debit",
        merchant="starbucks coffee",
        reference="ref12345",
    )
    assert fp1 == fp2


def test_fingerprint_null_empty_handling():
    fp1 = generate_transaction_fingerprint(
        financial_account_id="11111111-1111-1111-1111-111111111111",
        transaction_date=date(2026, 1, 15),
        amount=Decimal("50.00"),
        transaction_type="debit",
        merchant=None,
        reference="",
    )
    fp2 = generate_transaction_fingerprint(
        financial_account_id="11111111-1111-1111-1111-111111111111",
        transaction_date=date(2026, 1, 15),
        amount=Decimal("50.00"),
        transaction_type="debit",
        merchant="",
        reference=None,
    )
    assert fp1 == fp2


def test_fingerprint_sensitivity_different_inputs():
    account_id = "11111111-1111-1111-1111-111111111111"
    base_fp = generate_transaction_fingerprint(
        account_id, date(2026, 1, 15), Decimal("100.00"), "debit", "Merchant A", "Ref 1"
    )

    # Different account
    assert base_fp != generate_transaction_fingerprint(
        "22222222-2222-2222-2222-222222222222", date(2026, 1, 15), Decimal("100.00"), "debit", "Merchant A", "Ref 1"
    )
    # Different date
    assert base_fp != generate_transaction_fingerprint(
        account_id, date(2026, 1, 16), Decimal("100.00"), "debit", "Merchant A", "Ref 1"
    )
    # Different amount
    assert base_fp != generate_transaction_fingerprint(
        account_id, date(2026, 1, 15), Decimal("100.01"), "debit", "Merchant A", "Ref 1"
    )
    # Different type
    assert base_fp != generate_transaction_fingerprint(
        account_id, date(2026, 1, 15), Decimal("100.00"), "credit", "Merchant A", "Ref 1"
    )
    # Different merchant
    assert base_fp != generate_transaction_fingerprint(
        account_id, date(2026, 1, 15), Decimal("100.00"), "debit", "Merchant B", "Ref 1"
    )
    # Different reference
    assert base_fp != generate_transaction_fingerprint(
        account_id, date(2026, 1, 15), Decimal("100.00"), "debit", "Merchant A", "Ref 2"
    )


# ----------------------------------------------------------------------------
# Helpers & Fixtures for DB Tests
# ----------------------------------------------------------------------------
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
    user = User(email=f"user_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
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
        currency="USD",
    )
    db.add(acc)
    db.commit()
    db.refresh(acc)
    return acc


# ----------------------------------------------------------------------------
# 2. Ingestion & Deduplication Tests
# ----------------------------------------------------------------------------
def test_ingest_transactions_and_skips_duplicates(db: Session, test_user: User, test_account: FinancialAccount):
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-02-01,50.00,Target,debit,REF100\n"
        b"2026-02-02,75.25,Walmart,debit,REF101\n"
    )
    file1 = DummyUploadFile("stmt1.csv", csv_content)
    doc1 = document_ingestion_service.process_document_upload(db, test_user, test_account.id, file1)

    assert doc1.processing_status == "completed"
    assert doc1.metadata_json["imported_transaction_count"] == 2
    assert doc1.metadata_json["skipped_duplicate_count"] == 0

    # Ingest file with 1 duplicate and 1 new
    csv_content_2 = (
        b"date,amount,merchant,type,reference\n"
        b"2026-02-01,50.00,Target,debit,REF100\n"  # Duplicate of file 1
        b"2026-02-03,120.00,Costco,debit,REF102\n" # New
    )
    file2 = DummyUploadFile("stmt2.csv", csv_content_2)
    doc2 = document_ingestion_service.process_document_upload(db, test_user, test_account.id, file2)

    assert doc2.processing_status == "completed"
    assert doc2.metadata_json["imported_transaction_count"] == 1
    assert doc2.metadata_json["skipped_duplicate_count"] == 1

    # Verify total transactions in DB for this account is 3 (not 4)
    tx_count = db.query(Transaction).filter(Transaction.financial_account_id == test_account.id).count()
    assert tx_count == 3


def test_intra_batch_deduplication(db: Session, test_user: User, test_account: FinancialAccount):
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-02-10,25.00,Gas Station,debit,REF200\n"
        b"2026-02-10,25.00,Gas Station,debit,REF200\n" # Duplicate row inside same statement
    )
    file = DummyUploadFile("stmt_batch_dup.csv", csv_content)
    doc = document_ingestion_service.process_document_upload(db, test_user, test_account.id, file)

    assert doc.processing_status == "completed"
    assert doc.metadata_json["imported_transaction_count"] == 1
    assert doc.metadata_json["skipped_duplicate_count"] == 1


def test_same_transaction_in_different_account_allowed(db: Session, test_user: User, test_account: FinancialAccount):
    # Second account for same user
    acc2 = FinancialAccount(
        user_id=test_user.id,
        name="Secondary Savings",
        account_type="bank",
        currency="USD",
    )
    db.add(acc2)
    db.commit()
    db.refresh(acc2)

    csv_content1 = (
        b"date,amount,merchant,type,reference\n"
        b"2026-02-15,300.00,Transfer,credit,REF300\n"
    )
    file1 = DummyUploadFile("stmt_acc1.csv", csv_content1)
    doc1 = document_ingestion_service.process_document_upload(db, test_user, test_account.id, file1)
    assert doc1.metadata_json["imported_transaction_count"] == 1

    csv_content2 = (
        b"date,amount,merchant,type,reference\n"
        b"2026-02-15,300.00,Transfer,credit,REF300\n"
        b"# Account 2 export\n"
    )
    file2 = DummyUploadFile("stmt_acc2.csv", csv_content2)
    doc2 = document_ingestion_service.process_document_upload(db, test_user, acc2.id, file2)
    assert doc2.metadata_json["imported_transaction_count"] == 1


def test_document_hash_dedup_distinct_from_transaction_dedup(db: Session, test_user: User, test_account: FinancialAccount):
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-02-20,10.00,Bakery,debit,REF400\n"
    )
    file1 = DummyUploadFile("doc1.csv", csv_content)
    document_ingestion_service.process_document_upload(db, test_user, test_account.id, file1)

    # Re-uploading exact same document file causes HTTP 409 Conflict (Phase 7 Document Dedup)
    file1_again = DummyUploadFile("doc1.csv", csv_content)
    with pytest.raises(HTTPException) as exc_info:
        document_ingestion_service.process_document_upload(db, test_user, test_account.id, file1_again)
    assert exc_info.value.status_code == 409


# ----------------------------------------------------------------------------
# 3. Financial Events, Immutability & Atomicity Tests
# ----------------------------------------------------------------------------
def test_financial_event_creation_and_payload(db: Session, test_user: User, test_account: FinancialAccount):
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-03-01,500.00,Employer,credit,SALARY01\n"
    )
    file = DummyUploadFile("salary.csv", csv_content)
    document_ingestion_service.process_document_upload(db, test_user, test_account.id, file)

    events = db.query(FinancialEvent).filter(FinancialEvent.financial_account_id == test_account.id).all()
    assert len(events) == 1

    event = events[0]
    assert event.event_type == "TRANSACTION_IMPORTED"
    assert event.user_id == test_user.id
    assert event.financial_account_id == test_account.id
    assert event.payload["amount"] == "500.00"
    assert event.payload["merchant"] == "Employer"


def test_financial_event_immutability(db: Session, test_user: User, test_account: FinancialAccount):
    event = FinancialEvent(
        user_id=test_user.id,
        financial_account_id=test_account.id,
        event_type="TRANSACTION_IMPORTED",
        source="test",
        idempotency_key=f"test_immutability_{uuid.uuid4().hex}",
        payload={"test": "data"},
    )
    db.add(event)
    db.commit()

    # Attempting to update event must raise RuntimeError
    event.source = "tampered"
    with pytest.raises(RuntimeError, match="immutable"):
        db.commit()

    db.rollback()

    # Attempting to delete event must raise RuntimeError
    with pytest.raises(RuntimeError, match="immutable"):
        db.delete(event)
        db.commit()

    db.rollback()


# ----------------------------------------------------------------------------
# 4. Replay Service Tests
# ----------------------------------------------------------------------------
def test_replay_service_calculations(db: Session, test_user: User, test_account: FinancialAccount):
    csv_content = (
        b"date,amount,merchant,type,reference\n"
        b"2026-03-05,1000.00,Paycheck,credit,REF1\n"
        b"2026-03-06,200.00,Groceries,debit,REF2\n"
        b"2026-03-07,50.00,Utilities,debit,REF3\n"
    )
    file = DummyUploadFile("replay_stmt.csv", csv_content)
    document_ingestion_service.process_document_upload(db, test_user, test_account.id, file)

    summary = replay_service.replay_account(db, test_user.id, test_account.id)
    assert summary["transaction_count"] == 3
    assert summary["financial_event_count"] == 3
    assert summary["total_credits"] == Decimal("1000.0000")
    assert summary["total_debits"] == Decimal("250.0000")
    assert summary["net_balance_movement"] == Decimal("750.0000")


# ----------------------------------------------------------------------------
# 5. Security & Isolation Tests
# ----------------------------------------------------------------------------
def test_cross_user_isolation(db: Session, test_user: User, test_account: FinancialAccount):
    other_user = User(email=f"other_{uuid.uuid4().hex[:8]}@example.com", is_active=True)
    db.add(other_user)
    db.commit()

    # User B cannot access User A's replay
    with pytest.raises(HTTPException) as exc_info:
        replay_service.replay_account(db, other_user.id, test_account.id)
    assert exc_info.value.status_code == 404
