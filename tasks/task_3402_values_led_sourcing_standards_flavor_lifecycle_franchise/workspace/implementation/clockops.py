"""The logical clock: advance endpoint and time-driven evaluations (PRD 2.5).

Advancing the clock triggers certification expiry (with claim retraction),
commitment lapse, and production-slot completion. The same evaluations are
applied lazily on every request via the app.before_request hook.
"""
from datetime import date

from flask import Blueprint

import cascades
from auth import authenticate, authorize
from db import LOGICAL_CLOCK, STORE, touch
from envelope import ok
from errors import fail
from timeutil import fmt_dt, parse_iso
from validate import get_body, req_dt

bp = Blueprint("clockops", __name__)


def sweep():
    """Apply all time-driven state evaluations against the logical clock."""
    now = LOGICAL_CLOCK["now"]
    today = now.date()
    expired = []
    for c in STORE["certifications"].values():
        if (c["status"] in ("PENDING", "VERIFIED")
                and parse_iso(c["valid_until"]) < now):
            c["status"] = "EXPIRED"
            touch(c)
            expired.append(c["id"])
    if expired:
        cascades.retract_claims_citing(expired)
    for cm in STORE["commitments"].values():
        if cm["status"] == "ACTIVE" and parse_iso(cm["effective_to"]) < now:
            cm["status"] = "LAPSED"
            touch(cm)
    for s in STORE["slots"].values():
        if (s["status"] == "CONFIRMED"
                and date.fromisoformat(s["production_date"]) < today):
            s["status"] = "COMPLETED"
            touch(s)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = authenticate()
    authorize(role, ("ParentOpsController",))
    body = get_body()
    target = req_dt(body, "to_iso8601")
    if target < LOGICAL_CLOCK["now"]:
        fail("ERR_CLOCK_REGRESSION",
             "The logical clock may not move backwards")
    LOGICAL_CLOCK["now"] = target
    sweep()
    return ok({"current_utc": fmt_dt(LOGICAL_CLOCK["now"])})
