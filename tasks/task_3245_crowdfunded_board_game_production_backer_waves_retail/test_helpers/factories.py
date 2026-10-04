"""Payload factories — one per entity, input fields only (PRD §3)."""
from .constants import TEST_DEFAULTS


def create_campaign_payload(**overrides) -> dict:
    defaults = {
        "title": "Test Campaign",
        "owner_user_id": TEST_DEFAULTS["OWNER_USER_ID"],
        "goal_cents": TEST_DEFAULTS["GOAL_CENTS"],
        "currency": TEST_DEFAULTS["CURRENCY"],
        "closes_at": "2026-10-01T00:00:00Z",
        "pledge_levels": [
            {
                "name": TEST_DEFAULTS["LEVEL_NAME"],
                "price_cents": TEST_DEFAULTS["LEVEL_PRICE_CENTS"],
                "contents": ["base"],
                "quantity_cap": None,
                "late_pledge_premium_pct": 0.0,
                "status": "OPEN",
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_pledge_payload(campaign_id, expected_campaign_version, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "backer_user_id": "b1",
        "backer_email": "b1@x",
        "region_code": TEST_DEFAULTS["REGION"],
        "pledge_level_name": TEST_DEFAULTS["LEVEL_NAME"],
        "expected_campaign_version": expected_campaign_version,
    }
    defaults.update(overrides)
    return defaults


def create_manufacturing_quote_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "factory_name": TEST_DEFAULTS["FACTORY_NAME"],
        "tier_breaks": [
            {
                "min_units": TEST_DEFAULTS["TIER_MIN_UNITS"],
                "unit_price_cents": TEST_DEFAULTS["TIER_UNIT_PRICE_CENTS"],
            }
        ],
    }
    defaults.update(overrides)
    return defaults


def create_production_run_payload(campaign_id, quote_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "quote_id": quote_id,
    }
    defaults.update(overrides)
    return defaults


def create_freight_shipment_payload(production_run_id, **overrides) -> dict:
    defaults = {
        "production_run_id": production_run_id,
        "region_code": TEST_DEFAULTS["REGION"],
        "container_count": 1,
        "declared_value_cents": 10_000,
        "departs_at": "2026-09-07T00:00:00Z",
        "arrives_at": "2026-09-10T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_wave_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "region_code": TEST_DEFAULTS["REGION"],
        "sequence_index": 1,
        "capacity": 10,
        "dispatch_window_start": "2026-09-12T00:00:00Z",
        "dispatch_window_end": "2026-09-15T00:00:00Z",
        "address_lock_at": "2026-09-14T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_distributor_allocation_payload(
    campaign_id, production_run_id, **overrides
) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "distributor_user_id": "d-1",
        "distributor_name": "DistA",
        "region_code": TEST_DEFAULTS["REGION"],
        "msrp_positioning_pct": 0.45,
        "allocation_priority": 1,
        "production_run_id": production_run_id,
        "units_reserved": 1,
    }
    defaults.update(overrides)
    return defaults


def create_replacement_request_payload(campaign_id, pledge_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "pledge_id": pledge_id,
        "component_sku": "base",
        "quantity": 1,
    }
    defaults.update(overrides)
    return defaults


def create_localization_agreement_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "partner_name": "LocPartner",
        "language_code": "fr",
        "royalty_pct": 0.10,
        "print_commitment_units": 100,
        "print_window_start": "2026-10-01T00:00:00Z",
        "print_window_end": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_reprint_decision_payload(campaign_id, **overrides) -> dict:
    defaults = {
        "campaign_id": campaign_id,
        "proposed_units": 100,
        "demand_signal_cents": 10_000,
    }
    defaults.update(overrides)
    return defaults
