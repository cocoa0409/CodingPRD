"""Test-driving logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

from db import CLOCK
from middleware import auth
from response import ok
from util import as_iso_dt, body, parse_dt, required

bp = Blueprint("clock", __name__, url_prefix="/api")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth(["CommitteeAdmin"])
    data = body()
    to_iso8601 = as_iso_dt(required(data, "to_iso8601"), "to_iso8601")
    CLOCK["raw"] = to_iso8601
    CLOCK["dt"] = parse_dt(to_iso8601)
    return ok({"current_utc": CLOCK["raw"]})
