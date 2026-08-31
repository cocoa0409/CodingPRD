"""Deterministic, atomic cascades (PRD §2.10, §3.2, §3.3, §3.6, §3.7)."""

from calc import ZERO, NO_SHOW_SUSPEND_THRESHOLD, dec
from rollups import (
    appointments_of_event,
    appointments_of_resident,
    assignments_of_event,
    effective_posture,
    events_of_site,
    lines_of_appointment,
    live_reserved_slot_count,
    live_slot_capacity,
    program_of_event,
)
from store import clock_raw, ordered, set_and_touch, store

OPEN_APPOINTMENT_STATUSES = ("REQUESTED", "CONFIRMED", "WAITLISTED")


def sweep_order(appointments):
    """created_at ascending, tie-broken by queue_seq ascending (never by id)."""
    return sorted(appointments, key=lambda a: (a["created_at"], a["queue_seq"] or 0))


def append_finding(event, origin, result, finding_code, inspector_user_id):
    entry = {
        "origin": origin,
        "result": result,
        "finding_code": finding_code,
        "inspector_user_id": inspector_user_id,
        "recorded_at": clock_raw(),
    }
    findings = list(event["containment_findings"])
    findings.append(entry)
    event["containment_findings"] = findings


def cancel_appointment(appointment, reason):
    set_and_touch(
        appointment,
        status="CANCELLED",
        cancel_reason=reason,
        waitlist_reason=None,
        reserved_kg=ZERO,
    )


def release_assignment(assignment, reason):
    set_and_touch(assignment, status="RELEASED", released_reason=reason)


# ------------------------------------------------------- resident suspension --

def maybe_suspend_resident(resident):
    """PRD §3.7 — a second no-show strike suspends the resident automatically."""
    if resident is None:
        return
    strikes = len([a for a in appointments_of_resident(resident["id"])
                   if a["status"] == "NO_SHOW"])
    if strikes < NO_SHOW_SUSPEND_THRESHOLD:
        return
    if resident["eligibility_status"] != "ELIGIBLE":
        return
    set_and_touch(resident, eligibility_status="SUSPENDED")
    for appointment in appointments_of_resident(resident["id"]):
        if appointment["status"] in OPEN_APPOINTMENT_STATUSES:
            cancel_appointment(appointment, "RESIDENT_SUSPENDED")


# ------------------------------------------------------- containment cascade --

def containment_deficiency_cascade(event):
    """Every CONFIRMED appointment drops to the waitlist and gives back its
    reservation, in created_at ascending order."""
    for appointment in ordered(appointments_of_event(event["id"])):
        if appointment["status"] != "CONFIRMED":
            continue
        set_and_touch(
            appointment,
            status="WAITLISTED",
            waitlist_reason="CONTAINMENT_DEFICIENCY",
            reserved_kg=ZERO,
        )


def waitlist_promotion_sweep(event):
    """PRD §3.6 — put back the people the deficiency displaced."""
    program = program_of_event(event)
    candidates = [a for a in appointments_of_event(event["id"])
                  if a["status"] == "WAITLISTED"
                  and a["waitlist_reason"] == "CONTAINMENT_DEFICIENCY"]
    for appointment in sweep_order(candidates):
        capacity = live_slot_capacity(event)
        if live_reserved_slot_count(event) + 1 > capacity:
            continue
        resident = store.residents.get(appointment["resident_id"])
        if resident is None or resident["eligibility_status"] != "ELIGIBLE":
            continue
        if program is None or effective_posture(program) != "OPEN":
            continue
        set_and_touch(
            appointment,
            status="CONFIRMED",
            waitlist_reason=None,
            reserved_kg=dec(appointment["declared_total_kg"]),
        )


def force_event_deficient(event, origin, finding_code, inspector_user_id):
    """Force the containment axis to DEFICIENT and run the full cascade."""
    event["containment_status"] = "DEFICIENT"
    append_finding(event, origin, "FAIL", finding_code, inspector_user_id)
    set_and_touch(event)
    containment_deficiency_cascade(event)


# ------------------------------------------------------------ site cascades --

def site_suspension_cascade(site, inspector_user_id, finding_code):
    """PRD §3.2 — suspending a site forces its live events deficient."""
    for event in ordered(events_of_site(site["id"])):
        if event["lifecycle_status"] not in ("SITE_CONFIRMED", "OPEN_FOR_REGISTRATION"):
            continue
        force_event_deficient(event, "SITE", finding_code, inspector_user_id)


# ----------------------------------------------------------- event cascades --

def close_event_sweep(event):
    """PRD §3.3 — two passes over the event's appointments, created_at ASC."""
    snapshot = ordered(appointments_of_event(event["id"]))
    for appointment in snapshot:
        if appointment["status"] == "WAITLISTED":
            set_and_touch(appointment, status="EXPIRED", waitlist_reason=None)
    for appointment in snapshot:
        if appointment["status"] not in ("REQUESTED", "CONFIRMED"):
            continue
        set_and_touch(appointment, status="NO_SHOW", reserved_kg=ZERO,
                      waitlist_reason=None)
        maybe_suspend_resident(store.residents.get(appointment["resident_id"]))


def cancel_event_cascade(event, from_status):
    """PRD §3.3 — the three cancellation branches."""
    if from_status == "OPEN_FOR_REGISTRATION":
        for appointment in ordered(appointments_of_event(event["id"])):
            if appointment["status"] in OPEN_APPOINTMENT_STATUSES:
                cancel_appointment(appointment, "EVENT_CANCELLED")
    if from_status in ("SITE_CONFIRMED", "OPEN_FOR_REGISTRATION"):
        for assignment in ordered(assignments_of_event(event["id"])):
            if assignment["status"] == "ACTIVE":
                release_assignment(assignment, "EVENT_CANCELLED")


# ----------------------------------------------------- referral rewrite (§3.7)

def rewrite_lines_as_referred(appointment):
    for line in lines_of_appointment(appointment["id"]):
        set_and_touch(
            line,
            disposition="REFERRED_BUSINESS",
            rejection_reason_code="BUSINESS_GENERATOR",
            estimated_disposal_cost_cents=0,
        )
