"""System endpoints: logical clock and expiry sweep (Admin only)."""
from flask import Blueprint, request

import db
from errors import ERR_VALIDATION, raise_err, not_found
from middleware import require_roles
from models import touch
from response import iso_z, success_object
from services import run_promotion, end_loan
from datetime import datetime

bp = Blueprint("system", __name__)


def _parse_iso(s):
    try:
        v = s.replace("Z", "+00:00")
        return datetime.fromisoformat(v)
    except Exception:
        raise_err(ERR_VALIDATION, "to_iso8601 must be a valid ISO 8601 timestamp")


@bp.post("/archive/_clock/set_current_utc")
def set_clock():
    require_roles("Admin")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise_err(ERR_VALIDATION, "to_iso8601 is required")
    dt = _parse_iso(to_iso)
    if dt.tzinfo is None:
        from datetime import timezone
        dt = dt.replace(tzinfo=timezone.utc)
    db.set_clock(dt)
    return success_object({"current_utc": iso_z(db.now())})


@bp.post("/archive/_sweeps/run")
def run_sweeps():
    require_roles("Admin")
    now = db.now()
    expired_loan_ids = []
    suspended_patron_ids = []
    offered_entry_ids = []

    # Expire ACTIVE loans whose due_at <= clock, by due_at ASC then created_at ASC.
    due_loans = [
        loan for loan in db.loans.values()
        if loan["status"] == "ACTIVE" and _ts(loan["due_at"]) <= now
    ]
    due_loans.sort(key=lambda l: (l["due_at"], l["created_at"]))
    for loan in due_loans:
        newly = end_loan(loan, "EXPIRED")
        expired_loan_ids.append(loan["id"])
        if newly:
            suspended_patron_ids.append(loan["patron_id"])

    # Expire OFFERED waitlist entries whose offer_expires_at <= clock,
    # by offer_expires_at ASC, re-promoting after each.
    due_offers = [
        e for e in db.waitlist_entries.values()
        if e["status"] == "OFFERED" and _ts(e["offer_expires_at"]) <= now
    ]
    due_offers.sort(key=lambda e: e["offer_expires_at"])
    for entry in due_offers:
        entry["status"] = "EXPIRED_OFFER"
        touch(entry)
        promoted = run_promotion(entry["work_id"])
        if promoted is not None:
            offered_entry_ids.append(promoted["id"])

    # Promotions triggered by loan expiry already ran inside end_loan; collect
    # all entries OFFERED during this sweep run for the report.
    # (end_loan promotions may have offered entries not tied to offer expiry.)
    # We track them by re-scanning: entries currently OFFERED whose offered_at
    # equals the current clock and which are not in expired flow.
    # Simpler and deterministic: collect OFFERED entries stamped at this clock.
    current = iso_z(now)
    for e in db.waitlist_entries.values():
        if (
            e["status"] == "OFFERED"
            and e["offered_at"] == current
            and e["id"] not in offered_entry_ids
        ):
            offered_entry_ids.append(e["id"])

    return success_object({
        "expired_loan_ids": expired_loan_ids,
        "expired_offer_ids": [e["id"] for e in due_offers],
        "suspended_patron_ids": suspended_patron_ids,
        "offered_entry_ids": offered_entry_ids,
    })


def _ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))
