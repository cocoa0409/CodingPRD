"""Platform-level logical clock endpoint (mounted OUTSIDE /evaluation)."""
from flask import Blueprint

from clock import parse_iso, set_now
from services import evaluate_irb_expiry
from util import ok_obj
from validation import (ROLE_PLATFORM_ADMIN, authenticate, authorize,
                        check_schema, get_json_body)

bp = Blueprint("clock_route", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _uid, role = authenticate()
    authorize(role, [ROLE_PLATFORM_ADMIN])
    body = get_json_body()
    check_schema(body, {"to_iso8601": ("dt", True)})
    set_now(parse_iso(body["to_iso8601"]))
    evaluate_irb_expiry()
    return ok_obj({"current_utc": body["to_iso8601"]})
