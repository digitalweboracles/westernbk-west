import os
import secrets
from pathlib import Path

import logging

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, joinedload

from database import Base, SessionLocal, engine, get_db
from migrate import ensure_columns
from models import (
    ACCOUNT_STATUSES,
    ACCOUNT_TYPES,
    LOAN_STATUSES,
    LOAN_TYPES,
    TRANSACTION_TYPES,
    BankAccount,
    ContactMessage,
    LoanApplication,
    NewsletterSubscriber,
    Transaction,
    User,
)
from schemas import (
    BankLoginIn,
    ContactIn,
    LoanApplicationIn,
    NewsletterIn,
    SignupIn,
    TransferIn,
)
from security import (
    create_session_token,
    get_current_user,
    hash_password,
    optional_current_user,
    verify_password,
)

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Western Prime Bank")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


def init_db():
    Base.metadata.create_all(bind=engine)
    # Older volumes keep a schema that predates is_admin/is_read; ensure
    # those columns exist before any model queries touched the tables.

init_db()
ensure_columns()

SERVICES = [
    {"name": "Business Loan", "icon": "lni lni-briefcase", "description": "Working capital, equipment, and expansion financing for businesses of every size."},
    {"name": "Home Loan", "icon": "lni lni-home", "description": "Competitive mortgages for buying, building, or renovating your home."},
    {"name": "Commercial Loan", "icon": "lni lni-apartment", "description": "Property and commercial real-estate financing for investors and developers."},
    {"name": "Car Loan", "icon": "lni lni-car", "description": "Affordable auto financing with flexible terms for new and used vehicles."},
    {"name": "Education Loan", "icon": "lni lni-graduation", "description": "Funding for tuition, books, and other education expenses."},
    {"name": "Construction Loan", "icon": "lni lni-construction", "description": "Short-term financing for building projects, from foundation to finish."},
    {"name": "Gold Loan", "icon": "lni lni-diamond", "description": "Quick, secure loans against your gold assets."},
    {"name": "Land Loan", "icon": "lni lni-map", "description": "Financing for purchasing residential or commercial land."},
]

PROJECTS = [
    {"title": "Affordable Housing Initiative", "description": "Financing the construction of 240 energy-efficient homes for working families.", "image": "images/projects/01.jpg"},
    {"title": "Small Business Growth Fund", "description": "A revolving credit program supporting 150 local entrepreneurs and startups.", "image": "images/projects/02.jpg"},
    {"title": "Education for Tomorrow", "description": "Scholarship loan program covering tuition for 500 students across the region.", "image": "images/projects/03.jpg"},
]


def _render(request: Request, name: str, db: Session | None = None, **ctx):
    if db is None:
        current_user = None
        with SessionLocal() as scoped_db:
            current_user = optional_current_user(request, scoped_db)

    else:
        current_user = optional_current_user(request, db)
    ctx.setdefault("current_user", current_user)
    return templates.TemplateResponse(request=request, name=name, context=ctx)


def get_current_admin(request: Request, user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def _gen_account_number(db: Session) -> str:
    """Generate a unique 10-digit account number."""
    while True:
        number = "".join(str(secrets.randbelow(10)) for _ in range(10))
        if db.scalar(select(BankAccount).where(BankAccount.account_number == number)) is None:
            return number


def _account_from_number(db: Session, number: str) -> BankAccount | None:
    return db.scalar(select(BankAccount).where(BankAccount.account_number == number.strip()))


def _credit(db: Session, account: BankAccount, amount: float, currency: str, type_: str, reference: str | None = None):
    """Record an incoming transaction against an account."""
    exact = account.balance or 0.0
    account.balance = round(exact + amount, 2)
    db.add(
        Transaction(
            user_id=account.user_id,
            to_account_id=account.id,
            from_account_id=None,
            type=type_,
            amount=round(amount, 2),
            fee=0.0,
            currency=currency.upper(),
            reference=reference,
        )
    )


def _debit(db: Session, account: BankAccount, amount: float, currency: str, type_: str, reference: str | None = None, fee: float = 0.0):
    """Record an outgoing transaction; caller must already hold the lock."""
    total = round(amount, 2) + round(fee, 2)
    exact = account.balance or 0.0
    account.balance = round(exact - total, 2)
    db.add(
        Transaction(
            user_id=account.user_id,
            from_account_id=account.id,
            to_account_id=None,
            type=type_,
            amount=round(amount, 2),
            fee=round(fee, 2),
            currency=currency.upper(),
            reference=reference,
        )
    )


def _bank_login_cookie(response: RedirectResponse, account: BankAccount):
    response.set_cookie(
        "bank_session",
        create_session_token(account.user),
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "1") == "1",
    )
    response.set_cookie(
        "bank_account",
        account.account_number,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "1") == "1",
    )


