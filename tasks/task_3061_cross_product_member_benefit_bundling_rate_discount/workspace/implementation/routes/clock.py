"""The logical clock capability — the one endpoint reachable unauthenticated."""

from flask import Blueprint, request

from db import DB
from errors import ERR_FORBIDDEN_ROLE, ERR_INVALID_REQUEST, ApiError
from middleware import as_timestamp, reject_unknown, raw_body
from response import ok_object
from services import recompute

BP = Blueprint("clock", __name__)

ALLOWED = {"current_utc"}


@BP.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    """Advance the logical clock; reachable without an authenticated identity.

    A caller that does present identity headers must still present the admitted
    role, so a wrong-role caller is refused rather than silently admitted.
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (user_id and str(user_id).strip()) or (role and str(role).strip()):
        if role != "PlatformAdmin":
            raise ApiError(ERR_FORBIDDEN_ROLE)

    payload = raw_body()
    reject_unknown(payload, ALLOWED)
    if "current_utc" not in payload:
        raise ApiError(ERR_INVALID_REQUEST)
    current_utc = as_timestamp(payload, "current_utc")
    previous = DB.clock_iso()
    if DB.set_clock(current_utc) is None:
        raise ApiError(ERR_INVALID_REQUEST)

    recompute.recompute_all_enrollments()
    recompute.refresh_all_members()
    return ok_object({"current_utc": DB.clock_iso(), "previous_utc": previous})