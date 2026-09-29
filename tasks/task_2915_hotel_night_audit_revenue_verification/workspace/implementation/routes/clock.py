"""The logical clock (PRD 2.5)."""
from flask import Blueprint

import db
import response
import shapes
from middleware import ALL_ROLES, authenticate

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate(ALL_ROLES)
    body = shapes.parse([shapes.Field("current_utc", "instant", required=True)])
    db.store.clock = body["current_utc"]
    return response.ok({})
