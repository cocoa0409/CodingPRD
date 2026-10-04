"""Ops endpoints: logical clock, monthly ops run, shipping sweep."""

from flask import Blueprint

import db
from errors import raise_err
from middleware import require_roles
from response import object_response
from services import fire_clock_transitions, run_points_expiry, run_shipping
from routes.common import get_body, req_field

bp = Blueprint("ops", __name__)


@bp.post("/club/_clock/set_current_utc")
@require_roles("ClubAdmin")
def set_clock():
    body = get_body()
    to_iso = req_field(body, "to_iso8601")
    if not isinstance(to_iso, str):
        raise_err("ERR_INVALID_REQUEST", "to_iso8601 must be an ISO8601 string")
    # Normalize to %Y-%m-%dT%H:%M:%SZ.
    import datetime
    s = to_iso.strip()
    if s.endswith("Z"):
        core = s[:-1]
    elif "+" in s[10:] or s[10:].count("-") > 2:
        # Offset form: convert to UTC.
        try:
            dt = datetime.datetime.fromisoformat(s)
            dt = dt.astimezone(datetime.timezone.utc)
            core = dt.strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            raise_err("ERR_INVALID_REQUEST", "to_iso8601 must parse as ISO8601")
    else:
        core = s
    try:
        if "." in core:
            dt = datetime.datetime.strptime(core, "%Y-%m-%dT%H:%M:%S.%f")
        else:
            dt = datetime.datetime.strptime(core, "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        raise_err("ERR_INVALID_REQUEST", "to_iso8601 must parse as ISO8601")
    db.clock.set(dt.strftime("%Y-%m-%dT%H:%M:%SZ"))
    fire_clock_transitions()
    return object_response({})


@bp.post("/club/_ops/run-ops")
@require_roles("ClubAdmin")
def run_ops():
    expired_total, teachers_affected = run_points_expiry()
    fire_clock_transitions()
    return object_response({
        "expired_total_points": expired_total,
        "teachers_affected": teachers_affected,
    })


@bp.post("/club/_ops/run-shipping")
@require_roles("ClubAdmin")
def run_shipping_ep():
    shipped, touched = run_shipping()
    return object_response({
        "shipped_line_count": shipped,
        "orders_touched": touched,
    })
