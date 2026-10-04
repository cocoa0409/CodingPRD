"""Payload factories — one per creatable resource, input fields only.

Conventions:
- Keys whose value is None are OMITTED from the payload, so optional inputs
  (tooling_fee_cents, tooling_code, prestige_similarity, cross_platform_spread,
  successor_product_id, channel, blocked_items, notes) are simply absent by
  default, and a caller can strip a defaulted optional key with override=None.
- Unknown override keys pass straight through (tests that poke system-field
  injection, e.g. a client-supplied id, rely on this).
- Concept names and SKU names default to unique values so repeated factory
  use within one test never trips the non-KILLED concept-name uniqueness rule.
"""
import itertools

from .constants import (
    DEFAULT_OCCUPANCY_END,
    DEFAULT_OCCUPANCY_START,
    DEFAULT_PRODUCTION_QUARTER,
    DEFAULT_QUOTE_VALID_UNTIL,
    DEFAULT_REVIEW_DATE,
    DEFAULT_SEASON,
    DEFAULT_WINDOW_END,
    DEFAULT_WINDOW_START,
)

__all__ = [
    "unique_name",
    "unique_sku",
    "create_trend_signal_payload",
    "create_concept_payload",
    "create_product_payload",
    "create_manufacturer_payload",
    "create_formula_project_payload",
    "create_cost_quote_payload",
    "create_compliance_dossier_payload",
    "create_dossier_review_payload",
    "create_retail_partner_payload",
    "create_line_review_payload",
    "create_planogram_slot_payload",
    "create_launch_plan_payload",
    "create_sample_distribution_payload",
    "create_discontinuation_review_payload",
]

_name_counter = itertools.count(1)


def unique_name(prefix: str = "Concept") -> str:
    """Globally unique label — uniqueness across tests is a harmless superset
    of the per-test uniqueness the server requires."""
    return f"{prefix} {next(_name_counter)}"


def unique_sku(prefix: str = "SKU") -> str:
    return f"{prefix}-{next(_name_counter):04d}"


def _clean(payload: dict) -> dict:
    """Drop keys whose value is None (absent, not JSON null)."""
    return {k: v for k, v in payload.items() if v is not None}


def create_trend_signal_payload(**overrides) -> dict:
    """Default: a prestige-launch signal scoring exactly 70.0 on evaluation
    (0.5*80 + 0.3*50 + 0.2*75), i.e. exactly at the selection threshold."""
    defaults = {
        "source": "PRESTIGE_LAUNCH",
        "platform": "runway",
        "category": "EYES",
        "mention_velocity_7d": 4000,
        "engagement_growth_pct": 1.0,
        "prestige_similarity": 0.75,
        "cross_platform_spread": None,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_concept_payload(**overrides) -> dict:
    """FK trend_signal_id must be supplied via override."""
    defaults = {
        "trend_signal_id": None,
        "name": unique_name(),
        "category": "EYES",
        "target_price_point_cents": 1000,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_product_payload(**overrides) -> dict:
    """FK concept_id must be supplied via override. tooling_code omitted by
    default (null code can never be tooling reuse)."""
    defaults = {
        "concept_id": None,
        "sku_name": unique_sku(),
        "tooling_code": None,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_manufacturer_payload(**overrides) -> dict:
    defaults = {
        "name": "FastLab Cosmetics",
        "capabilities": ["EYES", "LIPS"],
        "base_lead_time_weeks": 4,
        "moq_units": 500,
        "quality_tier": "STANDARD",
        "capacity_slots_per_quarter": 4,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_formula_project_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "contract_manufacturer_id": None,
        "brief": "Volumizing mascara, vegan wax blend",
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_cost_quote_payload(**overrides) -> dict:
    """Default commercial terms produce landed_provisional_cents == 234
    (200 + ceil(10000/1000)=10 + round(40000*50/500000)=4 + round(204*0.10)=20).
    FKs and expected_product_version must be supplied via override (the
    fixtures fill expected_product_version with the product's live version
    when the caller does not pin one)."""
    defaults = {
        "product_id": None,
        "contract_manufacturer_id": None,
        "unit_cost_cents": 200,
        "tooling_fee_cents": 10000,
        "freight_total_cents": 40000,
        "unit_weight_grams": 50,
        "shipment_weight_grams": 500000,
        "duty_rate": 0.10,
        "initial_order_qty": 1000,
        "valid_until": DEFAULT_QUOTE_VALID_UNTIL,
        "production_quarter": DEFAULT_PRODUCTION_QUARTER,
        "expected_product_version": None,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_compliance_dossier_payload(**overrides) -> dict:
    defaults = {"product_id": None}
    defaults.update(overrides)
    return _clean(defaults)


def create_dossier_review_payload(dimension: str, outcome: str, **overrides) -> dict:
    defaults = {
        "dimension": dimension,
        "outcome": outcome,
        "blocked_items": None,
        "notes": None,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_retail_partner_payload(**overrides) -> dict:
    defaults = {
        "name": "ValueMart",
        "banner_code": "VM",
        "category_capacities": {"EYES": 10, "LIPS": 8},
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_line_review_payload(**overrides) -> dict:
    """Default submission window is the half-open interval
    [2026-10-01, 2026-10-15) with review date 2026-10-20."""
    defaults = {
        "retail_partner_id": None,
        "season": DEFAULT_SEASON,
        "submission_window_start": DEFAULT_WINDOW_START,
        "submission_window_end": DEFAULT_WINDOW_END,
        "review_date": DEFAULT_REVIEW_DATE,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_planogram_slot_payload(**overrides) -> dict:
    """FKs and expected_line_review_version must be supplied via override."""
    defaults = {
        "line_review_id": None,
        "product_id": None,
        "category": "EYES",
        "position_code": "EYES-A1",
        "facings": 10,
        "occupancy_start": DEFAULT_OCCUPANCY_START,
        "occupancy_end": DEFAULT_OCCUPANCY_END,
        "expected_line_review_version": None,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_launch_plan_payload(**overrides) -> dict:
    """Default: demand 800 / marketing 50000 / cogs 200000 / sample 20000.
    Against the default 10-facing slot this yields capacity 960, variants
    800 (DEMAND) and 640 (RISK_ADJUSTED at risk 0.20)."""
    defaults = {
        "product_id": None,
        "planogram_slot_id": None,
        "demand_forecast_units": 800,
        "marketing_budget_cents": 50000,
        "cogs_budget_cents": 200000,
        "sample_budget_cents": 20000,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_sample_distribution_payload(event_type: str, units: int, **overrides) -> dict:
    defaults = {
        "event_type": event_type,
        "units": units,
        "channel": None,
    }
    defaults.update(overrides)
    return _clean(defaults)


def create_discontinuation_review_payload(**overrides) -> dict:
    defaults = {
        "product_id": None,
        "reason": "TREND_DECAY",
        "successor_product_id": None,
    }
    defaults.update(overrides)
    return _clean(defaults)
