import os
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import Base, SessionLocal, engine, get_db
from models import (
    LOAN_TYPES,
    ContactMessage,
    LoanApplication,
    NewsletterSubscriber,
    User,
)
from schemas import ContactIn, LoanApplicationIn, NewsletterIn, SignupIn
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


init_db()

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
    return _render(request, "services.html", active_page="services", services=SERVICES)


@app.get("/projects", response_class=HTMLResponse)
async def projects(request: Request):
    return _render(request, "projects.html", active_page="projects", projects=PROJECTS)


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
    user: User = Depends(get_current_user),
):
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
