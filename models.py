from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

LOAN_TYPES = [
    "Business Loan",
    "Home Loan",
    "Commercial Loan",
    "Car Loan",
    "Education Loan",
    "Construction Loan",
    "Gold Loan",
    "Land Loan",
]

LOAN_STATUSES = ["Pending", "Under Review", "Approved", "Declined"]


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)

    applications: Mapped[list["LoanApplication"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    accounts: Mapped[list["BankAccount"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )


class LoanApplication(TimestampMixin, Base):
    __tablename__ = "loan_applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    loan_type: Mapped[str] = mapped_column(String(60))
    amount: Mapped[float] = mapped_column()
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    term_months: Mapped[int | None] = mapped_column(nullable=True)
    purpose: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="Pending")
    admin_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="applications")


class ContactMessage(TimestampMixin, Base):
    __tablename__ = "contact_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(255))
    subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    reply_to: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


class AdminLoginActivity(TimestampMixin, Base):
    __tablename__ = "admin_login_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_email: Mapped[str] = mapped_column(String(255))
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="Success")


class NewsletterSubscriber(TimestampMixin, Base):
    __tablename__ = "newsletter_subscribers"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


ACCOUNT_TYPES = ["Checking", "Savings", "Business", "Fixed Deposit"]
ACCOUNT_STATUSES = ["Active", "Frozen", "Closed"]

TRANSACTION_TYPES = [
    "Deposit",
    "Withdrawal",
    "Transfer",
    "Payment",
    "Fee",
]


class BankAccount(TimestampMixin, Base):
    __tablename__ = "bank_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    account_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    account_type: Mapped[str] = mapped_column(String(30), default="Checking")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    balance: Mapped[float] = mapped_column(default=0.0)
    status: Mapped[str] = mapped_column(String(20), default="Active")

    user: Mapped["User"] = relationship(back_populates="accounts")
    outgoing: Mapped[list["Transaction"]] = relationship(
        foreign_keys="Transaction.from_account_id",
        back_populates="from_account",
        cascade="all, delete-orphan",
    )
    incoming: Mapped[list["Transaction"]] = relationship(
        foreign_keys="Transaction.to_account_id",
        back_populates="to_account",
        cascade="all, delete-orphan",
    )


class Transaction(TimestampMixin, Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    from_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("bank_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type: Mapped[str] = mapped_column(String(30))
    amount: Mapped[float] = mapped_column(default=0.0)
    fee: Mapped[float] = mapped_column(default=0.0)
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped["User | None"] = relationship()
    from_account: Mapped["BankAccount | None"] = relationship(
        foreign_keys=[from_account_id], back_populates="outgoing"
    )
    to_account: Mapped["BankAccount | None"] = relationship(
        foreign_keys=[to_account_id], back_populates="incoming"
    )
