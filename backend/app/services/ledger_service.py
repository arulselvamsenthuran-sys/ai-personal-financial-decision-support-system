"""Double-Entry Ledger Posting Engine for Phase 9.

Responsibilities
----------------
1. Ensure every user has a default set of ledger accounts (ASSET / INCOME / EXPENSE).
2. Post balanced ledger entries for every imported transaction:
     - Credit transaction  →  Debit ASSET "Bank Account", Credit INCOME "Salary Income"
     - Debit  transaction  →  Debit EXPENSE "General Expenses", Credit ASSET "Bank Account"
3. Validate that the posted entries are balanced (sum(debit) == sum(credit)).

All public methods accept a SQLAlchemy Session and expect to be called inside
an existing database transaction managed by the caller (document_service).

Engineering rules followed:
  - Decimal-only arithmetic, no float.
  - Timezone-aware datetime via func.now() / server_default (not Python naive timestamps).
  - No hardcoded user IDs.
  - User isolation enforced: every query filters on user_id.
"""

from decimal import Decimal
from typing import List, Optional
import uuid

from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.ledger import AccountType, LedgerAccount, LedgerEntry
from app.models.transaction import Transaction

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Default chart-of-accounts definition
# ---------------------------------------------------------------------------
_DEFAULT_ACCOUNTS: List[dict] = [
    {
        "name": "Bank Account",
        "account_type": AccountType.ASSET,
    },
    {
        "name": "Salary Income",
        "account_type": AccountType.INCOME,
    },
    {
        "name": "General Expenses",
        "account_type": AccountType.EXPENSE,
    },
]

# Transaction types treated as credits (money IN)
_CREDIT_TYPES = frozenset({"credit", "income", "deposit", "salary", "transfer_in"})
# Transaction types treated as debits (money OUT)
_DEBIT_TYPES = frozenset({"debit", "expense", "withdrawal", "payment", "transfer_out"})


