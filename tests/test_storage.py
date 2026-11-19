"""Tests for DocumentStorage and Vercel Serverless Filesystem Compatibility."""

import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.models.financial_account import FinancialAccount
from app.models.financial_document import FinancialDocument
from app.models.user import User
from app.services.document_service import DocumentIngestionService
from app.services.storage import (
    DocumentStorage,
    get_default_storage_root,
    is_vercel_env,
)


def test_storage_initialization_local(monkeypatch):
    """Test storage root defaults to backend/uploads in local development."""
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("VERCEL_ENV", raising=False)
    monkeypatch.delenv("VERCEL_REGION", raising=False)
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)

    assert not is_vercel_env()
    root = get_default_storage_root()
    assert str(root).endswith("uploads")
    assert not str(root).startswith("/var/task")

    storage = DocumentStorage()
    assert storage.storage_root == root


def test_storage_initialization_vercel(monkeypatch):
    """Test storage root defaults to /tmp/uploads when running in Vercel."""
    monkeypatch.setenv("VERCEL", "1")
    assert is_vercel_env()
    assert get_default_storage_root() == Path("/tmp/uploads")

    monkeypatch.delenv("VERCEL")
    monkeypatch.setenv("VERCEL_ENV", "production")
    assert is_vercel_env()
    assert get_default_storage_root() == Path("/tmp/uploads")


def test_storage_var_task_protection():
    """Verify storage never creates directories or writes inside /var/task."""
    var_task_root = Path("/var/task/uploads")
    storage = DocumentStorage(storage_root=var_task_root)

    # Initializing with /var/task should not raise
    assert storage.storage_root == var_task_root

    # Saving inside /var/task should be blocked
    with pytest.raises(OSError, match="read-only /var/task"):
        storage.save(uuid.uuid4(), b"content", ".csv")


def test_storage_save_read_delete():
    """Test end-to-end file save, read, and delete in a writable storage directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = DocumentStorage(storage_root=Path(tmpdir))
        user_id = uuid.uuid4()
        test_bytes = b"date,amount,merchant\n2026-11-17,99.99,Acme Store\n"

        # Hash computation
        content_hash = storage.compute_hash(test_bytes)
        assert len(content_hash) == 64

        # Save
        ref = storage.save(user_id, test_bytes, "csv")
        assert ref.startswith(str(user_id))
        assert ref.endswith(".csv")

        # Read
        retrieved = storage.read(ref)
        assert retrieved == test_bytes

        # Delete
        assert storage.delete(ref) is True
        assert not (Path(tmpdir) / ref).exists()

        # Reading deleted file raises FileNotFoundError
        with pytest.raises(FileNotFoundError):
            storage.read(ref)


def test_storage_path_traversal_blocked():
    """Test that relative path traversal references are rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        storage = DocumentStorage(storage_root=Path(tmpdir))
        with pytest.raises(ValueError, match="Invalid storage reference"):
            storage._ref_to_path("../../../etc/shadow")

        with pytest.raises(ValueError, match="Invalid storage reference"):
            storage._ref_to_path("/absolute/path")


def test_document_ingestion_with_storage(monkeypatch):
    """Test DocumentIngestionService end-to-end with DocumentStorage."""
    with tempfile.TemporaryDirectory() as tmpdir:
        custom_storage = DocumentStorage(storage_root=Path(tmpdir))
        monkeypatch.setattr(
            "app.services.document_service.document_storage",
            custom_storage,
        )

        monkeypatch.setattr(
            "app.services.document_service.ledger_service.post_transaction_to_ledger",
            MagicMock(),
        )

        service = DocumentIngestionService()
        user_id = uuid.uuid4()
        account_id = uuid.uuid4()

        user = User(id=user_id, email="tester@example.com")
        account = FinancialAccount(
            id=account_id,
            user_id=user_id,
            currency="USD",
            name="Checking",
        )

        csv_content = b"date,amount,merchant\n2026-11-17,50.00,Coffee Shop\n"

        mock_file = MagicMock()
        mock_file.filename = "statement.csv"
        mock_file.content_type = "text/csv"
        mock_file.file.read.return_value = csv_content

        mock_db = MagicMock()
        # Mock queries
        mock_query = mock_db.query.return_value
        mock_filter = mock_query.filter.return_value

        # First query: account lookup -> returns account
        # Second query: existing_doc lookup -> returns None
        mock_filter.first.side_effect = [account, None]
        # existing_fingerprints -> empty set
        mock_filter.all.return_value = []

        doc = service.process_document_upload(
            db=mock_db,
            user=user,
            account_id=account_id,
            file=mock_file,
        )

        assert doc.processing_status == "completed"
        assert doc.file_size == len(csv_content)
        assert doc.storage_reference.startswith(str(user_id))

        # Verify file was actually written to the storage directory
        stored_bytes = custom_storage.read(doc.storage_reference)
        assert stored_bytes == csv_content
