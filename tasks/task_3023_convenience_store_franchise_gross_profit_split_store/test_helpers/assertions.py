"""Entity assertions and domain invariant checkers.

Each ``assert_<entity>`` validates the resource's declared shape against the
PRD contract. The invariant checkers encode the arithmetic relationships the
PRD states directly (shares summing to the split base, ledger conservation).
"""

import pytest

from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

MONEY_FIELDS = (
    "amount_cents", "recovered_cents", "rebate_cents", "flowthrough_cents",
    "book_inventory_cents", "physical_inventory_cents", "shrink_cents",
    "shrink_charge_cents", "gross_sales_cents", "cost_of_goods_cents",
    "line_gross_profit_cents",
)


def _assert_common(data: dict):
    """Every resource carries the common system-managed fields."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_franchisee(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["owner_name"], str) and data["owner_name"]
    assert data["entity_type"] in ("INDIVIDUAL", "LLC", "CORPORATION")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "TERMINATED")
    assert data["risk_band"] in ("A", "B", "C")
    assert isinstance(data["stated_net_worth_cents"], int)
    assert isinstance(data["draw_outstanding_cents"], int)
    assert isinstance(data["open_shrink_charge_cents"], int)
    assert isinstance(data["audit_adjusted_net_worth_cents"], int)


def assert_store(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("franchisee_id", "")), "franchisee_id must be a UUID"
    assert isinstance(data["store_number"], str) and data["store_number"]
    assert isinstance(data["state_code"], str)
    assert data["format"] in ("URBAN", "SUBURBAN", "RURAL")
    assert data["lease_owner"] == "FRANCHISOR"
    assert data["equipment_owner"] == "FRANCHISOR"
    assert data["status"] in ("ACTIVE", "TERMINATED")
    assert data["transfer_status"] in ("NONE", "PENDING", "APPROVED", "DENIED")
    assert isinstance(data["cold_chain_certified"], bool)


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("franchisee_id", "")), "franchisee_id must be a UUID"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert data["royalty_pct"] == 0.0, "royalty_pct is always 0.0000"
    assert data["status"] in ("DRAFT", "ACTIVE", "RENEWAL_PENDING",
                              "RENEWED", "EXPIRED", "TERMINATED")
    assert data["performance_tier"] in ("STANDARD", "PREFERRED", "PREMIER")
    for field in ("split_pct", "waste_share_pct", "shrink_responsibility_pct",
                  "rebate_pass_pct"):
        assert isinstance(data[field], (int, float)), f"{field} must be numeric"


def assert_settlement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert is_valid_uuid(data.get("franchisee_id", "")), "franchisee_id must be a UUID"
    assert data["status"] in ("OPEN", "DRAW_PAID", "RECONCILED", "DISPUTED", "FINALIZED")
    assert isinstance(data["provisional"], bool)
    assert isinstance(data["trailing_avg_gross_profit_cents"], int)


def assert_revenue_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("settlement_id", "")), "settlement_id must be a UUID"
    assert data["category"] in ("MERCHANDISE", "FUEL", "SERVICES")
    assert data["line_gross_profit_cents"] == (
        data["gross_sales_cents"] - data["cost_of_goods_cents"]
    ), "line_gross_profit_cents must be gross sales minus cost of goods"


def assert_draw(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("franchisee_id", "")), "franchisee_id must be a UUID"
    assert data["status"] in ("ISSUED", "PARTIALLY_RECOVERED", "RECOVERED", "REVERSED")
    assert isinstance(data["amount_cents"], int)
    assert isinstance(data["recovered_cents"], int)


def assert_rebate(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert isinstance(data["vendor_code"], str) and data["vendor_code"]
    assert isinstance(data["recommended_vendor"], bool)
    assert data["status"] in ("POSTED", "APPLIED", "RETRACTED")


def assert_shrink_audit(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert data["status"] in ("SCHEDULED", "COUNTED", "FINALIZED")


def assert_delivery_window(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert data["day_of_week"] in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
    assert data["status"] in ("SCHEDULED", "LOCKED", "CANCELLED")
    assert isinstance(data["capacity_units"], int)
    assert isinstance(data["reserved_units"], int)


def assert_fresh_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert is_valid_uuid(data.get("delivery_window_id", "")), "delivery_window_id must be a UUID"
    assert data["status"] in ("PLACED", "CONFIRMED", "DELIVERED", "RECONCILED", "CANCELLED")
    assert isinstance(data["ordered_units"], int)
    assert isinstance(data["unit_cost_cents"], int)


# ─── Domain invariants ───────────────────────────────────────────────────────

def assert_split_legs_sum_to_gross_profit(settlement: dict):
    """The operator's share plus the franchisor's share always equals the base."""
    total = settlement["franchisee_split_cents"] + settlement["franchisor_share_cents"]
    assert total == pytest.approx(settlement["gross_profit_cents"], abs=0.01), (
        f"franchisee_split_cents {settlement['franchisee_split_cents']} + "
        f"franchisor_share_cents {settlement['franchisor_share_cents']} != "
        f"gross_profit_cents {settlement['gross_profit_cents']}"
    )


def assert_franchisee_net_worth_invariants(franchisee: dict):
    """audit_adjusted_net_worth is stated net worth less both recognised liabilities."""
    expected = (
        franchisee["stated_net_worth_cents"]
        - franchisee["draw_outstanding_cents"]
        - franchisee["open_shrink_charge_cents"]
    )
    assert franchisee["audit_adjusted_net_worth_cents"] == expected, (
        f"audit_adjusted_net_worth_cents {franchisee['audit_adjusted_net_worth_cents']} "
        f"!= stated {franchisee['stated_net_worth_cents']} "
        f"- draw {franchisee['draw_outstanding_cents']} "
        f"- shrink {franchisee['open_shrink_charge_cents']}"
    )
    assert franchisee["draw_outstanding_cents"] >= 0


def assert_expected_risk_band(franchisee: dict):
    """Risk band follows the audit-adjusted figure, thresholds inclusive."""
    adjusted = franchisee["audit_adjusted_net_worth_cents"]
    if adjusted >= 15_000_000:
        expected = "A"
    elif adjusted >= 5_000_000:
        expected = "B"
    else:
        expected = "C"
    assert franchisee["risk_band"] == expected, (
        f"risk_band {franchisee['risk_band']} != {expected} for adjusted {adjusted}"
    )


def assert_draw_ledger_conserved(draws: list, franchisee: dict):
    """The operator's outstanding figure equals the unrecovered draw balances."""
    expected = sum(
        d["amount_cents"] - d["recovered_cents"]
        for d in draws
        if d["status"] in ("ISSUED", "PARTIALLY_RECOVERED")
    )
    assert franchisee["draw_outstanding_cents"] == expected, (
        f"draw_outstanding_cents {franchisee['draw_outstanding_cents']} != {expected}"
    )


__all__ = [
    "assert_franchisee", "assert_store", "assert_agreement", "assert_settlement",
    "assert_revenue_line", "assert_draw", "assert_rebate", "assert_shrink_audit",
    "assert_delivery_window", "assert_fresh_order",
    "assert_split_legs_sum_to_gross_profit", "assert_franchisee_net_worth_invariants",
    "assert_expected_risk_band", "assert_draw_ledger_conserved",
]