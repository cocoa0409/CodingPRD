"""Location fix ingestion: geofence eval, place-alert windows, trip continuity."""
from db import db, now, touch, new_entity
import calculations as calc
from middleware import circle_posture
from services import recompute_member_interval

TRIP_TIMEOUT_S = 600


def _open_alert(place, member, fix, event_kind):
    alert = new_entity(
        place_id=place["id"],
        member_id=member["id"],
        event_kind=event_kind,
        alert_status="PENDING_DWELL",
        window_open_fix_id=fix["id"],
        window_close_fix_id=None,
        suppressed_reason=None,
        visible_to_owner=None,
    )
    db.place_alerts[alert["id"]] = alert
    return alert


def _member_prev_inside(place_id, member_id, exclude_fix_id):
    """Was the member inside this place as of their most recent prior ACCEPTED
    fix (by recorded_at, then created_at)? Uses frozen place_ids_inside."""
    fixes = [f for f in db.fixes.values()
             if f["member_id"] == member_id and f["id"] != exclude_fix_id
             and f["fix_status"] == "ACCEPTED"]
    if not fixes:
        return False
    fixes.sort(key=lambda f: (f["recorded_at"], f["created_at"]))
    return place_id in fixes[-1].get("place_ids_inside", [])


def _confirm_or_resolve(alert, place, member, close_fix, circle):
    """Pinned dwell evaluation order."""
    open_fix = db.fixes.get(alert["window_open_fix_id"])
    if open_fix is None:
        return
    gap = (close_fix["recorded_at"] - open_fix["recorded_at"]).total_seconds()
    eff = calc.effective_sample_interval(
        member["sampling_profile"], open_fix["motion_context"],
        open_fix["battery_pct"], circle["subscription_tier"])
    if gap < 0.5 * eff:
        alert["alert_status"] = "SUPPRESSED"
        alert["suppressed_reason"] = "DUPLICATE_EVENT"
        alert["window_close_fix_id"] = close_fix["id"]
        touch(alert)
        return
    if circle_posture(circle) != "OPEN":
        # Held back: posture not OPEN at confirmation time -> suppress.
        alert["alert_status"] = "SUPPRESSED"
        alert["suppressed_reason"] = "TIER_HISTORY"
        alert["window_close_fix_id"] = close_fix["id"]
        touch(alert)
        return
    if gap >= place["dwell_bucket_seconds"]:
        alert["alert_status"] = "CONFIRMED"
        alert["window_close_fix_id"] = close_fix["id"]
        alert["visible_to_owner"] = member["privacy_mode"] in ("PRECISE", "BLURRED")
        if member["privacy_mode"] == "HIDDEN":
            # Would otherwise have fired, but member is HIDDEN at confirmation.
            alert["alert_status"] = "SUPPRESSED"
            alert["suppressed_reason"] = "PRIVACY_HIDDEN"
            alert["visible_to_owner"] = False
        touch(alert)
    else:
        alert["alert_status"] = "SUPPRESSED"
        alert["suppressed_reason"] = None
        alert["window_close_fix_id"] = close_fix["id"]
        touch(alert)


def evaluate_places(member, fix, circle):
    """Open/close PlaceAlert windows for each ACTIVE place of the circle."""
    inside_now = set()
    for place in db.places.values():
        if place["circle_id"] != circle["id"] or place["place_status"] != "ACTIVE":
            continue
        inside, _acc_rej = calc.geofence_inside(place, fix)
        if inside:
            inside_now.add(place["id"])
    fix["place_ids_inside"] = sorted(inside_now)

    for place in db.places.values():
        if place["circle_id"] != circle["id"] or place["place_status"] != "ACTIVE":
            continue
        was_inside = _member_prev_inside(place["id"], member["id"], fix["id"])
        is_inside = place["id"] in inside_now
        # Resolve open PENDING_DWELL alerts first.
        pending = [a for a in db.place_alerts.values()
                   if a["place_id"] == place["id"] and a["member_id"] == member["id"]
                   and a["alert_status"] == "PENDING_DWELL"]
        for alert in pending:
            if alert["event_kind"] == "ARRIVAL":
                if is_inside:
                    _confirm_or_resolve(alert, place, member, fix, circle)
                else:
                    # Opposite-direction fix closes window.
                    alert["alert_status"] = "SUPPRESSED"
                    alert["suppressed_reason"] = "DUPLICATE_EVENT"
                    alert["window_close_fix_id"] = fix["id"]
                    touch(alert)
            else:  # DEPARTURE candidate: waiting for member to stay outside
                if not is_inside:
                    _confirm_or_resolve(alert, place, member, fix, circle)
                else:
                    alert["alert_status"] = "SUPPRESSED"
                    alert["suppressed_reason"] = "DUPLICATE_EVENT"
                    alert["window_close_fix_id"] = fix["id"]
                    touch(alert)
        # Open new candidates only if no pending remains for this place/member.
        still_pending = any(a for a in db.place_alerts.values()
                            if a["place_id"] == place["id"]
                            and a["member_id"] == member["id"]
                            and a["alert_status"] == "PENDING_DWELL")
        if still_pending:
            continue
        if is_inside and not was_inside and place["notify_on_arrive"]:
            _open_alert(place, member, fix, "ARRIVAL")
        elif not is_inside and was_inside and place["notify_on_depart"]:
            _open_alert(place, member, fix, "DEPARTURE")


