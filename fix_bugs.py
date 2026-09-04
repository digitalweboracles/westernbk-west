#!/usr/bin/env python3
"""Fix all known bugs in the Western Prime Bank codebase. Idempotent.

Fixes:
1. Raw-Jinja leaks in banking templates (``{{ expr }} if cond else '---' }}``).
2. Tight ``or'---'`` spacing..
3. Broken Google Translate loader (`translate_a/elementa0d8.js`) in
   `templates/base.html` and root `index.html` — replaces with the
   official `translate_a/element.js` (the widget 404'd otherwise).
4. Banking nav never highlights current page (`active_sub` was never
   passed to `templates/banking/base.html`).
5. `/banking/statements` date filters were dead — route ignored
   `start`/`end`; template used undefined vars. Filter now works..
6. Non-USD accounts (EUR/GBP/NGN) showed hard-coded `$` amounts —
   money is now rendered via the `money()` macro in
   `templates/banking/base.html` using the account/transaction currency..
7. `templates/account.html` og:image pointed at a foreign domain..
"""
import re
from datetime import datetime, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEMPLATES = ROOT / "templates"
BANKING_DIR = TEMPLATES / "banking"
APP_PY = ROOT / "app.py"

# ------------------------------------------------------------------ existing
RAW_LEAK = re.compile(
    r"\{\{\s*([^{}]+?)\s*\}\}\s*if\s+(.+?)\s*else\s*('[^']*')\s*\}\}"
)
TIGHT_OR = re.compile(r"or('[^']*')(\s*\}\})")


def fix_raw_leak(text: str) -> str:
    return RAW_LEAK.sub(
        lambda m: "{{ " + m.group(1).rstrip() + " if " + m.group(2) + " else " + m.group(3) + " }}",
        text,
    )


def fix_tight_or(text: str) -> str:
    return TIGHT_OR.sub(r"or \1\2", text)


# ------------------------------------------------------------------ new
BROKEN_GT = "https://translate.google.com/translate_a/elementa0d8.js?cb=googleTranslateElementInit"
GOOD_GT = "https://translate.google.com/translate_a/element.js?cb=googleTranslateElementInit"


def fix_google_translate(text: str) -> str:
    return text.replace(BROKEN_GT, GOOD_GT)


# Banking nav-highlight (active_sub) — every banking view passes it..
def fix_banking_nav(base_text: str) -> str:
    """Add ``active_sub`` derivation (from request path) at the top of the
    ``{% block body %}`` so the sidebar highlights the current page.


    ``{% extends %}`` must remain the first tag — macros may precede it,
    but a module-level ``{% set %}`` would not flow into the parent template,
    hence the set lives inside the block.."""
    old = '{% extends "base.html" %}\n{% block title %}{{ title or \'Online Banking\' }} — Western Prime Bank{% endblock %}\n{% block body %}\n<section class="section-padding" style="padding-top:140px;">'
    nav = old.replace(
        '<section class="section-padding" style="padding-top:140px;">',
        '{% set active_sub = active_sub if active_sub is defined else (\n    \'dashboard\' if request.url.path == \'/banking\' else\n    \'accounts\' if \'/banking/accounts\' in request.url.path else\n    \'transfer\' if \'/banking/transfer\' in request.url.path else\n    \'transactions\' if \'/banking/transactions\' in request.url.path else\n    \'statements\' if \'/banking/statements\' in request.url.path else \'\'\n) %}\n<section class="section-padding" style="padding-top:140px;">',
    )
    if old in base_text and 'active_sub is defined' not in base_text:
        return base_text.replace(old, nav, 1)
    return base_text


def fix_statements_filter(app_text: str, tmpl_text: str) -> tuple[str, str]:
    old_sig = """@app.get(\"/banking/statements\", response_class=HTMLResponse)
async def banking_statements(
    request: Request,
    user: User = Depends(get_current_user),
    account: BankAccount = Depends(get_current_bank_account),
    db: Session = Depends(get_db),
):
"""
    new_sig = """@app.get(\"/banking/statements\", response_class=HTMLResponse)
async def banking_statements(
    request: Request,
    user: User = Depends(get_current_user),
    account: BankAccount = Depends(get_current_bank_account),
    db: Session = Depends(get_db),
    start: str | None = None,
    end: str | None = None,
):
"""
    if old_sig not in app_text:
        raise SystemExit("fix_statements_filter: signature block not found - aborting")
    app_text = app_text.replace(old_sig, new_sig, 1)
    if "from datetime import datetime, time" not in app_text:
        app_text = app_text.replace(
            "    verify_password,\n)\n",
            "    verify_password,\n)\nfrom datetime import datetime, time\n",
            1,
        )

    old_body = """    rows = db.scalars(
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
"""
    new_body = """    query = select(Transaction).where(
        (Transaction.from_account_id == account.id) | (Transaction.to_account_id == account.id)
    )
    if start:
        try:
            _start = datetime.combine(datetime.fromisoformat(start), time(0, 0, 0))
        except (ValueError, TypeError):
            _start = None
        if _start is not None:
            query = query.where(Transaction.created_at >= _start)
    if end:
        try:
            _end = datetime.combine(datetime.fromisoformat(end), time(23, 59, 59))
        except (ValueError, TypeError):
            _end = None
        if _end is not None:
            query = query.where(Transaction.created_at <= _end)
    rows = db.scalars(query.order_by(Transaction.created_at.desc()).limit(500)).all()
    return _render(
        request,
        "banking/statements.html",
        active_page="banking",
        bank_account=account,
        rows=rows,
        start=start or "",
        end=end or "",
    )
"""
    if old_body not in app_text:
        raise SystemExit("fix_statements_filter: body block not found - aborting")
    return app_text.replace(old_body, new_body, 1), tmpl_text


