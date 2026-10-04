"""Entity assertions and domain invariant helpers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    AgreementStatus,
    CommitmentStatus,
    LineReviewStatus,
    PACKAGING_CLAIMS,
    PenaltyStatus,
    SafetyStatus,
    SafetyTestStatus,
    ShipmentStatus,
    ToolingOrderStatus,
    ToyLineStatus,
)


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an integer >= 1"


def assert_studio(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["confidentiality_tier"] in ("STANDARD", "STRICT")
    assert data["status"] in ("ACTIVE", "ARCHIVED")


def assert_property(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["studio_id"])
    assert isinstance(data["title"], str) and data["title"]
    assert data["category"] in ("FILM", "SERIES")
    assert is_iso8601_timestamp(data["reveal_date"])
    assert is_iso8601_timestamp(data["release_date"])
    assert isinstance(data["shift_count"], int) and data["shift_count"] >= 0
    assert data["lifecycle"] in ("CONFIDENTIAL", "REVEALED", "RELEASED")


def assert_license_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["territory"], str) and data["territory"]
    assert isinstance(data["royalty_rate_pct"], (int, float))
    assert isinstance(data["advance_guarantee_cents"], int)
    assert isinstance(data["annual_minimum_guarantee_cents"], int)
    assert data["status"] in AgreementStatus._value2member_map_
    assert isinstance(data["royalties_earned_cents"], int)
    assert isinstance(data["recouped_cents"], int)
    assert isinstance(data["guarantee_topups_cents"], int)
    assert isinstance(data["quarters_closed"], int)


def assert_toy_line(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["brand_kind"] in ("LICENSED", "EVERGREEN")
    assert data["status"] in ToyLineStatus._value2member_map_
    assert is_iso8601_timestamp(data["target_street_date"])


def assert_sku(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["toy_line_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["age_grade_months"], int)
    assert 36 <= data["age_grade_months"] <= 168
    assert isinstance(data["packaging_claims"], list)
    for claim in data["packaging_claims"]:
        assert claim in PACKAGING_CLAIMS
    assert isinstance(data["claims_validated"], bool)
    assert isinstance(data["moq_units"], int) and data["moq_units"] >= 1
    assert isinstance(data["unit_cost_cents"], int)
    assert isinstance(data["tooling_cost_cents"], int)
    assert data["safety_status"] in SafetyStatus._value2member_map_


def assert_factory(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["capacity_units_per_month"], int)
    assert isinstance(data["tooling_lead_weeks"], int)


def assert_tooling_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["toy_line_id"])
    assert is_valid_uuid(data["sku_id"])
    assert is_valid_uuid(data["factory_id"])
    assert isinstance(data["production_month"], str)
    assert isinstance(data["units"], int)
    assert isinstance(data["allocated_units"], int)
    assert isinstance(data["tooling_charge_cents"], int)
    assert data["status"] in ToolingOrderStatus._value2member_map_


def assert_retailer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["credit_balance_cents"], int)
    assert isinstance(data["violation_count"], int) and data["violation_count"] >= 0


def assert_line_review(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["retailer_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert is_iso8601_timestamp(data["commitment_deadline"])
    assert isinstance(data["shelf_slots_total"], int)
    assert isinstance(data["shelf_slots_used"], int)
    assert data["status"] in LineReviewStatus._value2member_map_
    assert data["lifecycle"] in ("SCHEDULED", "OPEN", "LOCKED")


def assert_commitment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["line_review_id"])
    assert is_valid_uuid(data["sku_id"])
    assert isinstance(data["committed_units"], int) and data["committed_units"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["shelf_slots"], int) and data["shelf_slots"] >= 1
    assert data["status"] in CommitmentStatus._value2member_map_


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["commitment_id"])
    assert is_iso8601_timestamp(data["planned_ship_date"])
    assert isinstance(data["units"], int) and data["units"] >= 1
    assert is_iso8601_timestamp(data["street_date"])
    assert isinstance(data["sold_units"], int) and data["sold_units"] >= 0
    assert data["status"] in ShipmentStatus._value2member_map_
    assert isinstance(data["penalty_cents"], int)
    assert data["penalty_status"] in PenaltyStatus._value2member_map_


def assert_safety_test(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["sku_id"])
    assert data["test_type"] in ("MECHANICAL", "FLAMMABILITY", "CHEMICAL")
    assert isinstance(data["lab_name"], str) and data["lab_name"]
    assert isinstance(data["claimed_age_grade_months"], int)
    assert data["status"] in SafetyTestStatus._value2member_map_
