"""Security utilities: Argon2id password hashing, session tokens, and policy enforcement."""

import hashlib
import secrets
from typing import Tuple

import argon2
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# Argon2id hasher configuration
# RFC 9106 recommended default configuration for general purpose password hashing:
# Type: Argon2id
# Memory: 64MB (65536 KiB)
# Time / Iterations: 3
# Parallelism: 4
hasher = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    type=argon2.Type.ID,
)

# Minimum & maximum password lengths
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id.

    Never store or log the plain password.
    Returns standard Argon2id encoded string ($argon2id$...).
    """
    return hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against an Argon2id hash.

    Returns True if valid, False otherwise without throwing exceptions.
    """
    if not hashed_password:
        return False
    try:
        return hasher.verify(hashed_password, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def generate_session_token() -> str:
    """Generate a cryptographically secure URL-safe random session token.

    Generates 32 random bytes (~43 characters URL-safe base64).
    """
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    """Produce a deterministic SHA-256 hash of a session token for database lookup.

    Raw tokens are never stored in PostgreSQL. Only this hex digest is persisted.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def validate_password_policy(password: str) -> Tuple[bool, str]:
    """Validate password against security policy.

    Rules:
    - Must be between 8 and 128 characters in length.
    - Must not be composed purely of whitespace.
    """
    if not password or len(password.strip()) == 0:
        return False, "Password cannot be empty or solely whitespace."
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if len(password) > MAX_PASSWORD_LENGTH:
        return False, f"Password must not exceed {MAX_PASSWORD_LENGTH} characters."
    return True, ""
