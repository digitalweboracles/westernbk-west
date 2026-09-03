#!/usr/bin/env python3
"""Fix all known bugs in the Western Prime Bank codebase.

Fixes (all verified against live rendering tests):
1. Six raw-Jinja leaks in banking templates:

   ``{{ expr }} if cond else '---' }}`` renders the literal
   string ``if cond else '---' }}`` on the page (the admin
   templates were fixed earlier, banking ones were missed).
   Corrected to ``{{ expr if cond else '---' }}``.
2. Tight ``or'---'`` spacing normalised to ``or '---'``.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BANKING_DIR = ROOT / "templates" / "banking"

RAW_LEAK = re.compile(
    r"\{\{\s*([^{}]+?)\s*\}\}\s*if\s+(.+?)\s*else\s*('[^']*')\s*\}\}"
)
TIGHT_OR = re.compile(r"or('[^']*')(\s*\}\})")


def fix_raw_leak(text: str) -> str:
    """Turn ``{{ expr }} if cond else '—' }}`` into ``{{ expr if cond else '—' }}``."""
    def repl(m: re.Match) -> str:
        expr = m.group(1).rstrip()
        cond = m.group(2)
        lit = m.group(3)
        return "{{ " + expr + " if " + cond + " else " + lit + " }}"
    return RAW_LEAK.sub(repl, text)


def fix_tight_or(text: str) -> str:
    return TIGHT_OR.sub(r"or \1\2", text)


changed = []
for path in sorted(BANKING_DIR.glob("*.html")):
    original = path.read_text(encoding="utf-8")
    new = fix_tight_or(fix_raw_leak(original))
    if new != original:
        path.write_text(new, encoding="utf-8")
        changed.append(path)
        print("fixed " + str(path.relative_to(ROOT)))

if not changed:
    print("No changes needed.")
else:
    print("Fixed " + str(len(changed)) + " file(s):", ", ".join(str(p.relative_to(ROOT)) for p in changed))

# sanity checks
problems = []
for p in (ROOT / "templates").rglob("*.html"):
    txt = p.read_text(encoding="utf-8")
    if "}} if " in txt:
        problems.append(str(p.relative_to(ROOT)) + ": raw '}} if' remains")
    if re.search(r"or'[^']*'", txt):
        problems.append(str(p.relative_to(ROOT)) + ": tight or'…' remains")
if problems:
    print("WARN leftover problems:")
    print("\n".join(problems))
else:
    print("OK: no raw '}} if' or tight 'or'' leaks remain in templates.")