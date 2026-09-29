"""Payload factories: PRD-exact field names, sensible defaults, overridable.

Money is emitted as JSON integers counting cents. Instants are full ISO 8601
UTC instants anchored on the logical clock's 2026-08-01T00:00:00Z start, never
date-only strings; `Patient.date_of_birth` is the one deliberate exception
because the PRD declares it an ISO calendar date with no time component.
"""
from .constants import (
    CLOCK_START,
    COMPLAINT_SORE_THROAT,
    CREDENTIAL_NP,
    ROLE_KIND_PRIMARY,
    THERAPY_ANTIBIOTIC_BETA_LACTAM,
    VALID_PHARMACY_NPI,
)


def state_rule_payload(state_code="CA", chart_review_sample_pct=40,
                       review_deadline_hours=72,
                       collaborating_physician_required=True,
                       min_independent_practice_age_months=24,
                       controlled_rx_allowed=False,
                       max_supervised_clinicians_per_physician=3, **overrides):
    payload = {
        "state_code": state_code,
        "chart_review_sample_pct": chart_review_sample_pct,
        "review_deadline_hours": review_deadline_hours,
        "collaborating_physician_required": collaborating_physician_required,
        "min_independent_practice_age_months": min_independent_practice_age_months,
        "controlled_rx_allowed": controlled_rx_allowed,
        "max_supervised_clinicians_per_physician":
            max_supervised_clinicians_per_physician,
    }
    payload.update(overrides)
    return payload


def protocol_payload(complaint_code=COMPLAINT_SORE_THROAT, min_age_months=12,
                     max_age_months=1200, base_price_cents=9900, acuity_tier=2,
                     red_flag_codes=("STRIDOR",), max_temp_c=39.5,
                     max_heart_rate_bpm=120, min_spo2_pct=92,
                     requires_cosign=False, allowed_state_codes=("CA",),
                     **overrides):
    payload = {
        "complaint_code": complaint_code,
        "min_age_months": min_age_months,
        "max_age_months": max_age_months,
        "base_price_cents": base_price_cents,
        "acuity_tier": acuity_tier,
        "red_flag_codes": list(red_flag_codes),
        "max_temp_c": max_temp_c,
        "max_heart_rate_bpm": max_heart_rate_bpm,
        "min_spo2_pct": min_spo2_pct,
        "requires_cosign": requires_cosign,
        "allowed_state_codes": list(allowed_state_codes),
    }
    payload.update(overrides)
    return payload


def clinic_payload(name="Test Clinic", state_code="CA", min_clinicians_required=1,
                   appointment_slots_per_hour=2, walk_in_queue_capacity=5,
                   **overrides):
    payload = {
        "name": name,
        "state_code": state_code,
        "min_clinicians_required": min_clinicians_required,
        "appointment_slots_per_hour": appointment_slots_per_hour,
        "walk_in_queue_capacity": walk_in_queue_capacity,
    }
    payload.update(overrides)
    return payload


def physician_payload(full_name="Dr Test", licensed_state_codes=("CA",),
                      max_supervised_clinicians=3, status=None, **overrides):
    payload = {
        "full_name": full_name,
        "licensed_state_codes": list(licensed_state_codes),
        "max_supervised_clinicians": max_supervised_clinicians,
    }
    if status is not None:
        payload["status"] = status
    payload.update(overrides)
    return payload


def clinician_payload(home_clinic_id, supervising_physician_id,
                      full_name="NP Test", credential=CREDENTIAL_NP,
                      license_state_code="CA", float_eligible=None, **overrides):
    payload = {
        "full_name": full_name,
        "credential": credential,
        "license_state_code": license_state_code,
        "home_clinic_id": home_clinic_id,
        "supervising_physician_id": supervising_physician_id,
    }
    if float_eligible is not None:
        payload["float_eligible"] = float_eligible
    payload.update(overrides)
    return payload


def patient_payload(full_name="Adult Patient", date_of_birth="1985-05-15",
                    payer_name=None, member_id=None, pcp_name=None,
                    pcp_direct_address=None, pcp_accepts_electronic_summary=None,
                    pcp_consent_on_file=None, **overrides):
    payload = {"full_name": full_name, "date_of_birth": date_of_birth}
    if payer_name is not None:
        payload["payer_name"] = payer_name
    if member_id is not None:
        payload["member_id"] = member_id
    if pcp_name is not None:
        payload["pcp_name"] = pcp_name
    if pcp_direct_address is not None:
        payload["pcp_direct_address"] = pcp_direct_address
    if pcp_accepts_electronic_summary is not None:
        payload["pcp_accepts_electronic_summary"] = pcp_accepts_electronic_summary
    if pcp_consent_on_file is not None:
        payload["pcp_consent_on_file"] = pcp_consent_on_file
    payload.update(overrides)
    return payload


