"""Patient state machine and its cascades (PRD 3.1, 3.5, 3.10, 3.14)."""
from datetime import timedelta

import db
from constants import DOSE_OPEN, PRIVILEGE_GRANTED, REINSTATEMENT_SURCHARGE
from errors import ApiError
from services import carry, entity, program as program_svc, stability
from services.num import r1, r2


def patient_of(patient_id):
    row = db.patients.get(patient_id)
    if row is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "No Patient with the supplied id")
    return row


def program_of(patient):
    return db.programs.get(patient.get("program_id"))


SWEEP_STATUS = {"SCHEDULED"}


def _prior_order_for(patient_id, exclude_id):
    rows = [
        r
        for r in db.dose_orders.values()
        if r.get("patient_id") == patient_id and r["id"] != exclude_id
    ]
    if not rows:
        return None
    rows.sort(key=lambda r: (str(r.get("created_at", "")), str(r.get("id", ""))))
    return rows[-1]


def supersede_orders(patient, keep_order_id):
    """A new order supersedes the patient's prior orders, preserving the titration ceiling."""
    for row in db.dose_orders.values():
        if row.get("patient_id") != patient["id"] or row["id"] == keep_order_id:
            continue
        if row.get("status") in ("DRAFT", "ACTIVE", "SUSPENDED"):
            row["status"] = "DISCONTINUED"
            db.stamp(row)
            for dose in db.dose_dispenses.values():
                if dose.get("dose_order_id") == row["id"] and dose.get("status") == "SCHEDULED":
                    dose["status"] = "CANCELLED"
                    dose["completed_at"] = db.fmt_dt(db.clock_dt())
                    db.stamp(dose)


# ---------------------------------------------------------------------------
# confirm-diagnosis: PENDING_ADMISSION -> ADMITTED
# ---------------------------------------------------------------------------
def confirm_diagnosis(patient, actor):
    program = program_of(patient)
    if patient.get("status") != "PENDING_ADMISSION":
        raise ApiError("ERR_PATIENT_NOT_PENDING_ADMISSION", "Patient is not PENDING_ADMISSION")
    if patient.get("diagnosis_code") not in ("F11_10", "F11_20", "F11_99"):
        raise ApiError(
            "ERR_INVALID_DIAGNOSIS_CODE",
            "diagnosis_code is not in the ICD-10 F11 opioid dependence block",
        )
    if actor.role == "Physician":
        if actor.program_id is None or actor.program_id != patient.get("program_id"):
            raise ApiError(
                "ERR_PHYSICIAN_NOT_IN_PROGRAM",
                "The acting physician belongs to another program",
            )
    if program is not None:
        program_svc.ensure_normal_for_medication(program)
    if patient.get("diversion_standing") == "CONFIRMED_DIVERSION":
        raise ApiError(
            "ERR_DIVERSIONS_OR_FINDINGS_OPEN",
            "The patient is under confirmed diversion",
        )
    for row in db.diversion_cases.values():
        if row.get("patient_id") == patient["id"] and row.get("status") in ("OPEN", "UNDER_REVIEW"):
            raise ApiError(
                "ERR_PATIENT_FLAGGED_FOR_DIVERSION",
                "An open diversion case references this patient",
            )
    tracker = entity.refresh_tracker(patient)
    if tracker.get("dual_enrollment_flag"):
        raise ApiError(
            "ERR_DUAL_ENROLLMENT_DETECTED",
            "The registry reports dual enrollment for this patient",
        )

    patient["diagnosis_confirmed"] = True
    patient["status"] = "ADMITTED"
    patient["admission_datetime"] = db.fmt_dt(db.clock_dt())
    patient["time_in_treatment_days"] = 0
    patient["stability_posting"] = stability.direction_a(patient)
    db.stamp(patient)
    return patient


