"""Logical clock endpoints (test-driving)."""
from __future__ import annotations

from flask import Blueprint, request

from db import DB, CLOCK
from errors import invalid_input
from middleware import require_roles
from response import success
from services.calculations import parse_iso8601, to_iso8601_ms
from services.entity import touch


bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_roles("ValuationAdmin", "DataOps")
    body = request.get_json(silent=True) or {}
    to_iso = body.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise invalid_input("to_iso8601 is required")
    try:
        new_dt = parse_iso8601(to_iso)
    except Exception:
        raise invalid_input("to_iso8601 must be ISO 8601")

    CLOCK.set(new_dt)

    # Cascade: every QUOTED or INSPECTED offer whose expires_at < new clock -> EXPIRED
    for offer in DB.cash_offers.values():
        if offer["status"] in ("QUOTED", "INSPECTED"):
            if offer["expires_at_dt"] < new_dt:
                offer["status"] = "EXPIRED"
                touch(offer)

    # PRD §2.4: confidence_score is NOT recomputed by the clock advance.

    return success({}, 200, response_type="object")
