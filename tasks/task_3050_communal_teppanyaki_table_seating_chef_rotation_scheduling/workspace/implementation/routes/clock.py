"""POST /_clock/set_current_utc — the test-driving logical clock."""
from flask import Blueprint

import constants as C
import db
from helpers import as_datetime, payload, q
from middleware import guard
from response import ok

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    body = payload()
    guard(["PlatformAdmin"])
    instant = as_datetime(body, "current_utc")
    db.set_clock(instant)
    return ok({}, 200)