# ---------------------------------------------------------------------------
# Dose order activation (ADMITTED -> ACTIVE second step)
# ---------------------------------------------------------------------------
def activate_dose_order(order, actor):
    patient = patient_of(order["patient_id"])
    program = program_of(patient)

    if order.get("status") == "SUSPENDED":
        if program is not None:
            program_svc.ensure_normal_for_medication(program)
        order["status"] = "ACTIVE"
        order["phase_at_authorization"] = patient.get("treatment_phase")
        db.stamp(order)
        return order

    if order.get("status") != "DRAFT":
        raise ApiError("ERR_DOSE_ORDER_NOT_DRAFT", "DoseOrder is not DRAFT")
    if patient.get("status") != "ADMITTED":
        raise ApiError("ERR_PATIENT_NOT_ADMITTED", "Patient is not ADMITTED")
    if (order.get("ordered_daily_mg") or 0.0) > (order.get("medication_ceiling_mg") or 0.0):
        raise ApiError(
            "ERR_DOSE_EXCEEDS_MEDICATION_CEILING",
            "ordered_daily_mg exceeds the medication ceiling",
        )
    previous = order.get("previous_ordered_daily_mg") or 0.0
    if order.get("_has_prior_order"):
        if (order.get("ordered_daily_mg") or 0.0) > previous + 10.0:
            raise ApiError(
                "ERR_DOSE_TITRATION_TOO_FAST",
                "ordered_daily_mg exceeds the previous ordered dose by more than 10.0 mg",
            )
    if program is not None:
        program_svc.ensure_normal_for_medication(program)

    order["status"] = "ACTIVE"
    order["phase_at_authorization"] = patient.get("treatment_phase")
    db.stamp(order)
    patient["status"] = "ACTIVE"
    patient["stability_posting"] = stability.direction_a(patient)
    db.stamp(patient)
    return order


# ---------------------------------------------------------------------------
# Privilege revocation cascade
# ---------------------------------------------------------------------------
def revoke_privilege(privilege, reset_phase=True, cancel_doses=True, quarantine_lots=True):
    """REVOKED: freed_carries, cancelled take-home doses, voided mg, lot quarantine."""
    if not cancel_doses:
        privilege["decision"] = "REVOKED"
        privilege["freed_carries"] = privilege.get("approved_carries") or 0
        privilege["approved_carries"] = 0
        privilege["hold_ledger_delta"] = 1
        db.stamp(privilege)
        return privilege

    privilege["decision"] = "REVOKED"
    privilege["freed_carries"] = privilege.get("approved_carries") or 0
    privilege["approved_carries"] = 0
    privilege["hold_ledger_delta"] = 1

    cancelled = []
    for row in db.dose_dispenses.values():
        if row.get("privilege_id") != privilege["id"]:
            continue
        if row.get("status") != "SCHEDULED":
            continue
        row["status"] = "CANCELLED"
        row["completed_at"] = db.fmt_dt(db.clock_dt())
        db.stamp(row)
        cancelled.append(row)

    patient = patient_of(privilege["patient_id"])
    ledger = carry.ensure_ledger_for_patient(patient)
    carry.void_carried_mg(ledger, cancelled)

    if quarantine_lots:
        for row in cancelled:
            lot = db.inventory_lots.get(row.get("inventory_lot_id"))
            if lot is not None and lot.get("status") != "DESTROYED":
                lot["status"] = "QUARANTINED"
                db.stamp(lot)

    carry.refresh_carry_ledger(ledger, bump=True)
    patient["carries_used"] = ledger.get("carries_used") or 0
    if reset_phase:
        patient["treatment_phase"] = "INDUCTION"
    db.stamp(patient)
    db.stamp(privilege)

    carry.release_carries(privilege.get("program_id"), privilege.get("freed_carries") or 0)
    return privilege


def revoke_patient_privileges(patient, reason_code=None, reset_phase=False, quarantine_lots=True):
    for row in list(db.take_home_privileges.values()):
        if row.get("patient_id") != patient["id"]:
            continue
        if row.get("decision") in PRIVILEGE_GRANTED:
            revoke_privilege(row, reset_phase=reset_phase, quarantine_lots=quarantine_lots)
        elif row.get("decision") == "PENDING_REVIEW" and reason_code is not None and row.get(
            "timetable_reconciled"
        ):
            row["decision"] = "DENIED"
            row["denial_reason_code"] = reason_code
            row["hold_ledger_delta"] = 0
            db.stamp(row)
    carry.refresh_patient_carries(patient, bump=False)