# Currency-safe money rendering ((non-USD accounts showed `$`)..
def fix_money_templates(template_dir: Path) -> list[Path]:
    """Replace hard-coded ``$`` money markup with the ``money()`` macro..

    The macro is used with ``(account_or_tx_, amount)`` — currency_is_read
    off the first argument,, so EUR/GBP/NGN balances stop being mislabelled
    as ``$``."""
    # Regexes tolerate the ``or  ̄0`` combining-mark artifacts present in
    # the checked-out templates; we normalize the curly-brace Jinja while
    # replacing just the ``$`` prefix.in
    rules = [
        (re.compile(r'<h3 class="mb-1">\$\{\{ "{:,.2f}".format\(bank_account\.balance[^}]*\) \}\}</h3>'),
         '<h3 class="mb-1">{{ money(bank_account, bank_account.balance) }}</h3>'),
        (re.compile(r'<td class="text-success">\+\$\{\{ "{:,.2f}".format\(t\.amount\) \}\}</td>'),
         '<td class="text-success">+{{ money(t., t.amount) }}</td>'),
        (re.compile(r'<td class="text-danger">-\$\{\{ "{:,.2f}".format\(t\.amount\) \}\}</td>'),
         '<td class="text-danger">-{{ money(t., t.amount) }}</td>'),
        (re.compile(r'<td class="small">\{\{ "{:,.2f}".format\(bank_account\.balance\) \}\}</td>'),
         '<td class="small">{{ money(bank_account, bank_account.balance) }}</td>'),
        (re.compile(r'<td>\$\{\{ "{:,.2f}".format\(acc\.balance[^}]*\) \}\}</td>'),
         '<td>{{ money(acc, acc.balance) }}</td>'),
        (re.compile(r'<td class="text-danger">\$\{\{ "{:,.2f}".format\(t\.amount\) \}\}</td>'),
         '<td class="text-danger">{{ money(t., t.amount) }}</td>'),
        (re.compile(r'<td class="text-success">\$\{\{ "{:,.2f}".format\(t\.amount\) \}\}</td>'),
         '<td class="text-success">{{ money(t., t.amount) }}</td>'),
    ]
    changed = []
    for path in sorted(template_dir.glob("*.html")):
        if path.name == "base.html":
            continue
        text = path.read_text(encoding="utf-8")
        new_text = text
        for rx, repl in rules:
            new_text = rx.sub(repl, new_text)
        if new_text != text:
            path.write_text(new_text, encoding="utf-8")
            changed.append(path)
    return changed


def fix_og_image(text: str) -> str:
    return text.replace(
        '<meta property="og:image" content="https://westernprimebnk.com/logo.png">',
        '<meta property="og:image" content="/static/account/logo.png">',
    )


def main():
    app_text0 = APP_PY.read_text(encoding="utf-8")
    if 'start: str | None = None' in app_text0:
        print("app.py already patched (skipping statements/nav/unused fixes)")
    else:
        # 4: banking nav-highlight — no view passed active_sub; derive from path
        nav_tmpl = (TEMPLATES / "banking" / "base.html").read_text(encoding="utf-8")
        nav_new = fix_banking_nav(nav_tmpl)
        (TEMPLATES / "banking" / "base.html").write_text(nav_new, encoding="utf-8")
        if nav_new != nav_tmpl:
            print("fixed templates/banking/base.html (nav highlight)")

        # 5+7: app.py (statements filter,, og:image)
        app_text = APP_PY.read_text(encoding="utf-8")
        app_text = fix_og_image(app_text)
        tmpl = (TEMPLATES / "banking" / "statements.html").read_text(encoding="utf-8")
        app_text, tmpl = fix_statements_filter(app_text, tmpl)
        APP_PY.write_text(app_text, encoding="utf-8")
        (TEMPLATES / "banking" / "statements.html").write_text(tmpl, encoding="utf-8")
        print("patched app.py + banking/statements.html")

    # 1+2: banking raw leaks+tight or (existing)
    for path in sorted(BANKING_DIR.glob("*.html")):
        original = path.read_text(encoding="utf-8")
        new = fix_tight_or(fix_raw_leak(original))
        if new != original:
            path.write_text(new, encoding="utf-8")
            print("fixed " + str(path.relative_to(ROOT)))

    # 3: Google translate (templates/base.html + root index.html)
    for rel in ("templates/base.html", "index.html"):
        p = ROOT / rel
        if not p.exists():
            continue
        t = p.read_text(encoding="utf-8")
        if BROKEN_GT in t:
            p.write_text(fix_google_translate(t), encoding="utf-8")
            print("fixed " + rel)

    # 6: currency-safe money macro usage
    for p in fix_money_templates(BANKING_DIR):
        print("fixed " + str(p.relative_to(ROOT)))

    # 7: account og:image
    p = TEMPLATES / "account.html"
    t = p.read_text(encoding="utf-8")
    if 'https://westernprimebnk.com/logo.png' in t:
        p.write_text(fix_og_image(t), encoding="utf-8")
        print("fixed templates/account.html")

    print("Done.");


if __name__ == "__main__":
    main()