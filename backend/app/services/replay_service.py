"""Replay service foundation based on financial events / transactions.

Computes total transaction counts, credits, debits, and net balance movement
using Python Decimal arithmetic.
"""

from decimal import Decimal
from typing import Dict, Any
import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.financial_account import FinancialAccount
from app.models.financial_event import FinancialEvent
from app.models.transaction import Transaction


class ReplayService:
    """Service to replay financial events / transactions for an account."""

    def replay_account(
        self,
        db: Session,
        user_id: uuid.UUID,
        financial_account_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Replay account transactions/events and derive summary totals.

        Strict user ownership verification enforced.
        """
        # 1. Verify account ownership
        account = (
            db.query(FinancialAccount)
            .filter(
                FinancialAccount.id == financial_account_id,
                FinancialAccount.user_id == user_id,
            )
            .first()
        )
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Financial account not found or access denied.",
            )

        # 2. Fetch all imported transactions for this account belonging to user
        transactions = (
            db.query(Transaction)
            .filter(
                Transaction.user_id == user_id,
                Transaction.financial_account_id == financial_account_id,
            )
            .all()
        )

        total_credits = Decimal("0.0000")
        total_debits = Decimal("0.0000")
        tx_count = 0

        for tx in transactions:
            tx_count += 1
            amt = Decimal(str(tx.amount))
            t_type = (tx.transaction_type or "").lower()

            # Credit increases balance; debit decreases balance
            if t_type in ("credit", "income", "deposit"):
                total_credits += amt
            elif t_type in ("debit", "expense", "withdrawal"):
                total_debits += amt
            else:
                # If amount is positive, treat as credit, if negative treat absolute as debit
                if amt >= Decimal("0"):
                    total_credits += amt
                else:
                    total_debits += abs(amt)

        net_movement = total_credits - total_debits

        # Count total financial events for accountability
        event_count = (
            db.query(FinancialEvent)
            .filter(
                FinancialEvent.user_id == user_id,
                FinancialEvent.financial_account_id == financial_account_id,
            )
            .count()
        )

        return {
            "financial_account_id": str(financial_account_id),
            "user_id": str(user_id),
            "transaction_count": tx_count,
            "financial_event_count": event_count,
            "total_credits": total_credits,
            "total_debits": total_debits,
            "net_balance_movement": net_movement,
        }


replay_service = ReplayService()
