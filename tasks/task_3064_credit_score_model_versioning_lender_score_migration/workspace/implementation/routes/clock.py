"""Logical clock endpoints (PRD §2.11)."""

from datetime import timedelta

from flask import Blueprint, request

from core import (
    DB, CLOCK, ok, resolve_actor, body_of, reject_unknown, require_fields, as_str,
    parse_iso, parse_month, now, now_iso, iso, touch, DISCOVERY_SWEEP_HOURS,
)
from errors import ApiError

bp = Blueprint("clock", __name__)


def _sweep_expired_discovery_slots():
    swept = 0
    threshold = now() - timedelta(hours=DISCOVERY_SWEEP_HOURS)
    for rec in DB["score_discovery_requests"].values():
        if rec["status"] != "REGISTERED":
            continue
        requested = parse_iso(rec["requested_at"])
        if requested < threshold:
            rec["status"] = "EXPIRED"
            touch(rec)
            swept += 1
    return swept


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    resolve_actor(request, ["BureauAdministrator"])
    body = body_of(request)
    reject_unknown(body, {"to_iso8601"})
    require_fields(body, ["to_iso8601"])
    instant = parse_iso(as_str(body["to_iso8601"], "to_iso8601"))
    CLOCK["now"] = instant
    expired = _sweep_expired_discovery_slots()
    return ok({"current_utc": iso(CLOCK["now"]), "expired_discovery_request_count": expired})


@bp.post("/_clock/advance_to_month")
def advance_to_month():
    resolve_actor(request, ["BureauAdministrator"])
    body = body_of(request)
    reject_unknown(body, {"month"})
    require_fields(body, ["month"])
    instant = parse_month(as_str(body["month"], "month"))
    CLOCK["now"] = instant
    return ok({"current_utc": iso(CLOCK["now"])})