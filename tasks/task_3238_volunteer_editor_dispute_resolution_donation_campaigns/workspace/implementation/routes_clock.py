"""Clock control endpoint (PlatformAdmin only)."""
from flask import Blueprint

from db import db
from helpers import get_body, require_fields, parse_datetime_field, iso
from middleware import require_roles
from response import success_object

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("PlatformAdmin")
    body = get_body()
    require_fields(body, ["to_iso8601"])
    dt = parse_datetime_field(body["to_iso8601"], "to_iso8601")
    db.set_clock(iso(dt))
    return success_object({"current_utc": db.now_iso()})
