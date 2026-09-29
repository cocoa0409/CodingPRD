"""Shared mutations: ledger entries, cascades A/B/C and derived-state maintenance."""
from decimal import Decimal

from flask import g

import calc
from core import ZERO2, base_row, d2, now, store, touch

# ---------------------------------------------------------------------------
# The immutable training record
# ---------------------------------------------------------------------------

def append_entry(recruit, kind, stage_code=None, hours_delta=None, topic_code=None,
                 actor_role=None, actor_user_id=None, subject_entity=None,
                 subject_entity_id=None, detail=""):
    row = base_row()
    row.update({
        "recruit_id": recruit["id"],
        "academy_class_id": recruit["academy_class_id"],
        "kind": kind,
        "stage_code": stage_code,
        "hours_delta": d2(hours_delta) if hours_delta is not None else ZERO2,
        "topic_code": topic_code,
        "actor_role": actor_role if actor_role is not None else getattr(g, "role", "system"),
        "actor_user_id": actor_user_id if actor_user_id is not None else getattr(g, "user_id", "system"),
        "subject_entity": subject_entity,
        "subject_entity_id": subject_entity_id,
        "detail": detail,
        "recorded_at_utc": now(),
    })
    store.entries[row["id"]] = row
    return row


def append_system_entry(recruit, kind, **kwargs):
    kwargs.setdefault("actor_role", "system")
    kwargs.setdefault("actor_user_id", "system")
    return append_entry(recruit, kind, **kwargs)


# ---------------------------------------------------------------------------
# Session enrolment maintenance
# ---------------------------------------------------------------------------

def rederive_enrollment(session, direction="down"):
    count = calc.session_enrolled_count(session)
    touch(session)
    if direction == "up":
        if session["status"] == "UNDER_MIN_ENROLLMENT" and count >= session["min_enrollment"]:
            session["status"] = "SCHEDULED"
    else:
        if session["status"] == "SCHEDULED" and count < session["min_enrollment"]:
            session["status"] = "UNDER_MIN_ENROLLMENT"
    return count


def void_provisional_attendance(recruit, void_reason):
    """Cascade levels that void a recruit's provisional ledger rows."""
    affected = []
    for row in calc.recruit_attendance(recruit["id"]):
        if row["ledger_status"] != "PROVISIONAL":
            continue
        row["ledger_status"] = "VOIDED"
        row["void_reason"] = void_reason
        row["credited_hours"] = ZERO2
        row["counted_absence_hours"] = ZERO2
        touch(row)
        session = store.sessions.get(row["course_session_id"])
        if session is not None and session not in affected:
            affected.append(session)
    for session in affected:
        rederive_enrollment(session, "down")
    return affected


# ---------------------------------------------------------------------------
# Cohort posture
# ---------------------------------------------------------------------------

def rederive_class_projection(cls):
    if cls is None:
        return
    touch(cls)
    if cls["status"] == "IN_SESSION" and calc.class_has_projection_shortfall(cls):
        cls["status"] = "AT_RISK"
    elif cls["status"] == "AT_RISK" and not calc.class_has_projection_shortfall(cls):
        cls["status"] = "IN_SESSION"


# ---------------------------------------------------------------------------
# Academy standing after an hours movement
# ---------------------------------------------------------------------------

def reevaluate_academy_standing(recruit):
    """Applied to each attending recruit after a delivery."""
    standard = calc.standard_for_recruit(recruit)
    touch(recruit)
    if standard is not None:
        accrual = calc.recruit_unexcused_absence_hours(recruit)
        if accrual > d2(standard["max_absence_hours"]) and \
                recruit["academy_status"] in ("IN_PROGRESS", "REMEDIATION"):
            recruit["academy_status"] = "DISMISSAL_PENDING"
            void_provisional_attendance(recruit, "academy dismissal pending")
            return
    if recruit["academy_status"] == "IN_PROGRESS" and calc.curriculum_satisfied(recruit):
        recruit["academy_status"] = "COMPLETE"


