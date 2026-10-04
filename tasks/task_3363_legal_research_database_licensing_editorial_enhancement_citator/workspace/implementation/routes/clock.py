"""Logical clock endpoint (PRD 2.4): PlatformAdmin test-driving capability."""

from flask import Blueprint

from db import fmt_dt, store
from middleware import require_roles
from response import ok_object
from util import get_body, parse_instant

bp = Blueprint("clock", __name__)


@bp.post("/legal-research/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    body = get_body()
    instant = parse_instant(body.get("to_iso8601"), "to_iso8601")
    store.clock = instant
    return ok_object({"current_utc": fmt_dt(store.clock)}, 200)
