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


def is_vercel_env() -> bool:
    """Check if the application is running in a Vercel serverless environment.

    Vercel sets VERCEL=1 (or '1'), VERCEL_ENV, VERCEL_REGION, or AWS_LAMBDA_FUNCTION_NAME.
    """
    return bool(
        os.environ.get("VERCEL")
        or os.environ.get("VERCEL_ENV")
        or os.environ.get("VERCEL_REGION")
        or os.environ.get("AWS_LAMBDA_FUNCTION_NAME")
    )


def get_default_storage_root() -> Path:
    """Determine the default storage root directory based on the execution environment.

    - On Vercel / serverless: uses `/tmp/uploads` since the deployment root (/var/task)
      is read-only and only `/tmp` is writable.
    - In local development: preserves the existing storage path relative to the backend directory.
    - Never returns a path inside `/var/task`.
    """
    backend_dir = Path(__file__).resolve().parent.parent.parent

    # Detect Vercel serverless environment or execution from /var/task
    if is_vercel_env() or backend_dir.as_posix().startswith("/var/task"):
        return Path("/tmp/uploads")

    # If explicitly configured via settings or environment variable
    configured_dir = Path(settings.upload_storage_dir)
    if configured_dir.is_absolute():
        if configured_dir.as_posix().startswith("/var/task"):
            logger.warning(
                "Configured storage path '%s' is inside read-only /var/task; falling back to /tmp/uploads",
                configured_dir,
            )
            return Path("/tmp/uploads")
        return configured_dir

    # Local development: relative to backend directory
    candidate = backend_dir / settings.upload_storage_dir
    if candidate.as_posix().startswith("/var/task"):
        return Path("/tmp/uploads")
    return candidate


_STORAGE_ROOT = get_default_storage_root()


class DocumentStorage:
    """Abstraction for document file storage.

    Files are stored under: {storage_root}/{user_id}/{uuid}.{extension}
    The storage_reference returned is an opaque key (never the full path).
    """

    def __init__(self, storage_root: Path | None = None) -> None:
        self.storage_root = storage_root if storage_root is not None else get_default_storage_root()
        self._ensure_storage_dir()

    def _ensure_storage_dir(self) -> None:
        """Ensure the storage root directory exists if the target is writable.

        Strictly avoids attempting directory creation inside read-only `/var/task`.
        Catches OSError/PermissionError gracefully during initialization so application
        import is never blocked.
        """
        posix_path = self.storage_root.as_posix()
        if posix_path.startswith("/var/task"):
            logger.warning(
                "Storage root '%s' is inside read-only /var/task; skipping directory creation.",
                self.storage_root,
            )
            return

        try:
            self.storage_root.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as e:
            logger.warning(
                "Could not create storage root directory '%s' during initialization: %s",
                self.storage_root,
                e,
            )

    def _ref_to_path(self, storage_reference: str) -> Path:
        """Convert an opaque storage reference to an absolute filesystem path."""
        # Prevent path traversal by rejecting any ".." or absolute components
        ref = Path(storage_reference)
        if (
            ref.is_absolute()
            or storage_reference.startswith(("/", "\\"))
            or ".." in ref.parts
        ):
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

        # Safety check: Never attempt to write inside /var/task
        if target.as_posix().startswith("/var/task"):
            raise OSError(
                f"Cannot save document: target path '{target}' is inside read-only /var/task"
            )

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
