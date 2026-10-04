"""Core services: posture, subscription ledger, consent cascade."""
from datetime import timedelta
from db import db, now, touch, new_entity
import calculations as calc
from middleware import circle_posture


# ---------------------------------------------------------------------------
# Subscription ledger
# ---------------------------------------------------------------------------

def current_billing_period_index(circle):
    """Highest billing_period_index observed on the circle's ledger (0-based)."""
    idx = 0
    for ev in db.subscription_events.values():
        if ev["circle_id"] == circle["id"]:
            idx = max(idx, ev.get("billing_period_index", 0))
    return idx


def append_subscription_event(circle, event_kind, from_tier=None, to_tier=None,
                              units_delta=0, billing_period_index=None):
    ev = new_entity(
        circle_id=circle["id"],
        event_kind=event_kind,
        from_tier=from_tier,
        to_tier=to_tier,
        effective_at=now(),
        units_delta=units_delta,
        billing_period_index=(billing_period_index
                              if billing_period_index is not None
                              else current_billing_period_index(circle)),
    )
    db.subscription_events[ev["id"]] = ev
    return ev


def recompute_posture(circle, bump=False):
    posture = circle_posture(circle)
    old = circle.get("circle_posture")
    circle["circle_posture"] = posture
    if bump and old != posture:
        touch(circle)
    return posture


def on_circle_frozen(circle):
    """Side effects of posture -> FROZEN: abandon OPEN trips, suppress
    PENDING_DWELL alerts with TIER_HISTORY."""
    for member in members_of_circle(circle["id"]):
        for trip in db.trips.values():
            if trip["member_id"] == member["id"] and trip["trip_status"] == "OPEN":
                trip["trip_status"] = "ABANDONED"
                trip["driver_score"] = None
                touch(trip)
        for alert in db.place_alerts.values():
            if alert["member_id"] == member["id"] and alert["alert_status"] == "PENDING_DWELL":
                alert["alert_status"] = "SUPPRESSED"
                alert["suppressed_reason"] = "TIER_HISTORY"
                touch(alert)


def members_of_circle(circle_id):
    return [m for m in db.members.values() if m["circle_id"] == circle_id]


# ---------------------------------------------------------------------------
# Consent cascade
# ---------------------------------------------------------------------------

def append_consent_record(member, granted_by_member_id, scope, action,
                          monetization_opt_in=False):
    rec = new_entity(
        member_id=member["id"],
        granted_by_member_id=granted_by_member_id,
        scope=scope,
        consent_action=action,
        effective_at=now(),
        monetization_opt_in=bool(monetization_opt_in),
    )
    db.consent_records[rec["id"]] = rec
    return rec


def on_consent_revoked(member):
    """GRANTED -> REVOKED compensations:
    - OPEN CrashEvents -> FALSE_ALARM (compensation)
    - SENT WellnessChecks -> CANCELLED
    - OPEN TripReports -> ABANDONED
    - PENDING_DWELL PlaceAlerts -> CANCELLED
    """
    for crash in db.crashes.values():
        if crash["member_id"] != member["id"]:
            continue
        if crash["crash_status"] in ("DETECTED", "WELLNESS_PENDING", "ESCALATED"):
            was_escalated = crash["crash_status"] == "ESCALATED"
            crash["crash_status"] = "FALSE_ALARM"
            crash["false_alarm_reason"] = "consent_revoked"
            wc = db.wellness_checks.get(crash.get("wellness_check_id"))
            if wc and wc["check_status"] == "SENT":
                wc["check_status"] = "CANCELLED"
                touch(wc)
            disp = db.dispatches.get(crash.get("dispatch_id")) if crash.get("dispatch_id") else None
            if disp and disp["dispatch_status"] in ("PENDING_VERIFICATION", "VERIFIED"):
                disp["dispatch_status"] = "CANCELLED"
                touch(disp)
            if was_escalated:
                circle = db.circles.get(member["circle_id"])
                if circle is not None:
                    circle["assistance_units_balance"] += 1
                    touch(circle)
            touch(crash)
    for trip in db.trips.values():
        if trip["member_id"] == member["id"] and trip["trip_status"] == "OPEN":
            trip["trip_status"] = "ABANDONED"
            trip["driver_score"] = None
            touch(trip)
    for alert in db.place_alerts.values():
        if alert["member_id"] == member["id"] and alert["alert_status"] == "PENDING_DWELL":
            alert["alert_status"] = "CANCELLED"
            touch(alert)


def recompute_member_interval(member, circle=None):
    """Recompute effective_sample_interval_seconds using the member's last fix
    context if present, else defaults (BALANCED-equivalent motion UNKNOWN,
    battery 100)."""
    if circle is None:
        circle = db.circles.get(member["circle_id"])
    tier = circle["subscription_tier"] if circle else "FREE"
    fix = db.fixes.get(member.get("last_known_fix_id")) if member.get("last_known_fix_id") else None
    if fix is not None:
        motion = fix["motion_context"]
        battery = fix["battery_pct"]
    else:
        motion = "UNKNOWN"
        battery = member.get("current_battery_pct", 100)
    member["effective_sample_interval_seconds"] = calc.effective_sample_interval(
        member["sampling_profile"], motion, battery, tier)
