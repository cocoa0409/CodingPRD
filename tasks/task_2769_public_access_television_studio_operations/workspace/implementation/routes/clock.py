"""The logical broadcast clock (PRD 2.5)."""

from flask import Blueprint

import db
import middleware
import response
import validation

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    # PRD 2.1: this operation accepts any of the seven roles and does not
    # require authentication headers at all.
    middleware.authorize_clock()
    body = validation.body()
    instant = validation.req_datetime(body, "to_iso8601")
    db.set_now(instant)
    from util import iso_s

    return response.object_response({"current_utc": iso_s(db.now())})
