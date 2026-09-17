"""Database model integration tests for Phase 2 architecture.

Tests are run inside rolled-back transactions to ensure the development database
is never polluted.
"""

from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.session import check_db_connection, engine
from app.models import (
    FinancialAccount,
    FinancialDocument,
    OAuthAccount,
    Session as AuthSession,
    Transaction,
    User,
    UserProfile,
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Yield a database session that is rolled back after each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, expire_on_commit=False)
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


def test_1_database_connection() -> None:
    """Test 1: Verify the backend can connect to PostgreSQL."""
    assert check_db_connection() is True
    with engine.connect() as conn:
        result = conn.execute(text("SELECT 1")).scalar()
        assert result == 1


def test_2_user_creation(db_session: Session) -> None:
    """Test 2: Create a test user and verify it can be stored and retrieved."""
    test_email = f"user_{uuid.uuid4().hex[:8]}@example.com"
    user = User(
        email=test_email,
        password_hash="mock_hash_for_testing",
        is_active=True,
        is_verified=False,
    )
    db_session.add(user)
    db_session.flush()

    assert user.id is not None
    assert isinstance(user.id, uuid.UUID)
    assert user.email == test_email
    assert user.is_active is True
    assert user.is_verified is False
    assert user.created_at is not None
    assert user.updated_at is not None

    # Retrieve from DB
    retrieved = db_session.get(User, user.id)
    assert retrieved is not None
    assert retrieved.email == test_email


