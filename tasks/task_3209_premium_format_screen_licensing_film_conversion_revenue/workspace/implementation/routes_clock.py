"""Logical clock endpoints."""
from __future__ import annotations

from flask import Blueprint

from db import db
from errors import ERR_INVALID_REQUEST, bad_request
from util import require_auth, get_body, parse_iso_datetime, iso_format, success_object
from domain import fire_clock_transitions

bp = Blueprint("clock", __name__)


@bp.post("/v1/_clock/set_current_utc")
def set_clock():
    require_auth()
    body = get_body()
    dt = parse_iso_datetime(body.get("to_iso8601"), "to_iso8601")
    db.logical_clock = dt
    fire_clock_transitions()
    return success_object({"current_utc": iso_format(db.logical_clock)})


@bp.get("/v1/_clock/current_utc")
def get_clock():
    require_auth()
    return success_object({"current_utc": iso_format(db.logical_clock)})
