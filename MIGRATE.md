# SQLite → Postgres data migration

Ship the existing `dev.db` data into the Railway Postgres **after** the web service
has been rewired toe `DATABASE_URL` and has booted once (that creates the schema
and seeds the admin).

## Hard requirements
1. Railway service `westernbk-west` already has `DATABASE_URL` pointing at the
   Postgres container (and has redeployed successfully once → schema exists).
2. Postgres reachable from where you run this — from your own machine after
   `railway login` + `railway connect`, or with Postgres public TCP enabled.

3. Docker local Postgres 15+/psql handy for dry-run (optional.



## Run (on YOUR machine, in repo root)

```bash
# 1. Optional dry-run against a throwaway local Postgres:
docker run --rm -d --name pgtest -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=railway \
  -p 15432:5432 postgres:15-alpine
PG_URL="postgresql://postgres:pw@localhost:15432/railway" python3 migrate_sqlite_to_pg.py

# 2. Real target (have the app already booted on Postgres once):
railway login            # if needed
railway link            # pick `gwr-debate-marathon`
railway connect <postgres-service>   # opens tunnel (or use public TCP)
# run in another terminal (tunnel gives you a localhost port, often 15432:
PG_URL="postgresql://postgres:POSTGRES_PW@localhost:PORT/railway" python3 migrate_sqlite_to_pg.py
```

Or, if you pasted the app's `DATABASE_URL` into your shell already, just:
```bash
python3 migrate_sqlite_to_pg.py        # reads DATABASE_URL automatically
```

For an SQLite file elsewhere: `SQLITE_PATH=/path/to/dev.db python3 migrate_sqlite_to_pg.py`.



## Expected output
```
Source: dev.db
  users: 6 inserted (0 existed/skipped)
  bank_accounts: 7 inserted...
  loan_applications: 1 inserted...
  transactions:  ̃12 inserted...
  contact_messages: 1 inserted...
  newsletter_subscribers: 1 inserted...

DONE - inserted 28 rows, skipped 0 existing.
```
Run again anytime — it skips existing rows (idempotent) and keeps sequences ahead of max(id).



## Verify after migrating
- `https://westernprimebank.com/login` — login as any pre-existing user
  (e.g. `teste2e@example.com` / `TestPass123!`) → dashboard shows migrated balances.
- `/banking/accounts` — account numbers/balances match SQLite fixtures.
- `/admin` — admin login (`admin@westernprimebank.com`) + panels 200.
- Optional SQL sanity: `SELECT max(id) FROM users;` etc — sequences ride above ids.



## Notes
- Script is idempotent + transactional (rolls back entirely on any error).
- It casts SQLite bool ints → Postgres booleans (`::boolean`) and preserves all
  original IDs so FKs (accounts→users, txns→accounts) stay valid.

- Postgres already has rows with those IDs? `ON CONFLICT DO NOTHING` silently
  skips them — safe to re-run after partial failures.

- Admin seeding: the web app seeds `admin@westernprimebank.com` with your
  `ADMIN_PASSWORD` on first boot before you run this; we also migrated any
  existing admin row — either way admin works.