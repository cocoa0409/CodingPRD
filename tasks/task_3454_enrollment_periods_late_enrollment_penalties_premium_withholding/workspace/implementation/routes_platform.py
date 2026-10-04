"""Platform (test-driving) endpoints — mounted OUTSIDE the /medicare prefix:
POST /_clock/set_current_utc and POST /_ops/run_monthly_cycle.
"""
from __future__ import annotations

from authn import ROLE_BENEFIT_ADMINISTRATOR, authenticate, authorize
from clock import format_clock_reading, now, parse_iso8601, set_now
from cycle import run_monthly_cycle
from envelope import success_object
from errors import fail
from validate import body_json, req_str


def set_clock():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFIT_ADMINISTRATOR])
    body = body_json()
    to_iso8601 = req_str(body, "to_iso8601")
    try:
        dt = parse_iso8601(to_iso8601)
    except (ValueError, TypeError):
        fail("ERR_VALIDATION", "to_iso8601 must be an ISO 8601 timestamp")
    set_now(dt)
    return success_object({"current_utc": format_clock_reading(now())})


def run_cycle():
    role, uid = authenticate()
    authorize(role, [ROLE_BENEFIT_ADMINISTRATOR])
    summary = run_monthly_cycle()
    return success_object(summary)


def register(app):
    app.add_url_rule("/_clock/set_current_utc", "set_clock", set_clock,
                     methods=["POST"])
    app.add_url_rule("/_ops/run_monthly_cycle", "run_cycle", run_cycle,
                     methods=["POST"])
