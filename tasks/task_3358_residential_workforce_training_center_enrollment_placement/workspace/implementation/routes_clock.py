"""POST /_clock/set_current_utc -- test-driving logical clock (PRD 2.4)."""
from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, parse_clock_iso
from envelope import ok_object
from errors import ApiError, ERR_INVALID_REQUEST
from helpers import get_body, check_unknown, as_str

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    authenticate_role = authenticate()
    require_role(authenticate_role[1], {"OperatorAdmin"})
    body = get_body()
    check_unknown(body, {"to_iso8601"})
    to_iso8601 = as_str(body, "to_iso8601", required=True)
    try:
        parse_clock_iso(to_iso8601)
    except (ValueError, TypeError):
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            ERR_INVALID_REQUEST[1],
            "to_iso8601 must be a valid ISO 8601 instant",
        )
    STORE.set_clock(to_iso8601)
    return ok_object({"current_utc": STORE.clock_echo}, status=200)
