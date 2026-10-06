"""Development-Only Seed Script: Seed LKR Account Liquidity (Phase 12).

Purpose:
  Populates or updates an active LKR FinancialAccount for a development user
  with a verified current balance of exactly LKR 150,000.00.

Security & Environment Invariants:
  - DEVELOPMENT / TEST USE ONLY. Never run in production.
  - Preserves user ownership and currency isolation.
  - Replays existing transaction movements to ensure the resulting total
    current balance is precisely LKR 150,000.00 Decimal.
"""

from __future__ import annotations

import argparse
from decimal import Decimal
import os
import sys
from pathlib import Path

# Add backend directory to sys.path so app imports work when running directly
backend_dir = Path(__file__).resolve().parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.config import settings
from app.db.session import SessionLocal
from app.models.financial_account import FinancialAccount
from app.models.user import User
from app.services.replay_service import replay_service


def seed_lkr_liquidity(target_email: str | None = None) -> None:
    """Seed or update an active LKR account with verified 150,000.00 LKR balance."""
    # Production Safety Guard
    env = getattr(settings, "ENVIRONMENT", "development") or os.getenv("ENVIRONMENT", "development")
    if env.lower() in ("production", "prod"):
        print("[ERROR] Refusing to run seed script in PRODUCTION environment.", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        # 1. Identify target user
        if target_email:
            user = db.query(User).filter(User.email == target_email).first()
            if not user:
                print(f"[ERROR] User with email '{target_email}' not found.", file=sys.stderr)
                sys.exit(1)
        else:
            # Prioritize real/interactive users (non-example.com) or most recent user
            real_users = (
                db.query(User)
                .filter(User.is_active.is_(True), ~User.email.endswith("@example.com"))
                .order_by(User.created_at.desc())
                .all()
            )
            if real_users:
                user = real_users[0]
            else:
                user = db.query(User).filter(User.is_active.is_(True)).order_by(User.created_at.asc()).first()

            if not user:
                print("[ERROR] No active users found in the database. Please register/create a user first.", file=sys.stderr)
                sys.exit(1)

        print(f"[INFO] Target User: {user.email} (ID: {user.id})")

        # 2. Find or create active LKR account for this user
        account = (
            db.query(FinancialAccount)
            .filter(
                FinancialAccount.user_id == user.id,
                FinancialAccount.currency == "LKR",
                FinancialAccount.is_active.is_(True),
            )
            .first()
        )

        target_balance = Decimal("150000.0000")

        if not account:
            account = FinancialAccount(
                user_id=user.id,
                name="Main LKR Checking",
                account_type="bank",
                institution_name="Commercial Bank of Ceylon",
                account_identifier_masked="****1234",
                currency="LKR",
                opening_balance=target_balance,
                is_active=True,
            )
            db.add(account)
            db.flush()
            print(f"[INFO] Created new active LKR account (ID: {account.id}) with opening balance LKR {target_balance:.2f}.")
        else:
            # Replay existing transactions on this account to offset movements accurately
            replay_res = replay_service.replay_account(
                db=db, user_id=user.id, financial_account_id=account.id
            )
            net_movement = replay_res["net_balance_movement"]
            required_opening = target_balance - net_movement
            account.opening_balance = required_opening
            print(
                f"[INFO] Existing LKR account found (ID: {account.id}). "
                f"Net movement: LKR {net_movement:.2f}. "
                f"Setting opening balance to LKR {required_opening:.2f}."
            )

        db.commit()
        db.refresh(account)

        # 3. Verify final current balance
        replay_check = replay_service.replay_account(
            db=db, user_id=user.id, financial_account_id=account.id
        )
        final_balance = Decimal(str(account.opening_balance)) + replay_check["net_balance_movement"]

        print("----------------------------------------------------------------")
        print("[SUCCESS] Development LKR liquidity test data seeded successfully!")
        print(f"  User Email:             {user.email}")
        print(f"  Financial Account ID:   {account.id}")
        print(f"  Currency:               {account.currency}")
        print(f"  Opening Balance:        LKR {account.opening_balance:.2f}")
        print(f"  Net Movement:           LKR {replay_check['net_balance_movement']:.2f}")
        print(f"  Verified Liquid Total:  LKR {final_balance:.2f}")
        print("----------------------------------------------------------------")

    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed active LKR account with LKR 150,000 verified balance.")
    parser.add_argument("--email", type=str, default=None, help="Target user email (defaults to first active user)")
    args = parser.parse_args()

    seed_lkr_liquidity(target_email=args.email)
