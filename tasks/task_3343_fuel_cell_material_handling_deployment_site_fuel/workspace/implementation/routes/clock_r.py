"""Logical clock administration."""

from flask import Blueprint

import clockops
import db
import envelope
import validators as v
from authz import require_roles

bp = Blueprint("clock", __name__)


@bp.post("/api/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    data = v.body()
    raw = v.req(data, "to_iso8601")
    v.datetime_value(raw, "to_iso8601")
    db.set_clock(v.parse_datetime(raw))
    clockops.reconcile()
    return envelope.ok({}, 200)
