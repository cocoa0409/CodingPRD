"""Entity assertions: scoring, classification, and insurance resources,
plus domain invariant checkers that must hold after any operation.
"""
from typing import Any, Dict, Iterable

import pytest

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)

from .assertions_entities import _is_number, assert_common_fields
from .constants import (
    CLASS_THRESHOLDS,
    COMMS_MAX_POINTS,
    CRR_TOTAL_CAP,
    DISTRIBUTION_MAX_POINTS,
    EQUIPMENT_MAX_POINTS,
    FD_TOTAL_MAX_POINTS,
    FLOW_MAX_POINTS,
    LOWEST_CLASS,
    PREMIUM_MODIFIER_TABLE,
    RESPONSE_MAX_POINTS,
    STAFFING_MAX_POINTS,
    STORAGE_MAX_POINTS,
    SUPPLY_MAX_POINTS,
    TRAINING_MAX_POINTS,
    WATER_MAX_POINTS,
)
from .types import (
    AppealGrounds,
    AppealStatus,
    ClassificationStatus,
    ConstructionType,
    CreditProgramType,
    CreditStatus,
    QuoteStatus,
    RequestStatus,
    ScoreSheetStatus,
    StaffingVariant,
    WaterVariant,
)


def _assert_two_dp(value: Any, name: str) -> None:
    assert _is_number(value), f"{name} must be numeric, got {value!r}"
    assert_cost_precision(float(value), 2)


