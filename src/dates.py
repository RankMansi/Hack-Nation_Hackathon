"""A date is kept when the source writes it. Otherwise it is computed only from a timing rule the same document states, or from the California rule for a chaptered non-urgency bill."""

import re
from datetime import date

MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
ORDINALS = {w: i for i, w in enumerate(["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth", "eleventh", "twelfth"], 1)}
APPROVED = re.compile(r"approved\s+(?:by\s+governor\s+)?([a-z]+)\s+(\d{1,2}),\s+(\d{4})", re.I)
CLAUSE = re.compile(r"this act shall take effect\s+(?:on\s+)?(?:the\s+)?(?:(first) day of the (\w+) month next following|"
                    r"(\d+)(?:st|nd|rd|th)? day (?:after|following)|immediately)", re.I)


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def dates_in(text: str) -> set[str]:
    t = re.sub(r"\s+", " ", text)
    found = set()
    for mon, d, y in re.findall(r"\b([A-Za-z]{3,9})\.? (\d{1,2}),? (\d{4})\b", t):
        m = next((i for i, n in enumerate(MONTHS, 1) if n.startswith(mon.lower())), None)
        if m:
            found.add(_iso(int(y), m, int(d)))
    for m, d, y in re.findall(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b", t):
        found.add(_iso(int(y) + (2000 if len(y) == 2 else 0), int(m), int(d)))
    return found - {None}


def act_effective(text: str) -> str | None:
    """The document's own 'this act shall take effect' clause applied to its single approval date."""
    t = re.sub(r"\s+", " ", text)
    clauses = list(CLAUSE.finditer(t))
    approvals = {(mon.lower(), int(d), int(y)) for mon, d, y in APPROVED.findall(t) if mon.lower() in MONTHS}
    if len(clauses) != 1 or len(approvals) != 1:
        return None
    clause = clauses[0]
    mon, d, y = next(iter(approvals))
    approved = date(y, MONTHS.index(mon) + 1, d)
    if clause.group(2):
        n = ORDINALS.get(clause.group(2).lower())
        if not n:
            return None
        k = approved.month - 1 + n
        return date(approved.year + k // 12, k % 12 + 1, 1).isoformat()
    if clause.group(3):
        from datetime import timedelta
        return (approved + timedelta(days=int(clause.group(3)))).isoformat()
    return approved.isoformat()


def ca_chapter_effective(text: str) -> str | None:
    """A California bill that shows a chapter number and one approval date, and no urgency or effective-date clause, takes effect January 1 of the next year."""
    if not re.search(r"\bCHAPTER\s+\d+\b", text):
        return None
    if re.search(r"urgency statute|take effect immediately", text, re.I):
        return None
    if re.search(r"this (act|section) shall (take effect|become operative)", text, re.I):
        return None
    t = re.sub(r"\s+", " ", text)
    approvals = {(mon.lower(), int(d), int(y)) for mon, d, y in APPROVED.findall(t) if mon.lower() in MONTHS}
    if len(approvals) != 1:
        return None
    return f"{next(iter(approvals))[2] + 1}-01-01"


def approval_dates(text: str) -> set[str]:
    t = re.sub(r"\s+", " ", text)
    return {f"{int(y)}-{MONTHS.index(mon.lower()) + 1:02d}-{int(d):02d}" for mon, d, y in APPROVED.findall(t) if mon.lower() in MONTHS}


def resolve_effective(claimed: str | None, text: str) -> tuple[str | None, str]:
    """An approval date is not an effective date. A date written elsewhere in the source is kept."""
    if claimed and claimed in dates_in(text) and claimed not in approval_dates(text):
        return claimed, "stated in the source"
    derived = act_effective(text)
    if derived:
        return derived, "computed from the act's effective-date clause and its approval date"
    chapter = ca_chapter_effective(text)
    if chapter:
        return chapter, "California chaptered bill with no urgency clause: January 1 of the year after approval"
    if claimed and claimed in dates_in(text):
        return claimed, "stated in the source"
    if claimed:
        return None, "date is not written in the source and no timing rule in the source produces it"
    return None, "none"
