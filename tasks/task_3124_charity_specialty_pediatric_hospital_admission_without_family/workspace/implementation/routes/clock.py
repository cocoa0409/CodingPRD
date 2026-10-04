"""Logical clock endpoint (PRD §2.4)."""

from flask import Blueprint

import db
import services
from helpers import get_body, req_dt, iso_date
from middleware import require_auth
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(["NetworkAdmin"])
    body = get_body()
    new_clock = req_dt(body, "current_utc")
    db.CLOCK = new_clock
    services.clock_touch()
    return success_object({"current_utc": iso_date(new_clock)}, 200)
