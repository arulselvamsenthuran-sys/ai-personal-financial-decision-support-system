from collections.abc import Generator
import uuid

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.audit import audit_log
from app.core.config import settings
from app.db.session import SessionLocal
from app.models.financial_account import FinancialAccount
from app.models.financial_document import FinancialDocument
from app.models.profile import UserProfile
from app.models.transaction import Transaction
from app.models.user import User
from app.services.auth_service import validate_session



def get_db() -> Generator[Session, None, None]:
    """Yield a database session from the session factory."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


from fastapi.security import APIKeyCookie

# Expose the session cookie requirement to OpenAPI (Swagger UI)
session_cookie_scheme = APIKeyCookie(name=settings.session_cookie_name, auto_error=False)


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    token: str = Depends(session_cookie_scheme),
) -> User:
    """Dependency that authenticates requests using the HttpOnly session cookie.

    Raises:
        HTTPException(401): If the cookie is absent, invalid, revoked, or expired.
    """
    # Fallback in case the token wasn't captured by the scheme
    if not token:
        token = request.cookies.get(settings.session_cookie_name)
        
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    user = validate_session(db, token)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired, was revoked, or is invalid.",
        )

    return user


def get_user_account(
    account_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancialAccount:
    """Fetch financial account with DB-level ownership enforcement: resource.user_id == current_user.id."""
    account = (
        db.query(FinancialAccount)
        .filter(
            FinancialAccount.id == account_id,
            FinancialAccount.user_id == current_user.id,
        )
        .first()
    )

    if not account:
        audit_log(
            event_type="AUTHORIZATION_FAILURE",
            user_id=current_user.id,
            resource_type="FINANCIAL_ACCOUNT",
            resource_id=account_id,
            status="BLOCKED",
            details={"reason": "Resource not found or ownership mismatch"},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Financial account not found.",
        )

    return account


def get_user_document(
    document_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> FinancialDocument:
    """Fetch financial document with DB-level ownership enforcement: resource.user_id == current_user.id."""
    doc = (
        db.query(FinancialDocument)
        .filter(
            FinancialDocument.id == document_id,
            FinancialDocument.user_id == current_user.id,
        )
        .first()
    )

    if not doc:
        audit_log(
            event_type="AUTHORIZATION_FAILURE",
            user_id=current_user.id,
            resource_type="FINANCIAL_DOCUMENT",
            resource_id=document_id,
            status="BLOCKED",
            details={"reason": "Resource not found or ownership mismatch"},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Financial document not found.",
        )

    return doc


def get_user_transaction(
    transaction_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Transaction:
    """Fetch transaction ensuring it belongs to an account owned by current_user."""
    tx = (
        db.query(Transaction)
        .join(FinancialAccount, Transaction.financial_account_id == FinancialAccount.id)
        .filter(
            Transaction.id == transaction_id,
            FinancialAccount.user_id == current_user.id,
        )
        .first()
    )

    if not tx:
        audit_log(
            event_type="AUTHORIZATION_FAILURE",
            user_id=current_user.id,
            resource_type="TRANSACTION",
            resource_id=transaction_id,
            status="BLOCKED",
            details={"reason": "Resource not found or ownership mismatch"},
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found.",
        )

    return tx


def get_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserProfile:
    """Fetch user profile with ownership enforcement."""
    profile = db.query(UserProfile).filter(UserProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User profile not found.",
        )
    return profile

