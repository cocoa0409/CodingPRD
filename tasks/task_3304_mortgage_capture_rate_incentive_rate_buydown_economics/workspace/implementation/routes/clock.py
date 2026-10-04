"""The logical clock test-driving endpoint (PRD section 2.13)."""

from flask import Blueprint

from db import db, parse_iso
from errors import fail
from response import ok
from checks import authenticate, body, require_fields

bp = Blueprint("clock", __name__)


@bp.post("/housing/_clock/set_current_utc")
def set_current_utc():
    # Priority 1 is waived for this endpoint only when credentials are absent.
    from flask import request

    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is not None or user_id is not None:
        authenticate(["PlatformAdmin", "ComplianceOfficer"])

    payload = body()
    require_fields(payload, ["to_iso8601"])
    target = payload["to_iso8601"]
    if not isinstance(target, str) or parse_iso(target) is None:
        fail("ERR_INVALID_ENUM_VALUE", "to_iso8601 must be an ISO 8601 instant")

    db.clock = target
    from services import lock_flows

    lock_flows.apply_clock_transitions()
    return ok({}, 200)