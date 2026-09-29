"""Derived state: clinic posture, its cascades, and the logical clock move.

Every derived quantity here is recomputed from scratch (PRD 1, 2.8): the
counters are never incrementally patched, which is what makes the compensating
actions conserve them exactly.
"""

from datetime import timedelta

import calc
from store import db, ordered, touch


# ---------------------------------------------------------------------------
# counter recomputation
# ---------------------------------------------------------------------------

def recompute_physician(physician_id):
    if physician_id is None:
        return
    physician = db.physicians.get(physician_id)
    if physician is None:
        return
    value = calc.physician_supervision_load(physician_id)
    if physician["current_supervised_count"] != value:
        physician["current_supervised_count"] = value
        touch(physician)


def recompute_clinician(clinician_id):
    if clinician_id is None:
        return
    clinician = db.clinicians.get(clinician_id)
    if clinician is None:
        return
    value = calc.clinician_active_assignment_count(clinician_id)
    if clinician["active_assignment_count"] != value:
        clinician["active_assignment_count"] = value
        touch(clinician)


def recompute_patient_balance(patient_id):
    patient = db.patients.get(patient_id)
    if patient is None:
        return
    value = calc.patient_outstanding_balance(patient_id)
    if patient["outstanding_balance_cents"] != value:
        patient["outstanding_balance_cents"] = value
        touch(patient)


def recompute_patient_therapy(patient_id):
    patient = db.patients.get(patient_id)
    if patient is None:
        return
    classes = calc.patient_active_therapy_classes(patient_id)
    if (
        patient["active_therapy_classes"] != classes
        or patient["active_therapy_class_count"] != len(classes)
    ):
        patient["active_therapy_classes"] = classes
        patient["active_therapy_class_count"] = len(classes)
        touch(patient)


# ---------------------------------------------------------------------------
# clinic posture
# ---------------------------------------------------------------------------

def derive_posture(on_duty, min_required):
    if on_duty == 0:
        return "CLOSED"
    if on_duty < min_required:
        return "LIMITED"
    return "OPEN"


def _on_duty_count(clinic_id):
    total = 0
    for assignment in db.assignments.values():
        if assignment["clinic_id"] == clinic_id and assignment["status"] == "ACTIVE":
            total += 1
    return total


def _waiting_count(clinic_id):
    total = 0
    for entry in db.queue_entries.values():
        if entry["clinic_id"] == clinic_id and entry["status"] == "WAITING":
            total += 1
    return total


def _defer_walk_ins(clinic_id):
    for entry in ordered(db.queue_entries.values()):
        if (
            entry["clinic_id"] == clinic_id
            and entry["kind"] == "WALK_IN"
            and entry["status"] == "WAITING"
        ):
            entry["status"] = "DEFERRED_CLOSURE"
            touch(entry)


def _defer_all(clinic_id):
    for entry in ordered(db.queue_entries.values()):
        if entry["clinic_id"] == clinic_id and entry["status"] in (
            "SCHEDULED",
            "WAITING",
        ):
            entry["status"] = "DEFERRED_CLOSURE"
            touch(entry)


def _cancel_screening_visits(clinic_id):
    for visit in ordered(db.visits.values()):
        if visit["clinic_id"] == clinic_id and visit["clinical_status"] == "SCREENING":
            visit["clinical_status"] = "CANCELLED_CLOSURE"
            touch(visit)


def refresh_clinic(clinic, extra_changed=False):
    """Re-derive every clinic reading, run the posture cascade, bump once."""
    if clinic is None:
        return
    before = (
        clinic["on_duty_clinician_count"],
        clinic["open_status"],
        clinic["waiting_count"],
        clinic["posted_wait_minutes"],
        clinic["last_realized_wait_minutes"],
    )

    on_duty = _on_duty_count(clinic["id"])
    clinic["on_duty_clinician_count"] = on_duty

    previous_posture = clinic["open_status"]
    posture = derive_posture(on_duty, clinic["min_clinicians_required"])
    clinic["open_status"] = posture

    if posture != previous_posture:
        if posture == "LIMITED" and previous_posture == "OPEN":
            _defer_walk_ins(clinic["id"])
        elif posture == "CLOSED" and previous_posture in ("OPEN", "LIMITED"):
            _defer_all(clinic["id"])
            _cancel_screening_visits(clinic["id"])

    clinic["waiting_count"] = _waiting_count(clinic["id"])
    clinic["posted_wait_minutes"] = calc.posted_wait_minutes(clinic)

    after = (
        clinic["on_duty_clinician_count"],
        clinic["open_status"],
        clinic["waiting_count"],
        clinic["posted_wait_minutes"],
        clinic["last_realized_wait_minutes"],
    )
    if before != after or extra_changed:
        touch(clinic)


def activate_if_due(assignment):
    """SCHEDULED -> ACTIVE when the logical clock already sits in the interval."""
    if assignment["status"] != "SCHEDULED":
        return False
    if assignment["starts_at"] <= db.clock < assignment["ends_at"]:
        assignment["status"] = "ACTIVE"
        return True
    return False


# ---------------------------------------------------------------------------
# the logical clock move
# ---------------------------------------------------------------------------

def advance_clock(target):
    db.clock = target

    activated = []
    completed = []
    abandoned = []
    affected = []

    def mark(clinic_id):
        if clinic_id is not None and clinic_id not in affected:
            affected.append(clinic_id)

    for assignment in ordered(db.assignments.values()):
        if assignment["status"] != "SCHEDULED":
            continue
        if assignment["starts_at"] <= db.clock < assignment["ends_at"]:
            assignment["status"] = "ACTIVE"
            touch(assignment)
            activated.append(assignment["id"])
            mark(assignment["clinic_id"])

    for assignment in ordered(db.assignments.values()):
        if assignment["status"] != "ACTIVE":
            continue
        if db.clock >= assignment["ends_at"]:
            assignment["status"] = "COMPLETED"
            touch(assignment)
            completed.append(assignment["id"])
            mark(assignment["clinic_id"])

    limit = timedelta(minutes=calc.ABANDON_AFTER_MINUTES)
    for entry in ordered(db.queue_entries.values()):
        if entry["status"] != "WAITING":
            continue
        if entry.get("arrived_at") is None:
            continue
        if db.clock - entry["arrived_at"] >= limit:
            entry["status"] = "ABANDONED"
            touch(entry)
            abandoned.append(entry["id"])
            mark(entry["clinic_id"])

    touched_ids = set(activated) | set(completed)
    for clinic_id in list(affected):
        refresh_clinic(db.clinics.get(clinic_id))

    for assignment_id in ordered(
        [db.assignments[a] for a in touched_ids if a in db.assignments]
    ):
        recompute_physician(assignment_id["pinned_supervising_physician_id"])
        recompute_clinician(assignment_id["clinician_id"])

    ordered_clinics = [
        clinic["id"]
        for clinic in ordered(db.clinics.values())
        if clinic["id"] in affected
    ]

    return {
        "activated_assignment_ids": activated,
        "completed_assignment_ids": completed,
        "abandoned_queue_entry_ids": abandoned,
        "affected_clinic_ids": ordered_clinics,
    }
