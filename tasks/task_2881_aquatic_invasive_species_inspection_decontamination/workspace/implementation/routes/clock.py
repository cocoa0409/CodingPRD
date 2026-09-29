"""The logical program clock (PRD 2.5)."""

from flask import Blueprint

from envelope import ok
from store import db, fmt_iso
from validate import read_body, req_dt, require_auth

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_auth(("ProgramAdmin",))
    body = read_body()
    instant = req_dt(body, "to_iso8601")
    db.clock = instant
    return ok({"current_utc": fmt_iso(instant)})
