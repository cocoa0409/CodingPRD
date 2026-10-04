"""The logical clock capability."""

from flask import Blueprint

from core import constants as C
from core.auth import require_role
from core.clock import set_current
from core.errors import ERR_INVALID_REQUEST, ApiError
from core.response import send
from core import validate as V
from routes.common import body

bp = Blueprint("clock", __name__)

CLOCK_FIELDS = ("current_utc",)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    payload = body(CLOCK_FIELDS)
    current_utc = V.string(payload, "current_utc", required=True)
    require_role([C.ROLE_PLATFORM_ADMIN])
    parsed = set_current(current_utc)
    if parsed is None:
        raise ApiError(ERR_INVALID_REQUEST, "current_utc must be an ISO-8601 UTC instant.")
    return send({"current_utc": current_utc})
