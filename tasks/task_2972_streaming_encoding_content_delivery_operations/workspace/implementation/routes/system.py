"""The logical clock control and the availability sweep (PRD 2.5)."""

from flask import Blueprint

from db import db, iso
from middleware import endpoint
from response import ok
from services.domain import run_sweep
from validation import S, parse_body

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_clock():
    payload = parse_body([S("current_utc", "instant")])
    db.clock = payload["current_utc"]
    # Setting the clock transitions nothing by itself.
    return ok({"current_utc": iso(db.clock)})


@bp.post("/availability-sweep")
@endpoint(["PlatformAdmin", "ContentOps"])
def availability_sweep():
    parse_body([])
    return ok(run_sweep())
