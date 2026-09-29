"""Request-payload builders.

Every builder emits the field types the contract declares: money is always an
integer number of cents, percentages and nutrient grams are always JSON
numbers with a fractional part allowed, counts are integers, and instants are
ISO 8601 UTC strings.  No numeric field is ever emitted as a string.  Each
builder accepts ``**overrides`` so a caller can restate one field, and an
override whose value is ``None`` removes the key entirely, which is how the
tests exercise omitted-optional and missing-required behaviour.
"""

from test_helpers.constants import (
    AUDIT_CAPABILITY,
    CLAIM_NUTRIENT_CONTENT,
    DECISION_ACCEPT,
    DEFECT_FOREIGN_MATERIAL,
    DISPOSITION_DISCONTINUE,
    RUN_FIRST_PRODUCTION,
    SEVERITY_CRITICAL,
    STUDY_BENCH_TOP,
    SCOPE_NONE,
    TIER_NBE,
)

def _merge(base: dict, overrides: dict) -> dict:
    """Apply overrides; a ``None`` override deletes the key."""
    merged = dict(base)
    for key, value in overrides.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = value
    return merged


def keep_null(payload: dict, *fields) -> dict:
    """Re-add fields with an explicit JSON null after ``_merge`` dropped them."""
    for field in fields:
        payload[field] = None
    return payload


# --- Brand programs -------------------------------------------------------


def program_payload(**overrides) -> dict:
    return _merge(
        {
            "brand_name": "Harvest Lane",
            "retailer_name": "MidState Grocers",
            "fiscal_year": 2026,
            "dev_budget_cents": 5000000,
        },
        overrides,
    )


def program_lifecycle_payload(action, **overrides) -> dict:
    return _merge({"action": action}, overrides)


# --- Category gaps --------------------------------------------------------


def gap_payload(program_id, **overrides) -> dict:
    """The reference crackers gap: score 47.00, recommended tier NBE."""
    return _merge(
        {
            "program_id": program_id,
            "category_code": "CRACKERS",
            "national_brand_name": "Sunbite",
            "nb_retail_price_cents": 360,
            "category_annual_sales_cents": 250000000,
            "pl_share_pct": 20.0,
            "unit_velocity_per_week": 520,
            "shelf_slots_quota": 2,
        },
        overrides,
    )


def premium_gap_payload(program_id, **overrides) -> dict:
    """An olive-oil gap that scores 79.50 and recommends PREMIUM."""
    return _merge(
        {
            "program_id": program_id,
            "category_code": "OLIVE_OIL",
            "national_brand_name": "Grovemark",
            "nb_retail_price_cents": 649,
            "category_annual_sales_cents": 800000000,
            "pl_share_pct": 12.5,
            "unit_velocity_per_week": 900,
            "shelf_slots_quota": 3,
        },
        overrides,
    )


def single_slot_gap_payload(program_id, **overrides) -> dict:
    """A cookies gap with a one-slot shelf quota."""
    return _merge(
        {
            "program_id": program_id,
            "category_code": "COOKIES",
            "national_brand_name": "Chipmont",
            "nb_retail_price_cents": 420,
            "category_annual_sales_cents": 180000000,
            "pl_share_pct": 25.0,
            "unit_velocity_per_week": 400,
            "shelf_slots_quota": 1,
        },
        overrides,
    )


def tier_decision_payload(decision="APPROVE", approved_tier=TIER_NBE, **overrides) -> dict:
    return _merge({"decision": decision, "approved_tier": approved_tier}, overrides)


# --- Suppliers ------------------------------------------------------------


def supplier_payload(program_id, **overrides) -> dict:
    return _merge(
        {
            "program_id": program_id,
            "legal_name": "Northmill Bakers",
            "plant_country": "US",
            "gfsi_certificate_expiry": "2027-06-30T00:00:00Z",
        },
        overrides,
    )


