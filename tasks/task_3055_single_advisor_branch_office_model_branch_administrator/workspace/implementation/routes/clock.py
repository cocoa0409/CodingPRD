"""Logical clock route (§2.7)."""
from flask import Blueprint

import db
from middleware import auth_context, require_role
from helpers import body_json, require_fields, parse_dt
from response import success_object
from routes.goodwill import expire_transfers

bp = Blueprint("clock", __name__)


@bp.route("/branch-office/_clock/set_current_utc", methods=["POST"])
def set_clock():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    body = body_json()
    require_fields(body, ["to_iso8601"])
    dt = parse_dt(body["to_iso8601"], "to_iso8601")
    db.clock.set(dt)
    # side effect: expire aged-out goodwill offers
    expire_transfers()
    return success_object({})
