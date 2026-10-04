"""Shared entity helpers: common fields, lookups, version bumps."""

import clock
from store import all_rows, get, new_id, put


def new_common():
    now = clock.get_current()
    return {"id": new_id(), "created_at": now, "updated_at": now, "version": 1}


def bump(row):
    """Every mutation of a versioned resource increments version and refreshes updated_at."""
    row["version"] += 1
    row["updated_at"] = clock.get_current()


def latest_verification(application_id, completed_only=False):
    rows = [v for v in all_rows("verifications") if v["application_id"] == application_id]
    if completed_only:
        rows = [v for v in rows if v["status"] == "COMPLETED"]
    return rows[-1] if rows else None


def latest_pass_review(application_id):
    rows = [r for r in all_rows("credit_reviews")
            if r["application_id"] == application_id and r["verdict"] == "PASS"]
    return rows[-1] if rows else None


def app_grants(application_id):
    return [g for g in all_rows("grants") if g["application_id"] == application_id]


def loan_tranches(loan_id):
    rows = [t for t in all_rows("tranches") if t["loan_id"] == loan_id]
    return sorted(rows, key=lambda t: t["stage_number"])


def loan_milestones(loan_id):
    return [m for m in all_rows("milestones") if m["loan_id"] == loan_id]


def loan_settlements(loan_id):
    return [s for s in all_rows("settlements") if s["loan_id"] == loan_id]


def loan_actions(loan_id):
    return [a for a in all_rows("servicing_actions") if a["loan_id"] == loan_id]


def loan_payments(loan_id):
    return [p for p in all_rows("payments") if p["loan_id"] == loan_id]


def loan_receivables(loan_id):
    return [r for r in all_rows("receivables") if r["loan_id"] == loan_id]


def open_receivable(loan_id):
    """At most one receivable per loan in {OPEN, PARTIALLY_PAID}."""
    for r in loan_receivables(loan_id):
        if r["status"] in ("OPEN", "PARTIALLY_PAID"):
            return r
    return None


def verified_milestone_total(loan_id):
    return sum(m["verified_cost_cents"] for m in loan_milestones(loan_id)
               if m["status"] == "VERIFIED")


def get_or_404(kind, rid):
    row = get(kind, rid)
    if row is None:
        from errors import raise_err
        raise_err("ERR_NOT_FOUND", "resource not found: %s" % rid)
    return row
