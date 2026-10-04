"""Payload factories — one per entity, input fields only.

Every factory returns a dict of the request body for the corresponding create
call. Optional fields are omitted unless overridden.
"""

DEFAULTS = {
    "PRACTICE_NAME": "P1",
    "PRACTICE_TIMEZONE": "America/New_York",
    "PROVIDER_DISPLAY_NAME": "Dr A",
    "PROVIDER_SPECIALTY": "DERM",
    "TYPE_CODE": "NEW30",
    "TYPE_DISPLAY_NAME": "New patient 30",
    "TYPE_DURATION_MINUTES": 30,
    "TYPE_COPAY_CENTS": 10000,
    "PLAN_CARRIER": "Aetna",
    "PLAN_NAME": "A1",
    "PLAN_CODE": "A1",
    "PATIENT_FULL_NAME": "Pat One",
    "PATIENT_EMAIL": "p1@x.com",
    "SLOT_START": "2026-09-03T10:00:00Z",
    "SLOT_END": "2026-09-03T10:30:00Z",
    "ATTEST_FROM": "2026-01-01T00:00:00Z",
    "ATTEST_TO": "2027-01-01T00:00:00Z",
    "COMPLAINT_TYPE": "INSURANCE_MISMATCH",
    "REVIEW_RATING": 5,
    "REVIEW_TEXT": "great",
    "AUDIT_SCOPE": "AVAILABILITY",
    "CONTACT_CHANNEL": "PHONE",
}


def create_practice_payload(**overrides) -> dict:
    defaults = {
        "name": DEFAULTS["PRACTICE_NAME"],
        "timezone": DEFAULTS["PRACTICE_TIMEZONE"],
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(practice_id, **overrides) -> dict:
    defaults = {
        "practice_id": practice_id,
        "display_name": DEFAULTS["PROVIDER_DISPLAY_NAME"],
        "specialty": DEFAULTS["PROVIDER_SPECIALTY"],
    }
    defaults.update(overrides)
    return defaults


def create_slot_payload(**overrides) -> dict:
    defaults = {
        "start_at": DEFAULTS["SLOT_START"],
        "end_at": DEFAULTS["SLOT_END"],
    }
    defaults.update(overrides)
    return defaults


def bulk_publish_payload(slots, expected_provider_version) -> dict:
    return {"slots": slots, "expected_provider_version": expected_provider_version}


def create_appointment_type_payload(**overrides) -> dict:
    defaults = {
        "code": DEFAULTS["TYPE_CODE"],
        "display_name": DEFAULTS["TYPE_DISPLAY_NAME"],
        "duration_minutes": DEFAULTS["TYPE_DURATION_MINUTES"],
        "booked_copay_cents": DEFAULTS["TYPE_COPAY_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_insurance_plan_payload(**overrides) -> dict:
    defaults = {
        "carrier": DEFAULTS["PLAN_CARRIER"],
        "plan_name": DEFAULTS["PLAN_NAME"],
        "plan_code": DEFAULTS["PLAN_CODE"],
    }
    defaults.update(overrides)
    return defaults


def create_attestation_payload(provider_id, plan_id, **overrides) -> dict:
    defaults = {
        "provider_id": provider_id,
        "plan_id": plan_id,
        "effective_from": DEFAULTS["ATTEST_FROM"],
        "effective_to": DEFAULTS["ATTEST_TO"],
    }
    defaults.update(overrides)
    return defaults


def create_patient_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PATIENT_FULL_NAME"],
        "email": DEFAULTS["PATIENT_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_contact_event_payload(patient_id, contacted_at, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "contacted_at": contacted_at,
        "channel": DEFAULTS["CONTACT_CHANNEL"],
    }
    defaults.update(overrides)
    return defaults


def create_booking_payload(patient_id, appointment_type_id, **overrides) -> dict:
    defaults = {
        "patient_id": patient_id,
        "appointment_type_id": appointment_type_id,
    }
    defaults.update(overrides)
    return defaults


def generate_invoices_payload(practice_id, period) -> dict:
    return {"practice_id": practice_id, "period": period}


def dispute_invoice_payload(charge_ids, reason="disputed") -> dict:
    return {"charge_ids": charge_ids, "reason": reason}


def resolve_dispute_payload(resolutions) -> dict:
    return {"resolutions": resolutions}


def create_complaint_payload(booking_id, complaint_type=None, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "complaint_type": complaint_type or DEFAULTS["COMPLAINT_TYPE"],
    }
    defaults.update(overrides)
    return defaults


def respond_complaint_payload(response="looking into it") -> dict:
    return {"response": response}


def resolve_complaint_payload(outcome, **overrides) -> dict:
    defaults = {"outcome": outcome}
    defaults.update(overrides)
    return defaults


def create_review_payload(booking_id, rating=None, **overrides) -> dict:
    defaults = {
        "booking_id": booking_id,
        "rating": rating if rating is not None else DEFAULTS["REVIEW_RATING"],
    }
    defaults.update(overrides)
    return defaults


def flag_review_payload(reason="spam") -> dict:
    return {"reason": reason}


def moderate_review_payload(action) -> dict:
    return {"action": action}


def verify_attestation_payload(decision) -> dict:
    return {"decision": decision}


def create_audit_case_payload(provider_id, scope=None) -> dict:
    return {"provider_id": provider_id, "scope": scope or DEFAULTS["AUDIT_SCOPE"]}


def resolve_finding_payload(finding_index, resolution_note="resolved") -> dict:
    return {"finding_index": finding_index, "resolution_note": resolution_note}


def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def update_patient_plan_payload(plan_id, expected_patient_version) -> dict:
    return {"plan_id": plan_id, "expected_patient_version": expected_patient_version}
