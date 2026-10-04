"""POST /_clock/set_current_utc — the administrative logical-clock capability
(lives outside the /api prefix). PlatformAdmin only."""

from flask import Blueprint

from auth import authenticate, require_role
from db import STORE
from util import success_object
from validate import get_body, validate_payload

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    _uid, role = authenticate()
    require_role(role, {"PlatformAdmin"})
    values, raws = validate_payload(
        get_body(),
        {"to_iso8601": {"kind": "datetime", "required": True}},
    )
    STORE.clock = values["to_iso8601"]
    # Echo the exact string the client supplied.
    return success_object({"current_utc": raws["to_iso8601"]})
