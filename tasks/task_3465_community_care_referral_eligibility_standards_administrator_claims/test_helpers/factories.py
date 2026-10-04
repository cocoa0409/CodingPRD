"""Payload factories — one per entity, input fields only.

FK arguments (home_station_id, veteran_id, ...) are required parameters so a
payload can never silently reference a missing parent; everything else has a
sensible default overridable via **overrides.
"""
from . import constants as C


def create_care_station_payload(**overrides) -> dict:
    defaults = {
        "name": "Station Alpha",
        "latitude": C.DEFAULT_STATION_LATITUDE,
        "longitude": C.DEFAULT_STATION_LONGITUDE,
        "primary_wait_days": C.DEFAULT_PRIMARY_WAIT_DAYS,
        "specialty_wait_days": C.DEFAULT_SPECIALTY_WAIT_DAYS,
        "service_codes": [C.DEFAULT_SERVICE_CODE],
    }
    defaults.update(overrides)
    return defaults


def create_tpa_payload(**overrides) -> dict:
    defaults = {"name": "TPA One", "region_code": "R1"}
    defaults.update(overrides)
    return defaults


def create_provider_payload(**overrides) -> dict:
    defaults = {
        "name": "Prov One",
        "service_codes": [C.DEFAULT_SERVICE_CODE],
        "contract_scheduling": "TPA",
        "latitude": 40.1,
        "longitude": -75.1,
    }
    # contract_rates is optional; only included when the caller passes it.
    defaults.update(overrides)
    return defaults


def create_veteran_payload(home_station_id, **overrides) -> dict:
    defaults = {
        "full_name": "V One",
        "home_station_id": home_station_id,
        "priority_group": C.DEFAULT_PRIORITY_GROUP,
        "home_latitude": C.DEFAULT_HOME_LATITUDE,
        "home_longitude": C.DEFAULT_HOME_LONGITUDE,
    }
    defaults.update(overrides)
    return defaults


def create_eligibility_assessment_payload(expected_veteran_version, **overrides) -> dict:
    defaults = {
        "service_code": C.DEFAULT_SERVICE_CODE,
        "service_category": "PRIMARY_CARE",
        "geo_classification": "URBAN",
        "choice_requested": False,
        "expected_veteran_version": expected_veteran_version,
    }
    defaults.update(overrides)
    return defaults


def create_referral_authorization_payload(veteran_id, assessment_id, provider_id,
                                          **overrides) -> dict:
    defaults = {
        "veteran_id": veteran_id,
        "assessment_id": assessment_id,
        "provider_id": provider_id,
        "service_code": C.DEFAULT_SERVICE_CODE,
        "authorized_visits": 2,
        "duration_days": 60,
        "start_date": C.DEFAULT_START_DATE,
    }
    defaults.update(overrides)
    return defaults


def create_extension_request_payload(**overrides) -> dict:
    defaults = {"requested_visits": 2, "requested_extra_days": 0}
    defaults.update(overrides)
    return defaults


def decide_extension_request_payload(decision, expected_referral_authorization_version,
                                     **overrides) -> dict:
    defaults = {
        "decision": decision,
        "expected_referral_authorization_version": expected_referral_authorization_version,
    }
    defaults.update(overrides)
    return defaults


def create_appointment_payload(scheduled_start=None, **overrides) -> dict:
    defaults = {
        "scheduled_start": scheduled_start or f"{C.DEFAULT_APPOINTMENT_DATE}T10:00:00Z",
        "requested_date": C.DEFAULT_REQUESTED_DATE,
    }
    defaults.update(overrides)
    return defaults


def submit_documentation_payload(**overrides) -> dict:
    defaults = {"content_ref": "bundle-v1"}
    defaults.update(overrides)
    return defaults


def review_documentation_payload(decision="ACCEPTED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def credential_decision_payload(target_status="CREDENTIALED", **overrides) -> dict:
    defaults = {"target_status": target_status}
    defaults.update(overrides)
    return defaults


def claim_service_line(**overrides) -> dict:
    defaults = {
        "service_code": "GEN1",
        "service_category": "PRIMARY_CARE",
        "units": 1,
        "unit_billed_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(referral_authorization_id, service_date, service_lines=None,
                         **overrides) -> dict:
    defaults = {
        "referral_authorization_id": referral_authorization_id,
        "service_date": service_date,
        "service_lines": service_lines if service_lines is not None
        else [claim_service_line()],
    }
    defaults.update(overrides)
    return defaults


def adjudicate_claim_payload(decision="PAID", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults


def resubmit_claim_payload(service_lines=None, **overrides) -> dict:
    defaults = {
        "service_lines": service_lines if service_lines is not None
        else [claim_service_line()],
    }
    defaults.update(overrides)
    return defaults


def reverse_payment_payload(**overrides) -> dict:
    defaults = {"reason": "recoupment"}
    defaults.update(overrides)
    return defaults


def create_urgent_care_visit_payload(veteran_id, **overrides) -> dict:
    defaults = {"veteran_id": veteran_id, "facility_name": "QuickCare"}
    defaults.update(overrides)
    return defaults


def create_rx_urgent_payload(urgent_care_visit_id, **overrides) -> dict:
    """Urgent-care-linked fill request (supply cap 14 days)."""
    defaults = {
        "urgent_care_visit_id": urgent_care_visit_id,
        "medication_name": "amoxicillin 500mg",
        "days_supply": 7,
        "controlled_substance": False,
    }
    defaults.update(overrides)
    return defaults


def create_rx_appointment_payload(appointment_id, **overrides) -> dict:
    """Appointment-linked fill request (supply cap 90 days)."""
    defaults = {
        "appointment_id": appointment_id,
        "medication_name": "lisinopril 10mg",
        "days_supply": 30,
        "controlled_substance": False,
    }
    defaults.update(overrides)
    return defaults


def decide_rx_payload(decision="FILLED", **overrides) -> dict:
    defaults = {"decision": decision}
    defaults.update(overrides)
    return defaults
