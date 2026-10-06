"""Generic PDF text extractor and statement parser for financial document ingestion.

Extracts text content page-by-page using pdfplumber (or pypdf fallback) and parses tabular/line-based transactions.
"""

import io
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from app.core.logging import get_logger
from app.services.parsers.base import (
    ParsedStatement,
    ParsedTransaction,
    StatementParser,
    sanitize_csv_formula,
)

logger = get_logger(__name__)

# Known date formats commonly found in bank PDFs
_DATE_PATTERNS = [
    (re.compile(r"\b(\d{4}-\d{2}-\d{2})\b"), "%Y-%m-%d"),
    (re.compile(r"\b(\d{2}/\d{2}/\d{4})\b"), "%d/%m/%Y"),
    (re.compile(r"\b(\d{2}-\d{2}-\d{4})\b"), "%d-%m-%Y"),
    (re.compile(r"\b([A-Za-z]{3}\s+\d{1,2},\s+\d{4})\b"), "%b %d, %Y"),
    (re.compile(r"\b(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})\b"), "%d %b %Y"),
]

# Pattern for currency tokens / symbols: $, £, €, USD, EUR, etc.
_CURRENCY_PATTERN = re.compile(
    r"\b(USD|EUR|GBP|CAD|AUD|JPY|CHF|LKR|INR|SGD|NZD)\b|[$£€¥₹]",
    re.IGNORECASE,
)

# Pattern for currency amount: e.g. $1,234.56, 3500 LKR, 80000, 45.50 EUR, -120.00, +2500.00, 1234.56 CR/DR
_AMOUNT_PATTERN = re.compile(
    r"(?P<sign>[+-]?)\s*(?P<pre_curr>[$£€¥₹]|USD|EUR|GBP|LKR|INR)?\s*(?P<num>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?P<post_curr>[$£€¥₹]|USD|EUR|GBP|LKR|INR)?\s*(?P<tag>CR|DR)?\b",
    re.IGNORECASE,
)


# Common keywords that indicate a credit/income or debit/expense when not explicit
_CREDIT_KEYWORDS = {"salary", "payroll", "deposit", "credit", "refund", "interest", "income", "direct dep", "dividend"}
_DEBIT_KEYWORDS = {"withdrawal", "debit", "pos", "fee", "bill", "payment", "charge", "purchase"}


class GenericPDFParser(StatementParser):
    """Generic PDF parser extracting text from financial statements."""

    def parse(self, content: bytes, filename: str = "") -> ParsedStatement:
        errors: List[str] = []
        raw_text = self._extract_text(content, errors)

        if not raw_text.strip():
            return ParsedStatement(
                transactions=[],
                errors=errors + ["PDF file contains no extractable text."],
            )

        # Detect statement-level currency if present in header/text
        statement_currency = self._detect_statement_currency(raw_text)

        transactions = self._parse_lines(raw_text.splitlines(), statement_currency, errors)

        return ParsedStatement(
            transactions=transactions,
            file_type="pdf",
            errors=errors,
        )

    def _extract_text(self, content: bytes, errors: List[str]) -> str:
        """Extract text content from PDF bytes safely."""
        extracted_pages: List[str] = []

        # Try pdfplumber first
        try:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(content)) as pdf:
                for page_idx, page in enumerate(pdf.pages):
                    text = page.extract_text()
                    if text:
                        extracted_pages.append(text)
            return "\n".join(extracted_pages)
        except Exception as e:
            logger.warning("pdfplumber extraction failed, trying pypdf fallback: %s", str(e))

        # Fallback to pypdf if pdfplumber fails or is unavailable
        try:
            import pypdf

            reader = pypdf.PdfReader(io.BytesIO(content))
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    extracted_pages.append(text)
            return "\n".join(extracted_pages)
        except Exception as e:
            msg = f"Failed to extract text from PDF: {str(e)}"
            logger.error(msg)
            errors.append(msg)
            return ""

    def _detect_statement_currency(self, text: str) -> Optional[str]:
        """Look for currency mentions in the statement text."""
        match = _CURRENCY_PATTERN.search(text[:2000])
        if match:
            found = match.group(0).upper()
            symbol_map = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR"}
            return symbol_map.get(found, found)
        return None

    def _parse_lines(
        self, lines: List[str], statement_currency: Optional[str], errors: List[str]
    ) -> List[ParsedTransaction]:
        """Parse lines of text extracted from PDF for financial transaction records."""
        transactions: List[ParsedTransaction] = []

        for line_num, raw_line in enumerate(lines, 1):
            line = raw_line.strip()
            if not line:
                continue

            # Look for a date in the line
            parsed_date, date_str, date_fmt = self._find_date(line)
            if not parsed_date:
                continue

            # Remove date string from line to parse description and amount
            remaining = line.replace(date_str, "", 1).strip()
            if not remaining:
                continue

            # Extract potential monetary amounts from remaining string
            amount_matches = list(_AMOUNT_PATTERN.finditer(remaining))
            if not amount_matches:
                continue

            # Use the last matched amount token as the transaction amount
            last_match = amount_matches[-1]
            sign = last_match.group("sign") or ""
            curr_str = last_match.group("pre_curr") or last_match.group("post_curr") or ""
            num_str = last_match.group("num") or ""
            tag = (last_match.group("tag") or "").upper()

            # Clean number
            clean_num = num_str.replace(",", "")
            try:
                raw_val = Decimal(clean_num)
            except (InvalidOperation, TypeError):
                continue

            # Determine transaction type:
            # 1. If explicit CR/DR tag: CR -> credit, DR -> debit
            # 2. If explicit sign: + -> credit, - -> debit
            # 3. Description heuristic (e.g. Salary, Payroll, Deposit -> credit)
            # 4. Default: debit for expenses
            tx_type = "debit"
            if tag == "CR" or sign == "+":
                tx_type = "credit"
            elif tag == "DR" or sign == "-":
                tx_type = "debit"

            # Remove amount substring to isolate the description
            desc_text = (remaining[: last_match.start()] + " " + remaining[last_match.end() :]).strip()

            # Check description keywords if not explicit
            if tag == "" and sign == "":
                lower_desc = desc_text.lower()
                if any(kw in lower_desc for kw in _CREDIT_KEYWORDS):
                    tx_type = "credit"
                elif any(kw in lower_desc for kw in _DEBIT_KEYWORDS):
                    tx_type = "debit"

            desc = sanitize_csv_formula(desc_text or "PDF Transaction")

            # Determine currency from line token or statement level
            currency = None
            if curr_str:
                symbol_map = {"$": "USD", "£": "GBP", "€": "EUR", "¥": "JPY", "₹": "INR"}
                currency = symbol_map.get(curr_str.upper(), curr_str.upper())
            else:
                currency = statement_currency


            transactions.append(
                ParsedTransaction(
                    transaction_date=parsed_date,
                    description=desc,
                    amount=abs(raw_val),
                    transaction_type=tx_type,
                    currency=currency,
                    raw_record={"line_number": line_num, "raw": line},
                )
            )

        if not transactions and not errors:
            errors.append("No valid transaction rows found in PDF text.")

        return transactions

    def _find_date(self, line: str) -> tuple[date | None, str, str]:
        """Find and parse a date in a text line."""
        for pattern, fmt in _DATE_PATTERNS:
            match = pattern.search(line)
            if match:
                date_str = match.group(1)
                try:
                    dt = datetime.strptime(date_str, fmt).date()
                    return dt, date_str, fmt
                except ValueError:
                    continue
        return None, "", ""