def test_3_user_uniqueness(db_session: Session) -> None:
    """Test 3: Verify duplicate email values are rejected."""
    duplicate_email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
    user1 = User(email=duplicate_email, password_hash="hash1")
    db_session.add(user1)
    db_session.flush()

    user2 = User(email=duplicate_email, password_hash="hash2")
    db_session.add(user2)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_4_user_profile_relationship(db_session: Session) -> None:
    """Test 4: Create a user and profile and verify the 1:1 relationship."""
    user = User(email=f"profile_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    db_session.flush()

    profile = UserProfile(
        user_id=user.id,
        display_name="Jane Doe",
        preferred_currency="EUR",
        timezone="Europe/Paris",
    )
    db_session.add(profile)
    db_session.flush()

    assert profile.id is not None
    assert profile.user_id == user.id
    assert user.profile is not None
    assert user.profile.display_name == "Jane Doe"
    assert user.profile.preferred_currency == "EUR"
    assert profile.user.id == user.id

    # Verify 1:1 uniqueness constraint
    duplicate_profile = UserProfile(user_id=user.id, display_name="Another Profile")
    db_session.add(duplicate_profile)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_5_financial_account_relationship(db_session: Session) -> None:
    """Test 5: Create a user and financial account and verify ownership."""
    user = User(email=f"finacc_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    db_session.flush()

    account = FinancialAccount(
        user_id=user.id,
        name="Primary Checking",
        account_type="bank",
        institution_name="Demo Bank",
        currency="USD",
        is_active=True,
    )
    db_session.add(account)
    db_session.flush()

    assert account.id is not None
    assert account.user_id == user.id
    assert len(user.financial_accounts) == 1
    assert user.financial_accounts[0].name == "Primary Checking"
    assert account.user.email == user.email


def test_6_transaction_relationship(db_session: Session) -> None:
    """Test 6: Create a financial account and transaction and verify foreign key relationship."""
    user = User(email=f"tx_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    db_session.flush()

    account = FinancialAccount(
        user_id=user.id,
        name="Credit Card",
        account_type="credit_card",
        currency="USD",
    )
    db_session.add(account)
    db_session.flush()

    tx = Transaction(
        financial_account_id=account.id,
        transaction_date=date(2026, 9, 17),
        amount=Decimal("45.5000"),
        currency="USD",
        transaction_type="debit",
        merchant="Grocery Store",
        description="Weekly grocery shopping",
        category="Groceries",
    )
    db_session.add(tx)
    db_session.flush()

    assert tx.id is not None
    assert tx.financial_account_id == account.id
    assert len(account.transactions) == 1
    assert account.transactions[0].merchant == "Grocery Store"
    assert tx.financial_account.name == "Credit Card"


def test_7_decimal_money(db_session: Session) -> None:
    """Test 7: Verify transaction amounts preserve exact monetary precision."""
    user = User(email=f"money_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    db_session.flush()

    account = FinancialAccount(
        user_id=user.id,
        name="Savings",
        account_type="savings",
        currency="USD",
    )
    db_session.add(account)
    db_session.flush()

    # Precise financial amount: 100.1000
    exact_amount = Decimal("100.1000")
    tx = Transaction(
        financial_account_id=account.id,
        transaction_date=date.today(),
        amount=exact_amount,
        currency="USD",
        transaction_type="credit",
        description="Interest payment",
    )
    db_session.add(tx)
    db_session.flush()

    # Expire cached attributes and re-query from database
    db_session.expire(tx)
    reloaded_tx = db_session.get(Transaction, tx.id)
    assert reloaded_tx is not None
    assert isinstance(reloaded_tx.amount, Decimal)
    assert reloaded_tx.amount == exact_amount
    assert str(reloaded_tx.amount) == "100.1000"
    # Ensure float inaccuracies did not occur
    assert str(reloaded_tx.amount) != "100.09999999999999"


def test_8_oauth_uniqueness(db_session: Session) -> None:
    """Test 8: Verify the same provider + provider_user_id cannot be registered twice."""
    user1 = User(email=f"oauth1_{uuid.uuid4().hex[:8]}@example.com")
    user2 = User(email=f"oauth2_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add_all([user1, user2])
    db_session.flush()

    shared_provider_user_id = f"google_id_{uuid.uuid4().hex[:8]}"
    oauth1 = OAuthAccount(
        user_id=user1.id,
        provider="google",
        provider_user_id=shared_provider_user_id,
    )
    db_session.add(oauth1)
    db_session.flush()

    # Duplicate provider + provider_user_id on another user must fail
    oauth2 = OAuthAccount(
        user_id=user2.id,
        provider="google",
        provider_user_id=shared_provider_user_id,
    )
    db_session.add(oauth2)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_9_session_expiration_fields(db_session: Session) -> None:
    """Test 9: Verify sessions support expiration and revocation."""
    user = User(email=f"sess_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    db_session.flush()

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=7)
    session_token_hash = f"hash_{uuid.uuid4().hex}"

    session = AuthSession(
        user_id=user.id,
        session_token_hash=session_token_hash,
        expires_at=expires_at,
        revoked_at=None,
    )
    db_session.add(session)
    db_session.flush()

    assert session.id is not None
    assert session.revoked_at is None
    assert session.expires_at == expires_at

    # Test explicit revocation
    revocation_time = datetime.now(timezone.utc)
    session.revoked_at = revocation_time
    db_session.flush()

    db_session.expire(session)
    reloaded_session = db_session.get(AuthSession, session.id)
    assert reloaded_session is not None
    assert reloaded_session.revoked_at is not None


def test_10_document_relationship(db_session: Session) -> None:
    """Test 10: Verify a financial document belongs to a user and optionally a financial account."""
    user = User(email=f"doc_{uuid.uuid4().hex[:8]}@example.com")
    db_session.add(user)
    db_session.flush()

    account = FinancialAccount(
        user_id=user.id,
        name="Checking Account",
        account_type="bank",
        currency="USD",
    )
    db_session.add(account)
    db_session.flush()

    # Document linked to both user and account
    doc_with_account = FinancialDocument(
        user_id=user.id,
        financial_account_id=account.id,
        file_name="statement_sept_2026.pdf",
        file_type="application/pdf",
        file_size=1024 * 250,
        storage_path="/uploads/statements/statement_sept_2026.pdf",
        processing_status="uploaded",
    )
    db_session.add(doc_with_account)
    db_session.flush()

    assert doc_with_account.id is not None
    assert doc_with_account.financial_account_id == account.id
    assert doc_with_account.financial_account is not None
    assert doc_with_account.financial_account.name == "Checking Account"

    # Document linked to user only (no financial account)
    doc_without_account = FinancialDocument(
        user_id=user.id,
        financial_account_id=None,
        file_name="receipt_misc.pdf",
        file_type="application/pdf",
        file_size=51200,
        storage_path="/uploads/receipts/receipt_misc.pdf",
        processing_status="uploaded",
    )
    db_session.add(doc_without_account)
    db_session.flush()

    assert doc_without_account.id is not None
    assert doc_without_account.financial_account_id is None
    assert doc_without_account.financial_account is None
    assert doc_without_account.user.id == user.id
    assert len(user.financial_documents) == 2
