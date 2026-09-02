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
Routes: `/`, `/healthz`, `/about`, `/services`, `/projects`, `/contact`, `/newsletter`, `/signup`, `/login`, `/logout`, `/dashboard`, `/apply`

## Local dev
`pip install -r requirements.txt`; `DATABASE_URL=sqlite:///./dev.db SESSION_SECRET=test uvicorn app:app --port 8000`