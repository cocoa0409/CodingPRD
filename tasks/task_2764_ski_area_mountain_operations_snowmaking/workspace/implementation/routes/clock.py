"""Administrative logical-clock control (PRD 2.5)."""
from flask import Blueprint

import db
import response
import validate
from middleware import auth, ALL_ROLES
from util import iso

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@bp.route("/mountain-ops/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth(*ALL_ROLES)
    body = validate.body()
    moment = validate.get_dt(body, "current_utc")
    db.set_clock(moment)
    return response.object_response({"current_utc": iso(moment)}, 200)
