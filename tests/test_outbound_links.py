"""Attribution links must stay dofollow — two written agreements require it in writing.

Coinalyze's permission (register §3.27, `DS-2026-019`) is conditioned on it:
"the link(s) to Coinalyze website must be a dofollow link". TradingView's
Advanced Charts agreement §3.2 says the same for its attribution and prices a
breach at USD 50,000 (§7.5).

`rel="noopener noreferrer"` is dofollow — `noreferrer` only suppresses the
Referer header. The three attributes that would break the condition are
`nofollow`, `ugc` and `sponsored`, so this looks for those and nothing else.
"""

from __future__ import annotations

import re
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
FORBIDDEN = {"nofollow", "ugc", "sponsored"}

# Both ways this codebase sets rel: an HTML attribute, and JavaScript that
# either assigns the property or calls setAttribute.
REL_SOURCES = (
    re.compile(r"""\brel\s*=\s*["']([^"']*)["']"""),
    re.compile(r"""setAttribute\(\s*["']rel["']\s*,\s*["']([^"']*)["']"""),
)


def _files() -> list[Path]:
    return [
        path
        for pattern in ("static/*.html", "static/*.js", "*.py")
        for path in sorted(APP.glob(pattern))
    ]


def test_no_outbound_link_is_marked_nofollow_ugc_or_sponsored():
    offenders: list[str] = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for pattern in REL_SOURCES:
            for match in pattern.finditer(text):
                tokens = {token.casefold() for token in match.group(1).split()}
                if tokens & FORBIDDEN:
                    line = text[: match.start()].count("\n") + 1
                    offenders.append(f"{path.name}:{line} rel=\"{match.group(1)}\"")
    assert not offenders, (
        "these links would breach the dofollow conditions in register §3.27 and "
        "TradingView §3.2: " + "; ".join(offenders)
    )


def test_the_scanner_is_actually_reading_the_link_markup():
    """A positive control: if the files stopped being scanned the test above would pass empty."""
    seen = 0
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for pattern in REL_SOURCES:
            seen += sum(1 for match in pattern.finditer(text) if "noopener" in match.group(1))
    assert seen > 10, f"expected the site's outbound links to be scanned, found {seen}"