def reevaluate_academy_standing_after_reversal(recruit):
    touch(recruit)
    if recruit["academy_status"] == "COMPLETE" and not calc.curriculum_satisfied(recruit):
        recruit["academy_status"] = "IN_PROGRESS"


# ---------------------------------------------------------------------------
# Probation schedule
# ---------------------------------------------------------------------------

def rederive_probation(recruit):
    if calc.derive_probation_schedule(recruit):
        touch(recruit)
        return True
    return False


# ---------------------------------------------------------------------------
# Rotations
# ---------------------------------------------------------------------------

def abort_rotation(rotation, reason, void_reports=True):
    was_counted = rotation["status"] in ("ACTIVE", "REMEDIAL")
    rotation["status"] = "ABORTED"
    rotation["abort_reason"] = reason
    touch(rotation)
    if void_reports:
        for report in calc.rotation_reports(rotation["id"]):
            report["voided"] = True
            touch(report)
    instructor = store.instructors.get(rotation["fto_instructor_id"])
    if instructor is not None and was_counted:
        touch(instructor)
    return rotation


def abort_open_rotations(recruit, reason):
    for rotation in calc.recruit_rotations(recruit["id"]):
        if rotation["status"] in ("PLANNED", "ACTIVE", "REMEDIAL"):
            abort_rotation(rotation, reason)


def restore_probation_after_abort(recruit):
    """The cascade-B compensation performed when a remedial rotation is aborted."""
    if recruit["probation_status"] != "EXTENSION_REQUIRED":
        return
    for rotation in calc.recruit_rotations(recruit["id"]):
        if rotation["status"] == "REMEDIAL":
            return
    recruit["probation_status"] = "ACTIVE"
    touch(recruit)
    rederive_probation(recruit)


# ---------------------------------------------------------------------------
# Cascade A: terminal examination failure
# ---------------------------------------------------------------------------

def cascade_a(recruit):
    if recruit["academy_status"] in ("IN_PROGRESS", "REMEDIATION"):
        recruit["academy_status"] = "DISMISSAL_PENDING"
        touch(recruit)
        void_provisional_attendance(recruit, "academy dismissal pending")


# ---------------------------------------------------------------------------
# Cascade B: the remedial flip after a filed observation report
# ---------------------------------------------------------------------------

def cascade_b(rotation, recruit):
    terminal, _rolling = calc.rotation_competency(rotation)
    touch(rotation)
    if terminal is None:
        return
    if rotation["status"] == "ACTIVE" and terminal < calc.COMPETENCY_THRESHOLD:
        rotation["status"] = "REMEDIAL"
        if recruit["probation_status"] == "ACTIVE":
            recruit["probation_status"] = "EXTENSION_REQUIRED"
            touch(recruit)
            rederive_probation(recruit)
    elif rotation["status"] == "REMEDIAL" and terminal >= calc.COMPETENCY_THRESHOLD:
        rotation["status"] = "ACTIVE"


# ---------------------------------------------------------------------------
# Cascade C: instructor certification revocation
# ---------------------------------------------------------------------------