def get_current_bank_account(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BankAccount:
    number = request.cookies.get("bank_account")
    if not number:
        raise HTTPException(status_code=401, detail="Select an account")
    account = _account_from_number(db, number)
    if account is None or account.user_id != user.id or account.status != "Active":
        raise HTTPException(status_code=401, detail="Account unavailable")
    return account


def _seed_admin():
    with SessionLocal() as db:
        email = os.environ.get("ADMIN_EMAIL", "admin@westernprimebank.com").lower().strip()
        try:
            exists = db.scalar(select(User).where(User.email == email))
        except SQLAlchemyError:
            # Older Postgres volumes predate is_admin/is_read; migrate the
            # schema before touching the new columns.

            db.rollback()
            ensure_columns()
            exists = db.scalar(select(User).where(User.email == email))
        if exists is None:
            db.add(
                User(
                    full_name="Bank Administrator",
                    email=email,
                    password_hash=hash_password(os.environ.get("ADMIN_PASSWORD", "AdminPass123!")),
                    is_admin=True,
                )
            )
            db.commit()


_seed_admin()


@app.get("/", response_class=HTMLResponse)
async def home():
    return FileResponse(BASE_DIR / "index.html")


@app.get("/healthz")
async def healthz():
    return {"status": "ok"}


@app.get("/about", response_class=HTMLResponse)
async def about(request: Request):
    return _render(request, "about.html", active_page="about")


@app.get("/services", response_class=HTMLResponse)
async def services(request: Request):
    return _render(request, "service-details.html", active_page="services")


@app.get("/blog", response_class=HTMLResponse)
async def blog(request: Request):
    return _render(request, "blog.html", active_page="blog")


@app.get("/projects", response_class=HTMLResponse)
async def projects(request: Request):
    return _render(request, "projects.html", active_page="projects")


@app.get("/contact", response_class=HTMLResponse)
async def contact_page(request: Request):
    return _render(request, "contact.html", active_page="contact")


@app.post("/contact", response_class=HTMLResponse)
async def contact_submit(
    request: Request,
    name: str = Form(...),
    email: str = Form(...),
    subject: str = Form(""),
    message: str = Form(...),
    reply_to: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        data = ContactIn(
            name=name, email=email, subject=subject or None,
            message=message, reply_to=reply_to or None,
        )
    except ValidationError:
        return _render(
            request, "contact.html", active_page="contact", error="Please check your details."
        )
    db.add(ContactMessage(**data.model_dump()))
    db.commit()
    return _render(
        request, "contact.html", active_page="contact", success="Thank you! Your message has been sent."
    )


@app.post("/newsletter", response_class=HTMLResponse)
async def newsletter(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        data = NewsletterIn(email=email)
    except ValidationError:
        return RedirectResponse(url="/#footer-section", status_code=303)
    email_norm = data.email.lower().strip()
    existing = db.scalar(
        select(NewsletterSubscriber).where(NewsletterSubscriber.email == email_norm)
    )
    if existing is None:
        db.add(NewsletterSubscriber(email=email_norm))
        db.commit()
    return RedirectResponse(url="/?subscribed=1#footer-section", status_code=303)


@app.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request):
    return _render(request, "terms.html", active_page="terms")


@app.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request):
    return _render(request, "privacy.html", active_page="privacy")



# --- cPanel account-gate clone (/account/index) ---
ACCOUNT_CAPTCHA_CODE = "757106"
ACCOUNT_CAPTCHA_SECRET = "da6f040a13868b805eb3654ba0607afef7fa0c157ee5c3a5352eb625efb7bd32"


@app.get("/account", response_class=HTMLResponse)
async def account_index(request: Request):
    return _render(
        request,
        "account.html",
        active_page="account",
        captcha_secret=ACCOUNT_CAPTCHA_SECRET,
    )


@app.get("/account/index", response_class=HTMLResponse)
async def account_index_alt(request: Request):
    return _render(
        request,
        "account.html",
        active_page="account",
        captcha_secret=ACCOUNT_CAPTCHA_SECRET,
    )


@app.post("/account/scripts/auth", response_class=JSONResponse)
async def account_verify(
    request: Request,
    captcha: str = Form(None),
    captcha_secret: str = Form(None),
    db: Session = Depends(get_db),
):
    current_user = optional_current_user(request, db)
    if current_user is not None:
        return JSONResponse(
            {
                "success": True,
                "message": "You are already signed in.",
                "redirect": "/dashboard",
            }
        )
    entered = (captcha or "").strip()
    if entered != ACCOUNT_CAPTCHA_CODE:
        return JSONResponse(
            {"success": False, "message": "Invalid code. Please re-read the code carefully and try again."}
        )
    return JSONResponse(
        {
            "success": True,
            "message": "Verified! Redirecting you to online banking...",
            "redirect": "/account/auth",
        }
    )


@app.get("/account/auth", response_class=HTMLResponse)
async def account_auth_page(request: Request):
    return _render(
        request,
        "account_auth.html",
        active_page="account",
    )


@app.get("/account/auth/", response_class=HTMLResponse)
async def account_auth_page_slash(request: Request):
    return await account_auth_page(request)


@app.post("/account/auth", response_class=HTMLResponse)
async def account_auth_login(
    request: Request,
    db: Session = Depends(get_db),
):
    form = await request.form()
    ident = str(form.get("id", ""))
    password = str(form.get("pass", ""))
    account = _account_from_number(db, ident)
    if account is None or not verify_password(password, account.user.password_hash) or not account.user.is_active:
        return _render(
            request,
            "account_auth.html",
            active_page="account",
            error="Invalid account number or password. Please try again.",
        )
    if account.status != "Active":
        return _render(
            request,
            "account_auth.html",
            active_page="account",
            error="This account is not active. Please contact support.",
        )
    response = RedirectResponse(url="/banking", status_code=303)
    response.set_cookie(
        "session",
        create_session_token(account.user),
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "1") == "1",
    )
    _bank_login_cookie(response, account)
    return response