def qualification_payload(decision, basis_audit_id=None, **overrides) -> dict:
    payload = {"decision": decision}
    if basis_audit_id is not None:
        payload["basis_audit_id"] = basis_audit_id
    return _merge(payload, overrides)


# --- Plant lines ----------------------------------------------------------


def plant_line_payload(supplier_id, **overrides) -> dict:
    return _merge(
        {
            "supplier_id": supplier_id,
            "line_code": "CRK-1",
            "daily_capacity_units": 60000,
            "changeover_buffer_minutes": 120,
        },
        overrides,
    )


# --- Plant audits ---------------------------------------------------------


def plant_audit_payload(supplier_id, **overrides) -> dict:
    return _merge(
        {
            "supplier_id": supplier_id,
            "audit_type": AUDIT_CAPABILITY,
            "window_start": "2026-07-20T08:00:00Z",
            "window_end": "2026-07-21T17:00:00Z",
        },
        overrides,
    )


def audit_finalize_payload(**overrides) -> dict:
    """Scores that yield PASS: food safety 92 and every pillar at or above 80."""
    return _merge(
        {
            "food_safety_score": 92,
            "sanitation_score": 88,
            "capacity_score": 85,
            "traceability_score": 90,
            "audited_yield_pct": 91.0,
        },
        overrides,
    )


def conditional_audit_finalize_payload(**overrides) -> dict:
    """Scores that yield CONDITIONAL: food safety 84, minimum pillar 72."""
    return _merge(
        {
            "food_safety_score": 84,
            "sanitation_score": 75,
            "capacity_score": 78,
            "traceability_score": 72,
            "audited_yield_pct": 91.0,
        },
        overrides,
    )


def failing_audit_finalize_payload(**overrides) -> dict:
    """Scores that yield FAIL: food safety 70."""
    return _merge(
        {
            "food_safety_score": 70,
            "sanitation_score": 60,
            "capacity_score": 55,
            "traceability_score": 50,
            "audited_yield_pct": 84.0,
        },
        overrides,
    )


# --- Product items --------------------------------------------------------


def item_payload(gap_id, **overrides) -> dict:
    return _merge(
        {
            "gap_id": gap_id,
            "item_name": "Harvest Lane Wheat Crackers",
            "tier": TIER_NBE,
            "pack_size_desc": "12 oz carton",
            "trailing_90d_units": 50000,
        },
        overrides,
    )


def second_item_payload(gap_id, **overrides) -> dict:
    return _merge(
        {
            "gap_id": gap_id,
            "item_name": "Harvest Lane Rye Crispbread",
            "tier": TIER_NBE,
            "pack_size_desc": "9 oz carton",
            "trailing_90d_units": 50000,
        },
        overrides,
    )


def shipment_feed_payload(trailing_90d_units, **overrides) -> dict:
    return _merge({"trailing_90d_units": trailing_90d_units}, overrides)


def rationalize_payload(disposition=DISPOSITION_DISCONTINUE, **overrides) -> dict:
    return _merge({"disposition": disposition}, overrides)


# --- Cost models ----------------------------------------------------------


def cost_model_payload(item_id, supplier_id, **overrides) -> dict:
    """The reference quote: base 221, as-quoted landed 269."""
    return _merge(
        {
            "item_id": item_id,
            "supplier_id": supplier_id,
            "ingredient_cost_cents_per_unit": 142,
            "packaging_cost_cents_per_unit": 31,
            "conversion_cost_cents_per_unit": 48,
            "quoted_yield_pct": 96.5,
            "freight_cents_per_pallet": 48000,
            "units_per_pallet": 1200,
            "moq_units": 12000,
            "tooling_cents": 400000,
        },
        overrides,
    )


