"""Ledger validation service for Phase 9.

Provides validate_double_entry(transaction_id) which verifies that the sum of
all debit amounts posted against a transaction equals the sum of all credit
amounts – the fundamental accounting equation.

This service is intentionally kept separate from ledger_service.py so that
validation logic can be unit-tested in isolation and reused from multiple
call sites (API endpoints, background jobs, etc.).
"""

from decimal import Decimal
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ledger import LedgerEntry

logger = get_logger(__name__)


class LedgerValidationError(Exception):
    """Raised when the double-entry invariant is violated for a transaction."""


class LedgerValidationService:
    """Service that validates double-entry integrity for ledger postings."""

    def validate_double_entry(
        self,
        db: Session,
        transaction_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> dict:
        """Verify that sum(debit_amount) == sum(credit_amount) for *transaction_id*.

        Args:
            db:             Active SQLAlchemy session.
            transaction_id: UUID of the Transaction to validate.
            user_id:        UUID of the owning user (prevents cross-user access).

        Returns:
            A dict with keys: transaction_id, total_debit, total_credit, is_balanced.

        Raises:
            LedgerValidationError: if the sums do not match.
        """
        entries = (
            db.query(LedgerEntry)
            .filter(
                LedgerEntry.transaction_id == transaction_id,
                LedgerEntry.user_id == user_id,
            )
            .all()
        )

        total_debit: Decimal = sum(
            (Decimal(str(e.debit_amount)) for e in entries if e.debit_amount is not None),
            Decimal("0"),
        )
        total_credit: Decimal = sum(
            (Decimal(str(e.credit_amount)) for e in entries if e.credit_amount is not None),
            Decimal("0"),
        )

        is_balanced = total_debit == total_credit
        difference = total_debit - total_credit

        result = {
            "transaction_id": transaction_id,
            "total_debit": total_debit,
            "total_credit": total_credit,
            "difference": difference,
            "is_balanced": is_balanced,
        }

        if not is_balanced:
            logger.error(
                "Ledger imbalance for transaction %s: debit=%s credit=%s diff=%s",
                transaction_id,
                total_debit,
                total_credit,
                difference,
            )
            raise LedgerValidationError(
                f"Double-entry imbalance for transaction {transaction_id}: "
                f"total_debit={total_debit} != total_credit={total_credit} "
                f"(difference={difference})"
            )

        logger.debug(
            "Ledger balanced for transaction %s: debit=%s credit=%s",
            transaction_id,
            total_debit,
            total_credit,
        )
        return result

    def get_user_balance_summary(
        self,
        db: Session,
        user_id: uuid.UUID,
    ) -> dict:
        """Return aggregate debit/credit/difference totals for all user ledger entries.

        Used by the GET /api/financial/ledger/balance endpoint.
        """
        rows = (
            db.query(LedgerEntry)
            .filter(LedgerEntry.user_id == user_id)
            .all()
        )

        total_debit: Decimal = sum(
            (Decimal(str(r.debit_amount)) for r in rows if r.debit_amount is not None),
            Decimal("0"),
        )
        total_credit: Decimal = sum(
            (Decimal(str(r.credit_amount)) for r in rows if r.credit_amount is not None),
            Decimal("0"),
        )
        difference = total_debit - total_credit
        is_balanced = difference == Decimal("0")

        return {
            "total_debit": total_debit,
            "total_credit": total_credit,
            "difference": difference,
            "is_balanced": is_balanced,
        }


ledger_validation_service = LedgerValidationService()