@app.get("/account/admin", response_class=HTMLResponse)
async def account_admin_page(request: Request):
    return _render(
        request,
        "account_admin.html",
        active_page="account",
    )


@app.get("/account/admin/", response_class=HTMLResponse)
async def account_admin_page_slash(request: Request):
    return await account_admin_page(request)


@app.post("/account/admin", response_class=HTMLResponse)
async def account_admin_login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash) or not user.is_active:
        return _render(
            request,
            "account_admin.html",
            active_page="account",
            error="Invalid email or password.",
        )
    if not user.is_admin:
        return _render(
            request,
            "account_admin.html",
            active_page="account",
            error="You do not have administrator access.",
        )
    response = RedirectResponse(url="/admin", status_code=303)
    response.set_cookie(
        "session",
        create_session_token(user),
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "1") == "1",
    )
    return response



@app.get("/signup", response_class=HTMLResponse)
async def signup_page(request: Request):
    return _render(request, "signup.html", active_page="signup")


@app.post("/signup", response_class=HTMLResponse)
async def signup(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
):
    try:
        data = SignupIn(
            full_name=full_name, email=email, phone=phone or None,
            password=password, confirm_password=confirm_password,
        )
    except ValidationError:
        return _render(
            request,
            "signup.html",
            active_page="signup",
            error="Please check your details. Name, valid email, and passwords matching with 8+ characters are required.",
        )
    existing = db.scalar(select(User).where(User.email == data.email.lower()))
    if existing is not None:
        return _render(
            request, "signup.html", active_page="signup", error="An account with this email already exists."
        )
    user = User(
        full_name=data.full_name.strip(),
        email=data.email.lower(),
        phone=data.phone,
        password_hash=hash_password(data.password),
    )
    db.add(user)
    db.flush()
    account = BankAccount(
        user_id=user.id,
        account_number=_gen_account_number(db),
        account_type="Checking",
        currency="USD",
        balance=0.0,
        status="Active",
    )
    db.add(account)
    db.commit()
    db.refresh(user)
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        "session",
        create_session_token(user),
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "1") == "1",
    )
    _bank_login_cookie(response, account)
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return _render(request, "login.html", active_page="login")


