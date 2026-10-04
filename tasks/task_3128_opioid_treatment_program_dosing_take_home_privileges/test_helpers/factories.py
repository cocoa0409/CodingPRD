"""Payload factories for the PRD's creatable resources.

Only client-supplied fields are included; system-managed fields are never sent.
"""

from .constants import TEST_DEFAULTS


def create_program_payload(**overrides) -> dict:
    """POST /otp/programs body. name, state_code, clinic_hours_start,
    clinic_hours_end, open_days and max_daily_dose_slots are required; the
    remaining three carry defaults."""
    defaults = {
        "name": TEST_DEFAULTS["PROGRAM_NAME"],
        "state_code": TEST_DEFAULTS["STATE_CODE"],
        "clinic_hours_start": TEST_DEFAULTS["CLINIC_HOURS_START"],
        "clinic_hours_end": TEST_DEFAULTS["CLINIC_HOURS_END"],
        "open_days": list(TEST_DEFAULTS["OPEN_DAYS"]),
        "max_daily_dose_slots": TEST_DEFAULTS["MAX_DAILY_DOSE_SLOTS"],
        "max_daily_mg_methadone": TEST_DEFAULTS["MAX_DAILY_MG_METHADONE"],
        "max_daily_mg_buprenorphine": TEST_DEFAULTS["MAX_DAILY_MG_BUPRENORPHINE"],
        "guest_dosing_enabled": True,
        "dose_checkin_grace_minutes": TEST_DEFAULTS["DOSE_CHECKIN_GRACE_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_carry_quota_payload(allotted_carries=None, **overrides) -> dict:
    payload = {"allotted_carries": allotted_carries if allotted_carries is not None
               else TEST_DEFAULTS["ALLOTTED_CARRIES"]}
    payload.update(overrides)
    return payload


def create_user_payload(program_id=None, full_name="Paul Physician",
                        staff_role="PHYSICIAN", license_number="MD-3001", **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "full_name": full_name,
        "staff_role": staff_role,
        "license_number": license_number,
    }
    payload.update(overrides)
    return payload


def create_patient_payload(program_id, full_name="Dana Patient",
                           date_of_birth="1985-04-02", government_id_hash="sha256:9f2c41aa",
                           diagnosis_code="F11_20", home_state_code="CA",
                           home_address="12 River Rd", transportation_type="PRIVATE_VEHICLE",
                           one_way_travel_minutes=15, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "government_id_hash": government_id_hash,
        "diagnosis_code": diagnosis_code,
        "home_state_code": home_state_code,
        "home_address": home_address,
        "transportation_type": transportation_type,
        "one_way_travel_minutes": one_way_travel_minutes,
    }
    payload.update(overrides)
    return payload


def create_dose_order_payload(patient_id, medication="METHADONE",
                              ordered_daily_mg=None, split_dose_authorized=False,
                              **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "medication": medication,
        "ordered_daily_mg": ordered_daily_mg if ordered_daily_mg is not None
        else TEST_DEFAULTS["ORDERED_DAILY_MG"],
        "split_dose_authorized": split_dose_authorized,
    }
    payload.update(overrides)
    return payload


def create_dose_dispense_payload(dose_order_id, dose_date=None, scheduled_datetime=None,
                                 source_type="OBSERVED_CLINIC", inventory_lot_id=None,
                                 **overrides) -> dict:
    payload = {
        "dose_order_id": dose_order_id,
        "dose_date": dose_date or TEST_DEFAULTS["SERVICE_DATE"],
        "scheduled_datetime": scheduled_datetime or TEST_DEFAULTS["SERVICE_DATETIME"],
        "source_type": source_type,
        "inventory_lot_id": inventory_lot_id,
    }
    payload.update(overrides)
    return payload


def create_privilege_payload(patient_id, requested_carries, expected_patient_version,
                             carry_interval_days=7, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "requested_carries": requested_carries,
        "carry_interval_days": carry_interval_days,
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def create_exception_payload(patient_id, requested_carries, supervisor_id,
                             expected_privilege_version, exception_type="TRAVEL_HARDSHIP",
                             clinical_justification=None, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "requested_carries": requested_carries,
        "exception_type": exception_type,
        "clinical_justification": clinical_justification or (
            "Patient travels 95 minutes each way with no reliable transport and "
            "cannot attend daily dosing during the winter road closures."
        ),
        "supervisor_id": supervisor_id,
        "expected_privilege_version": expected_privilege_version,
    }
    payload.update(overrides)
    return payload


def create_lot_payload(program_id, medication="METHADONE", lot_number="LOT-A1",
                       expiration_date="2027-06-30", quantity_received_mg=None,
                       dose_potency_mg_per_unit=1.0, reusable_for_take_home=False,
                       **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "medication": medication,
        "lot_number": lot_number,
        "expiration_date": expiration_date,
        "quantity_received_mg": quantity_received_mg if quantity_received_mg is not None
        else TEST_DEFAULTS["LOT_QUANTITY_MG"],
        "dose_potency_mg_per_unit": dose_potency_mg_per_unit,
        "reusable_for_take_home": reusable_for_take_home,
    }
    payload.update(overrides)
    return payload


def create_transaction_payload(lot_id, transaction_type, quantity_mg, **overrides) -> dict:
    payload = {
        "lot_id": lot_id,
        "transaction_type": transaction_type,
        "quantity_mg": quantity_mg,
    }
    payload.update(overrides)
    return payload


def create_counseling_session_payload(patient_id, scheduled_datetime,
                                      session_type="INDIVIDUAL", duration_minutes=60,
                                      counselor_staff_id=None, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "session_type": session_type,
        "scheduled_datetime": scheduled_datetime,
        "duration_minutes": duration_minutes,
        "counselor_staff_id": counselor_staff_id,
    }
    payload.update(overrides)
    return payload


def create_plan_review_payload(patient_id, reviewer_physician_id, reviewed_at,
                               signed_off=True, **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "reviewer_physician_id": reviewer_physician_id,
        "reviewed_at": reviewed_at,
        "signed_off": signed_off,
    }
    payload.update(overrides)
    return payload


def create_arrangement_payload(patient_id, receiving_program_id, expected_patient_version,
                               travel_start_date="2026-12-19", travel_end_date="2026-12-19",
                               **overrides) -> dict:
    payload = {
        "patient_id": patient_id,
        "receiving_program_id": receiving_program_id,
        "travel_start_date": travel_start_date,
        "travel_end_date": travel_end_date,
        "expected_patient_version": expected_patient_version,
    }
    payload.update(overrides)
    return payload


def create_inspection_payload(program_id, inspecting_agency="State Opioid Treatment Authority",
                              scheduled_date="2026-12-20",
                              inspection_type="DIVERSION_FOCUSED", **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "inspecting_agency": inspecting_agency,
        "scheduled_date": scheduled_date,
        "inspection_type": inspection_type,
    }
    payload.update(overrides)
    return payload


def create_finding_payload(inspection_id, requirement_code="WASTE_WITNESSED",
                           severity="CRITICAL", **overrides) -> dict:
    payload = {
        "inspection_id": inspection_id,
        "requirement_code": requirement_code,
        "severity": severity,
    }
    payload.update(overrides)
    return payload


def create_corrective_action_payload(program_id, severity="CRITICAL", plan_text=None,
                                     due_date="2026-12-31", finding_id=None, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "finding_id": finding_id,
        "severity": severity,
        "plan_text": plan_text or ("Retrain all dispensing nursing staff on witnessed "
                                   "waste documentation and audit weekly."),
        "due_date": due_date,
    }
    payload.update(overrides)
    return payload


def create_diversion_case_payload(program_id, patient_id, detection_source="COUNT_MISMATCH",
                                  severity="MAJOR", related_dose_dispense_id=None,
                                  **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "patient_id": patient_id,
        "related_dose_dispense_id": related_dose_dispense_id,
        "detection_source": detection_source,
        "severity": severity,
    }
    payload.update(overrides)
    return payload