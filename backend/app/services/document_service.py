"""Document ingestion business service (synchronous for SQLAlchemy Session).

Handles document upload validation, deduplication hashing, file storage,
parsing (CSV/PDF), database transaction creation, and document status updates.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Tuple

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


from app.core.config import settings
from app.core.logging import get_logger
from app.models.financial_account import FinancialAccount
from app.models.financial_document import FinancialDocument
from app.models.financial_event import FinancialEvent
from app.models.transaction import Transaction
from app.models.user import User
from app.services.fingerprint import generate_transaction_fingerprint
from app.services.ledger_service import ledger_service  # Phase 9
from app.services.parsers.base import StatementParser
from app.services.parsers.csv_parser import GenericCSVParser
from app.services.parsers.pdf_parser import GenericPDFParser
from app.services.storage import document_storage

logger = get_logger(__name__)

# Magic signatures (magic numbers) for file validation
_PDF_MAGIC = b"%PDF"


class DocumentIngestionService:
    """Service encapsulating the document upload & ingestion pipeline."""

    def process_document_upload(
        self,
        db: Session,
        user: User,
        account_id: uuid.UUID,
        file: UploadFile,
    ) -> FinancialDocument:
        """Process document upload safely end-to-end.

        1. Verify financial account ownership.
        2. Validate filename, size, and magic bytes / extension.
        3. Read content & calculate SHA-256 hash.
        4. Check duplicate hash for this user.
        5. Save file to storage abstraction.
        6. Create FinancialDocument record in database (status=processing).
        7. Parse statement (CSV or PDF).
        8. Convert parsed rows into Transaction objects owned by user & account.
        9. Update document status to completed or failed.
        """
        # Step 1: Verify financial account exists and belongs to current user
        account = (
            db.query(FinancialAccount)
            .filter(
                FinancialAccount.id == account_id,
                FinancialAccount.user_id == user.id,
            )
            .first()
        )
        if not account:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Financial account not found or does not belong to user.",
            )

        # Step 2: Validate file name & extension
        filename = file.filename or "upload.bin"
        ext = self._get_safe_extension(filename)

        if ext not in settings.upload_allowed_extensions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported file type '{ext}'. Allowed types: {settings.upload_allowed_extensions}",
            )

        # Step 3: Read content safely & check size
        content = file.file.read()
        if len(content) > settings.upload_max_file_size_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File size exceeds maximum allowed limit of {settings.upload_max_file_size_bytes} bytes.",
            )

        if len(content) == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is empty.",
            )

        # Validate magic bytes / file structure
        self._validate_file_content(content, ext)

        # Step 4: Calculate SHA-256 file hash and check duplicate for this user
        file_hash = document_storage.compute_hash(content)
        existing_doc = (
            db.query(FinancialDocument)
            .filter(
                FinancialDocument.user_id == user.id,
                FinancialDocument.file_hash == file_hash,
            )
            .first()
        )
        if existing_doc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A document with identical content has already been uploaded.",
            )

        # Step 5: Save raw binary content to storage
        storage_ref = document_storage.save(user.id, content, ext)

        # Safe mime_type
        mime_type = file.content_type or ("application/pdf" if ext == ".pdf" else "text/csv")

        # Step 6: Create initial database record (processing)
        doc = FinancialDocument(
            user_id=user.id,
            financial_account_id=account.id,
            original_filename=filename,
            document_type=f"{ext.lstrip('.').lower()}_statement",
            mime_type=mime_type,
            file_size=len(content),
            file_hash=file_hash,
            storage_reference=storage_ref,
            processing_status="processing",
            metadata_json={"original_filename": filename},
        )
        db.add(doc)
        db.commit()
        db.refresh(doc)

        # Step 7: Select appropriate parser & parse content
        parser = self._get_parser(ext)
        try:
            parsed_statement = parser.parse(content, filename=filename)

            if parsed_statement.errors and not parsed_statement.transactions:
                # Parsing produced only errors
                doc.processing_status = "failed"
                doc.processing_error = "; ".join(parsed_statement.errors).replace("\x00", "")
                db.commit()
                db.refresh(doc)
                return doc

            # Step 8: Normalize parsed records, fingerprint, deduplicate & record financial events
            account_curr = account.currency or "USD"
            created_transactions = []
            skipped_duplicate_count = 0

            # Existing fingerprints for this account in DB
            existing_fingerprints = set(
                fp for (fp,) in db.query(Transaction.transaction_fingerprint)
                .filter(Transaction.financial_account_id == account.id)
                .all()
            )
            seen_in_batch = set()

            for item in parsed_statement.transactions:
                fingerprint = generate_transaction_fingerprint(
                    financial_account_id=account.id,
                    transaction_date=item.transaction_date,
                    amount=item.amount,
                    transaction_type=item.transaction_type,
                    merchant=item.merchant,
                    reference=item.reference_number,
                )

                # Skip intra-batch duplicate or existing database duplicate
                if fingerprint in seen_in_batch or fingerprint in existing_fingerprints:
                    skipped_duplicate_count += 1
                    continue

                seen_in_batch.add(fingerprint)

                raw_meta = dict(item.raw_record or {})
                raw_meta["financial_document_id"] = str(doc.id)
                raw_meta["transaction_fingerprint"] = fingerprint
                resolved_currency = item.currency or account_curr

                tx = Transaction(
                    user_id=user.id,
                    financial_account_id=account.id,
                    transaction_fingerprint=fingerprint,
                    transaction_date=item.transaction_date,
                    amount=item.amount,
                    merchant=item.merchant,
                    description=item.description,
                    transaction_type=item.transaction_type,
                    currency=resolved_currency,
                    reference=item.reference_number,
                    source="document_import",
                    metadata_json=raw_meta,
                )

                tx_date_str = item.transaction_date.isoformat() if hasattr(item.transaction_date, "isoformat") else str(item.transaction_date)
                event_payload = {
                    "transaction_id": str(tx.id),
                    "financial_account_id": str(account.id),
                    "user_id": str(user.id),
                    "transaction_date": tx_date_str,
                    "amount": str(item.amount),
                    "transaction_type": item.transaction_type,
                    "merchant": item.merchant,
                    "currency": resolved_currency,
                    "reference": item.reference_number,
                    "document_id": str(doc.id),
                    "fingerprint": fingerprint,
                }

                fin_event = FinancialEvent(
                    user_id=user.id,
                    financial_account_id=account.id,
                    event_type="TRANSACTION_IMPORTED",
                    transaction_id=tx.id,
                    source="document_import",
                    idempotency_key=f"import:{account.id}:{fingerprint}",
                    payload=event_payload,
                )

                # Atomic insertion of transaction + event + ledger entries using a
                # savepoint so that a ledger failure rolls back only this row's inserts
                # (tx + event + ledger entries) without aborting the entire session.
                savepoint = db.begin_nested()
                try:
                    db.add(tx)
                    db.add(fin_event)
                    db.flush()  # flush so tx.id and fin_event.id are populated

                    # Phase 9: post balanced double-entry ledger entries
                    ledger_service.post_transaction_to_ledger(
                        db=db,
                        transaction=tx,
                        financial_event_id=fin_event.id,
                    )
                    db.flush()  # flush ledger entries

                    savepoint.commit()
                    existing_fingerprints.add(fingerprint)
                    created_transactions.append(tx)
                except (IntegrityError, ValueError, RuntimeError) as exc:
                    savepoint.rollback()
                    if isinstance(exc, IntegrityError):
                        skipped_duplicate_count += 1
                    else:
                        logger.warning(
                            "Ledger posting failed for fingerprint %s: %s – row skipped.",
                            fingerprint,
                            exc,
                        )
                        skipped_duplicate_count += 1


            # Step 9: Update document status to completed and set processed_at timestamp
            doc.processing_status = "completed"
            doc.processed_at = datetime.now(timezone.utc)
            doc.metadata_json = {
                **(doc.metadata_json or {}),
                "imported_transaction_count": len(created_transactions),
                "skipped_duplicate_count": skipped_duplicate_count,
                "skipped_duplicate_transaction_count": skipped_duplicate_count,
                "parser_warnings": [w.replace("\x00", "") for w in parsed_statement.errors],
            }
            db.commit()
            db.refresh(doc)


            logger.info(
                "Successfully processed document %s: %d transactions created.",
                doc.id,
                len(created_transactions),
            )
            return doc

        except Exception as exc:
            logger.error("Error processing document %s: %s", doc.id, str(exc))
            doc.processing_status = "failed"
            doc.processing_error = f"Processing error: {str(exc)}".replace("\x00", "")
            db.commit()
            db.refresh(doc)
            return doc

    def _get_safe_extension(self, filename: str) -> str:
        """Extract clean lowercased extension with dot from filename."""
        clean_name = filename.strip()
        if "." not in clean_name:
            return ""
        return "." + clean_name.rsplit(".", 1)[-1].lower()

    def _validate_file_content(self, content: bytes, ext: str) -> None:
        """Validate content magic numbers to prevent MIME spoofing."""
        if ext == ".pdf":
            if not content.startswith(_PDF_MAGIC):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File extension is .pdf but content is not a valid PDF file.",
                )
        elif ext == ".csv":
            # Basic sanity check: CSV must be readable text (not binary executable or containing null bytes)
            if b"\x00" in content:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File extension is .csv but content contains binary data.",
                )
            try:
                decoded = content.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="File extension is .csv but content contains binary data.",
                )



    def _get_parser(self, ext: str) -> StatementParser:
        """Factory method for document parsers."""
        if ext == ".csv":
            return GenericCSVParser()
        elif ext == ".pdf":
            return GenericPDFParser()
        else:
            raise ValueError(f"No parser registered for extension '{ext}'")


document_ingestion_service = DocumentIngestionService()
