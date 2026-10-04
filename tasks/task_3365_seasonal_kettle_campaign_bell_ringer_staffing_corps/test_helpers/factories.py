"""Payload factories — one per entity, input fields only."""
from .constants import (
    CAMPAIGN_STARTS_ON,
    CAMPAIGN_ENDS_ON,
    PLACEMENT_STARTS_ON,
    PLACEMENT_ENDS_ON,
    INTAKE_OPENS_ON,
    INTAKE_CLOSES_ON,
    DEFAULT_CAMPAIGN_GOAL_CENTS,
    DEFAULT_LABOR_BUDGET_CENTS,
    DEFAULT_DAILY_REQUIRED_MINUTES,
)

DEFAULTS = {
    "UNIT_NAME": "Corps 41",
    "TERRITORY_CODE": "NT",
    "CAMPAIGN_NAME": "2026 Christmas Kettle Campaign",
    "RETAILER_NAME": "Northgate Market",
    "STORE_NUMBER": "114",
    "CITY": "Springfield",
    "STATE_CODE": "IL",
    "LOCATION_CODE": "K-114-A",
    "RINGER_NAME": "Priya Raman",
    "RINGER_EMAIL": "priya.raman@example.org",
    "RINGER_DOB": "1985-09-30T00:00:00Z",
    "PROGRAM_NAME": "Christmas Toy Distribution",
    "CORPS_PROGRAM_NAME": "Sunbeam Youth Club",
}


def create_unit_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["UNIT_NAME"],
        "unit_type": "CORPS",
        "territory_code": DEFAULTS["TERRITORY_CODE"],
        "canteen_pool_size": 4,
    }
    payload.update(overrides)
    return payload


def create_campaign_payload(**overrides) -> dict:
    payload = {
        "name": DEFAULTS["CAMPAIGN_NAME"],
        "season_year": 2026,
        "starts_on": CAMPAIGN_STARTS_ON,
        "ends_on": CAMPAIGN_ENDS_ON,
        "goal_cents": DEFAULT_CAMPAIGN_GOAL_CENTS,
        "labor_budget_cents": DEFAULT_LABOR_BUDGET_CENTS,
    }
    payload.update(overrides)
    return payload


def create_host_site_payload(campaign_id, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "retailer_name": DEFAULTS["RETAILER_NAME"],
        "store_number": DEFAULTS["STORE_NUMBER"],
        "city": DEFAULTS["CITY"],
        "state_code": DEFAULTS["STATE_CODE"],
        "permission_starts_on": CAMPAIGN_STARTS_ON,
        "permission_ends_on": CAMPAIGN_ENDS_ON,
        "exclusivity_scope": "NON_EXCLUSIVE",
        "max_kettles": 3,
    }
    payload.update(overrides)
    return payload


def create_kettle_location_payload(host_site_id, campaign_id, **overrides) -> dict:
    payload = {
        "host_site_id": host_site_id,
        "campaign_id": campaign_id,
        "location_code": DEFAULTS["LOCATION_CODE"],
        "placement": "OUTDOOR",
        "placement_starts_on": PLACEMENT_STARTS_ON,
        "placement_ends_on": PLACEMENT_ENDS_ON,
        "daily_required_minutes": DEFAULT_DAILY_REQUIRED_MINUTES,
    }
    payload.update(overrides)
    return payload


def create_bell_ringer_payload(corps_id, **overrides) -> dict:
    payload = {
        "full_name": DEFAULTS["RINGER_NAME"],
        "email": DEFAULTS["RINGER_EMAIL"],
        "ringer_type": "VOLUNTEER",
        "corps_id": corps_id,
        "date_of_birth": DEFAULTS["RINGER_DOB"],
        "hourly_rate_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_shift_payload(kettle_location_id, bell_ringer_id, starts_at, ends_at,
                         expected_kettle_location_version, **overrides) -> dict:
    payload = {
        "kettle_location_id": kettle_location_id,
        "bell_ringer_id": bell_ringer_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "break_minutes": 0,
        "shift_kind": "REGULAR",
        "expected_kettle_location_version": expected_kettle_location_version,
    }
    payload.update(overrides)
    return payload


def create_collection_payload(kettle_location_id, collected_on, declared_cents,
                              **overrides) -> dict:
    payload = {
        "kettle_location_id": kettle_location_id,
        "collected_on": collected_on,
        "declared_cents": declared_cents,
        "coin_cents": 0,
        "currency_cents": 0,
        "check_cents": 0,
    }
    payload.update(overrides)
    return payload


def create_digital_giving_payload(campaign_id, unit_id, amount_cents, external_ref,
                                  **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "unit_id": unit_id,
        "amount_cents": amount_cents,
        "channel": "QR",
        "occurred_at": "2026-11-14T12:00:00Z",
        "external_ref": external_ref,
    }
    payload.update(overrides)
    return payload


def create_assistance_program_payload(campaign_id, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "name": DEFAULTS["PROGRAM_NAME"],
        "program_type": "TOY",
        "intake_opens_on": INTAKE_OPENS_ON,
        "intake_closes_on": INTAKE_CLOSES_ON,
        "household_cap": 50,
        "per_household_limit_cents": 25000,
    }
    payload.update(overrides)
    return payload


def create_assistance_application_payload(program_id, **overrides) -> dict:
    payload = {
        "program_id": program_id,
        "applicant_name": "Dolores Whitfield",
        "household_size": 4,
        "annual_income_cents": 3000000,
    }
    payload.update(overrides)
    return payload


def create_corps_program_payload(unit_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "name": DEFAULTS["CORPS_PROGRAM_NAME"],
        "category": "YOUTH",
        "capacity": 2,
        "waitlist_enabled": True,
        "meeting_pattern": "Tuesdays 16:00",
    }
    payload.update(overrides)
    return payload


def create_deployment_payload(unit_id, **overrides) -> dict:
    payload = {
        "unit_id": unit_id,
        "incident_name": "Prairie Ridge Wildfire",
        "incident_command_level": "TYPE_3",
        "requested_canteens": 2,
        "command_authority": "IC Dana Whitmore",
    }
    payload.update(overrides)
    return payload


def create_reallocation_payload(campaign_id, from_location_id, to_location_id,
                                moved_hours, effective_on, **overrides) -> dict:
    payload = {
        "campaign_id": campaign_id,
        "from_location_id": from_location_id,
        "to_location_id": to_location_id,
        "moved_hours": moved_hours,
        "effective_on": effective_on,
        "rationale": "source location underperforms per hour",
    }
    payload.update(overrides)
    return payload
