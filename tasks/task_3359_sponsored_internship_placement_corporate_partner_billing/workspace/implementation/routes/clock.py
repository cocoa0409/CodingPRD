"""The logical clock (PRD 2.6)."""

from flask import Blueprint

import middleware
import response
import timeutil
import validators
from services import partner_svc

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    middleware.require(("ProgramStaff",))
    data = validators.body()
    to_iso8601 = validators.as_dt(data, "to_iso8601")

    timeutil.set_clock(to_iso8601)
    partner_svc.sweep_invoices()
    return response.success({"current_utc": timeutil.iso(timeutil.now())})
