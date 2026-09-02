import re

from fastapi import HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from models import LOAN_TYPES

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class SignupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=40)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def confirm_matches(self):
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match")
        return self


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class ContactIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    subject: str | None = Field(default=None, max_length=200)
    message: str = Field(min_length=10, max_length=5000)
    reply_to: str | None = None

    @field_validator("reply_to")
    @classmethod
    def check_reply(cls, v):
        if v is not None and not EMAIL_RE.match(v):
            raise ValueError("Invalid reply-to email")
        return v


class NewsletterIn(BaseModel):
    email: EmailStr


class LoanApplicationIn(BaseModel):
    loan_type: str
    amount: float = Field(gt=0, le=1_000_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=10)
    term_months: int | None = Field(default=None, ge=1, le=600)
    purpose: str | None = Field(default=None, max_length=2000)

    @field_validator("loan_type")
    @classmethod
    def check_loan_type(cls, v):
        if v not in LOAN_TYPES:
            raise HTTPException(status_code=422, detail=f"Invalid loan type. Choose from: {', '.join(LOAN_TYPES)}")
        return v
