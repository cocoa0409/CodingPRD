"""Logical clock endpoint."""
from flask import Blueprint

import domain as D
from auth import endpoint
from envelope import single
from services import cascades
from store import db, flush, iso_instant, parse_instant
from validate import Field, parse_body, v_instant

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint(["ProgramAdmin"])
def set_current_utc():
    payload = parse_body([Field("current_utc", v_instant())])
    db.clock = parse_instant(payload["current_utc"])
    cascades.clock_cascade()
    flush()
    return single({"current_utc": iso_instant(db.clock)})
