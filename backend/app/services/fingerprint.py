"""Centralized deterministic transaction fingerprinting service.

Produces SHA-256 hash based STRICTLY on canonical identity fields:
- financial_account_id
- transaction_date
- amount
- transaction_type
- merchant
- reference

Never includes IDs, timestamps, document IDs, category, notes, or metadata.
"""

import hashlib
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Union
import uuid


def _normalize_str(val: Optional[str], case_fold: bool = True) -> str:
    """Normalize string by trimming, collapsing spaces, and optional case-folding."""
    if val is None:
        return ""
    # Collapse multiple whitespace characters into single space and strip
    cleaned = " ".join(val.split()).strip()
    if case_fold:
        cleaned = cleaned.lower()
    return cleaned


def _normalize_amount(amount: Union[Decimal, float, int, str]) -> str:
    """Format Decimal amount deterministically with 4 decimal places."""
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    # Standardize to 4 decimal places matching database numeric scale
    quantized = amount.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    return f"{quantized:.4f}"


def _normalize_date(tx_date: Union[date, str]) -> str:
    """Format date deterministically as YYYY-MM-DD."""
    if isinstance(tx_date, date):
        return tx_date.isoformat()
    return str(tx_date).strip()


def generate_transaction_fingerprint(
    financial_account_id: Union[uuid.UUID, str],
    transaction_date: Union[date, str],
    amount: Union[Decimal, float, int, str],
    transaction_type: str,
    merchant: Optional[str] = None,
    reference: Optional[str] = None,
) -> str:
    """Generate a deterministic SHA-256 transaction fingerprint.

    Canonical format:
    account_id|date|amount|tx_type|merchant|reference
    """
    account_str = _normalize_str(str(financial_account_id), case_fold=True)
    date_str = _normalize_date(transaction_date)
    amount_str = _normalize_amount(amount)
    type_str = _normalize_str(transaction_type, case_fold=True)
    merchant_str = _normalize_str(merchant, case_fold=True)
    ref_str = _normalize_str(reference, case_fold=True)

    canonical_parts = [
        account_str,
        date_str,
        amount_str,
        type_str,
        merchant_str,
        ref_str,
    ]
    canonical_string = "|".join(canonical_parts)

    return hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()
