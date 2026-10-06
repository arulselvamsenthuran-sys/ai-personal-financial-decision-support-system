"""Generic CSV parser for financial statement imports.

Handles common bank/credit-card CSV export formats:
- Single signed-amount column (positive = credit, negative = debit)
- Split debit/credit columns
- Various date formats
- Multiple delimiter styles (comma, semicolon, tab)
"""

import csv
import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Dict, List, Optional, Set

from app.core.logging import get_logger
from app.services.parsers.base import (
    ParsedStatement,
    ParsedTransaction,
    StatementParser,
    sanitize_csv_formula,
)

logger = get_logger(__name__)
# ... (keep mappings)


# ---------------------------------------------------------------------------
# Header normalisation mappings
# ---------------------------------------------------------------------------
_DATE_HEADERS: Set[str] = {
    "date", "transaction date", "trans date", "posting date",
    "posted date", "value date", "txn date", "transaction_date",
}
_AMOUNT_HEADERS: Set[str] = {
    "amount", "transaction amount", "trans amount", "value",
    "sum", "total",
}
_DEBIT_HEADERS: Set[str] = {
    "debit", "debit amount", "withdrawal", "withdrawals",
    "money out", "dr",
}
_CREDIT_HEADERS: Set[str] = {
    "credit", "credit amount", "deposit", "deposits",
    "money in", "cr",
}
_DESCRIPTION_HEADERS: Set[str] = {
    "description", "memo", "narrative", "details",
    "transaction description", "particulars", "remarks",
}
_MERCHANT_HEADERS: Set[str] = {
    "merchant", "payee", "vendor", "counterparty", "name",
}
_REFERENCE_HEADERS: Set[str] = {
    "reference", "ref", "reference number", "check number",
    "cheque number", "transaction id", "transaction ref",
}
_CURRENCY_HEADERS: Set[str] = {
    "currency", "ccy", "cur",
}
_TYPE_HEADERS: Set[str] = {
    "type", "transaction type", "tx type", "txn type", "transaction_type",
}

# Common date formats to try in order
_DATE_FORMATS = [
    "%Y-%m-%d",      # 2026-01-15
    "%m/%d/%Y",      # 01/15/2026
    "%d/%m/%Y",      # 15/01/2026
    "%m-%d-%Y",      # 01-15-2026
    "%d-%m-%Y",      # 15-01-2026
    "%Y/%m/%d",      # 2026/01/15
    "%d %b %Y",      # 15 Jan 2026
    "%d %B %Y",      # 15 January 2026
    "%b %d, %Y",     # Jan 15, 2026
    "%B %d, %Y",     # January 15, 2026
]


def _normalise_header(header: str) -> str:
    """Lowercase, strip, and collapse whitespace in a header string."""
    return re.sub(r"\s+", " ", header.strip().lower())


def _parse_date(value: str) -> date:
    """Attempt to parse a date string using common financial date formats.

    Raises:
        ValueError: If no format matches.
    """
    cleaned = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unable to parse date: '{cleaned}'")


def _parse_amount(value: str) -> Decimal:
    """Parse a monetary string into Decimal.

    Handles: '$1,234.56', '(1234.56)', '1.234,56' (European), etc.

    Raises:
        ValueError: If the value cannot be interpreted as a number.
    """
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Empty amount value")

    # Detect sign from parentheses: (123.45) → -123.45
    negative = False
    if cleaned.startswith("(") and cleaned.endswith(")"):
        negative = True
        cleaned = cleaned[1:-1].strip()

    # Remove currency symbols and whitespace
    cleaned = re.sub(r"[£$€¥₹\s]", "", cleaned)

    # Handle European format: 1.234,56 → 1234.56
    if "," in cleaned and "." in cleaned:
        if cleaned.rindex(",") > cleaned.rindex("."):
            # European: dots are thousands separators, comma is decimal
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            # US: commas are thousands separators
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned and "." not in cleaned:
        # Could be European decimal or US thousands separator
        parts = cleaned.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            # Likely European decimal: 123,45
            cleaned = cleaned.replace(",", ".")
        else:
            # Likely thousands separator: 1,234
            cleaned = cleaned.replace(",", "")

    try:
        result = Decimal(cleaned)
    except InvalidOperation:
        raise ValueError(f"Cannot parse amount: '{value}'")

    if negative:
        result = -result
    return result


