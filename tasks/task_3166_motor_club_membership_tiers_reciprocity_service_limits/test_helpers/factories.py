"""Payload factories — one per entity, input fields only (PRD §4)."""

DEFAULTS = {
    "CLUB_CODE": "NCA",
    "CLUB_NAME": "NorCal Auto",
    "TERRITORY": ["CA"],
    "ARRIVAL_TARGET_MINUTES": 45,
    "PRIMARY_NAME": "Pat Primary",
    "DOB_ADULT": "1980-01-01T00:00:00Z",
}

# Tier presets used across tests. Keys follow the tier code.
TIER_PRESETS = {
    "CLASSIC": {
        "code": "CLASSIC",
        "annual_dues_cents": 5000,
        "included_tow_miles": 5,
        "annual_call_cap": 4,
        "lockout_benefit_cents": 5500,
        "battery_service_included": False,
        "household_member_price_cents": 2500,
        "overage_rate_cents_per_mile": 650,
        "upgrade_waiting_days": 3,
        "rank": 1,
    },
    "PLUS": {
        "code": "PLUS",
        "annual_dues_cents": 9000,
        "included_tow_miles": 100,
        "annual_call_cap": 4,
        "lockout_benefit_cents": 6500,
        "battery_service_included": True,
        "household_member_price_cents": 3500,
        "overage_rate_cents_per_mile": 650,
        "upgrade_waiting_days": 3,
        "rank": 2,
    },
    "PREMIER": {
        "code": "PREMIER",
        "annual_dues_cents": 15000,
        "included_tow_miles": 200,
        "annual_call_cap": 6,
        "lockout_benefit_cents": 7500,
        "battery_service_included": True,
        "household_member_price_cents": 4500,
        "overage_rate_cents_per_mile": 600,
        "upgrade_waiting_days": 7,
        "rank": 3,
    },
}

_email_counter = [0]


def unique_email() -> str:
    _email_counter[0] += 1
    return f"member-{_email_counter[0]}@example.com"


def create_club_payload(**overrides) -> dict:
    defaults = {
        "club_code": DEFAULTS["CLUB_CODE"],
        "name": DEFAULTS["CLUB_NAME"],
        "territory_state_codes": list(DEFAULTS["TERRITORY"]),
        "default_arrival_target_minutes": DEFAULTS["ARRIVAL_TARGET_MINUTES"],
    }
    defaults.update(overrides)
    return defaults


def create_tier_payload(code: str = "CLASSIC", **overrides) -> dict:
    defaults = dict(TIER_PRESETS[code])
    defaults.update(overrides)
    return defaults


def create_membership_payload(home_club_id: str, tier_code: str = "CLASSIC", **overrides) -> dict:
    defaults = {
        "home_club_id": home_club_id,
        "primary_member_name": DEFAULTS["PRIMARY_NAME"],
        "primary_member_email": unique_email(),
        "tier_code": tier_code,
    }
    defaults.update(overrides)
    return defaults


def create_household_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": "Sam Spouse",
        "relationship": "SPOUSE",
        "date_of_birth": "1982-01-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_primary_member_payload(**overrides) -> dict:
    defaults = {
        "full_name": DEFAULTS["PRIMARY_NAME"],
        "relationship": "SPOUSE",
        "date_of_birth": DEFAULTS["DOB_ADULT"],
        "is_primary": True,
    }
    defaults.update(overrides)
    return defaults


def create_provider_payload(servicing_club_id: str, **overrides) -> dict:
    defaults = {
        "servicing_club_id": servicing_club_id,
        "name": "NCA Fleet 1",
        "provider_kind": "OWNED",
        "capabilities": ["TOW"],
        "home_base_state_code": "CA",
        "sla_multiplier": 1.0,
        "shift_start_minute": 0,
        "shift_end_minute": 0,
        "max_concurrent_dispatches": 2,
    }
    defaults.update(overrides)
    return defaults


def create_part_stock_payload(**overrides) -> dict:
    defaults = {
        "part_sku": "BAT-G24",
        "part_kind": "BATTERY",
        "quantity_on_hand": 3,
    }
    defaults.update(overrides)
    return defaults


def create_service_call_payload(membership_id: str, requesting_member_id: str, **overrides) -> dict:
    defaults = {
        "membership_id": membership_id,
        "requesting_member_id": requesting_member_id,
        "service_type": "TOW",
        "breakdown_location_state": "CA",
        "requested_tow_miles": 5,
    }
    defaults.update(overrides)
    return defaults


def create_settlement_period_payload(servicing_club_id: str, **overrides) -> dict:
    defaults = {
        "servicing_club_id": servicing_club_id,
        "period_start_date": "2026-09-01T00:00:00Z",
        "period_end_date": "2026-10-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_ancillary_product_payload(**overrides) -> dict:
    defaults = {
        "product_type": "IDENTITY_PROTECTION",
        "name": "ID Shield",
        "price_cents": 12000,
        "min_tier_code": "CLASSIC",
        "commission_bps": 1000,
    }
    defaults.update(overrides)
    return defaults


def create_ancillary_sale_payload(membership_id: str, product_id: str, **overrides) -> dict:
    defaults = {
        "membership_id": membership_id,
        "product_id": product_id,
    }
    defaults.update(overrides)
    return defaults
