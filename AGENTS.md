# Western Prime Bank (westernbk-west)

Static marketing site (original HTML/design) with FastAPI backend powering dynamic pages.

## Live deployment (Railway)
- URL: https://westernbk-west-production.up.railway.app
- Project: `gwr-debate-marathon` (id ``b904c023-5b7b-4f6c-8efd-c57960e8b7c7``)
- Service: `westernbk-west` (id ``1a221eea-c501-4b81-a88f-d1eae5a47384``); Postgres service id ``75c38127-2f9c-45f3-b6d6-424e8c2e6ea8``
- Deploys auto-run on push to `main` (repo-linked GitHub source with Railpack → Python/FastAPI runtime; `Procfile` boots uvicorn on `$PORT`)
- Railway token scoped to project (place in `RAILWAY_TOKEN`); project-scoped ops work (`status`, `service list`); project-linking/variable ops deny (`Unauthorized`)
- CLI: `~/.npm-global/bin/railway` (installed via `npm install -g --prefix "$HOME/.npm-global"`)

## DB backend
- `database.py` reads `DATABASE_URL` (Postgres-ready), falls back to `sqlite:///./dev.db` for dev
- Postgres was deleted/recreated by user on 2026-09-03; **current** URL uses `.railway.internal` host + fresh creds (password changes each recreation; get from Railway → Postgres → Variables → `DATABASE_URL`).

