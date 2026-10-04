"""Entity constructors and serializers.

Field names and defaults are transcribed from SCAFFOLD.yaml section 1.1 and the
narrative requirements in PRD.md.
"""
from datetime import timedelta

import db
from constants import (
    DEFAULT_CHECKIN_GRACE_MINUTES,
    DEFAULT_MAX_MG_BUPRENORPHINE,
    DEFAULT_MAX_MG_METHADONE,
    PATIENT_STATUSES,
)
from services.num import clean, eff, r2


def _base():
    row = db.common_fields()
    return row


# ---------------------------------------------------------------------------
# Program
# ---------------------------------------------------------------------------
def make_program(payload):
    row = _base()
    row.update(
        {
            "name": payload["name"],
            "state_code": payload["state_code"],
            "clinic_hours_start": payload["clinic_hours_start"],
            "clinic_hours_end": payload["clinic_hours_end"],
            "dose_checkin_grace_minutes": payload.get(
                "dose_checkin_grace_minutes", DEFAULT_CHECKIN_GRACE_MINUTES
            ),
            "open_days": list(payload["open_days"]),
            "max_daily_dose_slots": payload["max_daily_dose_slots"],
            "max_daily_mg_methadone": payload.get(
                "max_daily_mg_methadone", DEFAULT_MAX_MG_METHADONE
            ),
            "max_daily_mg_buprenorphine": payload.get(
                "max_daily_mg_buprenorphine", DEFAULT_MAX_MG_BUPRENORPHINE
            ),
            "guest_dosing_enabled": payload.get("guest_dosing_enabled", True),
            "posture": "NORMAL",
            "posture_reason_code": None,
            "open_diversion_case_count": 0,
            "open_critical_finding_count": 0,
            "latest_inventory_variance_mg": 0.0,
            "pending_waste_mg": 0.0,
            "cumulative_write_off_mg": 0.0,
            "status": "ACTIVE",
        }
    )
    return row


