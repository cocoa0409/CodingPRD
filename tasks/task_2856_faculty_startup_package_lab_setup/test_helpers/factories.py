"""Payload factories - one per write endpoint, input fields only.

All money is an integer number of cents and every datetime input is a full
ISO 8601 UTC instant; only the five calendar-date fields named by the PRD
(planned_start_date, departure_effective_on, spend_deadline_on, start_date,
end_date) are YYYY-MM-DD strings.
"""

from .constants import (
    FY2027_AVAILABLE_ON,
    FY2027_EXPIRES_ON,
    TEST_DEFAULTS,
)


def create_funding_unit_payload(**overrides) -> dict:
    defaults = {
        "name": "College of Natural Sciences",
        "unit_type": "COLLEGE",
        "cost_share_pool_cents": TEST_DEFAULTS["COLLEGE_POOL_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_faculty_payload(funding_unit_id: str, **overrides) -> dict:
    defaults = {
        "full_name": TEST_DEFAULTS["FACULTY_NAME"],
        "rank": TEST_DEFAULTS["FACULTY_RANK"],
        "funding_unit_id": funding_unit_id,
        "planned_start_date": TEST_DEFAULTS["PLANNED_START_DATE"],
    }
    defaults.update(overrides)
    return defaults


def create_startup_package_payload(faculty_id: str, dean_unit_id: str, **overrides) -> dict:
    defaults = {
        "faculty_id": faculty_id,
        "package_kind": "INITIAL",
        "dean_unit_id": dean_unit_id,
        "dept_share_pct": TEST_DEFAULTS["DEPT_SHARE_PCT"],
        "college_share_pct": TEST_DEFAULTS["COLLEGE_SHARE_PCT"],
        "dean_share_pct": TEST_DEFAULTS["DEAN_SHARE_PCT"],
        "proposed_total_cents": TEST_DEFAULTS["PROPOSED_TOTAL_CENTS"],
        "spend_deadline_on": TEST_DEFAULTS["SPEND_DEADLINE_ON"],
    }
    defaults.update(overrides)
    return defaults


def create_commitment_tranche_payload(**overrides) -> dict:
    defaults = {
        "category": "EQUIPMENT",
        "fiscal_year": 2027,
        "amount_cents": TEST_DEFAULTS["PROPOSED_TOTAL_CENTS"],
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    }
    defaults.update(overrides)
    return defaults


def create_lab_space_payload(**overrides) -> dict:
    defaults = {
        "building_code": "CHEM",
        "room_number": "101",
        "net_sq_ft": 900,
        "space_class": "WET",
        "power_kw_capacity": 120.0,
        "chilled_water_available": True,
        "fume_hood_count": 3,
        "floor_load_psf": 300,
    }
    defaults.update(overrides)
    return defaults


def utility_upgrade_payload(**overrides) -> dict:
    """All four envelope figures are supplied on an upgrade."""
    defaults = {
        "power_kw_capacity": 300.0,
        "fume_hood_count": 4,
        "chilled_water_available": True,
        "floor_load_psf": 500,
    }
    defaults.update(overrides)
    return defaults


def create_space_assignment_payload(
    space_id: str, faculty_id: str, expected_space_version: int, **overrides
) -> dict:
    defaults = {
        "space_id": space_id,
        "faculty_id": faculty_id,
        "share_pct": 100,
        "effective_from": "2026-08-01T00:00:00Z",
        "expected_space_version": expected_space_version,
    }
    defaults.update(overrides)
    return defaults


def release_space_assignment_payload(released_on: str) -> dict:
    return {"released_on": released_on}


def create_renovation_project_payload(package_id: str, space_id: str, **overrides) -> dict:
    defaults = {
        "package_id": package_id,
        "space_id": space_id,
        "scope_tier": "MODERATE",
        "estimate_cents": 12_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_renovation_phase_payload(**overrides) -> dict:
    defaults = {
        "sequence_no": 1,
        "name": "Demolition",
        "planned_start": "2026-08-10T00:00:00Z",
        "planned_end": "2026-09-30T00:00:00Z",
        "budget_cents": 6_000_000,
    }
    defaults.update(overrides)
    return defaults


def rescope_payload(revised_estimate_cents: int, scope_tier: str) -> dict:
    return {"revised_estimate_cents": revised_estimate_cents, "scope_tier": scope_tier}


def award_payload(awarded_cents: int) -> dict:
    return {"awarded_cents": awarded_cents}


def complete_phase_payload(actual_cost_cents: int) -> dict:
    return {"actual_cost_cents": actual_cost_cents}


def create_equipment_order_payload(package_id: str, install_space_id: str, **overrides) -> dict:
    defaults = {
        "package_id": package_id,
        "install_space_id": install_space_id,
        "vendor_name": "Thermo",
        "item_description": "Benchtop centrifuge",
        "quoted_cents": 3_000_000,
        "lead_time_days": 21,
        "required_power_kw": 4.0,
        "requires_chilled_water": False,
        "required_fume_hoods": 0,
        "required_floor_load_psf": 120,
    }
    defaults.update(overrides)
    return defaults


def place_equipment_order_payload(expected_package_version: int) -> dict:
    return {"expected_package_version": expected_package_version}


def create_staff_appointment_payload(package_id: str, **overrides) -> dict:
    defaults = {
        "package_id": package_id,
        "appointment_type": "GRAD_RA",
        "fte": 0.77,
        "monthly_cost_cents": 583_333,
        "start_date": "2026-09-01",
        "end_date": "2027-08-31",
    }
    defaults.update(overrides)
    return defaults


def end_staff_appointment_payload(end_date: str) -> dict:
    return {"end_date": end_date}


def departure_notice_payload(departure_intent: str, departure_effective_on: str, **overrides) -> dict:
    defaults = {
        "departure_intent": departure_intent,
        "departure_effective_on": departure_effective_on,
    }
    defaults.update(overrides)
    return defaults


def counter_payload(counter_total_cents: int) -> dict:
    return {"counter_total_cents": counter_total_cents}


def revise_payload(revised_total_cents: int) -> dict:
    return {"revised_total_cents": revised_total_cents}


def year_end_rollover_payload(fiscal_year: int) -> dict:
    return {"fiscal_year": fiscal_year}