def assert_risk_reduction_credit(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert data["program_type"] in {t.value for t in CreditProgramType}
    assert _is_number(data["activity_points"]) and data["activity_points"] > 0
    assert isinstance(data["evidence_note"], str)
    assert data["status"] in {s.value for s in CreditStatus}
    assert _is_number(data["credited_points"]) and data["credited_points"] >= 0
    assert data.get("verified_by") is None or isinstance(data["verified_by"], str)


def assert_score_sheet(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert data["status"] in {s.value for s in ScoreSheetStatus}
    assert data["staffing_variant_used"] in {v.value for v in StaffingVariant}
    assert data["water_variant_used"] in {v.value for v in WaterVariant}
    assert isinstance(data["base_class"], int) and 1 <= data["base_class"] <= 10
    assert isinstance(data["split_class_beyond_hydrant"], int) and 1 <= data["split_class_beyond_hydrant"] <= 10


def assert_classification(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert is_valid_uuid(data.get("cycle_id", "")), "cycle_id must be a UUID"
    assert is_valid_uuid(data.get("score_sheet_id", "")), "score_sheet_id must be a UUID"
    assert isinstance(data["base_class"], int) and 1 <= data["base_class"] <= 10
    assert isinstance(data["split_class_beyond_hydrant"], int) and 1 <= data["split_class_beyond_hydrant"] <= 10
    assert _is_number(data["premium_modifier"])
    assert data["status"] in {s.value for s in ClassificationStatus}
    assert isinstance(data["published_by"], str) and data["published_by"]
    assert is_iso8601_timestamp(data.get("published_at", "")), "published_at must be ISO 8601 UTC"
    assert data.get("effective_from") is None or isinstance(data["effective_from"], str)
    assert data.get("effective_until") is None or isinstance(data["effective_until"], str)


def assert_property_risk_profile(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert isinstance(data["address"], str)
    assert isinstance(data["distance_to_nearest_hydrant_ft"], int) and data["distance_to_nearest_hydrant_ft"] >= 0
    assert _is_number(data["distance_to_nearest_station_road_miles"]) and data["distance_to_nearest_station_road_miles"] >= 0
    assert data["construction_type"] in {t.value for t in ConstructionType}
    assert isinstance(data["insured_value_cents"], int) and data["insured_value_cents"] > 0
    assert data.get("applicable_class") is None or (isinstance(data["applicable_class"], int) and 1 <= data["applicable_class"] <= 10)
    assert data.get("applicable_premium_modifier") is None or _is_number(data["applicable_premium_modifier"])


def assert_premium_quote(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a UUID"
    assert is_valid_uuid(data.get("classification_id", "")), "classification_id must be a UUID"
    assert isinstance(data["coverage_amount_cents"], int) and data["coverage_amount_cents"] > 0
    assert isinstance(data["base_rate_bp"], int) and data["base_rate_bp"] > 0
    assert isinstance(data["term_months"], int) and 1 <= data["term_months"] <= 120
    assert isinstance(data["coverage_start_date"], str)
    assert isinstance(data["coverage_end_date"], str)
    assert isinstance(data["provisional_premium_cents"], int) and data["provisional_premium_cents"] >= 0
    assert data.get("final_premium_cents") is None or isinstance(data["final_premium_cents"], int)
    assert data["status"] in {s.value for s in QuoteStatus}
    assert data.get("bound_by") is None or isinstance(data["bound_by"], str)
    assert data.get("bound_at") is None or is_iso8601_timestamp(data["bound_at"])


def assert_reevaluation_request(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert isinstance(data["justification"], str)
    assert isinstance(data["evidence_items"], list) and len(data["evidence_items"]) >= 1
    assert data["status"] in {s.value for s in RequestStatus}
    assert isinstance(data["submitted_by"], str) and data["submitted_by"]
    assert data.get("decision_note") is None or isinstance(data["decision_note"], str)


def assert_appeal(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data.get("classification_id", "")), "classification_id must be a UUID"
    assert is_valid_uuid(data.get("community_id", "")), "community_id must be a UUID"
    assert data["grounds"] in {g.value for g in AppealGrounds}
    assert isinstance(data["evidence_items"], list) and len(data["evidence_items"]) >= 1
    assert data["status"] in {s.value for s in AppealStatus}
    assert isinstance(data["filed_by"], str) and data["filed_by"]
    assert data.get("adjudicated_by") is None or isinstance(data["adjudicated_by"], str)
    assert data.get("new_score_sheet_id") is None or is_valid_uuid(data["new_score_sheet_id"])


# ── Domain invariants (PRD-pinned cross-field rules) ─────────────────────

def assert_score_sheet_invariants(sheet: Dict[str, Any]) -> None:
    """Caps, totals, and class mapping that must hold on every score sheet."""
    caps = (
        ("equipment_points", EQUIPMENT_MAX_POINTS),
        ("staffing_points", STAFFING_MAX_POINTS),
        ("training_points", TRAINING_MAX_POINTS),
        ("response_points", RESPONSE_MAX_POINTS),
        ("fd_total_points", FD_TOTAL_MAX_POINTS),
        ("supply_points", SUPPLY_MAX_POINTS),
        ("flow_points", FLOW_MAX_POINTS),
        ("distribution_points", DISTRIBUTION_MAX_POINTS),
        ("storage_points", STORAGE_MAX_POINTS),
        ("water_total_points", WATER_MAX_POINTS),
        ("comms_points", COMMS_MAX_POINTS),
    )
    for key, cap in caps:
        _assert_two_dp(sheet[key], key)
        assert 0 <= sheet[key] <= cap, f"{key} {sheet[key]} outside [0, {cap}]"
    _assert_two_dp(sheet["crr_effective_points"], "crr_effective_points")
    assert 0 <= sheet["crr_effective_points"] <= CRR_TOTAL_CAP
    _assert_two_dp(sheet["subtotal_points"], "subtotal_points")
    _assert_two_dp(sheet["divergence_penalty_points"], "divergence_penalty_points")
    _assert_two_dp(sheet["adjusted_total_points"], "adjusted_total_points")
    assert sheet["fd_total_points"] == pytest.approx(
        sheet["equipment_points"] + sheet["staffing_points"]
        + sheet["training_points"] + sheet["response_points"], abs=0.011
    ), "fd_total_points must equal the sum of its four subscores"
    assert sheet["water_total_points"] == pytest.approx(
        sheet["supply_points"] + sheet["flow_points"]
        + sheet["distribution_points"] + sheet["storage_points"], abs=0.011
    ), "water_total_points must equal the sum of its four subscores"
    assert sheet["subtotal_points"] == pytest.approx(
        sheet["fd_total_points"] + sheet["water_total_points"] + sheet["comms_points"], abs=0.011
    ), "subtotal excludes the risk-reduction credit"
    expected_class = LOWEST_CLASS
    for threshold, cls in CLASS_THRESHOLDS:
        if sheet["adjusted_total_points"] >= threshold:
            expected_class = cls
            break
    assert sheet["base_class"] == expected_class, (
        f"base_class {sheet['base_class']} does not match adjusted_total "
        f"{sheet['adjusted_total_points']} against the fixed thresholds"
    )


def assert_modifier_for_class(premium_modifier: float, class_number: int) -> None:
    """The premium modifier is the fixed table lookup keyed on the class."""
    expected = PREMIUM_MODIFIER_TABLE[class_number]
    assert premium_modifier == pytest.approx(expected), (
        f"modifier for class {class_number} must be {expected}, got {premium_modifier}"
    )


def assert_bound_exposure_invariant(community: Dict[str, Any], quotes: Iterable[Dict[str, Any]]) -> None:
    """bound_exposure_cents always equals the sum over BOUND quotes only."""
    bound_total = sum(q["coverage_amount_cents"] for q in quotes if q.get("status") == "BOUND")
    assert community["bound_exposure_cents"] == bound_total, (
        f"bound_exposure_cents {community['bound_exposure_cents']} != "
        f"sum over BOUND quotes {bound_total}"
    )
