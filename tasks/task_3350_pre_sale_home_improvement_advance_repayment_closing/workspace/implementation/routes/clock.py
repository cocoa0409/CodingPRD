"""Logical clock endpoint (PRD 2.6). PlatformAdmin only."""
from flask import Blueprint

from auth import require_roles
from db import fmt_dt, store
from envelope import success_obj
from errors import ApiError, ERR_INVALID_REQUEST
from validate import body_json, parse_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    body = body_json(required=True)
    if "current_utc" not in body:
        raise ApiError(ERR_INVALID_REQUEST, "current_utc is required", 400)
    dt = parse_dt(body["current_utc"], "current_utc")
    store.clock = dt
    return success_obj({"current_utc": fmt_dt(dt)}, 200)
