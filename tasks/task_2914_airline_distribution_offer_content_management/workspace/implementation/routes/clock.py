"""The logical clock (PRD 2.5)."""
from flask import Blueprint

import validators as v
from auth import ROLE_PLATFORM_ADMIN, authenticate
from envelope import respond_object
from store import db, iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authenticate([ROLE_PLATFORM_ADMIN])
    body = v.json_body()
    current_utc = v.req_instant(body, "current_utc")
    # Moving the clock never rewrites a stored instant.
    db.clock = current_utc
    return respond_object({"current_utc": iso(db.clock)})
