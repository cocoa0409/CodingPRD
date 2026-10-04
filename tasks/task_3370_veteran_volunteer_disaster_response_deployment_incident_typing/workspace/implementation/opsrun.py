"""The ops-run epoch (PRD section 2.4): six sweeps in the pinned order.
(1) expire VERIFIED certs with current_utc > expires_at (strictly greater)
(2) auto-downgrade DEPLOYABLE volunteers left with zero VERIFIED certs
(3) expire OFFERED deployments older than CALL_UP_RESPONSE_HOURS(48)
(4) mark NO_SHOW deployments past start_date + NO_SHOW_GRACE_HOURS(24)
(5) complete due duty shifts, accrue fatigue, then reset fatigue after
    >= REST_RESET_HOURS(24) idle
(6) promote WAITLISTED enrollments into free seats (created_at ASC)
"""
from datetime import timedelta
import db
import domain
import calculations
import timeutil
from constants import (
    CALL_UP_RESPONSE_HOURS, NO_SHOW_GRACE_HOURS, REST_RESET_HOURS,
)


def _shifts_of_volunteer(volunteer_id):
    out = []
    for s in db.store["duty_shifts"].values():
        dep = db.get("deployments", s["deployment_id"])
        if dep is not None and dep["volunteer_id"] == volunteer_id:
            out.append(s)
    return out


def run_ops():
    now = db.now()
    counts = {
        "certs_expired": 0,
        "offers_expired": 0,
        "no_shows": 0,
        "shifts_completed": 0,
        "fatigue_resets": 0,
        "enrollments_promoted": 0,
        "volunteers_downgraded": 0,
    }

    # Sweep 1: certification expiry.
    affected_volunteers = set()
    for cert in db.all_of("certifications"):
        if cert["status"] == "VERIFIED" and now > timeutil.parse_iso(cert["expires_at"]):
            cert["status"] = "EXPIRED"
            db.touch(cert)
            counts["certs_expired"] += 1
            affected_volunteers.add(cert["volunteer_id"])
    for vid in affected_volunteers:
        vol = db.get("volunteers", vid)
        if vol is not None:
            domain.recompute_readiness(vol)
            db.touch(vol)

    # Sweep 2: auto-downgrade DEPLOYABLE volunteers holding zero VERIFIED certs.
    for vol in db.all_of("volunteers"):
        if vol["readiness_status"] == "DEPLOYABLE" and not domain.verified_kinds(vol["id"]):
            vol["readiness_status"] = "VETTED"
            domain.recompute_readiness(vol)
            db.touch(vol)
            counts["volunteers_downgraded"] += 1

    # Sweep 3: stale offers (created more than 48h ago) -> EXPIRED.
    for dep in db.all_of("deployments"):
        if dep["status"] == "OFFERED":
            deadline = timeutil.parse_iso(dep["created_at"]) + timedelta(hours=CALL_UP_RESPONSE_HOURS)
            if now > deadline:
                dep["status"] = "EXPIRED"
                db.touch(dep)
                counts["offers_expired"] += 1

    # Sweep 4: no-shows (ACCEPTED past operation start_date + 24h grace).
    for dep in db.all_of("deployments"):
        if dep["status"] == "ACCEPTED":
            op = db.get("operations", dep["operation_id"])
            if op is None:
                continue
            deadline = timeutil.parse_date(op["start_date"]) + timedelta(hours=NO_SHOW_GRACE_HOURS)
            if now > deadline:
                dep["status"] = "NO_SHOW"
                db.touch(dep)
                counts["no_shows"] += 1
                domain.recompute_operation(op)

    # Sweep 5a: complete due shifts in ends_at ASC (tie: created_at ASC) order.
    due = [s for s in db.all_of("duty_shifts")
           if s["status"] == "SCHEDULED" and timeutil.parse_iso(s["ends_at"]) <= now]
    due.sort(key=lambda s: (timeutil.parse_iso(s["ends_at"]), s["created_at"], s["_seq"]))
    fatigue_touched = set()
    for shift in due:
        shift["status"] = "COMPLETED"
        db.touch(shift)
        counts["shifts_completed"] += 1
        dep = db.get("deployments", shift["deployment_id"])
        vol = db.get("volunteers", dep["volunteer_id"]) if dep is not None else None
        if vol is not None:
            vol["fatigue_hours"] += calculations.shift_hours(shift["starts_at"], shift["ends_at"])
            fatigue_touched.add(vol["id"])
        if dep is not None and dep["duty_status"] == "ON_DUTY":
            still_on = any(
                x["status"] == "SCHEDULED"
                and timeutil.parse_iso(x["starts_at"]) <= now < timeutil.parse_iso(x["ends_at"])
                for x in domain.shifts_of_deployment(dep["id"])
            )
            if not still_on:
                dep["duty_status"] = "RESTING"
                db.touch(dep)

    # Sweep 5b: fatigue reset, per volunteer, AFTER all completions.
    for vol in db.all_of("volunteers"):
        if vol["fatigue_hours"] <= 0:
            continue
        completed = [s for s in _shifts_of_volunteer(vol["id"]) if s["status"] == "COMPLETED"]
        if not completed:
            continue
        max_end = max(timeutil.parse_iso(s["ends_at"]) for s in completed)
        in_window = any(
            s["status"] == "SCHEDULED"
            and timeutil.parse_iso(s["starts_at"]) <= now < timeutil.parse_iso(s["ends_at"])
            for s in _shifts_of_volunteer(vol["id"])
        )
        if now - max_end >= timedelta(hours=REST_RESET_HOURS) and not in_window:
            vol["fatigue_hours"] = 0
            fatigue_touched.add(vol["id"])
            counts["fatigue_resets"] += 1

    for vid in fatigue_touched:
        vol = db.get("volunteers", vid)
        if vol is not None:
            domain.recompute_readiness(vol)
            db.touch(vol)

    # Sweep 6: waitlist promotion while free seats remain (created_at ASC).
    for course in db.all_of("courses"):
        waiting = [e for e in db.all_of("enrollments")
                   if e["course_id"] == course["id"] and e["status"] == "WAITLISTED"]
        if not waiting:
            continue
        changed = False
        for enrollment in waiting:
            if course["seats_taken"] >= course["capacity"]:
                break
            enrollment["status"] = "ENROLLED"
            enrollment["waitlist_position"] = None
            db.touch(enrollment)
            course["seats_taken"] += 1
            changed = True
            counts["enrollments_promoted"] += 1
        if changed:
            remaining = [e for e in db.all_of("enrollments")
                         if e["course_id"] == course["id"] and e["status"] == "WAITLISTED"]
            for position, enrollment in enumerate(remaining, start=1):
                if enrollment["waitlist_position"] != position:
                    enrollment["waitlist_position"] = position
                    db.touch(enrollment)
            db.touch(course)

    return counts
