"""The facility's logical clock (test-driving capability, all roles)."""

from flask import Blueprint

from auth import ALL_ROLES, guard
from envelope import respond
from store import db, iso
from validation import v_datetime

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    ctx = guard(ALL_ROLES)
    _raw, moment = v_datetime(ctx.body, "to_iso8601")
    db.clock = moment
    return respond({"current_utc": iso(db.clock)})
