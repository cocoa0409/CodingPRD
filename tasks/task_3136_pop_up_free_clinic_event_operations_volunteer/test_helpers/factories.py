"""Payload factories — one per entity, input fields only."""

_counter = {"n": 0}


def _next() -> int:
    _counter["n"] += 1
    return _counter["n"]


def create_event_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "event_code": f"RAM-TN-{1000 + n}",
        "name": f"Clinic Event {n}",
        "host_state_code": "TN",
        "service_date": "2026-10-03",
        "doors_open_utc": "2026-10-03T10:00:00Z",
        "total_patient_capacity": 100,
    }
    defaults.update(overrides)
    return defaults


def create_site_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "site_name": f"School {n}",
        "site_type": "SCHOOL",
        "state_code": "TN",
        "square_footage": 8000,
        "has_loading_dock": False,
        "power_capacity_kw": 90.0,
        "sterilization_capable": False,
    }
    defaults.update(overrides)
    return defaults


def create_site_agreement_payload(site_id, expected_event_version, **overrides) -> dict:
    n = _next()
    defaults = {
        "site_id": site_id,
        "host_org_name": f"Host Org {n}",
        "liability_cap_cents": 5_000_000,
        "insurance_certificate_ref": f"CERT-{n}",
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


def create_volunteer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Volunteer {n}",
        "email": f"volunteer-{n}@example.com",
        "discipline": "MEDICAL",
        "license_number": f"L-{n}",
        "license_state_code": "TN",
        "license_expiry_date": "2028-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_general_volunteer_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"General Volunteer {n}",
        "email": f"general-{n}@example.com",
        "discipline": "GENERAL",
        "license_number": "",
        "license_state_code": "",
        "license_expiry_date": "",
    }
    defaults.update(overrides)
    return defaults


def create_verification_request_payload(clinic_event_id, **overrides) -> dict:
    defaults = {
        "clinic_event_id": clinic_event_id,
        "reviewer_notes": "ok",
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(volunteer_id, **overrides) -> dict:
    defaults = {
        "volunteer_id": volunteer_id,
        "shift_code": "FULL_DAY",
    }
    defaults.update(overrides)
    return defaults


def create_station_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "station_label": f"M-{n}",
        "station_type": "MEDICAL",
        "chair_count": 1,
        "minutes_per_patient": 15,
        "requires_sterilization": False,
        "service_window_open_utc": "2026-10-03T11:00:00Z",
        "service_window_close_utc": "2026-10-03T19:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ticket_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "patient_ref": f"P-{n}",
        "arrival_utc": "2026-10-03T10:00:00Z",
        "requested_service": "MEDICAL",
        "priority_tier": "STANDARD",
    }
    defaults.update(overrides)
    return defaults


def begin_service_payload(station_id, volunteer_id, **overrides) -> dict:
    defaults = {
        "station_id": station_id,
        "volunteer_id": volunteer_id,
        "encounter_type": "MEDICAL_CONSULT",
        "findings_summary": "routine",
        "requires_followup": False,
    }
    defaults.update(overrides)
    return defaults


def create_manifest_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "manifest_label": f"TRUCK-{n}",
        "item_count": 10,
        "weight_kg": 500.0,
        "requires_loading_dock": False,
        "contains_sterilizer": False,
    }
    defaults.update(overrides)
    return defaults


def create_cycle_payload(instrument_batch_size=2, **overrides) -> dict:
    defaults = {"instrument_batch_size": instrument_batch_size}
    defaults.update(overrides)
    return defaults


def create_handoff_payload(**overrides) -> dict:
    defaults = {
        "partner_org_name": "Community Health Partner",
        "teardown_checklist_complete": True,
    }
    defaults.update(overrides)
    return defaults


def create_referral_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "referral_type": "MEDICAL_FOLLOWUP",
        "partner_org_name": f"Partner Org {n}",
        "urgency": "ROUTINE",
        "notes": "follow-up needed",
    }
    defaults.update(overrides)
    return defaults


def authorize_payload(clinic_event_id, expected_event_version, **overrides) -> dict:
    defaults = {
        "clinic_event_id": clinic_event_id,
        "expected_event_version": expected_event_version,
    }
    defaults.update(overrides)
    return defaults


def suspend_payload(clinic_event_id, reason="audit", **overrides) -> dict:
    defaults = {
        "clinic_event_id": clinic_event_id,
        "suspension_reason": reason,
    }
    defaults.update(overrides)
    return defaults