def rival_cost_model_payload(item_id, supplier_id, **overrides) -> dict:
    """A competing quote used to observe supersession on award."""
    return _merge(
        {
            "item_id": item_id,
            "supplier_id": supplier_id,
            "ingredient_cost_cents_per_unit": 150,
            "packaging_cost_cents_per_unit": 30,
            "conversion_cost_cents_per_unit": 52,
            "quoted_yield_pct": 94.0,
            "freight_cents_per_pallet": 51000,
            "units_per_pallet": 1100,
            "moq_units": 15000,
            "tooling_cents": 450000,
        },
        overrides,
    )


def second_supplier_cost_model_payload(item_id, supplier_id, **overrides) -> dict:
    """A cheaper quote used for a second item under the same supplier."""
    return _merge(
        {
            "item_id": item_id,
            "supplier_id": supplier_id,
            "ingredient_cost_cents_per_unit": 138,
            "packaging_cost_cents_per_unit": 29,
            "conversion_cost_cents_per_unit": 44,
            "quoted_yield_pct": 96.5,
            "freight_cents_per_pallet": 48000,
            "units_per_pallet": 1200,
            "moq_units": 12000,
            "tooling_cents": 300000,
        },
        overrides,
    )


def cost_model_decision_payload(decision=DECISION_ACCEPT, **overrides) -> dict:
    return _merge({"decision": decision}, overrides)


# --- Comparison studies ---------------------------------------------------


def bench_top_payload(item_id, **overrides) -> dict:
    """Deltas that give parity index 93.00 and verdict PARITY."""
    return _merge(
        {
            "item_id": item_id,
            "study_type": STUDY_BENCH_TOP,
            "nb_control_lot_code": "NB-LOT-0731",
            "appearance_delta": 0.5,
            "aroma_delta": -0.5,
            "texture_delta": 0.0,
            "flavor_delta": 0.5,
        },
        overrides,
    )


def consumer_panel_payload(item_id, **overrides) -> dict:
    """A panel whose preference share is exactly 45.00, the PARITY boundary."""
    return _merge(
        {
            "item_id": item_id,
            "study_type": "CONSUMER_PANEL",
            "nb_control_lot_code": "NB-LOT-0731",
            "n_panelists": 140,
            "prefer_pl_count": 45,
            "prefer_nb_count": 55,
            "no_preference_count": 40,
        },
        overrides,
    )


# --- Artwork rounds -------------------------------------------------------


def artwork_round_payload(item_id, **overrides) -> dict:
    """The reference recipe: a 50 g serving whose panel declares 200 calories."""
    return _merge(
        {
            "item_id": item_id,
            "serving_size_g": 50.0,
            "servings_per_container": 6.8,
            "fat_g_per_100g": 13.0,
            "satfat_g_per_100g": 5.0,
            "carb_g_per_100g": 65.2,
            "fiber_g_per_100g": 2.8,
            "sugars_g_per_100g": 30.0,
            "added_sugars_g_per_100g": 24.0,
            "protein_g_per_100g": 6.8,
            "sodium_mg_per_100g": 640.0,
        },
        overrides,
    )


def review_payload(decision, **overrides) -> dict:
    return _merge({"decision": decision}, overrides)


# --- Label claims ---------------------------------------------------------


def label_claim_payload(artwork_round_id, **overrides) -> dict:
    return _merge(
        {
            "artwork_round_id": artwork_round_id,
            "claim_text": "Good source of fiber",
            "claim_type": CLAIM_NUTRIENT_CONTENT,
        },
        overrides,
    )


def health_claim_payload(artwork_round_id, **overrides) -> dict:
    return _merge(
        {
            "artwork_round_id": artwork_round_id,
            "claim_text": "Whole grains support heart health",
            "claim_type": "HEALTH",
            "substantiation_ref": "FDA-HC-2003-01",
        },
        overrides,
    )


# --- Specifications -------------------------------------------------------


