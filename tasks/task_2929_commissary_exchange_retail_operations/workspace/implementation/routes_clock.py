"""The logical clock (PRD 2.5)."""

from flask import Blueprint

import validation as V
from db import db
from envelope import iso_millis, object_response

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    V.authenticate(("SystemOperator",))
    body = V.raw_body()
    target = V.want_instant(body, "to_iso8601", required=True)
    # Repositioning the clock mutates no entity and runs no sweep.
    db.logical_clock = target
    return object_response({"current_utc": iso_millis(db.logical_clock)}, 200)
