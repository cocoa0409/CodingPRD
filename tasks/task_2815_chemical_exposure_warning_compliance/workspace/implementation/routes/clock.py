"""The logical clock (PRD 2.4).  Setting it modifies no stored entity."""
from flask import Blueprint

import db
import response
import validate
from middleware import guard
from util import fmt_dt

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@guard("RegistryAdmin")
def set_clock(who):
    body = validate.body_json()
    instant = validate.v_dt(body, "current_utc", required=True)
    validate.v_writable(body, ("current_utc",))
    current, previous = db.set_clock(instant)
    return response.ok({"current_utc": fmt_dt(current), "previous_utc": fmt_dt(previous)})