def specification_payload(
    item_id, pinned_cost_model_id, pinned_artwork_round_id, expected_item_version, **overrides
) -> dict:
    return _merge(
        {
            "item_id": item_id,
            "pinned_cost_model_id": pinned_cost_model_id,
            "pinned_artwork_round_id": pinned_artwork_round_id,
            "expected_item_version": expected_item_version,
        },
        overrides,
    )


# --- Production runs ------------------------------------------------------


def production_run_payload(
    item_id, specification_id, plant_line_id, **overrides
) -> dict:
    """A twelve-hour first-production window sized at the reference MOQ."""
    return _merge(
        {
            "item_id": item_id,
            "specification_id": specification_id,
            "plant_line_id": plant_line_id,
            "run_type": RUN_FIRST_PRODUCTION,
            "window_start": "2026-09-07T06:00:00Z",
            "window_end": "2026-09-07T18:00:00Z",
            "planned_units": 12000,
        },
        overrides,
    )


def run_complete_payload(produced_units=12000, completed_on_time=True, **overrides) -> dict:
    return _merge(
        {"produced_units": produced_units, "completed_on_time": completed_on_time},
        overrides,
    )


# --- Complaints -----------------------------------------------------------


def complaint_payload(item_id, **overrides) -> dict:
    return _merge(
        {
            "item_id": item_id,
            "defect_category": DEFECT_FOREIGN_MATERIAL,
            "severity": SEVERITY_CRITICAL,
            "lot_code": "PL-0801-A",
            "narrative": "Metal fragment reported in one carton",
        },
        overrides,
    )


def major_complaint_payload(item_id, **overrides) -> dict:
    return _merge(
        {
            "item_id": item_id,
            "defect_category": "PACKAGING",
            "severity": "MAJOR",
            "lot_code": "PL-0801-C",
            "narrative": "Seal split on two cartons",
        },
        overrides,
    )


def minor_complaint_payload(item_id, **overrides) -> dict:
    return _merge(
        {
            "item_id": item_id,
            "defect_category": "LABEL",
            "severity": "MINOR",
            "lot_code": "PL-0801-D",
            "narrative": "Print registration off by 2mm",
        },
        overrides,
    )


# --- Cost change requests -------------------------------------------------


def change_request_payload(
    item_id, cost_model_id, expected_cost_model_version, **overrides
) -> dict:
    """A tier T3 request against the reference quote: raw 30, net 17."""
    return _merge(
        {
            "item_id": item_id,
            "cost_model_id": cost_model_id,
            "requested_ingredient_cost_cents_per_unit": 168,
            "requested_packaging_cost_cents_per_unit": 33,
            "requested_conversion_cost_cents_per_unit": 50,
            "substitution_scope": SCOPE_NONE,
            "expected_cost_model_version": expected_cost_model_version,
        },
        overrides,
    )


def ingredient_substitution_payload(
    item_id, cost_model_id, expected_cost_model_version, **overrides
) -> dict:
    """The same request, scoped to an ingredient substitution."""
    return _merge(
        {
            "item_id": item_id,
            "cost_model_id": cost_model_id,
            "requested_ingredient_cost_cents_per_unit": 168,
            "requested_packaging_cost_cents_per_unit": 33,
            "requested_conversion_cost_cents_per_unit": 50,
            "substitution_scope": "INGREDIENT",
            "substitution_material_desc": "Alternate wheat flour blend",
            "expected_cost_model_version": expected_cost_model_version,
        },
        overrides,
    )


def counter_payload(counter_base_cents, **overrides) -> dict:
    return _merge({"counter_base_cents": counter_base_cents}, overrides)


def revise_payload(ingredient, packaging, conversion, **overrides) -> dict:
    return _merge(
        {
            "requested_ingredient_cost_cents_per_unit": ingredient,
            "requested_packaging_cost_cents_per_unit": packaging,
            "requested_conversion_cost_cents_per_unit": conversion,
        },
        overrides,
    )


def decision_payload(decision, **overrides) -> dict:
    return _merge({"decision": decision}, overrides)