def cascade_c(instructor, reason):
    instructor["certification_status"] = "REVOKED"
    instructor["fto_certified"] = False
    instructor["authorized_topic_codes"] = []
    instructor["revocation_reason"] = reason
    touch(instructor)

    # Level 2 - approved lesson plans authored by this instructor.
    plans = [p for p in calc.ordered(list(store.plans.values()))
             if p["instructor_id"] == instructor["id"]]
    for plan in plans:
        if plan["status"] == "APPROVED":
            plan["status"] = "REVISION_REQUESTED"
            plan["approved_revision_number"] = None
            plan["reviewer_notes"] = "authoring instructor certification revoked"
            touch(plan)

    # Level 3 - live sessions of record for this instructor.
    affected_classes = []
    for session in calc.ordered(list(store.sessions.values())):
        if session["instructor_id"] != instructor["id"]:
            continue
        if session["status"] not in ("SCHEDULED", "UNDER_MIN_ENROLLMENT"):
            continue
        session["status"] = "CANCELLED"
        touch(session)
        for row in calc.session_attendance(session["id"]):
            if row["ledger_status"] == "PROVISIONAL":
                row["ledger_status"] = "VOIDED"
                row["void_reason"] = "session cancelled"
                row["credited_hours"] = ZERO2
                row["counted_absence_hours"] = ZERO2
                touch(row)
        cls = store.classes.get(session["academy_class_id"])
        if cls is not None and cls not in affected_classes:
            affected_classes.append(cls)

    # Level 4 - affected cohorts re-derive projected hours.
    for cls in affected_classes:
        touch(cls)
        if cls["status"] == "IN_SESSION" and calc.class_has_projection_shortfall(cls):
            cls["status"] = "AT_RISK"

    # Independently: every live rotation naming this instructor as FTO aborts.
    for rotation in calc.instructor_rotations(instructor["id"]):
        if rotation["status"] in ("PLANNED", "ACTIVE", "REMEDIAL"):
            abort_rotation(rotation, "FTO certification revoked")
    touch(instructor)


# ---------------------------------------------------------------------------
# Delivery and its reversal
# ---------------------------------------------------------------------------

def deliver_session(session):
    cls = store.classes.get(session["academy_class_id"])
    session["status"] = "DELIVERED"
    session["delivered_at"] = now()
    touch(session)
    recruits = []
    for row in calc.session_attendance(session["id"]):
        if row["ledger_status"] != "PROVISIONAL":
            continue
        row["ledger_status"] = "CREDITED"
        row["credited_hours"] = calc.row_credited_hours(row, session)
        row["counted_absence_hours"] = calc.row_counted_absence_hours(row, session)
        row["void_reason"] = None
        touch(row)
        recruit = store.recruits.get(row["recruit_id"])
        if recruit is None:
            continue
        append_entry(
            recruit,
            "HOURS_CREDIT",
            stage_code="ACADEMY",
            hours_delta=row["credited_hours"],
            topic_code=session["topic_code"],
            subject_entity="CourseSession",
            subject_entity_id=session["id"],
            detail="hours credited from delivered session",
        )
        if recruit not in recruits:
            recruits.append(recruit)
    if cls is not None:
        touch(cls)
        if cls["status"] == "FORMING":
            cls["status"] = "IN_SESSION"
    for recruit in recruits:
        reevaluate_academy_standing(recruit)
    return recruits


def void_session_delivery(session, reason):
    cls = store.classes.get(session["academy_class_id"])
    session["status"] = "VOIDED"
    session["void_reason"] = reason
    session["delivered_at"] = None
    touch(session)
    recruits = []
    for row in calc.session_attendance(session["id"]):
        if row["ledger_status"] != "CREDITED":
            continue
        previous = d2(row["credited_hours"])
        row["ledger_status"] = "VOIDED"
        row["credited_hours"] = ZERO2
        row["counted_absence_hours"] = ZERO2
        row["void_reason"] = reason
        touch(row)
        recruit = store.recruits.get(row["recruit_id"])
        if recruit is None:
            continue
        append_entry(
            recruit,
            "HOURS_REVERSAL",
            stage_code="ACADEMY",
            hours_delta=-previous,
            topic_code=session["topic_code"],
            subject_entity="CourseSession",
            subject_entity_id=session["id"],
            detail="hours reversed by voided delivery",
        )
        if recruit not in recruits:
            recruits.append(recruit)
    if cls is not None:
        touch(cls)
        if cls["status"] == "IN_SESSION" and calc.class_has_projection_shortfall(cls):
            cls["status"] = "AT_RISK"
    for recruit in recruits:
        reevaluate_academy_standing_after_reversal(recruit)
    return recruits
