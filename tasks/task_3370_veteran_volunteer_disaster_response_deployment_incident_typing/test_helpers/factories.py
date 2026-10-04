"""Payload factories — one per creatable resource, input fields only."""
from .constants import (
    AVAILABILITY_WINDOW,
    CERT_EXPIRES_AT,
    CERT_ISSUED_AT,
    CHECK_IN_CLOCK,
    OP_START_DATE,
    PLANNED_END,
    PLANNED_START,
)


def create_volunteer_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Ada Voss",
        "email": "ada@x.org",
        "home_region": "TX-GULF",
        "skills": ["CHAINSAW"],
        "availability_windows": [dict(AVAILABILITY_WINDOW)],
    }
    defaults.update(overrides)
    return defaults


def create_certification_payload(**overrides) -> dict:
    defaults = {
        "kind": "CHAINSAW",
        "issued_at": CERT_ISSUED_AT,
        "expires_at": CERT_EXPIRES_AT,
    }
    defaults.update(overrides)
    return defaults


def create_incident_payload(**overrides) -> dict:
    defaults = {
        "name": "Hurricane Helena",
        "region": "TX-GULF",
    }
    defaults.update(overrides)
    return defaults


def create_operation_payload(**overrides) -> dict:
    defaults = {
        "title": "Helena Tree Ops",
        "hazard_focus": "TREE_REMOVAL",
        "team_size_required": 2,
        "duration_days": 4,
        "required_capabilities": ["CHAINSAW"],
        "start_date": OP_START_DATE,
    }
    defaults.update(overrides)
    return defaults


def offer_deployment_payload(**overrides) -> dict:
    defaults = {
        "volunteer_id": "",
        "travel_mode": "SELF",
        "planned_start": PLANNED_START,
        "planned_end": PLANNED_END,
        "needs_lodging": False,
    }
    defaults.update(overrides)
    return defaults


def create_fob_site_payload(**overrides) -> dict:
    defaults = {
        "name": "FOB Alpha",
        "bunks_total": 2,
        "nightly_rate_cents": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_duty_shift_payload(**overrides) -> dict:
    defaults = {
        "deployment_id": "",
        "kind": "OPERATIONS",
        "starts_at": "2026-09-10T08:00:00Z",
        "ends_at": "2026-09-10T18:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_work_order_payload(**overrides) -> dict:
    defaults = {
        "requester_name": "Elderly Homeowner",
        "hazard_kind": "TREE_REMOVAL",
        "vulnerable_resident": False,
        "municipality_sourced": False,
    }
    defaults.update(overrides)
    return defaults


def create_partner_payload(**overrides) -> dict:
    defaults = {
        "name": "County EM",
        "kind": "EMERGENCY_MANAGEMENT",
        "contact_email": "em@county.gov",
    }
    defaults.update(overrides)
    return defaults


def create_training_course_payload(**overrides) -> dict:
    defaults = {
        "title": "Chainsaw Ops 101",
        "grants_cert_kind": "CHAINSAW",
        "capacity": 2,
        "starts_at": "2026-09-20T09:00:00Z",
        "lead_instructor_volunteer_id": "",
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(**overrides) -> dict:
    defaults = {
        "volunteer_id": "",
    }
    defaults.update(overrides)
    return defaults


def set_clock_payload(to_iso8601: str = CHECK_IN_CLOCK) -> dict:
    return {"to_iso8601": to_iso8601}