def insured_patient_payload(full_name="Insured Patient",
                           date_of_birth="1985-05-15", payer_name="Aetna",
                           member_id="M-1001", **overrides):
    return patient_payload(full_name=full_name, date_of_birth=date_of_birth,
                           payer_name=payer_name, member_id=member_id, **overrides)


def staffing_assignment_payload(clinic_id, clinician_id,
                                starts_at=CLOCK_START,
                                ends_at="2026-08-01T23:00:00Z",
                                role_kind=ROLE_KIND_PRIMARY,
                                pinned_supervising_physician_id=None, **overrides):
    payload = {
        "clinic_id": clinic_id,
        "clinician_id": clinician_id,
        "role_kind": role_kind,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    if pinned_supervising_physician_id is not None:
        payload["pinned_supervising_physician_id"] = pinned_supervising_physician_id
    payload.update(overrides)
    return payload


def float_coverage_payload(covers_assignment_id, expected_clinic_version,
                           pinned_supervising_physician_id=None, **overrides):
    payload = {
        "covers_assignment_id": covers_assignment_id,
        "expected_clinic_version": expected_clinic_version,
    }
    if pinned_supervising_physician_id is not None:
        payload["pinned_supervising_physician_id"] = pinned_supervising_physician_id
    payload.update(overrides)
    return payload


def walk_in_payload(clinic_id, patient_id, complaint_code=COMPLAINT_SORE_THROAT,
                    **overrides):
    payload = {
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "kind": "WALK_IN",
        "complaint_code": complaint_code,
    }
    payload.update(overrides)
    return payload


def appointment_payload(clinic_id, patient_id, scheduled_at,
                        complaint_code=COMPLAINT_SORE_THROAT, **overrides):
    payload = {
        "clinic_id": clinic_id,
        "patient_id": patient_id,
        "kind": "APPOINTMENT",
        "complaint_code": complaint_code,
        "scheduled_at": scheduled_at,
    }
    payload.update(overrides)
    return payload


def visit_payload(queue_entry_id, clinician_id=None, **overrides):
    payload = {"queue_entry_id": queue_entry_id}
    if clinician_id is not None:
        payload["clinician_id"] = clinician_id
    payload.update(overrides)
    return payload


def eligibility_payload(coverage_status, copay_cents=None, coinsurance_pct=None,
                        **overrides):
    payload = {"coverage_status": coverage_status}
    if copay_cents is not None:
        payload["copay_cents"] = copay_cents
    if coinsurance_pct is not None:
        payload["coinsurance_pct"] = coinsurance_pct
    payload.update(overrides)
    return payload


def active_coverage_payload(copay_cents=2500, coinsurance_pct=12.5, **overrides):
    return eligibility_payload("ACTIVE", copay_cents=copay_cents,
                               coinsurance_pct=coinsurance_pct, **overrides)


def assessment_payload(visit_id, temp_c=37.2, heart_rate_bpm=84, spo2_pct=98,
                       red_flag_codes=(), **overrides):
    payload = {
        "visit_id": visit_id,
        "temp_c": temp_c,
        "heart_rate_bpm": heart_rate_bpm,
        "spo2_pct": spo2_pct,
        "red_flag_codes": list(red_flag_codes),
    }
    payload.update(overrides)
    return payload


def prescription_payload(visit_id, expected_visit_version,
                         drug_name="Amoxicillin 500mg",
                         therapy_class=THERAPY_ANTIBIOTIC_BETA_LACTAM,
                         days_supply=10, pharmacy_npi=VALID_PHARMACY_NPI,
                         supersedes_prescription_id=None, **overrides):
    payload = {
        "visit_id": visit_id,
        "drug_name": drug_name,
        "therapy_class": therapy_class,
        "days_supply": days_supply,
        "pharmacy_npi": pharmacy_npi,
        "expected_visit_version": expected_visit_version,
    }
    if supersedes_prescription_id is not None:
        payload["supersedes_prescription_id"] = supersedes_prescription_id
    payload.update(overrides)
    return payload
