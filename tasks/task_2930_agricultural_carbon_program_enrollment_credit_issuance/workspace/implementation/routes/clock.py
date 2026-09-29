"""The logical programme clock (section 2.4).

This is the one endpoint that requires no authentication headers, so that a
harness can position the clock before any actor exists.
"""

from flask import Blueprint

import db
import response as resp
import validators as v

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    body = v.json_body()
    raw, dt = v.v_instant(body, "current_utc")
    db.set_clock(raw, dt)
    return resp.object_response(
        {"current_utc": raw, "current_crop_year": db.current_crop_year()}
    )
