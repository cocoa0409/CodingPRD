"""Logical clock endpoint."""

from flask import Blueprint, request

from db import DB
from common import parse_dt
from middleware import require_role
from response import success_object
import services

bp = Blueprint("clock", __name__)


@bp.post("/venue/_clock/set_current_utc")
def set_clock():
    require_role("ProductionDirector")
    body = request.get_json(silent=True) or {}
    DB.clock = parse_dt(body.get("to_iso8601"))
    services.sweep_clock()
    return success_object({}, 200)
