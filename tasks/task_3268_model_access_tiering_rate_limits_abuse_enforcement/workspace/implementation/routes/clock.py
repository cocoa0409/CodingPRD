"""Logical clock endpoint."""
from __future__ import annotations

import db
from middleware import require_roles
from response import success
from services.domain import run_clock_transitions
from services.util import body, require_datetime

from flask import Blueprint

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    data = body()
    dt = require_datetime(data, "current_utc")
    with db.lock():
        db.set_now(dt)
        run_clock_transitions()
    return success({})
