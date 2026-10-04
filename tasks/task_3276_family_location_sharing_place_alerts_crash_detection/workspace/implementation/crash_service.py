"""Crash cascade and dispatch lifecycle services."""
from datetime import timedelta
from db import db, now, touch, new_entity
from middleware import circle_posture
from errors import (ApiError, ERR_INVALID_STATE, ERR_WELLNESS_EXPIRED,
                    ERR_DISPATCH_ALREADY_STAGED, ERR_ASSISTANCE_UNITS_EXHAUSTED,
                    ERR_CIRCLE_RESTRICTED)
from services import append_subscription_event

SEVERE_DEADLINE_S = 300
OTHER_DEADLINE_S = 600


def create_crash_event(member, trip, severity, note=None):
    detected = now()
    crash = new_entity(
        member_id=member["id"],
        trip_report_id=trip["id"],
        detected_at=detected,
        severity=severity,
        crash_status="DETECTED",
        wellness_check_id=None,
        dispatch_id=None,
        false_alarm_reason=None,
        note=note,
    )
    db.crashes[crash["id"]] = crash
    # DETECTED -> WELLNESS_PENDING immediately
    deadline = detected + timedelta(
        seconds=SEVERE_DEADLINE_S if severity == "SEVERE" else OTHER_DEADLINE_S)
    wc = new_entity(
        crash_event_id=crash["id"],
        check_status="SENT",
        deadline_at=deadline,
        acknowledged_by_member_id=None,
    )
    db.wellness_checks[wc["id"]] = wc
    crash["wellness_check_id"] = wc["id"]
    crash["crash_status"] = "WELLNESS_PENDING"
    touch(crash)
    return crash


def acknowledge_wellness(crash, check, actor_member_id):
    # PRD §3.7: acknowledgement is accepted only while the logical clock is
    # strictly before the check's deadline_at; an acknowledgement attempted at
    # or after the deadline is rejected with ERR_WELLNESS_EXPIRED — by then
    # the system has already escalated. The deadline gate therefore runs
    # before the state gate.
    if now() >= check["deadline_at"]:
        raise ApiError(ERR_WELLNESS_EXPIRED, 409, "Wellness deadline passed")
    if crash["crash_status"] != "WELLNESS_PENDING":
        raise ApiError(ERR_INVALID_STATE, 409, "Wellness check not pending")
    if check["check_status"] != "SENT":
        raise ApiError(ERR_INVALID_STATE, 409, "Wellness check not pending")
    check["check_status"] = "ACKNOWLEDGED"
    check["acknowledged_by_member_id"] = actor_member_id
    touch(check)
    crash["crash_status"] = "CONFIRMED_OK"
    disp = db.dispatches.get(crash.get("dispatch_id")) if crash.get("dispatch_id") else None
    if disp and disp["dispatch_status"] == "PENDING_VERIFICATION":
        disp["dispatch_status"] = "CANCELLED"
        touch(disp)
    touch(crash)
    return check


def mark_false_alarm(crash, reason):
    if crash["crash_status"] not in ("DETECTED", "WELLNESS_PENDING", "ESCALATED"):
        raise ApiError(ERR_INVALID_STATE, 409, "Cannot mark FALSE_ALARM from current state")
    was_escalated = crash["crash_status"] == "ESCALATED"
    crash["crash_status"] = "FALSE_ALARM"
    crash["false_alarm_reason"] = reason
    wc = db.wellness_checks.get(crash.get("wellness_check_id"))
    if wc and wc["check_status"] == "SENT":
        wc["check_status"] = "CANCELLED"
        touch(wc)
    disp = db.dispatches.get(crash.get("dispatch_id")) if crash.get("dispatch_id") else None
    if disp and disp["dispatch_status"] in ("PENDING_VERIFICATION", "VERIFIED"):
        disp["dispatch_status"] = "CANCELLED"
        touch(disp)
    if was_escalated:
        member = db.members.get(crash["member_id"])
        circle = db.circles.get(member["circle_id"]) if member else None
        if circle is not None:
            circle["assistance_units_balance"] += 1
            append_subscription_event(circle, "ASSISTANCE_GRANT", units_delta=1)
            touch(circle)
    touch(crash)
    return crash


def verify_dispatch(disp, crash, note):
    if disp["dispatch_status"] != "PENDING_VERIFICATION":
        raise ApiError(ERR_INVALID_STATE, 409, "Dispatch not pending verification")
    if crash["crash_status"] != "ESCALATED":
        raise ApiError(ERR_INVALID_STATE, 409, "Crash not in ESCALATED state")
    disp["verification_note"] = note
    disp["dispatch_status"] = "VERIFIED"
    # atomic follow-on VERIFIED -> STAGED
    disp["dispatch_status"] = "STAGED"
    disp["staged_at"] = now()
    touch(disp)
    crash["crash_status"] = "DISPATCHED"
    touch(crash)
    return disp


def complete_dispatch(disp, crash):
    if disp["dispatch_status"] != "STAGED":
        raise ApiError(ERR_INVALID_STATE, 409, "Dispatch not staged")
    if crash["crash_status"] != "DISPATCHED":
        raise ApiError(ERR_INVALID_STATE, 409, "Crash not in DISPATCHED state")
    disp["dispatch_status"] = "COMPLETED"
    touch(disp)
    crash["crash_status"] = "RESOLVED"
    touch(crash)
    return disp


def cancel_dispatch(disp, crash):
    if disp["dispatch_status"] in ("STAGED", "COMPLETED"):
        raise ApiError(ERR_DISPATCH_ALREADY_STAGED, 409,
                       "Dispatch in STAGED or COMPLETED cannot be cancelled")
    if disp["dispatch_status"] == "CANCELLED":
        raise ApiError(ERR_INVALID_STATE, 409, "Dispatch already cancelled")
    disp["dispatch_status"] = "CANCELLED"
    touch(disp)
    return disp
