"""Operational endpoints: the logical clock and the daily sweep."""
from flask import Blueprint

import domain
from authz import endpoint
from envelope import ok
from store import parse_datetime, store
from validation import F, raw_body, validate

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["ComplianceAuditor"])
def set_clock():
    data = validate(raw_body(), [F("to_iso8601", "datetime", required=True)])
    store.set_clock(parse_datetime(data["to_iso8601"]))
    return ok({"current_utc": store.now_iso()})


@bp.post("/_ops/daily-sweep")
@endpoint(["ComplianceAuditor"])
def daily_sweep():
    raw_body(required=False)
    return ok(domain.run_daily_sweep())
