"""Test-driving logical clock endpoint (PRD section 2.4)."""
from flask import Blueprint

import clock
from auth import identity, require_roles
from response import ok_object
from validation import KIND_DATETIME, get_body, validate

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    body = get_body()
    values = validate(body, [("to_iso8601", KIND_DATETIME, True, None, None)])
    role, _ = identity()
    require_roles(role, ("ProgramAdmin",))
    current = clock.set_current(values["to_iso8601"])
    return ok_object({"current_utc": clock.fmt(current)})
