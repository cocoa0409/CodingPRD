"""The administrative logical-clock setter (PRD 2.5)."""

from flask import Blueprint

from auth import OPERATOR_ROLES, authorize
from envelope import ok
from schema import body, f_dt, validate
from store import db, norm_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(*OPERATOR_ROLES)
    data = validate(body(), [f_dt("to_iso8601")])
    db.logical_clock = norm_dt(data["to_iso8601"])
    return ok({"current_utc": db.logical_clock})