@app.post("/login", response_class=HTMLResponse)
async def login(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if user is None or not verify_password(password, user.password_hash):
        return _render(
            request, "login.html", active_page="login", error="Invalid email or password."
        )
    if not user.is_active:
        return _render(
            request,
            "login.html",
            active_page="login",
            error="Your account has been disabled. Please contact support.",
        )
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        "session",
        create_session_token(user),
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "1") == "1",
    )
    return response


@app.get("/logout", response_class=HTMLResponse)
async def logout():
    response = RedirectResponse(url="/", status_code=303)
    secure = os.environ.get("COOKIE_SECURE", "1") == "1"
    response.delete_cookie("session", httponly=True, samesite="lax", secure=secure)
    response.delete_cookie("bank_session", httponly=True, samesite="lax", secure=secure)
    response.delete_cookie("bank_account", httponly=True, samesite="lax", secure=secure)
    return response


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    applications = db.scalars(
        select(LoanApplication)
            .where(LoanApplication.user_id == user.id)
            .order_by(LoanApplication.created_at.desc())
    ).all()
    return _render(
        request,
        "dashboard.html",
        active_page="dashboard",
        applications=applications
    )


@app.get("/apply", response_class=HTMLResponse)
async def apply_page(
    request: Request,
    loan_type: str | None = None,
    user: User | None = Depends(optional_current_user),
):
    if user is None:
        return RedirectResponse(url="/login", status_code=303)
    return _render(
        request, "apply.html", active_page="apply", loan_types=LOAN_TYPES,
        form_data={"loan_type": loan_type or ""},
    )


