"""Operations sweep and the logical-clock test-driving endpoint (PRD 3.7, 2.4)."""
from datetime import timedelta

from flask import Blueprint

from clock import CLOCK
from db import db, sorted_items
from errors import raise_error, ERR_INVALID_REQUEST
from middleware import get_caller, require_role
from response import success_object
from services.calc import (
    AUTO_APPROVE_CAP_CENTS,
    FOLLOWUP_AUTOCLOSE_DAYS,
    accrual_for_month,
)
from services.reserve import post_entry, touch
from util import fmt_ts, months_elapsed, parse_iso_datetime
from validate import get_body, req_str

bp = Blueprint("ops", __name__)


@bp.post("/ops/run-sweep")
def run_sweep():
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager"})
    get_body()
    now = CLOCK.now()
    counts = {
        "accrual_entries_posted": 0,
        "chargebacks_auto_approved": 0,
        "requests_marked_response_breached": 0,
        "requests_marked_completion_breached": 0,
        "requests_auto_closed": 0,
    }

    # 1. Monthly accruals: one ACCRUAL entry per fully elapsed, not-yet-posted
    #    month per home; idempotent — re-running posts nothing new.
    for reserve in sorted_items("warranty_reserves"):
        home = db["homes"].get(reserve["home_id"])
        if home is None:
            continue
        elapsed = months_elapsed(home["closing_date"], now.date())
        last = reserve["last_accrual_month_index"]
        for m in range(last + 1, elapsed + 1):
            amount = accrual_for_month(reserve["expected_lifetime_accrual_cents"], m)
            post_entry(reserve, "ACCRUAL", amount, month_index=m)
            counts["accrual_entries_posted"] += 1
        if elapsed > last:
            reserve["last_accrual_month_index"] = elapsed

    # 2. SLA breach flags: due instant strictly before now breaches (the due
    #    instant itself counts as met).
    for sr in sorted_items("service_requests"):
        if (sr["status"] == "RECEIVED"
                and not sr["response_breached"]
                and now > sr["response_due_at"]):
            sr["response_breached"] = True
            sr["escalation_level"] = max(sr["escalation_level"], 1)
            touch(sr)
            counts["requests_marked_response_breached"] += 1
        if (sr["status"] in ("APPROVED", "IN_SERVICE")
                and sr["completion_due_at"] is not None
                and not sr["completion_breached"]
                and now > sr["completion_due_at"]):
            sr["completion_breached"] = True
            sr["escalation_level"] = 2
            touch(sr)
            counts["requests_marked_completion_breached"] += 1

    # 3. Chargeback auto-approval gate: earliest issued_at first (creation-order
    #    tie-break); deadline strictly passed and payable at most the cap
    #    (payable exactly == cap IS auto-approved).
    issued = [c for c in db["chargebacks"].values() if c["status"] == "ISSUED"]
    issued.sort(key=lambda c: (c["issued_at"], c["_seq"]))
    for cb in issued:
        if (now > cb["contest_deadline_at"]
                and cb["payable_amount_cents"] <= AUTO_APPROVE_CAP_CENTS):
            cb["status"] = "APPROVED"
            touch(cb)
            counts["chargebacks_auto_approved"] += 1

    # 4. Auto-close stale follow-ups once the clock reaches
    #    followup_entered_at + 14 days.
    for sr in sorted_items("service_requests"):
        if (sr["status"] == "PENDING_FOLLOWUP"
                and now >= sr["followup_entered_at"] + timedelta(days=FOLLOWUP_AUTOCLOSE_DAYS)):
            sr["status"] = "CLOSED"
            sr["closed_at"] = now
            touch(sr)
            counts["requests_auto_closed"] += 1

    return success_object(counts)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _uid, role = get_caller()
    require_role(role, {"WarrantyManager"})
    body = get_body()
    raw = req_str(body, "to_iso8601")
    dt = parse_iso_datetime(raw)
    if dt is None:
        raise_error(ERR_INVALID_REQUEST, "to_iso8601 must be a valid ISO 8601 datetime")
    CLOCK.set(dt)
    return success_object({"current_utc": fmt_ts(CLOCK.now())})
