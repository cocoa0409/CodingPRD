"""The logical clock and the deferred-action compliance sweep (PRD 3.9)."""
from flask import Blueprint

import audit
import propagation
import routes_inquiries
import routes_suppression
import standing
from core import add_days, db, fmt_ts, now, ok, ordered, touch
from guards import ROLE_PLATFORM_ADMIN, authenticate, body, get_ts

bp = Blueprint("ops", __name__)

ABANDON_GRACE_DAYS = 30


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate([ROLE_PLATFORM_ADMIN])
    data = body()
    value = get_ts(data, "current_utc")
    db.clock = value
    return ok({"current_utc": fmt_ts(db.clock)})


@bp.post("/_ops/run-compliance-sweep")
def run_compliance_sweep():
    caller = authenticate([ROLE_PLATFORM_ADMIN])
    actor = audit.actor_system(caller)
    clock = now()
    counters = {
        "expired_registration_count": 0,
        "expired_suppression_count": 0,
        "abandoned_task_count": 0,
        "honored_signal_count": 0,
        "escalated_inquiry_count": 0,
    }

    # Step 1: expire accepted filings whose half-open coverage period ended.
    for reg in ordered(list(db.registrations.values())):
        if reg["status"] != "ACCEPTED":
            continue
        if reg["coverage_period_end"] > clock:
            continue
        broker = db.brokers[reg["broker_id"]]
        reg["status"] = "EXPIRED"
        # PRD 3.2: expiry refunds the charged fee and runs the same third and
        # fourth cascade links as a withdrawal.
        standing.refund_charged_fee(broker, reg)
        touch(reg)
        counters["expired_registration_count"] += 1
        standing.derive_standing(broker, actor, delinquency_cascade=True)
        audit.append(broker, "REGISTRATION_EXPIRED",
                     "REGISTRATION", reg["id"], actor,
                     "accepted filing expired at the end of its coverage "
                     "period")

    # Step 2: expire suppression windows the clock has moved past. The window
    # is closed, so it survives its own end instant.
    for entry in ordered(list(db.suppressions.values())):
        if entry["status"] != "ACTIVE":
            continue
        if not entry["window_end"] < clock:
            continue
        entry["status"] = "EXPIRED"
        touch(entry)
        counters["expired_suppression_count"] += 1
        audit.append(db.brokers[entry["broker_id"]], "SUPPRESSION_EXPIRED",
                     "SUPPRESSION_ENTRY", entry["id"], actor,
                     "suppression window ran out")

    # Step 3: abandon stalled propagation past its due_at plus a 30-day grace.
    for task in ordered(list(db.tasks.values())):
        if task["status"] not in propagation.OPEN_TASK_STATES:
            continue
        if not add_days(task["due_at"], ABANDON_GRACE_DAYS) < clock:
            continue
        propagation.abandon_task(
            task, actor,
            "propagation abandoned after its due date and 30-day grace")
        counters["abandoned_task_count"] += 1

    # Step 4: honor preference signals that reached their honor deadline.
    for signal in ordered(list(db.signals.values())):
        if signal["status"] != "RECEIVED":
            continue
        if signal["honor_deadline_at"] > clock:
            continue
        routes_suppression.honor_signal(
            signal, actor, "deferred opt-out honored at its honor deadline")
        counters["honored_signal_count"] += 1

    # Step 5: escalate inquiries nobody answered.
    for inquiry in ordered(list(db.inquiries.values())):
        if inquiry["status"] != "OPEN":
            continue
        if not inquiry["response_due_at"] < clock:
            continue
        broker = db.brokers[inquiry["broker_id"]]
        inquiry["status"] = "ESCALATED"
        inquiry["escalation_count"] += 1
        touch(inquiry)
        broker["open_breach_count"] += 1
        touch(broker)
        routes_inquiries._add_contrib(inquiry["id"], 1)
        standing.derive_standing(broker, actor)
        audit.append(broker, "INQUIRY_ESCALATED", "INQUIRY", inquiry["id"],
                     actor, "inquiry escalated because it went unanswered")
        counters["escalated_inquiry_count"] += 1

    # Step 6: re-derive standing for every broker; this is the only place the
    # 90-day delinquency rule fires.
    for broker in ordered(list(db.brokers.values())):
        changed = standing.derive_standing(broker, actor)
        if changed and broker["registry_standing"] == "SUSPENDED":
            standing.park_recipient_work(broker, actor)

    summary = {"swept_at": fmt_ts(clock)}
    summary.update(counters)
    return ok(summary)
