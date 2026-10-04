"""Test-driving clock endpoint (SCAFFOLD §1.5, PRD §3.10)."""

from flask import Blueprint

import db
from db import DB
from errors import ApiError
from http_util import body_json, required, require_role
from response import success_object
from routes._common import list_response  # noqa: F401  (blueprint import parity)

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_role("PlatformAdmin")
    data = body_json()
    value = required(data, "current_utc", "str")
    try:
        normalized = db.normalize_iso(value)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST")
    db.set_clock(normalized)
    return success_object({}, 200)