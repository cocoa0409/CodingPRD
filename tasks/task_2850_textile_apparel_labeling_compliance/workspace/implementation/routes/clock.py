"""The administrative logical-clock endpoint (PRD 2.4)."""
from flask import Blueprint

from auth import require_roles
from envelope import ok
from store import db
from util import fmt_sec, parse_loose_instant
from validate import body, present

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("ComplianceAdmin")
    payload = body()
    if not present(payload, "current_utc"):
        from errors import fail
        fail("ERR_INVALID_REQUEST", "Field 'current_utc' is required.")
    instant = parse_loose_instant(payload["current_utc"])
    # Setting the clock mutates no stored row and triggers no recomputation.
    db.logical_clock = instant
    return ok({"current_utc": fmt_sec(instant)})
