"""The logical show clock (PRD §2.4) — pure test-driving capability."""
from flask import Blueprint

import db
import response
from middleware import ANY_ROLE, require_roles
from validation import json_body

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles(ANY_ROLE)
    body = json_body()
    to_iso8601 = body.datetime_str("to_iso8601")
    # Repositioning the clock mutates no entity and fires no cascade.
    db.clock.set(to_iso8601)
    return response.ok({"current_utc": db.clock.iso})