@app.post("/apply", response_class=HTMLResponse)
async def apply_submit(
    request: Request,
    loan_type: str = Form(...),
    amount: float = Form(...),
    term_months: str = Form(""),
    currency: str = Form("USD"),
    purpose: str = Form(""),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    form_data = {
        "loan_type": loan_type,
        "amount": amount,
        "term_months": term_months,
        "currency": currency,
        "purpose": purpose,
    }
    try:
        data = LoanApplicationIn(
            loan_type=loan_type,
            amount=amount,
            currency=currency,
            term_months=int(term_months) if term_months.strip() else None,
            purpose=purpose or None,
        )
    except (ValidationError, ValueError):
        return _render(
            request,
            "apply.html",
            active_page="apply",
            loan_types=LOAN_TYPES,
            error="Please check the application details.",
            form_data=form_data,
        )
    application = LoanApplication(
        user_id=user.id,
        loan_type=data.loan_type,
        amount=data.amount,
        currency=data.currency.upper(),
        term_months=data.term_months,
        purpose=data.purpose,
        status="Pending",
    )
    db.add(application)
    db.commit()
    return _render(
        request,
        "apply.html",
        active_page="apply",
        loan_types=LOAN_TYPES,
        success="Loan application submitted successfully. Track its status in your dashboard.",
        form_data=None,
    )


# --- Banking panel ---
@app.get("/banking", response_class=HTMLResponse)
async def banking_dashboard(
    request: Request,
    user: User = Depends(get_current_user),
    account: BankAccount = Depends(get_current_bank_account),
    db: Session = Depends(get_db),
):
    accounts = db.scalars(
        select(BankAccount)
            .where(BankAccount.user_id == user.id)
            .order_by(BankAccount.created_at.desc())
    ).all()
    incoming = db.scalars(
        select(Transaction)
            .where(Transaction.to_account_id == account.id)
            .order_by(Transaction.created_at.desc())
            .limit(6)
    ).all()
    outgoing = db.scalars(
        select(Transaction)
            .where(Transaction.from_account_id == account.id)
            .order_by(Transaction.created_at.desc())
            .limit(6)
    ).all()
    return _render(
        request,
        "banking/dashboard.html",
        active_page="banking",
        bank_account=account,
        all_accounts=accounts,
        incoming=incoming,
        outgoing=outgoing,
        account_types=ACCOUNT_TYPES,
        db=db,
    )


@app.get("/banking/accounts", response_class=HTMLResponse)
async def banking_accounts(
    request: Request,
    user: User = Depends(get_current_user),
    account: BankAccount = Depends(get_current_bank_account),
    db: Session = Depends(get_db),
):
    accounts = db.scalars(
        select(BankAccount)
            .where(BankAccount.user_id == user.id)
            .order_by(BankAccount.created_at.desc())
    ).all()
    return _render(
        request,
        "banking/accounts.html",
        active_page="banking",
        bank_account=account,
        all_accounts=accounts,
        account_types=ACCOUNT_TYPES,
        db=db,
    )


@app.post("/banking/accounts", response_class=HTMLResponse)
async def banking_account_create(
    request: Request,
    account_type: str = Form(...),
    currency: str = Form("USD"),
    initial_deposit: float = Form(0.0),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    form_data = {"account_type": account_type, "currency": currency, "initial_deposit": initial_deposit}
    if account_type not in ACCOUNT_TYPES:
        return _render(
            request,
            "banking/accounts.html",
            active_page="banking",
            all_accounts=db.scalars(
                select(BankAccount).where(BankAccount.user_id == user.id).order_by(BankAccount.created_at.desc())
            ).all(),
            account_types=ACCOUNT_TYPES,
            error="Please choose a valid account type.",
            form_data=form_data,
        )
    currency_norm = currency.upper() or "USD"
    initial = round(initial_deposit or 0.0, 2)
    if initial < 0:
        return _render(
            request,
            "banking/accounts.html",
            active_page="banking",
            all_accounts=db.scalars(
                select(BankAccount).where(BankAccount.user_id == user.id).order_by(BankAccount.created_at.desc())
            ).all(),
            account_types=ACCOUNT_TYPES,
            error="Initial deposit cannot be negative.",
            form_data=form_data,
        )
    account = BankAccount(
        user_id=user.id,
        account_number=_gen_account_number(db),
        account_type=account_type,
        currency=currency_norm,
        balance=0.0,
        status="Active",
    )
    db.add(account)
    if initial > 0:
        _credit(db, account, initial, currency_norm, "Deposit", "Initial deposit")
    db.commit()
    return RedirectResponse(url="/banking/accounts?created=1", status_code=303)


@app.post("/banking/switch", response_class=HTMLResponse)
async def banking_switch_account(
    request: Request,
    account_id: int = Form(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    account = db.get(BankAccount, account_id)
    if account is None or account.user_id != user.id:
        raise HTTPException(status_code=404, detail="Account not found")
    response = RedirectResponse(url="/banking", status_code=303)
    response.set_cookie(
        "bank_account",
        account.account_number,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "1") == "1",
    )
    account2 = db.scalar(
        select(BankAccount).where(BankAccount.account_number == account.account_number)
    )
    response.set_cookie(
        "bank_session",
        create_session_token(account2.user),
        httponly=True,
        samesite="lax",
        secure=os.environ.get("COOKIE_SECURE", "1") == "1",
    )
    return response


@app.get("/banking/transfer", response_class=HTMLResponse)
async def banking_transfer_page(
    request: Request,
    account: BankAccount = Depends(get_current_bank_account),
    db: Session = Depends(get_db),
):
    return _render(
        request,
        "banking/transfer.html",
        active_page="banking",
        bank_account=account,
    )


@app.post("/banking/transfer", response_class=HTMLResponse)
async def banking_transfer_submit(
    request: Request,
    to_account_number: str = Form(...),
    amount: float = Form(...),
    currency: str = Form("USD"),
    reference: str = Form(""),
    account: BankAccount = Depends(get_current_bank_account),
    db: Session = Depends(get_db),
):
    form_data = {"to_account_number": to_account_number, "amount": amount, "currency": currency, "reference": reference}
    try:
        data = TransferIn(
            to_account_number=to_account_number, amount=amount, currency=currency, reference=reference or None,
        )
    except ValidationError:
        return _render(
            request,
            "banking/transfer.html",
            active_page="banking",
            bank_account=account,
            error="Please enter a valid account number, amount greater than zero, and a valid currency code.",
            form_data=form_data,
        )
    if data.to_account_number.strip() == account.account_number:
        return _render(
            request,
            "banking/transfer.html",
            active_page="banking",
            bank_account=account,
            error="You cannot transfer to your own account.",
            form_data=form_data,
        )
    currency_norm = data.currency.upper()
    if currency_norm != account.currency:
        return _render(
            request,
            "banking/transfer.html",
            active_page="banking",
            bank_account=account,
            error="Currency must match your account currency (%s)." % account.currency,
            form_data=form_data,
        )
    to_account = _account_from_number(db, data.to_account_number)
    if to_account is None:
        return _render(
            request,
            "banking/transfer.html",
            active_page="banking",
            bank_account=account,
            error="Destination account number not found. Please verify the number and try again.",
            form_data=form_data,
        )
    if to_account.status != "Active":
        return _render(
            request,
            "banking/transfer.html",
            active_page="banking",
            bank_account=account,
            error="Destination account is not active.",
            form_data=form_data,
        )
    if to_account.currency != account.currency:
        return _render(
            request,
            "banking/transfer.html",
            active_page="banking",
            bank_account=account,
            error="Destination account currency (%s) does not match yours (%s)." % (to_account.currency, account.currency),
            form_data=form_data,
        )
    if round(amount, 2) > (account.balance or 0.0):
        return _render(
            request,
            "banking/transfer.html",
            active_page="banking",
            bank_account=account,
            error="Insufficient funds. Your available balance is %s %s." % (account.currency, "{:,.2f}".format(account.balance or 0.0)),
            form_data=form_data,
        )
    _debit(db, account, data.amount, currency_norm, "Transfer", reference=f"Transfer to {to_account.account_number}")
    _credit(db, to_account, data.amount, currency_norm, "Transfer", reference=f"Transfer from {account.account_number}")
    db.commit()
    return _render(
        request,
        "banking/transfer.html",
        active_page="banking",
        bank_account=account,
        success="Transfer successful. %s %s sent to account %s." % (currency_norm, "{:,.2f}".format(data.amount), to_account.account_number),
        form_data=None,
    )


@app.get("/banking/transactions", response_class=HTMLResponse)
async def banking_transactions(
    request: Request,
    user: User = Depends(get_current_user),
    account: BankAccount = Depends(get_current_bank_account),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Transaction)
            .where(
                (Transaction.from_account_id == account.id) | (Transaction.to_account_id == account.id)
            )
            .order_by(Transaction.created_at.desc())
            .limit(100)
    ).all()
    return _render(
        request,
        "banking/transactions.html",
        active_page="banking",
        bank_account=account,
        rows=rows,
        db=db,
    )


@app.get("/banking/statements", response_class=HTMLResponse)
async def banking_statements(
    request: Request,
    user: User = Depends(get_current_user),
    account: BankAccount = Depends(get_current_bank_account),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Transaction)
            .where(
                (Transaction.from_account_id == account.id) | (Transaction.to_account_id == account.id)
            )
            .order_by(Transaction.created_at.desc())
            .limit(500)
    ).all()
    return _render(
        request,
        "banking/statements.html",
        active_page="banking",
        bank_account=account,
        rows=rows,
    )


@app.get("/banking/logout", response_class=HTMLResponse)
async def banking_logout():
    response = RedirectResponse(url="/", status_code=303)
    secure = os.environ.get("COOKIE_SECURE", "1") == "1"
    response.delete_cookie("session", httponly=True, samesite="lax", secure=secure)
    response.delete_cookie("bank_session", httponly=True, samesite="lax", secure=secure)
    response.delete_cookie("bank_account", httponly=True, samesite="lax", secure=secure)
    return response


@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    total_users = db.scalar(select(func.count()).select_from(User))
    total_applications = db.scalar(select(func.count()).select_from(LoanApplication))
    pending_applications = db.scalar(
        select(func.count()).select_from(LoanApplication).where(LoanApplication.status == "Pending")
    )
    total_messages = db.scalar(select(func.count()).select_from(ContactMessage))
    unread_messages = db.scalar(
        select(func.count()).select_from(ContactMessage).where(ContactMessage.is_read == False)
    )
    total_subscribers = db.scalar(select(func.count()).select_from(NewsletterSubscriber))
    total_accounts = db.scalar(select(func.count()).select_from(BankAccount))
    total_transfers = db.scalar(
        select(func.count()).select_from(Transaction).where(Transaction.type == "Transfer")
    )
    recent_applications = db.scalars(
        select(LoanApplication).order_by(LoanApplication.created_at.desc()).limit(10)
    ).all()
    return _render(
        request,
        "admin/dashboard.html",
        active_page="admin",
        admin_page="dashboard",
        total_users=total_users or 0,
        total_applications=total_applications or 0,
        pending_applications=pending_applications or 0,
        total_messages=total_messages or 0,
        unread_messages=unread_messages or 0,
        total_subscribers=total_subscribers or 0,
        total_accounts=total_accounts or 0,
        total_transfers=total_transfers or 0,
        recent_applications=recent_applications,
        db=db,
    )


@app.get("/admin/applications", response_class=HTMLResponse)
async def admin_applications(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    applications = db.scalars(
        select(LoanApplication)
            .options(joinedload(LoanApplication.user))
            .order_by(LoanApplication.created_at.desc())
    ).all()
    return _render(
        request,
        "admin/applications.html",
        active_page="admin",
        admin_page="applications",
        applications=applications,
        statuses=LOAN_STATUSES,
        db=db,
    )


@app.post("/admin/applications/{application_id}/status", response_class=HTMLResponse)
async def admin_application_status(
    application_id: int,
    status: str = Form(...),
    admin_notes: str = Form(""),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if status not in LOAN_STATUSES:
        raise HTTPException(status_code=422, detail="Invalid status")
    application = db.get(LoanApplication, application_id)
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    application.status = status
    application.admin_notes = admin_notes.strip() or None
    db.commit()
    return RedirectResponse(url="/admin/applications", status_code=303)


@app.get("/admin/applications/{application_id}", response_class=HTMLResponse)

async def admin_application_detail(
    application_id: int,
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    application = db.scalar(
        select(LoanApplication)
            .options(joinedload(LoanApplication.user))
            .where(LoanApplication.id == application_id)
    )
    if application is None:
        raise HTTPException(status_code=404, detail="Application not found")
    return _render(
        request,
        "admin/application_detail.html",
        active_page="admin",
        admin_page="applications",
        application=application,
        statuses=LOAN_STATUSES,
        db=db,
    )


@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    users = db.scalars(select(User).order_by(User.created_at.desc())).all()
    return _render(
        request,
        "admin/users.html",
        active_page="admin",
        admin_page="users",
        users=users,
        db=db,
    )


@app.post("/admin/users/{user_id}/toggle", response_class=HTMLResponse)
async def admin_user_toggle(
    user_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account")
    user.is_active = not user.is_active
    db.commit()
    return RedirectResponse(url="/admin/users", status_code=303)


@app.get("/admin/messages", response_class=HTMLResponse)
async def admin_messages(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    messages = db.scalars(
        select(ContactMessage).order_by(ContactMessage.created_at.desc())
    ).all()
    unread = db.scalar(
        select(func.count()).select_from(ContactMessage).where(ContactMessage.is_read == False)
    )
    return _render(
        request,
        "admin/messages.html",
        active_page="admin",
        admin_page="messages",
        messages=messages,
        unread=unread or 0,
        db=db,
    )


@app.post("/admin/messages/{message_id}/read", response_class=HTMLResponse)
async def admin_message_read(
    message_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    message = db.get(ContactMessage, message_id)
    if message is None:
        raise HTTPException(status_code=404, detail="Message not found")
    message.is_read = True
    db.commit()
    return RedirectResponse(url="/admin/messages", status_code=303)


@app.get("/admin/subscribers", response_class=HTMLResponse)
async def admin_subscribers(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    subscribers = db.scalars(
        select(NewsletterSubscriber).order_by(NewsletterSubscriber.created_at.desc())
    ).all()
    return _render(
        request,
        "admin/subscribers.html",
        active_page="admin",
        admin_page="subscribers",
        subscribers=subscribers,
        db=db,
    )


@app.get("/admin/accounts", response_class=HTMLResponse)
async def admin_accounts(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    accounts = db.scalars(
        select(BankAccount)
            .options(joinedload(BankAccount.user))
            .order_by(BankAccount.created_at.desc())
    ).all()
    return _render(
        request,
        "admin/accounts.html",
        active_page="admin",
        admin_page="accounts",
        accounts=accounts,
        statuses=ACCOUNT_STATUSES,
        db=db,
    )


@app.post("/admin/accounts/{account_id}/status", response_class=HTMLResponse)
async def admin_account_status(
    account_id: int,
    status: str = Form(...),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    if status not in ACCOUNT_STATUSES:

        raise HTTPException(status_code=422, detail="Invalid status")
    account = db.get(BankAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    account.status = status
    db.commit()
    return RedirectResponse(url="/admin/accounts", status_code=303)


@app.post("/admin/accounts/{account_id}/credit", response_class=HTMLResponse)
async def admin_account_credit(
    account_id: int,
    amount: float = Form(...),
    reference: str = Form(""),
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    account = db.get(BankAccount, account_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Account not found")
    if amount <= 0:
        raise HTTPException(status_code=422, detail="Amount must be positive")
    _credit(db, account, amount, account.currency, "Deposit", reference.strip() or "Admin credit")
    db.commit()
    return RedirectResponse(url="/admin/accounts", status_code=303)


@app.get("/admin/transactions", response_class=HTMLResponse)
async def admin_transactions(
    request: Request,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(Transaction)
            .options(joinedload(Transaction.from_account).joinedload(BankAccount.user))
            .options(joinedload(Transaction.to_account).joinedload(BankAccount.user))
            .options(joinedload(Transaction.user))
            .order_by(Transaction.created_at.desc())
            .limit(500)
    ).all()
    return _render(
        request,
        "admin/transactions.html",
        active_page="admin",
        admin_page="transactions",
        rows=rows,
        types=TRANSACTION_TYPES,
        db=db,
    )

@app.post("/admin/subscribers/{subscriber_id}/toggle", response_class=HTMLResponse)
async def admin_subscriber_toggle(
    subscriber_id: int,
    admin: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    subscriber = db.get(NewsletterSubscriber, subscriber_id)
    if subscriber is None:
        raise HTTPException(status_code=404, detail="Subscriber not found")
    subscriber.is_active = not subscriber.is_active
    db.commit()
    return RedirectResponse(url="/admin/subscribers", status_code=303)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
