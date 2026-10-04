"""Logical clock and ops checkpoint endpoints (PlatformAdmin)."""

from flask import Blueprint

import db
from auth import require_roles
from calculations import CONTACT_INTERVALS, whole_days_between
from clock import CLOCK, parse_iso
from db import touch
from envelope import ok
from validation import body_json, reject_unknown, req_datetime

bp = Blueprint("ops", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("PlatformAdmin")
    body = body_json()
    reject_unknown(body, {"to_iso8601"})
    raw = req_datetime(body, "to_iso8601")
    CLOCK.set(raw)
    return ok({"current_utc": CLOCK.stamp()})


@bp.post("/ops/contact-overdue-sweep")
def contact_overdue_sweep():
    require_roles("PlatformAdmin")
    now = CLOCK.now_dt()
    swept_case_count = 0
    newly_overdue_case_ids = []
    for case in db.cases.values():
        if case["status"] == "CLOSED":
            continue
        swept_case_count += 1
        interval = CONTACT_INTERVALS.get(case["status"])
        last_contact_dt = parse_iso(case["last_contact_at"])
        days_since = whole_days_between(now, last_contact_dt)
        overdue = days_since > interval  # strictly greater; == is not overdue
        if overdue != case["contact_overdue"]:
            case["contact_overdue"] = overdue
            touch(case)
            if overdue:
                newly_overdue_case_ids.append(case["id"])
    return ok({
        "swept_case_count": swept_case_count,
        "newly_overdue_count": len(newly_overdue_case_ids),
        "newly_overdue_case_ids": newly_overdue_case_ids,
    })
