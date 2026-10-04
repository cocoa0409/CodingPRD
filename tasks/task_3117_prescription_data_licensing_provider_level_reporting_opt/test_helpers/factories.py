"""Payload factories — one per entity, input fields only."""
import itertools

from .constants import TEST_DEFAULTS

_counters = itertools.count(1)


def _next() -> int:
    return next(_counters)


def create_client_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Client {n}",
        "entitlement_cells_total": TEST_DEFAULTS["ENTITLEMENT_CELLS_TOTAL"],
    }
    defaults.update(overrides)
    return defaults


def create_supplier_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Supplier {n}",
        "supplier_type": "PHARMACY",
        "state_code": "CA",
    }
    defaults.update(overrides)
    return defaults


def create_agreement_payload(**overrides) -> dict:
    defaults = {
        "data_domain": "RETAIL_SCRIPTS",
        "exclusivity_start_date": "2026-01-01",
        "exclusivity_end_date": "2027-01-01",
        "royalty_budget_cents": TEST_DEFAULTS["ROYALTY_BUDGET_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_deid_profile_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"DP-{n}",
        "salt_version": f"sv-{n}",
    }
    defaults.update(overrides)
    return defaults


def create_batch_payload(agreement_id, **overrides) -> dict:
    defaults = {
        "agreement_id": agreement_id,
        "period_code": "2026-08",
        "record_count": TEST_DEFAULTS["RECORD_COUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_prescriber_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "full_name": f"Dr Prescriber {n}",
        "npi": f"NPI-{100000 + n}",
        "state_code": "TX",
        "specialty": "CARDIOLOGY",
    }
    defaults.update(overrides)
    return defaults


def create_jurisdiction_rule_payload(**overrides) -> dict:
    defaults = {
        "state_code": "CA",
        "restrict_prescriber_identifiable": True,
        "effective_from": "2026-01-01",
    }
    defaults.update(overrides)
    return defaults


def create_methodology_payload(**overrides) -> dict:
    n = _next()
    defaults = {
        "name": f"Methodology {n}",
        "default_variant": "PROJECTION_WEIGHTED",
    }
    defaults.update(overrides)
    return defaults


def create_cell_payload(methodology_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "methodology_id": methodology_id,
        "geography_code": f"GEO-{n:02d}",
        "specialty": "CARDIOLOGY",
        "period_code": "2026-08",
        "sample_units": 10,
        "market_outlets": 10,
        "sampled_outlets": 10,
        "market_population": 1000,
        "sampled_population": 1000,
        "specialty_uptake_index": 1.0,
        "supplier_ids": [],
    }
    defaults.update(overrides)
    return defaults


def create_product_payload(client_id, methodology_id, **overrides) -> dict:
    n = _next()
    defaults = {
        "client_id": client_id,
        "methodology_id": methodology_id,
        "name": f"Product {n}",
        "prescriber_ids": [],
        "base_fee_cents": TEST_DEFAULTS["BASE_FEE_CENTS"],
        "cell_fee_base_cents": TEST_DEFAULTS["CELL_FEE_BASE_CENTS"],
        "cell_fee_multiplier": TEST_DEFAULTS["CELL_FEE_MULTIPLIER"],
        "volume_discount_pct": TEST_DEFAULTS["VOLUME_DISCOUNT_PCT"],
        "monthly_license_fee_cents": TEST_DEFAULTS["MONTHLY_LICENSE_FEE_CENTS"],
    }
    defaults.update(overrides)
    return defaults


def create_delivery_period_payload(**overrides) -> dict:
    defaults = {
        "period_code": "2026-08",
        "period_end_date": "2026-08-31",
        "total_due_deliveries": 1,
    }
    defaults.update(overrides)
    return defaults
