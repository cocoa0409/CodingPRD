"""Payload factories — one per entity, input fields only (PRD §4)."""
from .constants import DY_END, DY_LABEL, DY_START, TEST_DEFAULTS


def create_delivery_year_payload(**overrides) -> dict:
    defaults = {
        "delivery_year_label": DY_LABEL,
        "planning_period_start": DY_START,
        "planning_period_end": DY_END,
    }
    defaults.update(overrides)
    return defaults


def create_zone_payload(zone_code="RTO", **overrides) -> dict:
    defaults = {"zone_code": zone_code}
    defaults.update(overrides)
    return defaults


def create_forecast_payload(**overrides) -> dict:
    defaults = {
        "rto_peak_load_mw": TEST_DEFAULTS["PEAK_LOAD_MW"],
        "reserve_margin_pct": TEST_DEFAULTS["RESERVE_MARGIN_PCT"],
        "pool_wide_avg_eford": TEST_DEFAULTS["POOL_WIDE_AVG_EFORD"],
        "zonal_peak_shares": {"RTO": 1.0},
    }
    defaults.update(overrides)
    return defaults


def create_owner_payload(**overrides) -> dict:
    defaults = {
        "legal_name": "Alpha GenCo",
        "contact_email": "alpha@x.com",
        "credit_score": TEST_DEFAULTS["CREDIT_SCORE"],
    }
    defaults.update(overrides)
    return defaults


def create_resource_payload(owner_id, zone_id, **overrides) -> dict:
    defaults = {
        "owner_id": owner_id,
        "zone_id": zone_id,
        "resource_type": "GEN",
        "nameplate_mw": TEST_DEFAULTS["NAMEPLATE_MW"],
    }
    defaults.update(overrides)
    return defaults


def create_accreditation_payload(resource_id, delivery_year_id, **overrides) -> dict:
    defaults = {
        "resource_id": resource_id,
        "delivery_year_id": delivery_year_id,
        "method": "CLASS_AVG",
        "class_avg_factor": TEST_DEFAULTS["CLASS_AVG_FACTOR"],
        "forced_outage_rate": TEST_DEFAULTS["FORCED_OUTAGE_RATE"],
        "scarcity_hours_sampled": TEST_DEFAULTS["SCARCITY_HOURS_SAMPLED"],
    }
    defaults.update(overrides)
    return defaults


def create_auction_run_payload(delivery_year_id, **overrides) -> dict:
    defaults = {"delivery_year_id": delivery_year_id, "run_label": "BRA"}
    defaults.update(overrides)
    return defaults


def create_offer_payload(resource_id, auction_run_id, **overrides) -> dict:
    defaults = {
        "resource_id": resource_id,
        "auction_run_id": auction_run_id,
        "offer_mw": 10.0,
        "offer_price_per_mw_day": 70.0,
    }
    defaults.update(overrides)
    return defaults


def create_replacement_payload(commitment_id, replacement_resource_id,
                               expected_commitment_version, **overrides) -> dict:
    defaults = {
        "commitment_id": commitment_id,
        "replacement_resource_id": replacement_resource_id,
        "replacement_mw": 4.0,
        "price_per_mw_day": 55.0,
        "expected_commitment_version": expected_commitment_version,
    }
    defaults.update(overrides)
    return defaults


def create_emergency_event_payload(delivery_year_id, **overrides) -> dict:
    defaults = {
        "delivery_year_id": delivery_year_id,
        "event_start": "2029-06-10T13:00:00Z",
        "event_end": "2029-06-10T15:00:00Z",
        "event_type": "EMERGENCY_ACTION",
    }
    defaults.update(overrides)
    return defaults


def create_measurement_report_payload(resource_id, delivery_year_id, **overrides) -> dict:
    defaults = {
        "resource_id": resource_id,
        "delivery_year_id": delivery_year_id,
        "reporting_period_start": "2029-06-01T00:00:00Z",
        "reporting_period_end": "2029-08-01T00:00:00Z",
        "metered_mwh": 1464.0,
        "baseline_mwh": 2000.0,
    }
    defaults.update(overrides)
    return defaults
