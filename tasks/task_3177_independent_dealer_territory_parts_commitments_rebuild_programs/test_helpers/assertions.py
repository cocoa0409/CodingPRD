"""Entity assertions and domain invariant checkers."""
import pytest

from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

_COMMON_FIELDS = ("created_at", "updated_at", "version")

FAMILIES = ["EXCAVATION", "EARTHMOVING", "COMPACTION", "POWER_SYSTEMS", "LIFT_TRUCK"]


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a system-managed integer"
    )


def assert_append_only_common(data: dict):
    """Common-shape check for the resource declared without the common field set."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "this resource carries no updated_at"
    assert "version" not in data, "this resource carries no version"


def assert_dealer(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["home_state_code"], str) and data["home_state_code"]
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert data["status"] in ["PENDING_AGREEMENT", "ACTIVE", "SUSPENDED", "TERMINATED"]
    for counter in ("certified_family_count", "trusted_commitment_count", "open_backorder_units"):
        assert isinstance(data[counter], int) and data[counter] >= 0
    assert isinstance(data["market_share_pct"], (int, float))


def assert_dealer_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["product_family"] in FAMILIES
    assert data["exclusivity_level"] in ["EXCLUSIVE", "SHARED"]
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "ACTIVE", "SUSPENDED", "PERFORMANCE_DEFICIENT", "TERMINATED",
    ]
    assert data["tooling_compliance_status"] in ["NOT_SUBMITTED", "PARTIAL", "COMPLIANT"]
    assert isinstance(data["trusted_commitment"], bool)
    assert isinstance(data["certified_technician_count"], int)
    assert isinstance(data["performance_plan_share_pct"], (int, float))
    assert data["start_at"] is not None and data["end_at"] is not None


def assert_parts_commitment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["agreement_id"]), "agreement_id must be a UUID"
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["product_family"] in FAMILIES
    assert data["status"] in [
        "PLANNED", "SUBMITTED", "ORDER_READY", "CORE_PENDING",
        "PERFORMANCE_DEFICIENT", "SUSPENDED", "COMPLETE",
    ]
    assert isinstance(data["machine_population_units"], int)
    assert isinstance(data["committed_units"], int)
    assert isinstance(data["fulfilled_units"], int)
    assert isinstance(data["credit_balance_cents"], int)
    assert data["credit_balance_cents"] >= 0


def assert_parts_order_batch(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["commitment_id"]), "commitment_id must be a UUID"
    assert data["product_family"] in FAMILIES
    assert data["status"] in [
        "OPEN", "ORDERED", "RECEIVED", "PARTIALLY_RETURNED", "CLOSED", "CANCELLED",
    ]
    assert isinstance(data["requested_units"], int)
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["unfilled_units"], int)
    assert isinstance(data["core_units"], int)
    assert isinstance(data["emergency"], bool)
    assert isinstance(data["core_return_required"], bool)


def assert_certification_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["product_family"] in FAMILIES
    assert data["credential_code"] in ["DEALER_MASTER", "DEALER_CERTIFIED"]
    assert data["status"] in ["ACTIVE", "EXPIRED", "REVOKED"]
    assert isinstance(data["recurrence_within_period"], bool)


def assert_rebuild_claim(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["product_family"] in FAMILIES
    assert data["status"] in [
        "REQUESTED", "APPROVED", "CORE_PENDING", "CORE_RETURNED", "DELIVERED",
        "CERTIFIED", "COMPLETE", "DENIED", "DECLINED",
    ]
    assert data["certified_rebuild_spec_code"] in [
        "CAT_CERTIFIED_1", "CAT_CERTIFIED_2", "CAT_CERTIFIED_3",
    ]
    assert isinstance(data["machine_operating_weight_lb"], int)


def assert_equipment_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["product_family"] in FAMILIES
    assert data["status"] in [
        "DRAFT", "SUBMITTED", "FINANCE_APPROVED", "DELIVERED", "CANCELLED",
    ]
    assert isinstance(data["list_price_cents"], int)
    assert isinstance(data["supportable_machine_registered"], bool)


def assert_trade_in_unit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["order_id"]), "order_id must be a UUID"
    assert isinstance(data["machine_serial"], str) and data["machine_serial"]
    assert data["status"] in ["APPRAISED", "ACCEPTED", "REMARKETED", "SCRAPPED"]
    assert isinstance(data["appraised_value_cents"], int)


def assert_support_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["plan_tier"] in ["BASIC", "PLUS", "PREMIUM"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["coverage_multiplier"], (int, float))


def assert_market_share_observation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["product_family"] in FAMILIES
    assert data["kind"] in ["MACHINE", "LIGHT"]
    assert isinstance(data["observed_machine_units"], int)
    assert isinstance(data["territory_machine_units"], int)
    assert isinstance(data["observed_share_pct"], (int, float))


def assert_party_registration(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["status"] in ["REGISTERED", "SUPERSEDED"]
    assert isinstance(data["territory_code"], str)


def assert_machine_population_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert data["product_family"] in FAMILIES
    assert isinstance(data["machine_serial"], str) and data["machine_serial"]
    assert data["status"] in ["ACTIVE", "RETIRED"]
    assert isinstance(data["machine_operating_weight_lb"], int)
    if data.get("weight_class_tier") is not None:
        assert data["weight_class_tier"] in ["LIGHT", "MIDDLE", "HEAVY"]


def assert_service_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert is_valid_uuid(data["commitment_id"]), "commitment_id must be a UUID"
    assert data["kind"] in ["EMERGENCY_FILL", "RESTRICTION", "SLA_AUDIT"]
    assert data["status"] in ["OPEN", "IN_PROGRESS", "FILLED", "ESCALATED", "RESOLVED"]
    assert data["restriction_scope"] in ["HOURS_SPENT", "METER_RUNNING", "FULL_STOP"]
    assert isinstance(data["orderable_ref_enabled"], bool)


def assert_performance_review(data: dict):
    assert_append_only_common(data)
    assert is_valid_uuid(data["dealer_id"]), "dealer_id must be a UUID"
    assert is_valid_uuid(data["agreement_id"]), "agreement_id must be a UUID"
    assert data["status"] in [
        "DRAFT", "RESULTS_RECORDED", "REMEDIATION_REQUIRED",
        "CIRCUMSTANCE_PENDING", "EVALUATED",
    ]
    assert isinstance(data["sampled_service_orders"], int)
    assert isinstance(data["met_sla_service_orders"], int)


# ─── Domain invariants ────────────────────────────────

def assert_stocking_mandate_invariants(data: dict):
    """The final variant never exceeds the active variant on any input."""
    active = data.get("required_stocking_units")
    final = data.get("required_stocking_units_final")
    if active is not None and final is not None:
        assert final <= active, (
            f"required_stocking_units_final ({final}) must be <= "
            f"required_stocking_units ({active})"
        )
    if data.get("available_commitment_units") is not None:
        assert data["available_commitment_units"] >= 0


def assert_commitment_counters_non_negative(data: dict):
    assert data["credit_balance_cents"] >= 0
    assert data["committed_units"] >= 0
    assert data["fulfilled_units"] >= 0


def assert_percentage_precision(value, places=4):
    assert round(float(value), places) == pytest.approx(float(value), abs=1e-9), (
        f"{value} carries more than {places} decimal places"
    )


__all__ = [
    "assert_append_only_common", "assert_dealer", "assert_dealer_agreement",
    "assert_parts_commitment", "assert_parts_order_batch",
    "assert_certification_record", "assert_rebuild_claim", "assert_equipment_order",
    "assert_trade_in_unit", "assert_support_agreement",
    "assert_market_share_observation", "assert_party_registration",
    "assert_machine_population_record", "assert_service_order",
    "assert_performance_review", "assert_stocking_mandate_invariants",
    "assert_commitment_counters_non_negative", "assert_percentage_precision",
]