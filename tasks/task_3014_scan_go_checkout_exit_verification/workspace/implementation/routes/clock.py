"""Test-driving logical clock endpoint."""

from flask import Blueprint

from db import STORE
from logic import parse_iso
from middleware import get_context, get_body, require_role, require_fields
from response import success

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    _, role = get_context()
    require_role(role, ["PlatformAdmin"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    STORE.clock = parse_iso(body["to_iso8601"], "to_iso8601")
    return success({})
