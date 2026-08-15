"""Logical clock endpoint (PRD 2.6): strictly forward, then sweeps."""
from flask import Blueprint

from middleware import authorized
from response import success_object
from services.sweeps import run_sweeps
from util import CLOCK, fmt_datetime
from validate import get_body, no_unknown_fields, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    body = get_body()
    no_unknown_fields(body, {"to_iso8601"})
    to_iso8601 = req_datetime(body, "to_iso8601")
    authorized(["CommissionStaff"])
    new_dt = CLOCK.set(to_iso8601)
    run_sweeps(new_dt)
    return success_object({"current_utc": fmt_datetime(new_dt)})
