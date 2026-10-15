"""Database models package.

All models inherit from app.db.base.Base and are exposed here for Alembic
discovery and application usage.
"""

from app.models.background_job import BackgroundJob  # Phase 19
from app.models.monitoring_schedule import MonitoringSchedule  # Phase 20
from app.models.notification import Notification  # Phase 20
from app.models.conversation import Conversation, ConversationMessage  # Phase 17
from app.models.financial_account import FinancialAccount
from app.models.financial_document import FinancialDocument
from app.models.financial_event import FinancialEvent
from app.models.financial_insight import FinancialInsight  # Phase 10
from app.models.ledger import LedgerAccount, LedgerEntry  # Phase 9
from app.models.oauth import OAuthAccount
from app.models.profile import UserProfile
from app.models.session import Session
from app.models.transaction import Transaction
from app.models.user import User

__all__ = [
    "User",
    "UserProfile",
    "Session",
    "OAuthAccount",
    "FinancialAccount",
    "Transaction",
    "FinancialDocument",
    "FinancialEvent",
    # Phase 9
    "LedgerAccount",
    "LedgerEntry",
    # Phase 10
    "FinancialInsight",
    # Phase 17
    "Conversation",
    "ConversationMessage",
    # Phase 19
    "BackgroundJob",
    # Phase 20
    "MonitoringSchedule",
    "Notification",
]
