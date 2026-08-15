"""System / test-driving endpoints (PRD 2.4, 2.5): logical clock and the
retention purge."""
from flask import Blueprint

from db import db
from middleware import authorized
from response import success_object
from services.core import TERMINAL_CASE_STATES, RETENTION_YEARS
from util import CLOCK, fmt_datetime, parse_datetime, add_years
from validate import get_body, req_datetime

bp = Blueprint("system", __name__)


@bp.post("/_clock/set_current_utc")
def set_clock():
    authorized(["CaseAdministrator"])
    body = get_body()
    to_iso8601 = req_datetime(body, "to_iso8601")
    new_dt = CLOCK.set(to_iso8601)
    return success_object({"current_utc": fmt_datetime(new_dt)})


@bp.post("/records/purge-run")
def purge_run():
    authorized(["CaseAdministrator"])
    now = CLOCK.now()
    purged_event_count = 0
    purged_case_ids = []
    # Eligible: terminal case whose closed_at + 7 years is on or before the
    # logical clock (inclusive boundary). DISMISSED carries closed_at and is
    # included in the sweep; cases and statistics are preserved.
    for case in db["cases"].values():
        closed_at = case.get("closed_at")
        if closed_at is None:
            continue
        if case["status"] not in TERMINAL_CASE_STATES and case["status"] != "DISMISSED":
            continue
        if add_years(parse_datetime(closed_at), RETENTION_YEARS) <= now:
            doomed = [eid for eid, e in db["case_events"].items() if e["case_id"] == case["id"]]
            if doomed:
                for eid in doomed:
                    del db["case_events"][eid]
                purged_event_count += len(doomed)
                purged_case_ids.append(case["id"])
    return success_object({
        "purged_event_count": purged_event_count,
        "purged_case_ids": purged_case_ids,
    })