# ---------------------------------------------------------------------------
# miss cascade -> SUSPENDED_NON_COMPLIANT
# ---------------------------------------------------------------------------
def suspend_non_compliant(patient):
    """ACTIVE -> SUSPENDED_NON_COMPLIANT with the full second-hop cascade."""
    if patient.get("status") != "ACTIVE":
        return patient
    if (patient.get("missed_dose_streak") or 0) < 3:
        return patient

    patient["status"] = "SUSPENDED_NON_COMPLIANT"

    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient["id"]:
            continue
        if row.get("status") in DOSE_OPEN:
            row["status"] = "CANCELLED"
            row["completed_at"] = db.fmt_dt(db.clock_dt())
            db.stamp(row)

    ledger = carry.ensure_ledger_for_patient(patient)
    cancelled_take_home = []
    for row in list(db.take_home_privileges.values()):
        if row.get("patient_id") != patient["id"]:
            continue
        if row.get("decision") in PRIVILEGE_GRANTED:
            row["decision"] = "REVOKED"
            row["freed_carries"] = row.get("approved_carries") or 0
            row["approved_carries"] = 0
            row["hold_ledger_delta"] = 1
            db.stamp(row)
            carry.release_carries(row.get("program_id"), row.get("freed_carries") or 0)
        elif row.get("decision") == "PENDING_REVIEW" and row.get("timetable_reconciled"):
            row["decision"] = "DENIED"
            row["denial_reason_code"] = "ACTIVE_DENIAL_HISTORY"
            row["hold_ledger_delta"] = 0
            db.stamp(row)

    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient["id"]:
            continue
        if row.get("source_type") == "TAKE_HOME_ISSUANCE" and row.get("status") == "CANCELLED":
            cancelled_take_home.append(row)
    carry.void_carried_mg(ledger, cancelled_take_home)
    carry.refresh_carry_ledger(ledger, bump=True)
    patient["carries_used"] = ledger.get("carries_used") or 0

    patient["stability_posting"] = stability.direction_b(patient)
    db.stamp(patient)
    recut_risk(patient)

    for order in db.dose_orders.values():
        if order.get("patient_id") != patient["id"]:
            continue
        if order.get("status") == "ACTIVE":
            order["status"] = "SUSPENDED"
            db.stamp(order)
    return patient


def recut_risk(patient, surcharge=0.0):
    """Recompute risk_score_points from its formula, add any surcharge, recut the tier."""
    from services import patient as patient_svc

    score = patient_svc.compute_risk_score(patient)
    if surcharge:
        score = r1(score + surcharge)
    patient["risk_score_points"] = score
    patient["risk_tier"] = patient_svc.cut_tier(score)
    return score


# ---------------------------------------------------------------------------
# reinstate
# ---------------------------------------------------------------------------
def reinstate(patient, actor):
    program = program_of(patient)
    if patient.get("status") != "SUSPENDED_NON_COMPLIANT":
        raise ApiError("ERR_PATIENT_NOT_SUSPENDED", "Patient is not SUSPENDED_NON_COMPLIANT")
    if (patient.get("missed_dose_streak") or 0) >= 3:
        raise ApiError(
            "ERR_REINSTATEMENT_DENIAL_STREAK",
            "missed_dose_streak is still 3 or more",
        )
    if patient.get("counseling_standing") == "COUNSELING_DEFICIENT":
        raise ApiError(
            "ERR_COUNSELING_CADENCE_BREACHED",
            "counseling_standing is COUNSELING_DEFICIENT",
        )
    if program is not None and program.get("posture") == "FROZEN":
        raise ApiError("ERR_PROGRAM_OPERATIONALLY_BLOCKED", "Program posture is FROZEN")

    patient["status"] = "ACTIVE"
    patient["treatment_phase"] = "INDUCTION"
    from services import patient as patient_svc

    patient_svc.refresh_counseling(patient)
    patient["stability_posting"] = stability.direction_a(patient)
    recut_risk(patient, surcharge=REINSTATEMENT_SURCHARGE)
    db.stamp(patient)
    return patient


