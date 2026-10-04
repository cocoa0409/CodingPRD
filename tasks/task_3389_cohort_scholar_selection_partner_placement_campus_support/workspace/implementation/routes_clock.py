"""POST /api/_clock/set_current_utc — advance the logical clock (PRD 2.4)."""

from constants import BOOT_ISO
from core import fmt_dt, parse_iso, store
from errors import ApiError, ERR_INVALID_REQUEST
from flask import Blueprint
from response import ok
from services import run_offer_expiry_sweep
from validate import auth, body, req_str, require_role

bp_clock = Blueprint("clock", __name__)


@bp_clock.post("/api/_clock/set_current_utc")
def set_current_utc():
    _uid, role = auth()
    data = body()
    raw = req_str(data, "to_iso8601")
    try:
        target = parse_iso(raw)
    except ValueError:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "to_iso8601 is not a parseable ISO8601 datetime"
        )
    if target < parse_iso(BOOT_ISO):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "to_iso8601 must be at or after 2026-09-01T00:00:00Z",
        )
    require_role(role, ["ProgramAdmin"])
    store.clock = target
    run_offer_expiry_sweep()
    return ok({"current_utc": fmt_dt(store.clock)}, 200)