def handle_trip(member, fix, circle):
    """Open/extend/close trips based on motion context."""
    open_trip = None
    for t in db.trips.values():
        if t["member_id"] == member["id"] and t["trip_status"] == "OPEN":
            open_trip = t
            break
    if fix["motion_context"] == "DRIVING":
        if open_trip is None:
            open_trip = new_entity(
                member_id=member["id"],
                started_at=fix["recorded_at"],
                ended_at=fix["recorded_at"],
                trip_status="OPEN",
                distance_m=0,
                max_speed_mps=fix["speed_mps"],
                speed_event_count=0,
                phone_use_event_count=0,
                driver_score=None,
            )
            db.trips[open_trip["id"]] = open_trip
        else:
            if fix["recorded_at"] > open_trip["ended_at"]:
                open_trip["ended_at"] = fix["recorded_at"]
            if fix["speed_mps"] > (open_trip.get("max_speed_mps") or 0):
                open_trip["max_speed_mps"] = fix["speed_mps"]
            touch(open_trip)
    else:
        if open_trip is not None:
            close_trip(open_trip, member, circle)
    return open_trip


def _trip_driving_fixes(trip):
    fixes = [f for f in db.fixes.values()
             if f["member_id"] == trip["member_id"]
             and f["fix_status"] == "ACCEPTED"
             and f["motion_context"] == "DRIVING"
             and trip["started_at"] <= f["recorded_at"] <= trip["ended_at"]]
    fixes.sort(key=lambda f: (f["recorded_at"], f["created_at"]))
    return fixes


def close_trip(trip, member, circle):
    fixes = _trip_driving_fixes(trip)
    trip["trip_status"] = "CLOSED"
    trip["distance_m"] = calc.trip_distance_m(fixes)
    trip["max_speed_mps"] = max((f["speed_mps"] for f in fixes), default=0.0)
    trip["speed_event_count"] = calc.speed_event_count(fixes, circle["subscription_tier"])
    trip["phone_use_event_count"] = calc.phone_use_event_count(fixes)
    trip["driver_score"] = calc.driver_score(
        trip["distance_m"], trip["speed_event_count"], trip["phone_use_event_count"])
    touch(trip)


def check_trip_timeouts():
    """Close OPEN trips whose last DRIVING fix is > 600s old (called on sweeps
    and on fix ingestion)."""
    now_dt = now()
    for trip in db.trips.values():
        if trip["trip_status"] != "OPEN":
            continue
        if (now_dt - trip["ended_at"]).total_seconds() > TRIP_TIMEOUT_S:
            member = db.members.get(trip["member_id"])
            circle = db.circles.get(member["circle_id"]) if member else None
            if circle is not None:
                close_trip(trip, member, circle)


def ingest_fix(member, circle, payload, recorded_at):
    """Create the LocationFix and run the side-effect chain. Returns the fix."""
    consent_ok = member["consent_state"] == "GRANTED"
    fix = new_entity(
        member_id=member["id"],
        recorded_at=recorded_at,
        lat=payload["lat"],
        lng=payload["lng"],
        accuracy_m=payload["accuracy_m"],
        speed_mps=payload["speed_mps"],
        battery_pct=payload["battery_pct"],
        phone_in_use=bool(payload.get("phone_in_use", False)),
        motion_context=payload["motion_context"],
        fix_status="ACCEPTED" if consent_ok else "REJECTED_CONSENT",
        place_ids_inside=[],
    )
    db.fixes[fix["id"]] = fix
    if not consent_ok:
        return fix
    member["last_known_fix_id"] = fix["id"]
    member["current_battery_pct"] = fix["battery_pct"]
    member["effective_sample_interval_seconds"] = calc.effective_sample_interval(
        member["sampling_profile"], fix["motion_context"], fix["battery_pct"],
        circle["subscription_tier"])
    touch(member)
    evaluate_places(member, fix, circle)
    handle_trip(member, fix, circle)
    return fix
