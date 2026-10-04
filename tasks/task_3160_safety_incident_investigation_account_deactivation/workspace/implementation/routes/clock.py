"""The logical clock. The startup default is 2026-09-01T00:00:00Z."""

from flask import Blueprint, request

from db import STORE, iso, parse_iso
from errors import ApiError
from middleware import route
from response import success

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@route("PlatformAdmin")
def set_current_utc(ident):
    payload = request.get_json(silent=True) or {}
    supplied = payload.get("current_utc")
    instant = parse_iso(supplied)
    if instant is None:
        raise ApiError("ERR_INVALID_STATE", "current_utc must be an ISO 8601 instant.", 409)
    STORE.clock = instant
    return success({"current_utc": iso(STORE.clock)})