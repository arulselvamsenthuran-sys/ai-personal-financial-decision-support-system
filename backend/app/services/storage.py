"""Local filesystem document storage abstraction.

Provides a clean interface for storing and retrieving uploaded documents.
Can be replaced with S3/GCS implementation without changing calling code.
"""

import hashlib
import os
import uuid
from pathlib import Path

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Resolve storage root relative to the backend directory
_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_STORAGE_ROOT = _BACKEND_DIR / settings.upload_storage_dir


class DocumentStorage:
    """Abstraction for document file storage.

    Files are stored under: {storage_root}/{user_id}/{uuid}.{extension}
    The storage_reference returned is an opaque key (never the full path).
    """

    def __init__(self, storage_root: Path | None = None) -> None:
        self.storage_root = storage_root or _STORAGE_ROOT
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _ref_to_path(self, storage_reference: str) -> Path:
        """Convert an opaque storage reference to an absolute filesystem path."""
        # Prevent path traversal by rejecting any ".." or absolute components
        ref = Path(storage_reference)
        if ref.is_absolute() or ".." in ref.parts:
            raise ValueError("Invalid storage reference.")
        return self.storage_root / ref

    def save(self, user_id: uuid.UUID, file_bytes: bytes, extension: str) -> str:
        """Save document bytes and return an opaque storage reference.

        Args:
            user_id: Owner's UUID.
            file_bytes: Raw file content.
            extension: File extension including dot (e.g. '.csv').

        Returns:
            Opaque storage reference string (never a full filesystem path).
        """
        # Sanitize extension
        ext = extension.lower().lstrip(".")
        file_id = uuid.uuid4()
        # Opaque reference: {user_id}/{file_uuid}.{ext}
        ref = f"{user_id}/{file_id}.{ext}"

        target = self._ref_to_path(ref)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file_bytes)

        logger.info(
            "Document stored: ref=%s, size=%d bytes", ref, len(file_bytes)
        )
        return ref

    def read(self, storage_reference: str) -> bytes:
        """Read document bytes by storage reference.

        Raises:
            FileNotFoundError: If the referenced file does not exist.
        """
        target = self._ref_to_path(storage_reference)
        if not target.exists():
            raise FileNotFoundError(f"Document not found for reference.")
        return target.read_bytes()

    def delete(self, storage_reference: str) -> bool:
        """Delete a stored document. Returns True if file was removed."""
        target = self._ref_to_path(storage_reference)
        if target.exists():
            target.unlink()
            logger.info("Document deleted: ref=%s", storage_reference)
            return True
        return False

    @staticmethod
    def compute_hash(file_bytes: bytes) -> str:
        """Compute SHA-256 hex digest of file content."""
        return hashlib.sha256(file_bytes).hexdigest()


# Module-level singleton for dependency injection
document_storage = DocumentStorage()
