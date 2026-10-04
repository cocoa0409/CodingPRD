"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_storm_event_payload(**overrides) -> dict:
    defaults = {"name": TEST_DEFAULTS["STORM_NAME"]}
    defaults.update(overrides)
    return defaults


def create_unit_payload(**overrides) -> dict:
    defaults = {
        "unit_code": TEST_DEFAULTS["UNIT_CODE"],
        "address": TEST_DEFAULTS["UNIT_ADDRESS"],
    }
    defaults.update(overrides)
    return defaults


def create_condition_report_payload(**overrides) -> dict:
    defaults = {
        "power": "UP",
        "water": "UP",
        "gas": "UP",
        "payment_network": "UP",
    }
    defaults.update(overrides)
    return defaults


def create_menu_activation_payload(**overrides) -> dict:
    defaults = {"tier": "TIER1_NO_POWER"}
    defaults.update(overrides)
    return defaults


def create_checklist_item_payload(key="POWER_RESTORED", **overrides) -> dict:
    defaults = {"key": key, "result": "PASS"}
    defaults.update(overrides)
    return defaults


def create_cash_drop_payload(**overrides) -> dict:
    defaults = {"amount_cents": 5000, "shift_lead_note": "drawer skim"}
    defaults.update(overrides)
    return defaults


def create_crew_member_payload(home_unit_id, **overrides) -> dict:
    defaults = {
        "full_name": TEST_DEFAULTS["CREW_FULL_NAME"],
        "role": "GRILL_OP",
        "home_unit_id": home_unit_id,
        "is_jump_team": True,
    }
    defaults.update(overrides)
    return defaults


def create_assignment_payload(crew_member_id, unit_id, **overrides) -> dict:
    defaults = {
        "crew_member_id": crew_member_id,
        "unit_id": unit_id,
        "assigned_from": "2026-09-10T08:00:00Z",
        "assigned_until": "2026-09-12T08:00:00Z",
        "travel_origin": TEST_DEFAULTS["TRAVEL_ORIGIN"],
    }
    defaults.update(overrides)
    return defaults


def create_asset_payload(home_unit_id, **overrides) -> dict:
    defaults = {"kind": "GENERATOR", "home_unit_id": home_unit_id}
    defaults.update(overrides)
    return defaults


def create_allocation_payload(asset_id, unit_id, **overrides) -> dict:
    defaults = {"asset_id": asset_id, "unit_id": unit_id}
    defaults.update(overrides)
    return defaults


def create_lodging_booking_payload(crew_assignment_id, unit_id, **overrides) -> dict:
    defaults = {
        "crew_assignment_id": crew_assignment_id,
        "unit_id": unit_id,
        "rooms": 1,
        "nightly_rate_cents": TEST_DEFAULTS["NIGHTLY_RATE_CENTS"],
        "check_in": "2026-09-10T14:00:00Z",
        "check_out": "2026-09-11T09:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_relief_org_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["RELIEF_ORG_NAME"],
        "contact_email": TEST_DEFAULTS["RELIEF_ORG_EMAIL"],
    }
    defaults.update(overrides)
    return defaults


def create_relief_pledge_payload(relief_org_id, **overrides) -> dict:
    defaults = {
        "relief_org_id": relief_org_id,
        "meal_count": 10,
        "service_date": "2026-09-10",
    }
    defaults.update(overrides)
    return defaults
