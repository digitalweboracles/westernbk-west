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
- Postgres service is deployed and Online but as of the last check the web service runs SQLite (`dev.db` inside ephemeral container disk) — `DATABASE_URL` **not yet** wired in the web service variables. User must add a Service Reference variable `DATABASE_URL` from the Postgres service (dashboard → service Variables) and redeploy to go fully Postgres.

## Static assets
- `index.html` + all asset dirs (css/fonts/images/js) live under `static/`; mounted at `/static` (mount name `"static"` so `url_for('static', path=...)` works)
- Do NOT mount `/static` to the repo root — it exposed runtime-created `dev.db` publicly (fixed in commit `1b37408`)

## Stack
Python FastAPI + SQLAlchemy + Jinja2; auth = JWT session cookie (`session`), PBKDF2 (`security.py`); env `SESSION_SECRET` optional (auto-generated)
Routes: `/`, `/healthz`, `/about`, `/services`, `/projects`, `/blog`, `/contact`, `/newsletter`, `/signup`, `/login`, `/logout`, `/dashboard`, `/apply`

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