"""Row -> payload projection."""

from calc import days_remaining
from store import public


def view(row):
    out = public(row)
    if row.get("_kind") == "decision_review":
        # PRD 3.9: days_remaining is re-derived on every read.
        out["days_remaining"] = days_remaining(row)
    return out


def view_all(rows):
    return [view(r) for r in rows]