## Required service variables (Railway dashboard → service Variables)
Set these on the `westernbk-west` service (web service)::
- `DATABASE_URL` — **literal string**, e.g. `postgresql://postgres:...@postgres.railway.internal:5432/railway` (NOT a Service Reference; see DB backend note)
- `SESSION_SECRET` — stable random hex (e.g. `openssl rand -hex 32`); without it `security.py` auto-generates a new secret per deploy → all existing login cookies invalidate on every redeploy
- `ADMIN_PASSWORD` — seeded admin password (`_seed_admin` uses it); if unset, default `AdminPass123!` applies only to fresh DB (existing user row keeps old hash)
- `ADMIN_EMAIL` — optional; default `admin@westernprimebank.com`
- `COOKIE_SECURE` — default `"1"` (secure cookies; keep `1` on HTTPS prod

## Static assets
- `index.html` + all asset dirs (css/fonts/images/js) live under `static/`; mounted at `/static` (mount name `"static"` so `url_for('static', path=...)` works)
- Do NOT mount `/static` to the repo root — it exposed runtime-created `dev.db` publicly (fixed in commit `1b37408`)

## Stack
Python FastAPI + SQLAlchemy + Jinja2; auth = JWT session cookie (`session`), PBKDF2 (`security.py`); env `SESSION_SECRET` optional (auto-generated)
Routes: `/`, `/healthz`, `/about`, `/services`, `/projects`, `/blog`, `/contact`, `/newsletter`, `/signup`, `/login`, `/logout`, `/dashboard`, `/apply`

## Asset URLs (2026-09)
- **Never use `url_for('static', path=...)` in templates.** Behind Railway the app sees plain `http` (proxy `X-Forwarded-Proto` not trusted by default), so `url_for` emits absolute `http://<host>/static/...` links → browsers block every asset as mixed content on HTTPS → the page renders unstyled/"totally different". Use literal `/static/<path>` paths (host/scheme independent) everywhere — this is what the templates do now (commit `2e3bfca`)。 Same for JS redirects: hardcode `/dashboard`/`/account/auth` literals instead of `url_for('dashboard')`.

## Local dev
`pip install -r requirements.txt`; `DATABASE_URL=sqlite:///./dev.db SESSION_SECRET=test uvicorn app:app --port 8000`

## Session notes (2026-09)
- Admin area complete locally: routes `/admin`, `/admin/applications`, `/admin/applications/{id}`, `/admin/applications/{id}/status`, `/admin/users`, `/admin/users/{id}/toggle`, `/admin/messages`, `/admin/messages/{id}/read`, `/admin/subscribers`, `/admin/subscribers/{id}/toggle`; templates in `templates/admin/`.
- `models.py` adds `User.is_admin` and `ContactMessage.is_read` (bool, default false). Prod runs SQLite ephemeral disk → fresh DB per deploy → `create_all` rebuilds schema incl these columns, so no ALTER migration needed yet. If Postgres volume persistence is enabled later, add lightweight ALTER-migration at startup before relying on old rows.

- Login rejects inactive users (`POST /login` returns error page, no session); `get_current_user`/`optional_current_user` both check `is_active` (disabled → 401/None.
- Added `GET /terms` and `GET /privacy` routes + `templates/terms.html`/`privacy.html`; footer/admin nav links updated; `index.html` links/forms/typos cleaned (incl social links now real URLs).
- Known quirk: local plain-HTTP curl does not persist `Secure` cookie deletion → logout appears no-op over HTTP; over HTTPS (prod) `Set-Cookie: session=; Max-Age=0` works — verify with browser.
- Railway env not yet wired: `DATABASE_URL` should be a Service Reference to the Postgres service; `SESSION_SECRET`/`ADMIN_PASSWORD` settable via service variables.
- **cPanel parity (2026-09)**: Railway now mirrors WesternPrimeBNK.com (cPanel) page set. Ported bodies of `about.php`, `projects.php`, `service-details.php` (→ `/services`), `contact.php`, `blog.php` into Jinja templates extending `base.html` (same iddrak template/CSS) with assets via `url_for('static',...)`; images fetched from cPanel into `static/images/` (blog/, projects/04-05, service/01-02/service-details.jpg). `/blog` added; `/services` serves service-details body. Contact page retains working FastAPI POST form (+ cPanel info cards/map). Homepage nav/service/project cards rewired from `#` anchors to real routes; Blog item added in `base.html` + `index.html` nav; Backend refs updated in `app.py`
- **Account-gate clone exact-mirror (2026-09, commits e473342 + 7744d04 + exact)**: `static/account/` = byte-for-byte clone of `https://westernprimebnk.com/account/index` + its real Softnio DashLite v2.4 assets (css/js bundles, 28 fonts, favicon, logo; 3 slider SVGs recreated (server serves 404 for them)). Routes `/account` + `/account/index` render `templates/account.html` — now an a-z mirror of the live page: identical `Leggo` branding (`og:title/site_name`, two `<title>`s, "LG Online banking channels" writeup, slider copy "Leggo"/"westernprimebnk.com", footer "© 2026 Leggo"), Google Translate widget + `goog-te-gadget-simple` styles, Henny-Penny captcha font + `#033d75`/`#d13636` colour overrides, button font/size/classes byte-identical. Cloud differences (deliberate): static refs use `url_for('static', ...)`; the captcha code is **rotating per-request** (server-generated 6 digits in `_new_captcha_code`, stored in `_captcha_codes` deque,, one-time-use validation at POST — live uses a fresh random code per page too); POST `/account/scripts/auth?action=verifyRecaptcha` returns the same raw-HTML alert fragments as live (success/`Invalid code...`), and our page JS additionally auto-redirects to `/account/auth` after success (live just injects HTML. Logged-in visitors auto-redirect to `/dashboard`.
- **Banking portal (2026-09, commit 7744d04)**: real banking stack beneath the gate. `BankAccount`/`Transaction` models (+ `ACCOUNT_TYPES=Checking/Savings/Business/Fixed Deposit`, `ACCOUNT_STATUSES=Active/Frozen/Closed`, `TRANSACTION_TYPES=Deposit/Withdrawal/Transfer/Payment/Fee`); `_gen_account_number`, `_credit`, `_debit`, `_account_from_number` helpers in app.py. Signup auto-creates a Checking account (975 K + full-name-based default password `Western@<first><digits>`); `/account/auth` bank-login by account number + password (validates user active + account Active,, sets session + `bank_account_id` switch cookie; `/account/admin` admin-gate login by email+password, rejects non-admins). Banking pages `/banking`, `/banking/accounts` (+POST), `/banking/transfer` (+POST,, flags: self-transfer/insufficient/unknown-destination), `/banking/transactions`, `/banking/statements`, `/banking/switch`, `/banking/logout`; templates `templates/banking/*` extend `base.html` with the account switcher sidebar. Admin banking `/admin/accounts` (+POST credit/debit/status toggle), `/admin/transactions` (ledger joinedload from/to/user). Landing `/script/signup.php` (cPanel clone) now auto-provisions an account+user with default password (for demo parity), and the real `/signup` form too. E2E verified: signup → captcha → bank-login → dashboard → admin credit → transfer (both legs, balances, edge cases) → admin ledger. User `admin@westernprimebank.com` / `Admin@123` = site admin (dev seed). Tests: plain-HTTP curl on 401/redirect behavior; JWT cookie set via browser HTTPS required for prod niches.