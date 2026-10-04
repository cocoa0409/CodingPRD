"""Logical clock endpoint: POST /api/_clock/set_current_utc."""
from flask import Blueprint

import clock
from errors import raise_err, ERR_INVALID_REQUEST
from helpers import get_body, require_fields, reject_unknown_fields
from middleware import require_roles
from response import success_object
from services import cascades

bp = Blueprint("clock", __name__)

FIELDS = {"to_iso8601"}


@bp.route("/api/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles({"PlatformAdmin"})
    body = get_body()
    reject_unknown_fields(body, FIELDS)
    require_fields(body, ["to_iso8601"])
    try:
        dt = clock.parse_iso(body["to_iso8601"])
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 malformed")
    clock.set_now(dt)
    invitations_expired, researchers_reinstated = cascades.sweep(dt)
    return success_object(
        {
            "now": clock.iso(dt),
            "invitations_expired": invitations_expired,
            "researchers_reinstated": researchers_reinstated,
        }
    )
