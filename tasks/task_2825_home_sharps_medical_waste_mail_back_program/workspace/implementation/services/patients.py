"""Patient status cascades (PRD section 3.9)."""
import clock
import db
from services import accounting, kits, lookup

PAUSE_SOURCE_STATUSES = ("ACTIVE",)
TERMINATE_SOURCE_STATUSES = ("DRAFT", "PENDING_SPONSOR_APPROVAL", "ACTIVE", "PAUSED")


def suspend_patient(patient):
    """The five-hop suspension cascade."""
    # hop 1 -- the patient itself
    patient["status"] = "SUSPENDED"
    patient["suspended_at"] = clock.now_iso()
    db.bump(patient)

    programs = {}
    for enrollment in lookup.patient_enrollments(patient["id"]):
        if enrollment["status"] not in PAUSE_SOURCE_STATUSES:
            continue
        # hop 2 -- the enrollment
        enrollment["status"] = "PAUSED"
        # hop 3 -- the paused enrollment's due date and its ISSUED kits
        enrollment["next_autoship_due_date"] = None
        program = lookup.enrollment_program(enrollment)
        for kit in lookup.enrollment_kits(enrollment["id"]):
            if kit["status"] != "ISSUED":
                continue
            # hop 4 -- the reservation release for each voided kit
            kits.void_kit(kit, kits.VOID_ENROLLMENT_PAUSED, accounting.MEMO_ENROLLMENT_PAUSED, program)
        kits.recompute_kits_issued(enrollment)
        db.bump(enrollment)
        if program is not None:
            programs[program["id"]] = program

    # hop 5 -- the program's available_cents and ACTIVE/EXHAUSTED status
    for program in programs.values():
        accounting.recompute_program(program)
    return patient


def reinstate_patient(patient):
    patient["status"] = "ENROLLED"
    # suspended_at deliberately keeps its historical value
    db.bump(patient)
    today = clock.now_date_iso()
    for enrollment in lookup.patient_enrollments(patient["id"]):
        if enrollment["status"] != "PAUSED":
            continue
        enrollment["status"] = "ACTIVE"
        enrollment["next_autoship_due_date"] = today
        db.bump(enrollment)
    return patient


def withdraw_patient(patient):
    patient["status"] = "WITHDRAWN"
    db.bump(patient)

    programs = {}
    for enrollment in lookup.patient_enrollments(patient["id"]):
        if enrollment["status"] not in TERMINATE_SOURCE_STATUSES:
            continue
        enrollment["status"] = "TERMINATED"
        enrollment["next_autoship_due_date"] = None
        program = lookup.enrollment_program(enrollment)
        for kit in lookup.enrollment_kits(enrollment["id"]):
            if kit["status"] != "ISSUED":
                continue
            kits.void_kit(
                kit, kits.VOID_ENROLLMENT_TERMINATED, accounting.MEMO_ENROLLMENT_TERMINATED, program
            )
        kits.recompute_kits_issued(enrollment)
        db.bump(enrollment)
        if program is not None:
            programs[program["id"]] = program

    for program in programs.values():
        accounting.recompute_program(program)
    return patient
