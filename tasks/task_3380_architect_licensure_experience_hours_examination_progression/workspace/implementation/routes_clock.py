"""Logical clock and ops-run expiry sweep endpoints."""
from flask import Blueprint

from auth import get_body, require_roles
from dates import parse_date
from envelope import ok
from errors import fail
from services import all_divisions_passed, recompute_eligibility
from store import (db, format_instant, get_clock_iso, now_iso, parse_instant,
                   set_clock_iso, today, touch)

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("NcarbAdministrator")
    body = get_body()
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str) or not to_iso.strip():
        fail("ERR_INVALID_REQUEST", "to_iso8601 is required")
    try:
        dt = parse_instant(to_iso)
    except (ValueError, TypeError):
        fail("ERR_INVALID_REQUEST", "to_iso8601 must be a valid ISO 8601 instant")
    # Mutates no entity; only the logical clock advances.
    set_clock_iso(format_instant(dt))
    return ok({"current_utc": get_clock_iso()})


@bp.post("/_maintenance/run_expiry_sweep")
def run_expiry_sweep():
    require_roles("NcarbAdministrator")
    current = today()
    expired_divisions = 0
    touched_candidates = set()
    for row in list(db["divisions"].values()):
        if row["status"] != "PASSED":
            continue
        # Expiry is inclusive at the boundary day: current date >= expires_at.
        if parse_date(row["expires_at"]) <= current:
            row["status"] = "EXPIRED"
            touch(row)
            expired_divisions += 1
            touched_candidates.add(row["candidate_id"])
    for candidate_id in touched_candidates:
        cand = db["candidates"].get(candidate_id)
        if cand is None:
            continue
        changed = False
        # A lapse that leaves fewer than six valid passes drops ALL_PASSED.
        if cand["exam_status"] == "ALL_PASSED":
            if not all_divisions_passed(candidate_id):
                cand["exam_status"] = "AUTHORIZED"
                changed = True
        if recompute_eligibility(cand):
            changed = True
        if changed:
            touch(cand)
    lapsed_certificates = 0
    for cert in list(db["certificates"].values()):
        # Lapse is unconditional at period end regardless of CE totals.
        if cert["status"] == "ACTIVE" and parse_date(cert["period_end"]) <= current:
            cert["status"] = "LAPSED"
            touch(cert)
            lapsed_certificates += 1
    return ok({"expired_divisions": expired_divisions,
               "lapsed_certificates": lapsed_certificates})
