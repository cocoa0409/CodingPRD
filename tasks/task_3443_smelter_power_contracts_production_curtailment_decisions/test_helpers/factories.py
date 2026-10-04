"""Payload factories — one per create endpoint, input fields only (PRD §3)."""
from .constants import (
    DEFAULT_WINDOW_START,
    DEFAULT_WINDOW_END,
    FIXED_ONLY_COMPONENTS,
    TEST_DEFAULTS,
)


def create_smelter_payload(**overrides) -> dict:
    defaults = {
        "name": TEST_DEFAULTS["SMELTER_NAME"],
        "region_code": TEST_DEFAULTS["REGION"],
        "rated_capacity_tpd": TEST_DEFAULTS["RATED_CAPACITY_TPD"],
        "labor_headcount": TEST_DEFAULTS["LABOR_HEADCOUNT"],
    }
    defaults.update(overrides)
    return defaults


def create_potline_payload(smelter_id, **overrides) -> dict:
    defaults = {
        "smelter_id": smelter_id,
        "line_code": TEST_DEFAULTS["LINE_CODE"],
        "capacity_tpd": TEST_DEFAULTS["POTLINE_CAPACITY_TPD"],
        "amperage_ka": TEST_DEFAULTS["AMPERAGE_KA"],
    }
    defaults.update(overrides)
    return defaults


def create_power_contract_payload(smelter_id, **overrides) -> dict:
    defaults = {
        "smelter_id": smelter_id,
        "supplier_name": TEST_DEFAULTS["SUPPLIER_NAME"],
        "window_start": DEFAULT_WINDOW_START,
        "window_end": DEFAULT_WINDOW_END,
        "components": FIXED_ONLY_COMPONENTS,
    }
    defaults.update(overrides)
    return defaults


def create_interrupt_event_payload(contract_id, **overrides) -> dict:
    defaults = {
        "contract_id": contract_id,
        "start_at": "2026-03-01T00:00:00Z",
        "end_at": "2026-03-01T12:00:00Z",
        "mw_reduced": 50,
    }
    defaults.update(overrides)
    return defaults


def create_price_observation_payload(**overrides) -> dict:
    defaults = {
        "instrument": "ALUMINUM_LME",
        "region_code": "GLOBAL",
        "observed_at": "2026-08-15T00:00:00Z",
        "price_usd": 2400.00,
    }
    defaults.update(overrides)
    return defaults


def create_hedge_position_payload(smelter_id, **overrides) -> dict:
    defaults = {
        "smelter_id": smelter_id,
        "instrument": "LME_SWAP",
        "volume_tonnes": 5000,
        "strike_price_usd": 2400.00,
        "delivery_month": "2026-10",
    }
    defaults.update(overrides)
    return defaults


def create_alumina_agreement_payload(smelter_id, **overrides) -> dict:
    # PRD §3.4: the two pricing models carry mutually exclusive parameter
    # sets — COST_PLUS requires base_cost_per_tonne + markup_pct and forbids
    # market_discount_pct; MARKET_LINKED requires market_discount_pct and
    # forbids base_cost_per_tonne + markup_pct. Defaults must therefore be
    # pricing-model-aware so an overridden pricing_model does not leave
    # forbidden fields behind in the payload.
    pricing_model = overrides.get("pricing_model", "COST_PLUS")
    if pricing_model == "MARKET_LINKED":
        defaults = {
            "smelter_id": smelter_id,
            "refinery_name": "RefineryNorth",
            "pricing_model": "MARKET_LINKED",
            "market_discount_pct": 0.04,
            "monthly_volume_tonnes": 8000,
        }
    else:
        defaults = {
            "smelter_id": smelter_id,
            "refinery_name": "RefineryNorth",
            "pricing_model": "COST_PLUS",
            "base_cost_per_tonne": 300.00,
            "markup_pct": 0.15,
            "monthly_volume_tonnes": 8000,
        }
    defaults.update(overrides)
    return defaults


def create_curtailment_decision_payload(potline_id, expected_potline_version, **overrides) -> dict:
    defaults = {
        "potline_id": potline_id,
        "expected_potline_version": expected_potline_version,
        "trigger_type": "METAL_PRICE",
        "depth_pct": 50,
        "planned_start": "2026-09-05T00:00:00Z",
        "planned_end": "2026-10-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_restart_plan_payload(potline_id, **overrides) -> dict:
    defaults = {
        "potline_id": potline_id,
        "planned_restart_at": "2026-09-05T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_environmental_permit_payload(smelter_id, **overrides) -> dict:
    defaults = {
        "smelter_id": smelter_id,
        "permit_type": "SPL_DISPOSAL",
        "valid_from": "2026-01-01T00:00:00Z",
        "valid_to": "2027-06-01T00:00:00Z",
    }
    defaults.update(overrides)
    return defaults


def create_labor_agreement_payload(smelter_id, **overrides) -> dict:
    defaults = {
        "smelter_id": smelter_id,
        "union_name": TEST_DEFAULTS["UNION_NAME"],
        "notice_period_days": 0,
        "severance_weeks_per_year": TEST_DEFAULTS["SEVERANCE_WEEKS_PER_YEAR"],
    }
    defaults.update(overrides)
    return defaults


def create_production_plan_payload(smelter_id, expected_smelter_version, **overrides) -> dict:
    defaults = {
        "smelter_id": smelter_id,
        "expected_smelter_version": expected_smelter_version,
        "period_month": "2026-09",
        "allocations": [
            {"product_form": "BILLET", "tonnes": 12000},
            {"product_form": "SLAB", "tonnes": 9000},
            {"product_form": "VALUE_ADDED", "tonnes": 9000},
        ],
    }
    defaults.update(overrides)
    return defaults
