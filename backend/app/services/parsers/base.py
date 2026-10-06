"""Abstract base class for financial statement parsers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional


@dataclass
class ParsedTransaction:
    """Normalized transaction record produced by a parser.

    All monetary values use Decimal to avoid floating-point inaccuracies.
    """

    transaction_date: date
    amount: Decimal
    transaction_type: str  # "debit" or "credit"
    description: Optional[str] = None
    merchant: Optional[str] = None
    currency: Optional[str] = None
    reference_number: Optional[str] = None
    raw_record: Dict = field(default_factory=dict)


@dataclass
class ParsedStatement:
    """Result container for statement parsing containing parsed records and any non-fatal errors."""

    transactions: List[ParsedTransaction] = field(default_factory=list)
    file_type: str = ""
    errors: List[str] = field(default_factory=list)


def sanitize_csv_formula(value: str) -> str:
    """Sanitize string values to defend against CSV formula injection.

    If a string starts with dangerous characters ('=', '+', '-', '@', '\t', '\r'),
    prepend a single quote '\'' to force spreadsheet engines to treat it as plain text.
    Preserves negative numeric strings.
    """
    if not value or not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return value

    dangerous_chars = ("=", "+", "-", "@", "\t", "\r")
    if stripped.startswith(dangerous_chars):
        # Check if it's just a negative number
        if stripped.startswith("-"):
            try:
                Decimal(stripped)
                return value  # Valid negative number, leave unchanged
            except Exception:
                pass
        return f"'{value}"

    return value


class StatementParser(ABC):
    """Base interface for all financial statement parsers."""

    @abstractmethod
    def parse(self, raw_bytes: bytes, filename: str = "") -> ParsedStatement:
        """Parse raw file bytes into a ParsedStatement object."""
        ...
