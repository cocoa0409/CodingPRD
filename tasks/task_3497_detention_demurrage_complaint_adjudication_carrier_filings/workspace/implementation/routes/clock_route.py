"""Logical-clock test-driving endpoint — mounted OUTSIDE the /fmc business
surface (PRD §2.4)."""
from flask import Blueprint

from auth import require_roles
from clock import CLOCK
from envelope import ok_object
from errors import fail, ERR_INVALID_REQUEST
from util import body, req_str

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("CommissionAdmin")
    b = body()
    iso = req_str(b, "to_iso8601")
    try:
        CLOCK.set(iso)
    except (ValueError, TypeError):
        fail(ERR_INVALID_REQUEST,
             "to_iso8601 is not a valid ISO-8601 instant")
    return ok_object({"current_utc": CLOCK.render()})
