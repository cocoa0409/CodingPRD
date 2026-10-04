"""Logical clock endpoint (PRD §2.4) — outside the business surface, root-level."""
from flask import Blueprint

from constants import ROLE_TREASURY_SUPERVISOR
from db import clock_now, set_clock
from middleware import authenticate, get_body, require_roles, spec_field, validate_body
from response import ok
from services.cascades import settlement_sweep
from util import format_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    """Set the logical clock and run the settlement sweep over EXECUTED
    payments whose parent file's settlement date has arrived."""
    ctx = authenticate()
    require_roles(ctx, ROLE_TREASURY_SUPERVISOR)
    data = validate_body(get_body(), [
        spec_field("current_utc", "dt", required=True),
    ])
    set_clock(data["current_utc"])
    settlement_sweep()
    return ok({"current_utc": format_dt(clock_now())})