class LedgerService:
    """Core double-entry posting engine."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ensure_default_accounts(
        self,
        db: Session,
        user_id: uuid.UUID,
        currency: str,
        financial_account_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """Ensure the user has all default ledger accounts.  Returns a mapping of
        account_type → LedgerAccount for the three defaults.

        Safe to call multiple times (idempotent – uses get-or-create semantics).
        """
        accounts: dict = {}
        for spec in _DEFAULT_ACCOUNTS:
            acct = self._get_or_create_ledger_account(
                db=db,
                user_id=user_id,
                name=spec["name"],
                account_type=spec["account_type"],
                currency=currency,
                financial_account_id=(
                    financial_account_id
                    if spec["account_type"] == AccountType.ASSET
                    else None
                ),
            )
            accounts[spec["account_type"]] = acct
        return accounts

    def post_transaction_to_ledger(
        self,
        db: Session,
        transaction: Transaction,
        financial_event_id: Optional[uuid.UUID] = None,
    ) -> List[LedgerEntry]:
        """Create balanced double-entry ledger postings for *transaction*.

        Returns the two LedgerEntry objects (not yet flushed; caller flushes).

        Raises:
            ValueError – if the resulting entries would not balance.
        """
        user_id = transaction.user_id
        currency = transaction.currency
        amount = Decimal(str(transaction.amount))
        tx_type = (transaction.transaction_type or "").strip().lower()

        # Resolve accounts
        ledger_accounts = self.ensure_default_accounts(
            db=db,
            user_id=user_id,
            currency=currency,
            financial_account_id=transaction.financial_account_id,
        )
        bank_account = ledger_accounts[AccountType.ASSET]
        income_account = ledger_accounts[AccountType.INCOME]
        expense_account = ledger_accounts[AccountType.EXPENSE]

        entries: List[LedgerEntry] = []

        if tx_type in _CREDIT_TYPES:
            # Money IN: Debit bank (asset +), Credit income (income +)
            desc_prefix = f"[Credit] {transaction.merchant or transaction.description or 'Transaction'}"
            entries.append(
                self._make_debit_entry(
                    db=db,
                    user_id=user_id,
                    ledger_account=bank_account,
                    amount=amount,
                    currency=currency,
                    transaction=transaction,
                    financial_event_id=financial_event_id,
                    description=f"{desc_prefix} – Bank Dr",
                )
            )
            entries.append(
                self._make_credit_entry(
                    db=db,
                    user_id=user_id,
                    ledger_account=income_account,
                    amount=amount,
                    currency=currency,
                    transaction=transaction,
                    financial_event_id=financial_event_id,
                    description=f"{desc_prefix} – Income Cr",
                )
            )
        else:
            # Default: money OUT (debit / expense / unknown)
            # Debit expense account, Credit bank (asset -)
            desc_prefix = f"[Debit] {transaction.merchant or transaction.description or 'Transaction'}"
            entries.append(
                self._make_debit_entry(
                    db=db,
                    user_id=user_id,
                    ledger_account=expense_account,
                    amount=amount,
                    currency=currency,
                    transaction=transaction,
                    financial_event_id=financial_event_id,
                    description=f"{desc_prefix} – Expense Dr",
                )
            )
            entries.append(
                self._make_credit_entry(
                    db=db,
                    user_id=user_id,
                    ledger_account=bank_account,
                    amount=amount,
                    currency=currency,
                    transaction=transaction,
                    financial_event_id=financial_event_id,
                    description=f"{desc_prefix} – Bank Cr",
                )
            )

        # Inline balance assertion before returning
        self._assert_entries_balanced(entries, transaction.id)
        return entries

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_or_create_ledger_account(
        self,
        db: Session,
        user_id: uuid.UUID,
        name: str,
        account_type: AccountType,
        currency: str,
        financial_account_id: Optional[uuid.UUID] = None,
    ) -> LedgerAccount:
        """Return existing ledger account or create a new one (idempotent)."""
        existing = (
            db.query(LedgerAccount)
            .filter(
                LedgerAccount.user_id == user_id,
                LedgerAccount.name == name,
                LedgerAccount.account_type == account_type.value,
            )
            .first()
        )
        if existing:
            return existing

        new_acct = LedgerAccount(
            user_id=user_id,
            financial_account_id=financial_account_id,
            name=name,
            account_type=account_type.value,
            currency=currency,
        )
        db.add(new_acct)
        db.flush()  # flush so id is populated for subsequent FK references
        logger.debug(
            "Created ledger account '%s' (%s) for user %s",
            name,
            account_type.value,
            user_id,
        )
        return new_acct

    def _make_debit_entry(
        self,
        db: Session,
        user_id: uuid.UUID,
        ledger_account: LedgerAccount,
        amount: Decimal,
        currency: str,
        transaction: Transaction,
        financial_event_id: Optional[uuid.UUID],
        description: Optional[str],
    ) -> LedgerEntry:
        """Construct and add a debit LedgerEntry (not yet flushed)."""
        if amount < Decimal("0"):
            raise ValueError(
                f"Debit amount must be non-negative; got {amount} for transaction {transaction.id}"
            )
        entry = LedgerEntry(
            user_id=user_id,
            ledger_account_id=ledger_account.id,
            transaction_id=transaction.id,
            financial_event_id=financial_event_id,
            debit_amount=amount,
            credit_amount=None,
            currency=currency,
            description=description,
        )
        db.add(entry)
        return entry

    def _make_credit_entry(
        self,
        db: Session,
        user_id: uuid.UUID,
        ledger_account: LedgerAccount,
        amount: Decimal,
        currency: str,
        transaction: Transaction,
        financial_event_id: Optional[uuid.UUID],
        description: Optional[str],
    ) -> LedgerEntry:
        """Construct and add a credit LedgerEntry (not yet flushed)."""
        if amount < Decimal("0"):
            raise ValueError(
                f"Credit amount must be non-negative; got {amount} for transaction {transaction.id}"
            )
        entry = LedgerEntry(
            user_id=user_id,
            ledger_account_id=ledger_account.id,
            transaction_id=transaction.id,
            financial_event_id=financial_event_id,
            debit_amount=None,
            credit_amount=amount,
            currency=currency,
            description=description,
        )
        db.add(entry)
        return entry

    def _assert_entries_balanced(
        self, entries: List[LedgerEntry], transaction_id: uuid.UUID
    ) -> None:
        """Raise ValueError if the supplied entry list is not balanced."""
        total_debit = sum(
            (e.debit_amount or Decimal("0")) for e in entries
        )
        total_credit = sum(
            (e.credit_amount or Decimal("0")) for e in entries
        )
        if total_debit != total_credit:
            raise ValueError(
                f"Ledger imbalance detected for transaction {transaction_id}: "
                f"total_debit={total_debit} != total_credit={total_credit}"
            )


ledger_service = LedgerService()