def serialize_program(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "name": row["name"],
        "state_code": row["state_code"],
        "clinic_hours_start": row["clinic_hours_start"],
        "clinic_hours_end": row["clinic_hours_end"],
        "dose_checkin_grace_minutes": row["dose_checkin_grace_minutes"],
        "open_days": list(row["open_days"]),
        "max_daily_dose_slots": row["max_daily_dose_slots"],
        "max_daily_mg_methadone": clean(row["max_daily_mg_methadone"]),
        "max_daily_mg_buprenorphine": clean(row["max_daily_mg_buprenorphine"]),
        "guest_dosing_enabled": row["guest_dosing_enabled"],
        "posture": row["posture"],
        "posture_reason_code": row["posture_reason_code"],
        "open_diversion_case_count": row["open_diversion_case_count"],
        "open_critical_finding_count": row["open_critical_finding_count"],
        "latest_inventory_variance_mg": clean(r2(row["latest_inventory_variance_mg"])),
        "pending_waste_mg": clean(r2(row["pending_waste_mg"])),
        "cumulative_write_off_mg": clean(r2(row["cumulative_write_off_mg"])),
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# CarryQuotaLedger
# ---------------------------------------------------------------------------
def make_carry_quota_ledger(program_id, allotted_carries):
    row = _base()
    row.update(
        {
            "program_id": program_id,
            "allotted_carries": allotted_carries,
            "granted_carries": 0,
            "released_carries": 0,
            "available_carries": allotted_carries,
            "held_privilege_count": 0,
        }
    )
    return row


def serialize_carry_quota_ledger(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "program_id": row["program_id"],
        "allotted_carries": row["allotted_carries"],
        "granted_carries": row["granted_carries"],
        "released_carries": row["released_carries"],
        "available_carries": row["available_carries"],
        "held_privilege_count": row["held_privilege_count"],
    }


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
def make_user(payload):
    row = _base()
    row.update(
        {
            "program_id": payload.get("program_id"),
            "full_name": payload["full_name"],
            "staff_role": payload["staff_role"],
            "license_number": payload.get("license_number"),
            "is_active": True,
        }
    )
    return row


def serialize_user(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "program_id": row["program_id"],
        "full_name": row["full_name"],
        "staff_role": row["staff_role"],
        "license_number": row["license_number"],
        "is_active": row["is_active"],
    }


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------
def make_patient(payload):
    row = _base()
    row.update(
        {
            "program_id": payload["program_id"],
            "full_name": payload["full_name"],
            "date_of_birth": payload["date_of_birth"],
            "government_id_hash": payload["government_id_hash"],
            "diagnosis_code": payload["diagnosis_code"],
            "diagnosis_confirmed": False,
            "home_state_code": payload["home_state_code"],
            "home_address": payload["home_address"],
            "transportation_type": payload["transportation_type"],
            "one_way_travel_minutes": payload["one_way_travel_minutes"],
            "status": "PENDING_ADMISSION",
            "treatment_phase": "INDUCTION",
            "counseling_standing": "CURRENT",
            "diversion_standing": "CLEAR",
            "admission_datetime": None,
            "time_in_treatment_days": 0,
            "risk_tier": "LOW",
            "risk_score_points": 0.0,
            "stability_posting": 0,
            "stability_score": 50.0,
            "denial_count_12mo": 0,
            "missed_dose_streak": 0,
            "carries_used": 0,
            "journal_reconciled_through_date": None,
        }
    )
    return row


def serialize_patient(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "program_id": row["program_id"],
        "full_name": row["full_name"],
        "date_of_birth": row["date_of_birth"],
        "government_id_hash": row["government_id_hash"],
        "diagnosis_code": row["diagnosis_code"],
        "diagnosis_confirmed": row["diagnosis_confirmed"],
        "home_state_code": row["home_state_code"],
        "home_address": row["home_address"],
        "transportation_type": row["transportation_type"],
        "one_way_travel_minutes": row["one_way_travel_minutes"],
        "status": row["status"],
        "treatment_phase": row["treatment_phase"],
        "counseling_standing": row["counseling_standing"],
        "diversion_standing": row["diversion_standing"],
        "admission_datetime": row["admission_datetime"],
        "time_in_treatment_days": row["time_in_treatment_days"],
        "risk_tier": row["risk_tier"],
        "risk_score_points": clean(row["risk_score_points"]),
        "stability_posting": row["stability_posting"],
        "stability_score": clean(row["stability_score"]),
        "denial_count_12mo": row["denial_count_12mo"],
        "missed_dose_streak": row["missed_dose_streak"],
        "carries_used": row["carries_used"],
        "journal_reconciled_through_date": row["journal_reconciled_through_date"],
    }


# ---------------------------------------------------------------------------
# DoseOrder
# ---------------------------------------------------------------------------
def make_dose_order(patient, medication, ordered_daily_mg, split_dose_authorized, ceiling):
    row = _base()
    row.update(
        {
            "patient_id": patient["id"],
            "program_id": patient["program_id"],
            "medication": medication,
            "ordered_daily_mg": ordered_daily_mg,
            "medication_ceiling_mg": ceiling,
            "split_dose_authorized": split_dose_authorized,
            "previous_ordered_daily_mg": 0.0,
            "phase_at_authorization": None,
            "last_increase_date": None,
            "status": "DRAFT",
        }
    )
    return row


def serialize_dose_order(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "patient_id": row["patient_id"],
        "program_id": row["program_id"],
        "medication": row["medication"],
        "ordered_daily_mg": clean(row["ordered_daily_mg"]),
        "medication_ceiling_mg": clean(row["medication_ceiling_mg"]),
        "split_dose_authorized": row["split_dose_authorized"],
        "previous_ordered_daily_mg": clean(row["previous_ordered_daily_mg"]),
        "phase_at_authorization": row["phase_at_authorization"],
        "last_increase_date": row["last_increase_date"],
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# DoseDispense
# ---------------------------------------------------------------------------
def make_dose_dispense(
    order,
    patient,
    dose_date,
    scheduled_datetime,
    source_type="OBSERVED_CLINIC",
    inventory_lot_id=None,
    guest_arrangement_id=None,
    privilege_id=None,
    carry_count=0,
):
    row = _base()
    ordered_mg = (order or {}).get("ordered_daily_mg") or 0.0
    row.update(
        {
            "dose_order_id": (order or {}).get("id"),
            "patient_id": patient["id"],
            "program_id": patient["program_id"],
            "dose_date": dose_date,
            "scheduled_datetime": scheduled_datetime,
            "source_type": source_type,
            "ordered_mg": r2(ordered_mg),
            "dispensed_mg": 0.0,
            "wasted_mg": 0.0,
            "returned_mg": 0.0,
            "carry_count": 1 if source_type == "TAKE_HOME_ISSUANCE" else 0,
            "carries_before": 0,
            "carries_after": 0,
            "verification_result": None,
            "inventory_lot_id": inventory_lot_id,
            "witness_staff_id": None,
            "verification_staff_id": None,
            "arrived_at": None,
            "completed_at": None,
            "guest_arrangement_id": guest_arrangement_id,
            "privilege_id": privilege_id,
            "status": "SCHEDULED",
        }
    )
    return row


def serialize_dose_dispense(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "dose_order_id": row["dose_order_id"],
        "patient_id": row["patient_id"],
        "program_id": row["program_id"],
        "dose_date": row["dose_date"],
        "scheduled_datetime": row["scheduled_datetime"],
        "source_type": row["source_type"],
        "ordered_mg": clean(row["ordered_mg"]),
        "dispensed_mg": clean(row["dispensed_mg"]),
        "wasted_mg": clean(row["wasted_mg"]),
        "returned_mg": clean(row["returned_mg"]),
        "carry_count": row["carry_count"],
        "carries_before": row["carries_before"],
        "carries_after": row["carries_after"],
        "verification_result": row["verification_result"],
        "inventory_lot_id": row["inventory_lot_id"],
        "witness_staff_id": row["witness_staff_id"],
        "verification_staff_id": row["verification_staff_id"],
        "arrived_at": row["arrived_at"],
        "completed_at": row["completed_at"],
        "guest_arrangement_id": row["guest_arrangement_id"],
        "privilege_id": row["privilege_id"],
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# TakeHomePrivilege
# ---------------------------------------------------------------------------
def make_privilege(patient, requested_carries, carry_interval_days, reissued_from=None):
    row = _base()
    row.update(
        {
            "patient_id": patient["id"],
            "program_id": patient["program_id"],
            "requested_carries": requested_carries,
            "carry_interval_days": carry_interval_days,
            "approved_carries": 0,
            "freed_carries": 0,
            "expires_on": None,
            "decision": "PENDING_REVIEW",
            "denial_reason_code": None,
            "exception_id": None,
            "evaluation_basis": None,
            "timetable_reconciled": False,
            "eligible_carry_cap": 0,
            "reissued_from_privilege_id": reissued_from,
            "hold_ledger_delta": -1,
        }
    )
    return row


def serialize_privilege(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "patient_id": row["patient_id"],
        "program_id": row["program_id"],
        "requested_carries": row["requested_carries"],
        "carry_interval_days": row["carry_interval_days"],
        "approved_carries": row["approved_carries"],
        "freed_carries": row["freed_carries"],
        "expires_on": row["expires_on"],
        "decision": row["decision"],
        "denial_reason_code": row["denial_reason_code"],
        "exception_id": row["exception_id"],
        "evaluation_basis": row["evaluation_basis"],
        "timetable_reconciled": row["timetable_reconciled"],
        "eligible_carry_cap": row["eligible_carry_cap"],
        "reissued_from_privilege_id": row["reissued_from_privilege_id"],
        "hold_ledger_delta": row["hold_ledger_delta"],
    }


# ---------------------------------------------------------------------------
# TakeHomeException
# ---------------------------------------------------------------------------
def make_exception(
    patient,
    requested_carries,
    exception_type,
    clinical_justification,
    supervisor_id,
    requesting_physician_id,
):
    row = _base()
    row.update(
        {
            "patient_id": patient["id"],
            "program_id": patient["program_id"],
            "requested_carries": requested_carries,
            "exception_type": exception_type,
            "clinical_justification": clinical_justification,
            "requesting_physician_id": requesting_physician_id,
            "supervisor_id": supervisor_id,
            "granted_carries": 0,
            "status": "REQUESTED",
            "evaluated_domain_b": False,
        }
    )
    return row


def serialize_exception(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "patient_id": row["patient_id"],
        "program_id": row["program_id"],
        "requested_carries": row["requested_carries"],
        "exception_type": row["exception_type"],
        "clinical_justification": row["clinical_justification"],
        "requesting_physician_id": row["requesting_physician_id"],
        "supervisor_id": row["supervisor_id"],
        "granted_carries": row["granted_carries"],
        "status": row["status"],
        "evaluated_domain_b": row["evaluated_domain_b"],
    }


# ---------------------------------------------------------------------------
# TakeHomeCarryLedger
# ---------------------------------------------------------------------------
def make_take_home_carry_ledger(patient):
    row = _base()
    row.update(
        {
            "patient_id": patient["id"],
            "program_id": patient["program_id"],
            "owns_privilege_count": 0,
            "carries_used": 0,
            "carry_variance": 0,
            "carried_balance_mg": 0.0,
            "carried_issued_mg": 0.0,
            "carried_dispensed_mg": 0.0,
            "carried_voided_mg": 0.0,
            "carried_consumed_mg": 0.0,
            "carries_held": 0,
            "charges_held": 0,
        }
    )
    return row


def serialize_carry_ledger(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "patient_id": row["patient_id"],
        "program_id": row["program_id"],
        "owns_privilege_count": row["owns_privilege_count"],
        "carries_used": row["carries_used"],
        "carry_variance": row["carry_variance"],
        "carried_balance_mg": clean(r2(row["carried_balance_mg"])),
        "carried_issued_mg": clean(r2(row["carried_issued_mg"])),
        "carried_dispensed_mg": clean(r2(row["carried_dispensed_mg"])),
        "carried_voided_mg": clean(r2(row["carried_voided_mg"])),
        "carried_consumed_mg": clean(r2(row["carried_consumed_mg"])),
        "carries_held": row["carries_held"],
        "charges_held": row["charges_held"],
    }


# ---------------------------------------------------------------------------
# InventoryLot
# ---------------------------------------------------------------------------
def make_lot(payload):
    row = _base()
    row.update(
        {
            "program_id": payload["program_id"],
            "medication": payload["medication"],
            "lot_number": payload["lot_number"],
            "expiration_date": payload["expiration_date"],
            "quantity_received_mg": payload["quantity_received_mg"],
            "dose_potency_mg_per_unit": payload.get("dose_potency_mg_per_unit", 1.0),
            "reusable_for_take_home": payload.get("reusable_for_take_home", False),
            "running_on_hand_mg": payload["quantity_received_mg"],
            "status": "RECEIVED",
        }
    )
    return row


def lot_is_expired(row, clock=None):
    if clock is None:
        clock = db.clock_dt()
    if clock is None:
        return False
    expiration = db.parse_date(row.get("expiration_date"))
    if expiration is None:
        return False
    today = clock.replace(hour=0, minute=0, second=0, microsecond=0)
    return today >= expiration


def serialize_lot(row):
    on_hand = eff(row["running_on_hand_mg"])
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "program_id": row["program_id"],
        "medication": row["medication"],
        "lot_number": row["lot_number"],
        "expiration_date": row["expiration_date"],
        "quantity_received_mg": clean(row["quantity_received_mg"]),
        "dose_potency_mg_per_unit": clean(row["dose_potency_mg_per_unit"]),
        "reusable_for_take_home": row["reusable_for_take_home"],
        "running_on_hand_mg": clean(r2(on_hand)),
        "on_hand_mg": clean(r2(on_hand)),
        "is_expired": lot_is_expired(row),
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# InventoryTransaction
# ---------------------------------------------------------------------------
def make_transaction(
    lot, transaction_type, quantity_mg, patient_id=None, dose_dispense_id=None,
    witness_staff_id=None, status="RECORDED",
):
    row = _base()
    row.update(
        {
            "lot_id": lot["id"],
            "program_id": lot["program_id"],
            "patient_id": patient_id,
            "dose_dispense_id": dose_dispense_id,
            "transaction_type": transaction_type,
            "quantity_mg": quantity_mg,
            "reconciliation_period": db.clock_dt().strftime("%Y-%m"),
            "witness_staff_id": witness_staff_id,
            "residual_variance_mg": 0.0,
            "cumulative_write_off_mg": 0.0,
            "status": status,
        }
    )
    return row


def serialize_transaction(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "lot_id": row["lot_id"],
        "program_id": row["program_id"],
        "patient_id": row["patient_id"],
        "dose_dispense_id": row["dose_dispense_id"],
        "transaction_type": row["transaction_type"],
        "quantity_mg": clean(r2(row["quantity_mg"])),
        "reconciliation_period": row["reconciliation_period"],
        "witness_staff_id": row["witness_staff_id"],
        "residual_variance_mg": clean(r2(row["residual_variance_mg"])),
        "cumulative_write_off_mg": clean(r2(row["cumulative_write_off_mg"])),
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# CounselingSession
# ---------------------------------------------------------------------------
def make_session(patient, session_type, scheduled_datetime, duration_minutes, counselor_staff_id):
    row = _base()
    row.update(
        {
            "patient_id": patient["id"],
            "program_id": patient["program_id"],
            "session_type": session_type,
            "scheduled_datetime": scheduled_datetime,
            "duration_minutes": duration_minutes,
            "counselor_staff_id": counselor_staff_id,
            "completed_at": None,
            "attended_minutes": 0,
            "status": "SCHEDULED",
        }
    )
    return row


def serialize_session(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "patient_id": row["patient_id"],
        "program_id": row["program_id"],
        "session_type": row["session_type"],
        "scheduled_datetime": row["scheduled_datetime"],
        "duration_minutes": row["duration_minutes"],
        "counselor_staff_id": row["counselor_staff_id"],
        "completed_at": row["completed_at"],
        "attended_minutes": row["attended_minutes"],
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# TreatmentPlanReview
# ---------------------------------------------------------------------------
def make_review(patient, reviewer_physician_id, reviewed_at, signed_off):
    row = _base()
    row.update(
        {
            "patient_id": patient["id"],
            "program_id": patient["program_id"],
            "reviewer_physician_id": reviewer_physician_id,
            "reviewed_at": reviewed_at,
            "cadence_days_applied": 0,
            "next_due_at": None,
            "signed_off": signed_off,
            "status": "COMPLETED",
        }
    )
    return row


def serialize_review(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "patient_id": row["patient_id"],
        "program_id": row["program_id"],
        "reviewer_physician_id": row["reviewer_physician_id"],
        "reviewed_at": row["reviewed_at"],
        "cadence_days_applied": row["cadence_days_applied"],
        "next_due_at": row["next_due_at"],
        "signed_off": row["signed_off"],
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# GuestDosingArrangement
# ---------------------------------------------------------------------------
def make_arrangement(patient, receiving_program_id, travel_start_date, travel_end_date):
    row = _base()
    row.update(
        {
            "patient_id": patient["id"],
            "originating_program_id": patient["program_id"],
            "receiving_program_id": receiving_program_id,
            "travel_start_date": travel_start_date,
            "travel_end_date": travel_end_date,
            "dose_authorization_token": None,
            "authorized_mg": None,
            "token_consumed": False,
            "status": "DRAFT",
            "receiving_acknowledged_at": None,
        }
    )
    return row


def serialize_arrangement(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "patient_id": row["patient_id"],
        "originating_program_id": row["originating_program_id"],
        "receiving_program_id": row["receiving_program_id"],
        "travel_start_date": row["travel_start_date"],
        "travel_end_date": row["travel_end_date"],
        "dose_authorization_token": row["dose_authorization_token"],
        "authorized_mg": clean(row["authorized_mg"]) if row["authorized_mg"] is not None else None,
        "token_consumed": row["token_consumed"],
        "status": row["status"],
        "receiving_acknowledged_at": row["receiving_acknowledged_at"],
    }


# ---------------------------------------------------------------------------
# ComplianceInspection
# ---------------------------------------------------------------------------
def make_inspection(program_id, inspecting_agency, scheduled_date, inspection_type):
    row = _base()
    row.update(
        {
            "program_id": program_id,
            "inspecting_agency": inspecting_agency,
            "scheduled_date": scheduled_date,
            "inspection_type": inspection_type,
            "readiness_score": 0.0,
            "readiness_tier": None,
            "finding_count": 0,
            "status": "SCHEDULED",
        }
    )
    return row


def serialize_inspection(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "program_id": row["program_id"],
        "inspecting_agency": row["inspecting_agency"],
        "scheduled_date": row["scheduled_date"],
        "inspection_type": row["inspection_type"],
        "readiness_score": clean(r2(row["readiness_score"])),
        "readiness_tier": row["readiness_tier"],
        "finding_count": row["finding_count"],
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# ComplianceFinding
# ---------------------------------------------------------------------------
def make_finding(inspection, requirement_code, severity):
    row = _base()
    row.update(
        {
            "inspection_id": inspection["id"],
            "program_id": inspection["program_id"],
            "requirement_code": requirement_code,
            "severity": severity,
            "status": "OPEN",
            "corrected_at": None,
        }
    )
    return row


def serialize_finding(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "inspection_id": row["inspection_id"],
        "program_id": row["program_id"],
        "requirement_code": row["requirement_code"],
        "severity": row["severity"],
        "status": row["status"],
        "corrected_at": row["corrected_at"],
    }


# ---------------------------------------------------------------------------
# CorrectiveAction
# ---------------------------------------------------------------------------
def make_action(program_id, finding_id, severity, plan_text, due_date):
    row = _base()
    row.update(
        {
            "program_id": program_id,
            "finding_id": finding_id,
            "severity": severity,
            "plan_text": plan_text,
            "due_date": due_date,
            "status": "OPEN",
        }
    )
    return row


def serialize_action(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "program_id": row["program_id"],
        "finding_id": row["finding_id"],
        "severity": row["severity"],
        "plan_text": row["plan_text"],
        "due_date": row["due_date"],
        "status": row["status"],
    }


# ---------------------------------------------------------------------------
# DiversionCase
# ---------------------------------------------------------------------------
def make_diversion_case(
    program_id, patient_id, related_dose_dispense_id, opened_by_user_id,
    detection_source, severity,
):
    row = _base()
    row.update(
        {
            "program_id": program_id,
            "patient_id": patient_id,
            "related_dose_dispense_id": related_dose_dispense_id,
            "opened_by_user_id": opened_by_user_id,
            "detection_source": detection_source,
            "severity": severity,
            "status": "OPEN",
            "confirmed_at": None,
            "outcome_summary": None,
        }
    )
    return row


def serialize_diversion_case(row):
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "version": row["version"],
        "program_id": row["program_id"],
        "patient_id": row["patient_id"],
        "related_dose_dispense_id": row["related_dose_dispense_id"],
        "opened_by_user_id": row["opened_by_user_id"],
        "detection_source": row["detection_source"],
        "severity": row["severity"],
        "status": row["status"],
        "confirmed_at": row["confirmed_at"],
        "outcome_summary": row["outcome_summary"],
    }


# ---------------------------------------------------------------------------
# TimeInTreatmentTracker (derived, one per patient)
# ---------------------------------------------------------------------------
def make_tracker(patient):
    return {
        "id": db.new_id(),
        "patient_id": patient["id"],
        "program_id": patient["program_id"],
        "dual_enrollment_flag": False,
        "created_at": db.now_iso(),
        "updated_at": db.now_iso(),
        "version": 1,
    }


def refresh_tracker(patient, clock=None):
    """Re-run the registry dual-enrollment screen for this patient.

    The registry matches on the pair formed by government_id_hash and
    date_of_birth, using the hash verbatim as the screening key (PRD 3.1), so two
    records collide only when both agree.
    """
    if clock is None:
        clock = db.clock_dt()
    tracker = db.time_in_treatment_trackers.get(patient["id"])
    if tracker is None:
        tracker = make_tracker(patient)
        db.time_in_treatment_trackers[patient["id"]] = tracker
    collides = False
    for other in db.patients.values():
        if other["id"] == patient["id"]:
            continue
        if other.get("government_id_hash") != patient.get("government_id_hash"):
            continue
        if other.get("date_of_birth") != patient.get("date_of_birth"):
            continue
        if other.get("status") in ("ADMINISTRATIVELY_DISCHARGED", "COMPLETED_WITHDRAWAL"):
            continue
        collides = True
        break
    tracker["dual_enrollment_flag"] = collides
    tracker["updated_at"] = db.now_iso()
    return tracker


def serialize_tracker(tracker):
    return {
        "id": tracker["id"],
        "created_at": tracker["created_at"],
        "updated_at": tracker["updated_at"],
        "version": tracker["version"],
        "patient_id": tracker["patient_id"],
        "program_id": tracker["program_id"],
        "dual_enrollment_flag": tracker["dual_enrollment_flag"],
    }