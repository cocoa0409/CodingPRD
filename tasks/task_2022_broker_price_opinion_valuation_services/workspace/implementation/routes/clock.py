"""Logical clock test-driving endpoint (PRD 2.10)."""

from flask import Blueprint

import db
from middleware import allowed
from response import success_object
from validation import body, req_iso

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@allowed("PlatformAdmin")
def set_current_utc(user_id, role):
    b = body()
    target = req_iso(b, "to_iso8601")
    db.set_logical_now(target)
    return success_object({})
