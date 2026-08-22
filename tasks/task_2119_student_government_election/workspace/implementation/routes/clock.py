"""The logical election clock (PRD 2.4).

Nothing in this system reads the host wall clock.  Before the first call the
clock reads exactly 2026-08-01T00:00:00Z.  Moving it mutates no entity and
fires no scheduled transition implicitly.
"""
from flask import Blueprint

import auth
import constants
import db
import response
import validation

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    auth.require(constants.ELECTION_COMMISSIONER)
    body = validation.get_body()
    target = validation.req_dt(body, "to_iso8601")
    db.store.set_clock(target)
    return response.object_response({"current_utc": db.iso_millis(db.store.now())})