class GenericCSVParser(StatementParser):
    """Parse generic CSV bank/credit-card statements.

    Automatically detects:
    - Delimiter (comma, semicolon, tab)
    - Column mapping from header names
    - Single-amount vs split debit/credit columns
    - Common date formats
    """

    def parse(self, raw_bytes: bytes, filename: str = "") -> ParsedStatement:
        """Parse CSV bytes into a ParsedStatement object."""
        # Decode with fallback
        for encoding in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                text = raw_bytes.decode(encoding)
                break
            except (UnicodeDecodeError, ValueError):
                continue
        else:
            return ParsedStatement(
                transactions=[],
                file_type="csv",
                errors=["Unable to decode CSV file — unsupported encoding."],
            )

        # Detect dialect (delimiter)
        try:
            sample = text[:8192]
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        if not reader.fieldnames:
            return ParsedStatement(
                transactions=[],
                file_type="csv",
                errors=["CSV file has no headers."],
            )

        # Build column mapping
        col_map = self._build_column_map(reader.fieldnames)

        if "date" not in col_map:
            return ParsedStatement(
                transactions=[],
                file_type="csv",
                errors=[
                    "CSV file has no recognisable date column. "
                    f"Headers found: {', '.join(reader.fieldnames)}"
                ],
            )
        if "amount" not in col_map and "debit" not in col_map:
            return ParsedStatement(
                transactions=[],
                file_type="csv",
                errors=[
                    "CSV file has no recognisable amount/debit/credit columns. "
                    f"Headers found: {', '.join(reader.fieldnames)}"
                ],
            )

        transactions: List[ParsedTransaction] = []
        errors: List[str] = []

        for row_num, row in enumerate(reader, start=2):  # Row 1 = header
            try:
                tx = self._parse_row(row, col_map, row_num)
                if tx:
                    transactions.append(tx)
            except (ValueError, KeyError) as e:
                errors.append(f"Row {row_num}: {e}")

        logger.info(
            "CSV parsed: %d transactions, %d errors from '%s'",
            len(transactions), len(errors), filename,
        )
        return ParsedStatement(
            transactions=transactions,
            file_type="csv",
            errors=errors,
        )


    def _build_column_map(self, fieldnames: List[str]) -> Dict[str, str]:
        """Map normalised header names to actual CSV column names."""
        col_map: Dict[str, str] = {}
        for name in fieldnames:
            norm = _normalise_header(name)
            if norm in _DATE_HEADERS:
                col_map["date"] = name
            elif norm in _AMOUNT_HEADERS:
                col_map["amount"] = name
            elif norm in _DEBIT_HEADERS:
                col_map["debit"] = name
            elif norm in _CREDIT_HEADERS:
                col_map["credit"] = name
            elif norm in _DESCRIPTION_HEADERS:
                col_map["description"] = name
            elif norm in _MERCHANT_HEADERS:
                col_map["merchant"] = name
            elif norm in _REFERENCE_HEADERS:
                col_map["reference"] = name
            elif norm in _CURRENCY_HEADERS:
                col_map["currency"] = name
            elif norm in _TYPE_HEADERS:
                col_map["transaction_type"] = name
        return col_map

    def _parse_row(
        self, row: Dict[str, str], col_map: Dict[str, str], row_num: int
    ) -> Optional[ParsedTransaction]:
        """Parse a single CSV row into a ParsedTransaction."""
        # Skip completely empty rows
        if all(not v or not v.strip() for v in row.values()):
            return None

        # --- Date ---
        date_raw = row.get(col_map["date"], "").strip()
        if not date_raw:
            return None  # Skip rows without a date
        tx_date = _parse_date(date_raw)

        # --- Amount & Transaction Type ---
        amount: Decimal
        tx_type: str

        if "amount" in col_map:
            amount_raw = row.get(col_map["amount"], "").strip()
            if not amount_raw:
                raise ValueError("Missing amount")
            amount = _parse_amount(amount_raw)
            if amount < 0:
                tx_type = "debit"
                amount = abs(amount)
            else:
                tx_type = "credit"
        else:
            # Split debit/credit columns
            debit_raw = row.get(col_map.get("debit", ""), "").strip()
            credit_raw = row.get(col_map.get("credit", ""), "").strip()

            if debit_raw and debit_raw != "0" and debit_raw != "0.00":
                amount = abs(_parse_amount(debit_raw))
                tx_type = "debit"
            elif credit_raw and credit_raw != "0" and credit_raw != "0.00":
                amount = abs(_parse_amount(credit_raw))
                tx_type = "credit"
            else:
                raise ValueError("No debit or credit value found")

        # Explicit type column in CSV header overrides inferred type
        if "transaction_type" in col_map:
            explicit_type = row.get(col_map["transaction_type"], "").strip().lower()
            if explicit_type:
                tx_type = explicit_type

        # --- Optional fields ---
        description = None
        if "description" in col_map:
            description = sanitize_csv_formula(
                row.get(col_map["description"], "").strip()
            )

        merchant = None
        if "merchant" in col_map:
            merchant = sanitize_csv_formula(
                row.get(col_map["merchant"], "").strip()
            )

        reference = None
        if "reference" in col_map:
            reference = sanitize_csv_formula(
                row.get(col_map["reference"], "").strip()
            )

        currency = None
        if "currency" in col_map:
            currency = sanitize_csv_formula(
                row.get(col_map["currency"], "").strip()
            )

        return ParsedTransaction(
            transaction_date=tx_date,
            amount=amount,
            transaction_type=tx_type,
            description=description or merchant,
            merchant=merchant,
            currency=currency,
            reference_number=reference,
            raw_record={"source_row": row_num},
        )

