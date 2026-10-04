"""Entity shape assertions and domain invariant checkers.

Each assert_<entity>() checks the common envelope fields strictly (id UUID,
created_at/updated_at ISO 8601, integer version >= 1), the status field
against its lifecycle enum, the request-supplied fields for presence and
type, and the system/computed fields for type whenever present. Nullable
fields are read with .get() so "null until <event>" is accepted alongside a
populated value.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    CertStatus,
    ClaimStatus,
    ConceptStatus,
    CostQuoteStatus,
    DiscontinuationReason,
    DiscontinuationReviewStatus,
    FormulaProjectStatus,
    IngredientStatus,
    LaunchPlanStatus,
    LineReviewStatus,
    LockedVariant,
    ManufacturerStatus,
    PackagingStatus,
    PlanogramSlotStatus,
    ProductStatus,
    QualityTier,
    RegistrationStatus,
    SamplingStatus,
    TrendSignalStatus,
    TrendSource,
)

__all__ = [
    "assert_trend_signal",
    "assert_concept",
    "assert_product",
    "assert_manufacturer",
    "assert_formula_project",
    "assert_cost_quote",
    "assert_compliance_dossier",
    "assert_retail_partner",
    "assert_line_review",
    "assert_planogram_slot",
    "assert_launch_plan",
    "assert_discontinuation_review",
    "assert_launch_inventory_conserved",
    "assert_footprint_conservation",
    "assert_dossier_compliance_verdict",
    "assert_sample_cap_respected",
]


def _values(enum_cls) -> list:
    return [m.value for m in enum_cls]


def _assert_common(data: dict, entity: str) -> None:
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and not isinstance(data.get("version"), bool), (
        f"{entity}.version must be an integer, got {data.get('version')!r}"
    )
    assert data["version"] >= 1, f"{entity}.version must be >= 1, got {data['version']}"


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _assert_nullable_int(data: dict, field: str, entity: str) -> None:
    value = data.get(field)
    assert value is None or _is_int(value), f"{entity}.{field} must be an integer or null, got {value!r}"


def _assert_nullable_number(data: dict, field: str, entity: str) -> None:
    value = data.get(field)
    assert value is None or _is_number(value), f"{entity}.{field} must be a number or null, got {value!r}"


def _assert_nullable_str(data: dict, field: str, entity: str) -> None:
    value = data.get(field)
    assert value is None or isinstance(value, str), f"{entity}.{field} must be a string or null, got {value!r}"


def _assert_nullable_iso(data: dict, field: str, entity: str) -> None:
    value = data.get(field)
    assert value is None or is_iso8601_timestamp(value), (
        f"{entity}.{field} must be an ISO 8601 UTC timestamp or null, got {value!r}"
    )


def assert_trend_signal(data: dict) -> None:
    _assert_common(data, "TrendSignal")
    assert data["source"] in _values(TrendSource), f"source must be one of {_values(TrendSource)}"
    assert isinstance(data["platform"], str) and data["platform"], "platform must be a non-empty string"
    assert isinstance(data["category"], str) and data["category"], "category must be a non-empty string"
    assert _is_int(data["mention_velocity_7d"]) and data["mention_velocity_7d"] >= 0, (
        "mention_velocity_7d must be a non-negative integer"
    )
    assert _is_number(data["engagement_growth_pct"]) and data["engagement_growth_pct"] >= 0, (
        "engagement_growth_pct must be a non-negative number"
    )
    _assert_nullable_number(data, "prestige_similarity", "TrendSignal")
    _assert_nullable_number(data, "cross_platform_spread", "TrendSignal")
    assert data["status"] in _values(TrendSignalStatus), f"status must be one of {_values(TrendSignalStatus)}"
    _assert_nullable_number(data, "momentum_score", "TrendSignal")
    _assert_nullable_iso(data, "evaluated_at", "TrendSignal")


def assert_concept(data: dict) -> None:
    _assert_common(data, "Concept")
    assert isinstance(data["trend_signal_id"], str) and data["trend_signal_id"], "trend_signal_id required"
    assert isinstance(data["name"], str) and data["name"], "name must be a non-empty string"
    assert isinstance(data["category"], str) and data["category"], "category must be a non-empty string"
    assert _is_int(data["target_price_point_cents"]), "target_price_point_cents must be an integer"
    assert data["status"] in _values(ConceptStatus), f"status must be one of {_values(ConceptStatus)}"
    _assert_nullable_int(data, "target_unit_cost_cents", "Concept")
    _assert_nullable_iso(data, "selected_at", "Concept")


def assert_product(data: dict) -> None:
    _assert_common(data, "Product")
    assert isinstance(data["concept_id"], str) and data["concept_id"], "concept_id required"
    assert isinstance(data["sku_name"], str) and data["sku_name"], "sku_name must be a non-empty string"
    _assert_nullable_str(data, "tooling_code", "Product")
    assert data["status"] in _values(ProductStatus), f"status must be one of {_values(ProductStatus)}"
    assert data["packaging_status"] in _values(PackagingStatus), (
        f"packaging_status must be one of {_values(PackagingStatus)}"
    )
    assert isinstance(data["tooling_reuse"], bool), "tooling_reuse must be a boolean"
    assert _is_int(data["packaging_lead_weeks"]) and data["packaging_lead_weeks"] >= 1, (
        "packaging_lead_weeks must be a positive integer"
    )
    _assert_nullable_str(data, "successor_product_id", "Product")
    _assert_nullable_iso(data, "launched_at", "Product")


def assert_manufacturer(data: dict) -> None:
    _assert_common(data, "ContractManufacturer")
    assert isinstance(data["name"], str) and data["name"], "name must be a non-empty string"
    assert isinstance(data["capabilities"], list), "capabilities must be a list"
    assert all(isinstance(c, str) for c in data["capabilities"]), "capabilities entries must be strings"
    assert _is_int(data["base_lead_time_weeks"]) and data["base_lead_time_weeks"] >= 1, (
        "base_lead_time_weeks must be an integer >= 1"
    )
    assert _is_int(data["moq_units"]) and data["moq_units"] >= 1, "moq_units must be an integer >= 1"
    assert data["quality_tier"] in _values(QualityTier), f"quality_tier must be one of {_values(QualityTier)}"
    assert _is_int(data["capacity_slots_per_quarter"]) and data["capacity_slots_per_quarter"] >= 0, (
        "capacity_slots_per_quarter must be an integer >= 0"
    )
    assert data["status"] in _values(ManufacturerStatus), f"status must be one of {_values(ManufacturerStatus)}"


def assert_formula_project(data: dict) -> None:
    _assert_common(data, "FormulaProject")
    assert isinstance(data["product_id"], str) and data["product_id"], "product_id required"
    assert isinstance(data["contract_manufacturer_id"], str) and data["contract_manufacturer_id"], (
        "contract_manufacturer_id required"
    )
    assert isinstance(data["brief"], str), "brief must be a string"
    assert data["status"] in _values(FormulaProjectStatus), (
        f"status must be one of {_values(FormulaProjectStatus)}"
    )
    assert _is_int(data["round_count"]) and data["round_count"] >= 1, "round_count must be an integer >= 1"
    assert is_iso8601_timestamp(data.get("due_at", "")), "due_at must be an ISO 8601 UTC timestamp"
    _assert_nullable_iso(data, "submitted_at", "FormulaProject")
    assert isinstance(data["is_late"], bool), "is_late must be a boolean"
    _assert_nullable_int(data, "formula_version", "FormulaProject")


def assert_cost_quote(data: dict) -> None:
    _assert_common(data, "CostQuote")
    assert isinstance(data["product_id"], str) and data["product_id"], "product_id required"
    assert isinstance(data["contract_manufacturer_id"], str) and data["contract_manufacturer_id"], (
        "contract_manufacturer_id required"
    )
    for field in ("unit_cost_cents", "tooling_fee_cents", "freight_total_cents"):
        assert _is_int(data[field]) and data[field] >= 0, f"{field} must be an integer >= 0"
    assert _is_int(data["unit_weight_grams"]) and data["unit_weight_grams"] >= 1, (
        "unit_weight_grams must be an integer >= 1"
    )
    assert _is_int(data["shipment_weight_grams"]) and data["shipment_weight_grams"] >= data["unit_weight_grams"], (
        "shipment_weight_grams must be an integer >= unit_weight_grams"
    )
    assert _is_number(data["duty_rate"]) and 0 <= data["duty_rate"] <= 1, "duty_rate must be in [0, 1]"
    assert _is_int(data["initial_order_qty"]) and data["initial_order_qty"] >= 1, (
        "initial_order_qty must be an integer >= 1"
    )
    assert is_iso8601_timestamp(data.get("valid_until", "")), "valid_until must be an ISO 8601 UTC timestamp"
    assert isinstance(data["production_quarter"], str) and data["production_quarter"], (
        "production_quarter must be a non-empty string"
    )
    assert data["status"] in _values(CostQuoteStatus), f"status must be one of {_values(CostQuoteStatus)}"
    _assert_nullable_int(data, "landed_provisional_cents", "CostQuote")
    _assert_nullable_int(data, "landed_settled_cents", "CostQuote")
    _assert_nullable_int(data, "pinned_formula_version", "CostQuote")
    _assert_nullable_iso(data, "accepted_at", "CostQuote")


def assert_compliance_dossier(data: dict) -> None:
    _assert_common(data, "ComplianceDossier")
    assert isinstance(data["product_id"], str) and data["product_id"], "product_id required"
    assert data["ingredient_status"] in _values(IngredientStatus), (
        f"ingredient_status must be one of {_values(IngredientStatus)}"
    )
    assert isinstance(data["blocked_ingredients"], list), "blocked_ingredients must be a list"
    assert data["claim_status"] in _values(ClaimStatus), f"claim_status must be one of {_values(ClaimStatus)}"
    assert data["cert_status"] in _values(CertStatus), f"cert_status must be one of {_values(CertStatus)}"
    _assert_nullable_iso(data, "cert_expires_at", "ComplianceDossier")
    assert data["registration_status"] in _values(RegistrationStatus), (
        f"registration_status must be one of {_values(RegistrationStatus)}"
    )
    assert isinstance(data["compliant"], bool), "compliant must be a boolean"


def assert_retail_partner(data: dict) -> None:
    _assert_common(data, "RetailPartner")
    assert isinstance(data["name"], str) and data["name"], "name must be a non-empty string"
    assert isinstance(data["banner_code"], str), "banner_code must be a string"
    for field in ("category_capacities", "committed_facings", "available_facings"):
        assert isinstance(data[field], dict), f"{field} must be an object"
        assert all(_is_int(v) for v in data[field].values()), f"{field} values must be integers"


def assert_line_review(data: dict) -> None:
    _assert_common(data, "LineReview")
    assert isinstance(data["retail_partner_id"], str) and data["retail_partner_id"], "retail_partner_id required"
    assert isinstance(data["season"], str) and data["season"], "season must be a non-empty string"
    for field in ("submission_window_start", "submission_window_end", "review_date"):
        assert is_iso8601_timestamp(data.get(field, "")), f"{field} must be an ISO 8601 UTC timestamp"
    assert data["status"] in _values(LineReviewStatus), f"status must be one of {_values(LineReviewStatus)}"


def assert_planogram_slot(data: dict) -> None:
    _assert_common(data, "PlanogramSlot")
    assert isinstance(data["line_review_id"], str) and data["line_review_id"], "line_review_id required"
    assert isinstance(data["product_id"], str) and data["product_id"], "product_id required"
    assert isinstance(data["category"], str) and data["category"], "category must be a non-empty string"
    assert isinstance(data["position_code"], str) and data["position_code"], "position_code must be a non-empty string"
    assert _is_int(data["facings"]) and data["facings"] >= 1, "facings must be an integer >= 1"
    assert is_iso8601_timestamp(data.get("occupancy_start", "")), "occupancy_start must be an ISO 8601 UTC timestamp"
    assert is_iso8601_timestamp(data.get("occupancy_end", "")), "occupancy_end must be an ISO 8601 UTC timestamp"
    assert data["status"] in _values(PlanogramSlotStatus), f"status must be one of {_values(PlanogramSlotStatus)}"
    _assert_nullable_iso(data, "committed_at", "PlanogramSlot")


def assert_launch_plan(data: dict) -> None:
    _assert_common(data, "LaunchPlan")
    assert isinstance(data["product_id"], str) and data["product_id"], "product_id required"
    assert isinstance(data["planogram_slot_id"], str) and data["planogram_slot_id"], "planogram_slot_id required"
    for field in ("demand_forecast_units", "marketing_budget_cents", "cogs_budget_cents",
                  "sample_budget_cents", "samples_committed", "samples_distributed",
                  "sample_spend_cents", "markdown_units"):
        assert _is_int(data[field]) and data[field] >= 0, f"{field} must be an integer >= 0"
    assert data["status"] in _values(LaunchPlanStatus), f"status must be one of {_values(LaunchPlanStatus)}"
    assert data["sampling_status"] in _values(SamplingStatus), (
        f"sampling_status must be one of {_values(SamplingStatus)}"
    )
    assert _is_number(data["markdown_risk_pct"]) and 0 <= data["markdown_risk_pct"], (
        "markdown_risk_pct must be a non-negative number"
    )
    assert _is_int(data["capacity_units"]) and data["capacity_units"] >= 0, "capacity_units must be an integer >= 0"
    assert _is_int(data["qty_demand_variant_units"]) and data["qty_demand_variant_units"] >= 0, (
        "qty_demand_variant_units must be an integer >= 0"
    )
    assert _is_int(data["qty_risk_variant_units"]) and data["qty_risk_variant_units"] >= 0, (
        "qty_risk_variant_units must be an integer >= 0"
    )
    _assert_nullable_int(data, "qty_locked_units", "LaunchPlan")
    variant = data.get("locked_variant")
    assert variant is None or variant in _values(LockedVariant), (
        f"locked_variant must be one of {_values(LockedVariant)} or null"
    )
    _assert_nullable_int(data, "landed_locked_cents", "LaunchPlan")
    _assert_nullable_int(data, "retail_units_available", "LaunchPlan")
    _assert_nullable_int(data, "markdown_exposure_cents", "LaunchPlan")


def assert_discontinuation_review(data: dict) -> None:
    _assert_common(data, "DiscontinuationReview")
    assert isinstance(data["product_id"], str) and data["product_id"], "product_id required"
    _assert_nullable_str(data, "successor_product_id", "DiscontinuationReview")
    assert data["reason"] in _values(DiscontinuationReason), f"reason must be one of {_values(DiscontinuationReason)}"
    assert data["status"] in _values(DiscontinuationReviewStatus), (
        f"status must be one of {_values(DiscontinuationReviewStatus)}"
    )
    assert isinstance(data["proposed_by_user_id"], str) and data["proposed_by_user_id"], (
        "proposed_by_user_id must be a non-empty string"
    )


# ---------------------------------------------------------------------------
# Domain invariant checkers
# ---------------------------------------------------------------------------

def assert_launch_inventory_conserved(plan: dict) -> None:
    """Once a quantity is locked, launch inventory is conserved:
    qty_locked_units == retail + committed + distributed + markdown."""
    locked = plan.get("qty_locked_units")
    if locked is None:
        return  # conservation law applies from QUANTITY_LOCKED onward
    retail = plan.get("retail_units_available") or 0
    total = retail + plan["samples_committed"] + plan["samples_distributed"] + plan["markdown_units"]
    assert locked == total, (
        f"Launch inventory not conserved: qty_locked_units={locked} but "
        f"retail({retail}) + committed({plan['samples_committed']}) + "
        f"distributed({plan['samples_distributed']}) + markdown({plan['markdown_units']}) = {total}"
    )


def assert_footprint_conservation(partner: dict) -> None:
    """Per category: committed_facings + available_facings == category_capacities,
    and available is never negative."""
    capacities = partner["category_capacities"]
    committed = partner["committed_facings"]
    available = partner["available_facings"]
    for category, capacity in capacities.items():
        comm = committed.get(category, 0)
        avail = available.get(category, 0)
        assert comm + avail == capacity, (
            f"Footprint not conserved for {category}: committed({comm}) + "
            f"available({avail}) != capacity({capacity})"
        )
        assert avail >= 0, f"available_facings[{category}] must never be negative, got {avail}"


def assert_dossier_compliance_verdict(dossier: dict) -> None:
    """compliant == ingredient CLEARED and claim SUBSTANTIATED and cert
    CERTIFIED and registration REGISTERED."""
    expected = (
        dossier["ingredient_status"] == "CLEARED"
        and dossier["claim_status"] == "SUBSTANTIATED"
        and dossier["cert_status"] == "CERTIFIED"
        and dossier["registration_status"] == "REGISTERED"
    )
    assert dossier["compliant"] == expected, (
        f"compliant is {dossier['compliant']} but dimensions are "
        f"ingredient={dossier['ingredient_status']}, claim={dossier['claim_status']}, "
        f"cert={dossier['cert_status']}, registration={dossier['registration_status']} "
        f"(expected compliant == {expected})"
    )


def assert_sample_cap_respected(plan: dict) -> None:
    """Samples in flight (committed + distributed) never exceed
    floor(qty_locked_units * 0.10), and sample spend never exceeds the
    sampling budget."""
    import math

    locked = plan.get("qty_locked_units")
    if locked is None:
        return
    cap = math.floor(locked * 0.10)
    in_flight = plan["samples_committed"] + plan["samples_distributed"]
    assert in_flight <= cap, (
        f"Sample cap breached: committed({plan['samples_committed']}) + "
        f"distributed({plan['samples_distributed']}) = {in_flight} > cap {cap}"
    )
    assert plan["sample_spend_cents"] <= plan["sample_budget_cents"], (
        f"sample_spend_cents {plan['sample_spend_cents']} exceeds "
        f"sample_budget_cents {plan['sample_budget_cents']}"
    )
