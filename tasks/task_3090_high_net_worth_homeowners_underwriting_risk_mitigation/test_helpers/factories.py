"""Payload factories — one per entity, input fields only."""
from .constants import TEST_DEFAULTS


def create_risk_zone_payload(**overrides) -> dict:
    defaults = {
        "zone_code": "ZTEST",
        "state_code": "CA",
        "wildland_urban_interface_band": "WITHIN_WUI",
        "sustained_wind_mph": TEST_DEFAULTS["SUSTAINED_WIND_MPH"],
        "mitigation_band_multiplier": TEST_DEFAULTS["MITIGATION_BAND_MULTIPLIER"],
        "mitigated_loss_multiplier": TEST_DEFAULTS["MITIGATED_LOSS_MULTIPLIER"],
        "exposure_band": "EXTREME",
    }
    defaults.update(overrides)
    return defaults


def create_agency_payload(**overrides) -> dict:
    defaults = {
        "agency_code": "AGTEST",
        "legal_name": "Test Premier Agency",
        "state_code": "CA",
        "delegated_authority_limit_cents": 500_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_property_payload(risk_zone_id: str, agency_id: str, **overrides) -> dict:
    defaults = {
        "risk_zone_id": risk_zone_id,
        "agency_id": agency_id,
        "address_line": "1 Test Rd",
        "grid_risk_block": "TEST-A",
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_payload(**overrides) -> dict:
    defaults = {
        "appraiser_name": "Coast Valuation",
        "valuation_method": "SITE_MEASURED",
        "appraised_on": TEST_DEFAULTS["APPRAISED_ON"],
        "dwelling_cost_cents": TEST_DEFAULTS["REPLACEMENT_COST_CENTS"],
        "contents_cost_cents": TEST_DEFAULTS["CONTENTS_COST_CENTS"],
        "valuation_confidence_pct": 95.0,
    }
    defaults.update(overrides)
    return defaults


def create_appraisal_document_payload(**overrides) -> dict:
    defaults = {
        "item_class": "JEWELRY",
        "appraiser_name": "Coast Jewels",
        "appraisal_date": TEST_DEFAULTS["DOC_APPRAISAL_DATE"],
        "appraised_value_cents": 60_000_000,
    }
    defaults.update(overrides)
    return defaults


def create_scheduled_item_payload(appraisal_doc_id: str, **overrides) -> dict:
    defaults = {
        "item_type": "JEWELRY",
        "declared_value_cents": 50_000_000,
        "appraisal_doc_id": appraisal_doc_id,
    }
    defaults.update(overrides)
    return defaults


def create_mitigation_requirement_payload(**overrides) -> dict:
    defaults = {
        "requirement_code": "DEFENSIBLE_SPACE",
        "band_awarded": "CLEARED",
        "source": "UNDERWRITING",
        "due_on": "2026-12-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_risk_consultation_payload(**overrides) -> dict:
    defaults = {
        "consultant_user_id": TEST_DEFAULTS["CONSULTANT_USER_ID"],
        "scheduled_for": "2026-09-10T09:00:00Z",
        "duration_minutes": 60,
    }
    defaults.update(overrides)
    return defaults


def create_enrollment_payload(agency_id: str, **overrides) -> dict:
    defaults = {
        "agency_id": agency_id,
        "dwelling_coverage_cents": TEST_DEFAULTS["DWELLING_COVERAGE_CENTS"],
        "contents_coverage_cents": 0,
        "scheduled_coverage_cents": 0,
        "loss_of_use_coverage_cents": 0,
    }
    defaults.update(overrides)
    return defaults


def create_claim_payload(**overrides) -> dict:
    defaults = {
        "cause_of_loss": "WILDFIRE",
        "loss_date": "2026-09-20T00:00:00Z",
        "reported_indemnity_cents": 200_000_000,
        "adjuster_user_id": "adj-morgan",
        "adjuster_override": False,
    }
    defaults.update(overrides)
    return defaults


def create_non_renewal_notice_payload(**overrides) -> dict:
    defaults = {
        "ground": "MITIGATION_FAILURE",
        "effective_on": "2026-11-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults