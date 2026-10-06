"""Pydantic schemas for authentication requests and responses."""

from datetime import datetime
import uuid

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegisterRequest(BaseModel):
    """Payload for user registration."""

    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(..., description="Plaintext password to be validated and hashed")


class UserLoginRequest(BaseModel):
    """Payload for user authentication."""

    email: EmailStr = Field(..., description="Registered email address")
    password: str = Field(..., description="User password")


class UserResponse(BaseModel):
    """Safe public representation of a user identity."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: EmailStr
    is_active: bool
    is_verified: bool
    created_at: datetime


class MessageResponse(BaseModel):
    """Generic status/acknowledgment response."""

    detail: str
