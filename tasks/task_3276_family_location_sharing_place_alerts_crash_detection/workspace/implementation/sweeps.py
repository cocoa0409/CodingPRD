"""Daily sweeps: age, retention, wellness deadline, disclosure expiry."""
from datetime import timedelta
from db import db, now, touch
import calculations as calc
from middleware import circle_posture
from services import (append_consent_record, recompute_posture,
                      on_circle_frozen)
from errors import ApiError, ERR_ASSISTANCE_UNITS_EXHAUSTED, ERR_CIRCLE_RESTRICTED


def escalate_crash(crash):
    """WELLNESS_PENDING -> ESCALATED cascade. Returns True if escalated."""
    crash["crash_status"] = "ESCALATED"
    wc = db.wellness_checks.get(crash.get("wellness_check_id"))
    if wc and wc["check_status"] == "SENT":
        wc["check_status"] = "UNANSWERED"
        touch(wc)
    member = db.members.get(crash["member_id"])
    circle = db.circles.get(member["circle_id"]) if member else None
    disp = None
    if circle is not None:
        circle["assistance_units_balance"] -= 1
        from services import append_subscription_event
        append_subscription_event(circle, "ASSISTANCE_CONSUME", units_delta=-1)
        touch(circle)
        disp = _create_dispatch(crash)
    if disp is not None:
        crash["dispatch_id"] = disp["id"]
    touch(crash)
    return True


def _create_dispatch(crash):
    from db import new_entity
    disp = new_entity(
        crash_event_id=crash["id"],
        dispatch_status="PENDING_VERIFICATION",
        verification_note=None,
        staged_at=None,
    )
    db.dispatches[disp["id"]] = disp
    return disp


def can_escalate(crash):
    """Check fiscal/posture gates for escalation. Returns error or None."""
    member = db.members.get(crash["member_id"])
    circle = db.circles.get(member["circle_id"]) if member else None
    if circle is None:
        return None
    if circle_posture(circle) == "RESTRICTED":
        return ApiError(ERR_CIRCLE_RESTRICTED, 409, "Circle RESTRICTED blocks escalation")
    balance = circle["assistance_units_balance"]
    tier = circle["subscription_tier"]
    if tier == "PROTECT":
        if balance <= -1:
            return ApiError(ERR_ASSISTANCE_UNITS_EXHAUSTED, 402, "assistance units exhausted")
    else:
        if balance <= 0:
            return ApiError(ERR_ASSISTANCE_UNITS_EXHAUSTED, 402, "assistance units exhausted")
    return None


def run_wellness_deadline_sweep():
    """SENT checks past deadline -> UNANSWERED; crash -> ESCALATED (subject to
    fiscal/posture gates; when blocked, the crash stays WELLNESS_PENDING)."""
    escalated = []
    now_dt = now()
    for wc in list(db.wellness_checks.values()):
        if wc["check_status"] != "SENT":
            continue
        if now_dt < wc["deadline_at"]:
            continue
        crash = db.crashes.get(wc["crash_event_id"])
        if crash is None or crash["crash_status"] != "WELLNESS_PENDING":
            continue
        err = can_escalate(crash)
        if err is not None:
            continue
        escalate_crash(crash)
        escalated.append(crash["id"])
    return escalated


def run_age_sweep():
    """MINOR members whose recomputed age >= 16 -> MEMBER; tension cleared."""
    promoted = []
    now_dt = now()
    for m in db.members.values():
        m["age_years"] = calc.age_years(m["birthdate"], now_dt)
        if m["role"] == "MINOR" and m["age_years"] >= 16:
            m["role"] = "MEMBER"
            m["tension_flag"] = False
            touch(m)
            promoted.append(m["id"])
    return promoted


def run_retention_sweep():
    """Fixes older than their circle's retention window -> RETIRED."""
    retired = 0
    now_dt = now()
    for fix in db.fixes.values():
        if fix["fix_status"] in ("RETIRED",):
            continue
        member = db.members.get(fix["member_id"])
        if member is None:
            continue
        circle = db.circles.get(member["circle_id"])
        if circle is None:
            continue
        cutoff = now_dt - timedelta(days=circle["history_retention_days"])
        if fix["recorded_at"] < cutoff:
            if fix["fix_status"] != "RETIRED":
                fix["fix_status"] = "RETIRED"
                touch(fix)
                retired += 1
    return retired


def run_disclosure_sweep():
    """EXPIRE consent for GRANTED members with monetization_opt_in under an
    OPEN DATA_SHARING_DISCLOSURE hold older than 30 days (unacknowledged)."""
    expired = []
    now_dt = now()
    open_disclosure = {}
    for h in db.compliance_holds.values():
        if h["hold_kind"] == "DATA_SHARING_DISCLOSURE" and h["hold_status"] == "OPEN":
            open_disclosure.setdefault(h["circle_id"], h)
    for m in db.members.values():
        if m["consent_state"] != "GRANTED":
            continue
        hold = open_disclosure.get(m["circle_id"])
        if hold is None:
            continue
        if not m.get("monetization_opt_in"):
            continue
        opened_at = hold["created_at"]
        if (now_dt - opened_at) < timedelta(days=30):
            continue
        m["consent_state"] = "EXPIRED"
        m["privacy_mode"] = "HIDDEN"
        touch(m)
        append_consent_record(m, m["id"], "FULL", "EXPIRE",
                              monetization_opt_in=m.get("monetization_opt_in", False))
        if m["role"] == "MINOR":
            from db import new_entity
            audit = new_entity(
                circle_id=m["circle_id"],
                hold_kind="MINOR_PRIVACY_AUDIT",
                hold_status="OPEN",
                opened_reason="minor_consent_expired",
                resolved_by_member_id=None,
            )
            db.compliance_holds[audit["id"]] = audit
        circle = db.circles.get(m["circle_id"])
        if circle is not None:
            recompute_posture(circle, bump=True)
        expired.append(m["id"])
    return expired


def run_billing_anchor_roll():
    """PRD §2.8/§3.1: at each billing anchor (30-day rolling windows from the
    circle's creation instant) the assistance_units_balance replenishes TO the
    per-window tier allotment and identity_protection_credits restarts at the
    tier's window start (1 on PROTECT, 0 otherwise). A RENEWAL ledger row is
    appended per roll, carrying the signed units_delta actually applied to the
    assistance balance and the new billing_period_index."""
    from services import append_subscription_event, current_billing_period_index
    now_dt = now()
    for circle in db.circles.values():
        period = current_billing_period_index(circle)
        window_start = circle["created_at"] + timedelta(days=30 * period)
        while now_dt >= window_start + timedelta(days=30):
            period += 1
            window_start = circle["created_at"] + timedelta(days=30 * period)
            new_units = calc.TIER_UNITS[circle["subscription_tier"]]
            delta = new_units - circle["assistance_units_balance"]
            circle["assistance_units_balance"] = new_units
            circle["identity_protection_credits"] = calc.TIER_IDENTITY_CREDITS[
                circle["subscription_tier"]]
            append_subscription_event(circle, "RENEWAL", units_delta=delta,
                                      billing_period_index=period)
            touch(circle)


def run_all_sweeps():
    escalated = run_wellness_deadline_sweep()
    promoted = run_age_sweep()
    expired = run_disclosure_sweep()
    retired = run_retention_sweep()
    run_billing_anchor_roll()
    return {
        "promoted_member_ids": promoted,
        "expired_consent_member_ids": expired,
        "retired_fix_count": retired,
        "escalated_crash_ids": escalated,
    }
