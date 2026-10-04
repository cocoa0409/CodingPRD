"""Platform endpoint (UNPREFIXED): the logical clock (PRD §2.4)."""
from flask import Blueprint

from db import clock
from errors import err
from helpers import as_datetime, get_body, req_field
from middleware import require_roles
from response import success_object

bp = Blueprint("platform", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc(user_id, user_role):
    body = get_body()
    current_utc = req_field(body, "current_utc")
    as_datetime(current_utc, "current_utc")  # validates parseability -> 400
    clock.set(current_utc)
    return success_object({"current_utc": clock.raw}, status=200)