# ---------------------------------------------------------------------------
# discharge
# ---------------------------------------------------------------------------
def discharge(patient, reason_code, actor):
    if patient.get("status") not in ("ADMITTED", "ACTIVE", "SUSPENDED_NON_COMPLIANT"):
        raise ApiError("ERR_PATIENT_NOT_DISCHARGEABLE", "Patient is already in a terminal status")
    if reason_code not in ("TRANSFER", "REGULATORY", "NON_PAYMENT", "BEHAVIORAL"):
        raise ApiError(
            "ERR_INVALID_DISCHARGE_REASON",
            "reason_code must be one of TRANSFER, REGULATORY, NON_PAYMENT, BEHAVIORAL",
        )
    patient["status"] = "ADMINISTRATIVELY_DISCHARGED"
    for order in db.dose_orders.values():
        if order.get("patient_id") == patient["id"] and order.get("status") == "ACTIVE":
            order["status"] = "DISCONTINUED"
            db.stamp(order)
    for row in db.dose_dispenses.values():
        if row.get("patient_id") != patient["id"]:
            continue
        if row.get("status") in DOSE_OPEN:
            row["status"] = "CANCELLED"
            row["completed_at"] = db.fmt_dt(db.clock_dt())
            db.stamp(row)
    revoke_patient_privileges(patient, reset_phase=False, quarantine_lots=False)
    for row in db.guest_dosing_arrangements.values():
        if row.get("patient_id") != patient["id"]:
            continue
        if row.get("status") in ("DRAFT", "PENDING_RECEIVING_ACK", "ACTIVE"):
            row["status"] = "CANCELLED"
            db.stamp(row)
    db.stamp(patient)
    return patient


# ---------------------------------------------------------------------------
# complete-withdrawal
# ---------------------------------------------------------------------------
def complete_withdrawal(patient, actor):
    if patient.get("status") != "ACTIVE":
        raise ApiError("ERR_PATIENT_NOT_ACTIVE", "Patient is not ACTIVE")
    if patient.get("treatment_phase") != "MEDICAL_WITHDRAWAL":
        raise ApiError("ERR_NOT_IN_WITHDRAWAL_PHASE", "Patient is not in MEDICAL_WITHDRAWAL")
    for row in db.dose_dispenses.values():
        if row.get("patient_id") == patient["id"] and row.get("status") in DOSE_OPEN:
            raise ApiError("ERR_OPEN_DOSES_REMAIN", "Patient still has non-terminal dose rows")
    patient["status"] = "COMPLETED_WITHDRAWAL"
    for order in db.dose_orders.values():
        if order.get("patient_id") == patient["id"] and order.get("status") == "ACTIVE":
            order["status"] = "DISCONTINUED"
            db.stamp(order)
    revoke_patient_privileges(patient, reset_phase=False, quarantine_lots=False)
    db.stamp(patient)
    return patient


# ---------------------------------------------------------------------------
# PATCH treatment-phase
# ---------------------------------------------------------------------------
def move_phase(patient, new_phase, reconciled_days):
    from constants import TREATMENT_PHASES

    if new_phase not in TREATMENT_PHASES:
        raise ApiError("ERR_INVALID_REQUEST", "treatment_phase is not a declared value")
    patient["treatment_phase"] = new_phase
    if reconciled_days is not None and int(reconciled_days) >= 1:
        patient["journal_reconciled_through_date"] = db.clock_dt().strftime("%Y-%m-%d")
    from services import patient as patient_svc

    patient_svc.refresh_counseling(patient)
    stability.refresh_patient(patient, publish="A")
    db.stamp(patient)
    return patient


# ---------------------------------------------------------------------------
# recompute the look-ahead flag for a held privilege
# ---------------------------------------------------------------------------
def recompute_timetable(privilege, patient):
    """True when journal_reconciled_through_date is on/after the day before evaluation."""
    through = db.parse_date(patient.get("journal_reconciled_through_date"))
    lookahead = (db.clock_dt() - timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return bool(through is not None and through >= lookahead)