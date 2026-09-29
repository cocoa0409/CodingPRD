"""Field inventories for every resource the API exposes.

Tests use these to assert that a response row carries exactly the system
fields the contract promises, without restating the field list inline.
"""

from typing import Any, Dict, List

Payload = Dict[str, Any]
Headers = Dict[str, str]
Row = Dict[str, Any]

# Common system fields carried by every versioned resource (PRD 2.4).
COMMON_FIELDS: List[str] = ["id", "created_at", "updated_at", "version"]

# A regulatory standard is immutable and therefore carries neither an
# ``updated_at`` nor a ``version`` (PRD 2.4).
IMMUTABLE_COMMON_FIELDS: List[str] = ["id", "created_at"]

ENVELOPE_KEYS: List[str] = ["meta", "response_type", "data"]
META_KEYS: List[str] = ["api_request_id", "api_request_timestamp"]
PAGINATION_META_KEYS: List[str] = ["limit", "offset", "total_count", "has_more"]

MOTOR_DESIGN_INPUT_FIELDS: List[str] = [
    "model_code",
    "frame_size",
    "poles",
    "rated_output_kw",
    "rated_voltage_v",
    "target_efficiency_class",
    "lamination_grade",
    "lamination_stack_length_mm",
    "winding_copper_kg",
    "winding_type",
    "insulation_class",
    "stator_bore_id_mm",
    "design_air_gap_mm",
    "air_gap_tolerance_mm",
    "rotor_construction",
    "rotor_bar_count",
    "shaft_diameter_mm",
    "shaft_tolerance_class",
    "bearing_spec_de",
    "bearing_spec_nde",
    "lubrication_spec",
    "duty_type",
    "enclosure",
    "mounting",
]

MOTOR_DESIGN_COMPUTED_FIELDS: List[str] = [
    "core_loss_w",
    "copper_loss_w",
    "rotor_loss_w",
    "friction_windage_loss_w",
    "stray_loss_w",
    "total_predicted_loss_w",
    "predicted_efficiency_pct",
    "guaranteed_efficiency_pct",
    "design_estimate_class",
    "predicted_class",
]

DISTRIBUTOR_LEDGER_FIELDS: List[str] = [
    "units_outstanding",
    "stock_allowance_remaining_units",
    "warranty_credit_balance_cents",
    "open_presumed_defect_count",
]

COST_SUMMARY_FIELDS: List[str] = [
    "work_order_id",
    "unit_count",
    "per_unit_direct_cost_cents",
    "direct_cost_cents",
    "overhead_band",
    "overhead_cents",
    "standard_cost_cents",
    "actual_cost_cents",
    "cost_variance_cents",
    "rework_reject_count",
    "unit_standard_cost_cents",
]
