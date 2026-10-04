"""Entity assertions and domain invariant checkers (PRD §2.10, §3)."""
import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ALLOCATION_STATUSES,
    AUDIT_STATUSES,
    CAPACITY_PROFILE_STATUSES,
    CLAIM_STATUSES,
    DISTRIBUTION_STATUSES,
    FULFILLMENT_STATUSES,
    GIVING_PARTNER_STATUSES,
    LIABILITY_STATUSES,
    ORDER_LINE_STATUSES,
    ORDER_STATUSES,
    PRODUCT_LINE_STATUSES,
    PRODUCT_STATUSES,
    RETURN_STATUSES,
    SEASON_STATUSES,
    VETTING_OUTCOMES,
)


def _assert_common_fields(data: dict, status_key: str = "status", statuses=None):
    """id / created_at / updated_at / version for a mutable primary resource."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID with no type prefix"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601 UTC"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"
    if statuses is not None:
        assert data[status_key] in statuses, (
            f"status {data.get(status_key)!r} not in {statuses}"
        )


def assert_giving_partner(data: dict):
    _assert_common_fields(data, statuses=GIVING_PARTNER_STATUSES)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["need_score"], int)
    assert 0 <= data["need_score"] <= 100
    assert isinstance(data["registry_verified"], bool)
    assert isinstance(data["vetting_round"], int)
    assert isinstance(data["total_rejections"], int)


def assert_giving_partner_invariants(data: dict):
    """Invariants that hold after any operation on a partner."""
    assert data["capacity_utilization_units"] >= 0
    assert data["impact_units_total"] >= 0
    assert data["claim_attributed_units"] >= 0
    assert 0 <= data["need_score"] <= 100
    assert data["vetting_round"] >= 0
    assert data["total_rejections"] >= 0


def assert_capacity_profile(data: dict):
    _assert_common_fields(data, statuses=CAPACITY_PROFILE_STATUSES)
    assert isinstance(data["max_allocatable_units"], int)
    assert isinstance(data["committed_units"], int)
    assert isinstance(data["reserved_units"], int)


def assert_capacity_profile_invariants(data: dict):
    assert data["committed_units"] >= 0
    assert data["reserved_units"] >= 0
    assert data["capacity_utilization_units"] >= 0
    assert (
        data["capacity_utilization_units"]
        == max(0, data["committed_units"] + data["reserved_units"])
        or data["capacity_utilization_units"] >= 0
    )


def assert_vetting_round(data: dict):
    """A vetting round is append-only: it carries id and created_at only."""
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601 UTC"
    assert data["outcome"] in VETTING_OUTCOMES
    assert isinstance(data["round_number"], int) and data["round_number"] >= 1


def assert_vetting_round_has_no_version(data: dict):
    """No vetting round ever participates in an optimistic concurrency check."""
    assert "version" not in data or data.get("version") is None
    assert "updated_at" not in data or data.get("updated_at") is None


def assert_donation_product(data: dict):
    _assert_common_fields(data, statuses=PRODUCT_STATUSES)
    assert isinstance(data["product_name"], str) and data["product_name"]
    assert isinstance(data["design_weight_score"], int)
    assert 0 <= data["design_weight_score"] <= 100
    assert data["design_channel"] in ("DONATION_ONLY", "DUAL_CHANNEL")
    assert data["obligation_model"] in ("AT_SALE", "AT_VESTING")


def assert_donation_product_line(data: dict):
    _assert_common_fields(data, statuses=PRODUCT_LINE_STATUSES)
    assert data["design_variant_code"] in ("donation_specific", "retail_dual", "none")
    assert isinstance(data["obligation_units"], int) and data["obligation_units"] >= 0
    assert isinstance(data["unit_obligation_cost_cents"], int)


def assert_donation_liability(data: dict):
    _assert_common_fields(data, statuses=LIABILITY_STATUSES)
    for field in (
        "provisional_liability_units",
        "final_liability_units",
        "obligation_units",
        "donation_cost_cents",
        "donation_credit_units",
        "frozen_units",
        "carried_in_units",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer"


def assert_donation_liability_invariants(data: dict):
    assert data["provisional_liability_units"] >= 0
    assert data["final_liability_units"] >= 0
    assert data["donation_cost_cents"] >= 0
    assert data["carried_in_units"] >= 0


def assert_allocation(data: dict):
    _assert_common_fields(data, statuses=ALLOCATION_STATUSES)
    assert data["allocation_kind"] in ("ALLOCATION", "REVERSAL")
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 1
    assert data["priority_tier"] in ("EMERGENCY", "CRITICAL", "HIGH", "MODERATE")
    assert isinstance(data["rank_score"], int)
    assert 0 <= data["rank_score"] <= 100


def assert_distribution(data: dict):
    _assert_common_fields(data, statuses=DISTRIBUTION_STATUSES)
    assert isinstance(data["shipped_units"], int)
    assert isinstance(data["received_units"], int)
    assert data["impact_units_confirmed"] == data["received_units"]


def assert_impact_season(data: dict):
    _assert_common_fields(data, statuses=SEASON_STATUSES)
    assert isinstance(data["season_code"], str) and data["season_code"]
    assert isinstance(data["total_shipped_units"], int)
    assert isinstance(data["total_received_units"], int)
    assert isinstance(data["claim_frozen_units_total"], int)
    assert isinstance(data["liability_reconciliation_delta"], int)
    assert isinstance(data["attributed_units_total"], int)


def assert_marketing_claim(data: dict):
    _assert_common_fields(data, statuses=CLAIM_STATUSES)
    assert isinstance(data["stated_donation_units"], int)
    assert isinstance(data["winback_multiplier"], int) and data["winback_multiplier"] >= 1


def assert_sales_order(data: dict):
    _assert_common_fields(data, statuses=ORDER_STATUSES)
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    assert isinstance(data["ordered_units"], int)
    assert isinstance(data["refunded_cents"], int)


def assert_sales_order_line(data: dict):
    _assert_common_fields(data, statuses=ORDER_LINE_STATUSES)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["obligated_units"], int)


def assert_return_request(data: dict):
    _assert_common_fields(data, statuses=RETURN_STATUSES)
    assert isinstance(data["requested_units"], int) and data["requested_units"] >= 1
    assert data["liability_delta_units"] == 0
    if data.get("is_exchange"):
        assert data["refund_amount_cents"] == 0


def assert_impact_audit(data: dict):
    _assert_common_fields(data, statuses=AUDIT_STATUSES)
    assert data["audit_kind"] in ("ANNUAL_IMPACT", "PARTNER_PERFORMANCE")
    assert isinstance(data["shipped_units_verified"], int)
    assert isinstance(data["received_units_verified"], int)
    assert 0 <= data["scorecard_total"] <= 100


def assert_impact_audit_invariants(data: dict):
    assert data["shipped_units_verified"] >= 0
    assert data["received_units_verified"] >= 0
    assert 0 <= data["scorecard_total"] <= 100


def assert_liability_credits_match_final(data: dict):
    """Once payment has settled the credit ledger equals the final unit ledger."""
    assert data["donation_credit_units"] == data["final_liability_units"]


def assert_per_unit_cost_never_exceeds_manufacturing(line: dict, unit_cost_cents: int):
    """A dual-channel line is never charged more than its own manufacturing cost."""
    assert line["unit_obligation_cost_cents"] <= unit_cost_cents


def assert_response_shape_object(data: dict):
    assert isinstance(data, dict), "a single-resource response carries an object"


def assert_units_are_integers(data: dict, fields):
    for f in fields:
        value = data.get(f)
        assert isinstance(value, int) and not isinstance(value, bool), (
            f"{f} must be an integer, got {value!r}"
        )


def assert_close(actual, expected, abs_tol=0.01, message=""):
    assert actual == pytest.approx(expected, abs=abs_tol), (
        f"{message or 'value'} expected {expected}, got {actual}"
    )

def cited(sentence: str) -> str:
    """Wrap a PRD sentence in quotation marks for use inside a docstring."""
    return f'"{sentence}"'
