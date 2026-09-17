"""SQLAlchemy declarative base for all ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class for all database models.

    Future phases will define models that inherit from this class.
    Alembic uses Base.metadata to auto-generate migrations.
    """

    pass
