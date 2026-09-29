"""Shape and invariant assertions for the Landscape Supply Yard API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import pytest
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import THRESHOLDS

CENTS = 0.01


def assert_common_fields(data: Dict[str, Any]) -> None:
    """Every resource carries a UUID id, both timestamps and an integer version."""
    assert is_valid_uuid(data["id"]), f"id is not a bare UUID: {data['id']!r}"
    assert is_iso8601_timestamp(data["created_at"]), data["created_at"]
    assert is_iso8601_timestamp(data["updated_at"]), data["updated_at"]
    assert isinstance(data["version"], int)
    assert data["version"] >= 1


def assert_response_meta(body: Dict[str, Any]) -> None:
    """The envelope's meta block carries a ``req_``-prefixed id and a UTC timestamp."""
    meta = body["meta"]
    assert isinstance(meta["api_request_id"], str)
    assert meta["api_request_id"].startswith("req_"), meta["api_request_id"]
    assert is_iso8601_timestamp(meta["api_request_timestamp"]), meta["api_request_timestamp"]


def normalize_instant(value: str) -> str:
    """Render an ISO-8601 UTC instant with exactly three fractional digits."""
    assert isinstance(value, str), f"expected an ISO-8601 instant, got {value!r}"
    body = value[:-1] if value.endswith("Z") else value
    if "." in body:
        seconds, fraction = body.split(".", 1)
        fraction = (fraction + "000")[:3]
    else:
        seconds, fraction = body, "000"
    return f"{seconds}.{fraction}Z"


def assert_instant_equals(actual: str, expected: str) -> None:
    """Two instants name the same moment regardless of rendered sub-second width."""
    assert normalize_instant(actual) == normalize_instant(expected), f"{actual!r} != {expected!r}"


def _money(data: Dict[str, Any], field: str) -> None:
    value = data.get(field)
    if value is not None:
        assert isinstance(value, int), f"{field} must be integer cents, got {value!r}"


def assert_material(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["sku"], str)
    assert isinstance(data["name"], str)
    assert isinstance(data["offered_forms"], list) and data["offered_forms"]
    assert set(data["offered_forms"]) <= {"BULK", "BAGGED"}
    assert data["seasonal_category"] in {"MULCH", "SALT", "AGGREGATE", "SOIL"}
    assert data["density_lb_per_cubic_yard"] > 0
    assert 0 <= data["shrinkage_factor"] <= 0.5
    assert 0 <= data["moisture_pct"] <= 60
    assert data["unit_bag_cubic_yards"] > 0
    assert isinstance(data["prebuy_eligible"], bool)
    assert data["status"] in {"ACTIVE", "SUSPENDED", "DISCONTINUED"}
    assert data["effective_density_lb_per_cubic_yard"] == pytest.approx(
        expected_effective_density(data["density_lb_per_cubic_yard"], data["moisture_pct"]), abs=CENTS
    )
    assert data["available_net_cubic_yards"] >= -CENTS


def assert_price_schedule(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["material_id"])
    assert is_iso8601_timestamp(data["effective_from"]), data["effective_from"]
    _money(data, "bulk_price_per_cubic_yard_cents")
    _money(data, "bagged_price_per_bag_cents")
    assert data["bulk_price_per_cubic_yard_cents"] > 0
    assert data["bagged_price_per_bag_cents"] > 0
    assert 0 <= data["seasonal_surcharge_pct"] <= 50
    assert data["status"] in {"SCHEDULED", "EFFECTIVE", "SUPERSEDED"}


def assert_inventory_lot(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["material_id"])
    assert data["gross_cubic_yards"] > 0
    assert 0 <= data["moisture_pct_at_intake"] <= 60
    assert 0 <= data["current_moisture_pct"] <= 60
    assert data["basis"] in {"INTAKE", "SETTLEMENT"}
    assert data["withdrawn_gross_cubic_yards"] >= -CENTS
    assert data["net_sellable_cubic_yards"] >= -CENTS
    assert data["reserved_cubic_yards"] >= -CENTS
    assert data["status"] in {"AVAILABLE", "QUARANTINED", "DEPLETED"}


def assert_contractor_account(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["business_name"], str)
    for field in (
        "credit_limit_cents",
        "credit_used_cents",
        "credit_available_cents",
        "pallet_deposit_balance_cents",
    ):
        _money(data, field)
    assert data["credit_limit_cents"] >= 0
    assert isinstance(data["po_required"], bool)
    assert isinstance(data["driveway_protection_required"], bool)
    assert data["account_status"] in {"ACTIVE", "CREDIT_HOLD"}
    assert data["credit_available_cents"] == data["credit_limit_cents"] - data["credit_used_cents"]


def assert_job_purchase_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert isinstance(data["po_number"], str)
    assert isinstance(data["job_code"], str)
    _money(data, "po_limit_cents")
    _money(data, "committed_cents")
    assert data["po_limit_cents"] > 0
    assert data["status"] in {"OPEN", "EXHAUSTED", "CLOSED"}


def assert_prebuy_contract(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert is_valid_uuid(data["material_id"])
    _money(data, "locked_price_per_cubic_yard_cents")
    assert data["locked_price_per_cubic_yard_cents"] > 0
    assert data["contracted_cubic_yards"] > 0
    assert len(data["season_start_date"]) == 10
    assert len(data["season_end_date"]) == 10
    assert data["season_end_date"] >= data["season_start_date"]
    assert data["status"] in {"DRAFT", "ACTIVE", "EXHAUSTED", "EXPIRED"}
    assert data["remaining_cubic_yards"] == pytest.approx(
        data["contracted_cubic_yards"] - data["drawn_cubic_yards"], abs=CENTS
    )


def assert_material_order(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["contractor_account_id"])
    assert data["fulfillment_mode"] in {"DELIVERY", "WILL_CALL"}
    if data["driveway_access_class"] is not None:
        assert data["driveway_access_class"] in {"CLASS_A", "CLASS_B", "CLASS_C"}
    for field in (
        "bulk_subtotal_cents",
        "bagged_subtotal_cents",
        "volume_discount_cents",
        "min_load_fee_cents",
        "delivery_fee_cents",
        "quoted_total_cents",
        "final_total_cents",
        "credit_memo_cents",
        "paid_amount_cents",
    ):
        _money(data, field)
    assert data["fulfillment_status"] in {"DRAFT", "CONFIRMED", "ALLOCATED", "FULFILLED", "CANCELLED"}
    assert data["settlement_status"] in {"UNBILLED", "INVOICED", "SETTLED", "CREDIT_MEMO_ISSUED"}
    if data["quote_locked_at"] is not None:
        assert is_iso8601_timestamp(data["quote_locked_at"]), data["quote_locked_at"]


def assert_order_line(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["material_order_id"])
    assert is_valid_uuid(data["material_id"])
    assert data["form"] in {"BULK", "BAGGED"}
    assert data["quantity"] > 0
    for field in ("unit_price_cents", "line_price_cents", "final_line_price_cents"):
        _money(data, field)
    assert data["line_volume_cubic_yards"] >= 0
    assert data["delivered_volume_cubic_yards"] >= 0


def assert_delivery_truck(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert isinstance(data["truck_code"], str)
    assert data["axle_class"] in {"SINGLE", "TANDEM", "TRI_AXLE"}
    assert data["max_payload_lb"] > 0
    assert data["bed_capacity_cubic_yards"] > 0
    assert data["min_driveway_access_class"] in {"CLASS_A", "CLASS_B", "CLASS_C"}
    assert data["status"] in {"AVAILABLE", "IN_SERVICE", "OUT_OF_SERVICE"}


def assert_delivery_load(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["material_order_id"])
    assert is_valid_uuid(data["delivery_truck_id"])
    assert data["planned_cubic_yards"] > 0
    assert is_iso8601_timestamp(data["window_start"]), data["window_start"]
    assert is_iso8601_timestamp(data["window_end"]), data["window_end"]
    assert data["window_end"] > data["window_start"]
    assert isinstance(data["planned_payload_lb"], int)
    assert data["max_allowed_cubic_yards"] >= 0
    assert data["spillage_cubic_yards"] >= 0
    if data["refusal_reason"] is not None:
        assert data["refusal_reason"] in {"ACCESS_BLOCKED", "CUSTOMER_REFUSED", "EQUIPMENT_FAILURE"}
    assert data["status"] in {"PLANNED", "DISPATCHED", "DELIVERED", "REFUSED", "CANCELLED"}


def assert_will_call_ticket(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["material_order_id"])
    assert is_iso8601_timestamp(data["requested_pickup_at"]), data["requested_pickup_at"]
    assert data["priority_class"] in {1, 2}
    assert isinstance(data["ppe_confirmed"], bool)
    assert data["status"] in {"QUEUED", "STAGED", "LOADING", "LOADED", "RELEASED", "CANCELLED"}
    if data["status"] == "QUEUED":
        assert isinstance(data["queue_position"], int) and data["queue_position"] >= 1
    else:
        assert data["queue_position"] is None


def assert_claim_case(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["material_order_id"])
    assert data["claim_type"] in {"DRIVEWAY_DAMAGE", "SPILLAGE", "SHORT_LOAD"}
    for field in (
        "claimed_amount_cents",
        "approved_amount_cents",
        "payable_cents",
        "invoice_offset_cents",
        "deposit_offset_cents",
        "goodwill_credit_cents",
    ):
        _money(data, field)
    assert data["claimed_amount_cents"] > 0
    assert isinstance(data["review_round"], int) and data["review_round"] >= 0
    if data["approved_amount_cents"] is not None:
        assert data["approved_amount_cents"] <= data["claimed_amount_cents"]
    assert data["status"] in {
        "SUBMITTED",
        "UNDER_REVIEW",
        "INFO_REQUESTED",
        "APPROVED",
        "DENIED",
        "SETTLED",
    }


def assert_container_return(data: Dict[str, Any]) -> None:
    assert_common_fields(data)
    assert is_valid_uuid(data["material_order_id"])
    assert data["container_type"] in {"PALLET", "SUPER_SACK", "SALT_TOTE"}
    assert data["issued_count"] > 0
    assert data["returned_count"] >= 0
    for field in ("deposit_per_unit_cents", "refund_cents", "forfeited_cents"):
        _money(data, field)
    assert is_iso8601_timestamp(data["issued_at"]), data["issued_at"]
    if data["last_received_at"] is not None:
        assert is_iso8601_timestamp(data["last_received_at"]), data["last_received_at"]
    assert data["status"] in {"OUTSTANDING", "PARTIALLY_RETURNED", "CLOSED", "FORFEITED"}


# --------------------------------------------------------------------- invariants


def expected_effective_density(density_lb_per_cubic_yard: float, moisture_pct: float) -> float:
    """Density scaled by how far moisture sits from the reference percentage."""
    reference = THRESHOLDS["MOISTURE_REFERENCE_PCT"]
    raw = density_lb_per_cubic_yard * (1 + (moisture_pct - reference) / 100)
    return round(raw + 1e-9, 2)


def assert_effective_density(material: Dict[str, Any]) -> None:
    assert material["effective_density_lb_per_cubic_yard"] == pytest.approx(
        expected_effective_density(material["density_lb_per_cubic_yard"], material["moisture_pct"]),
        abs=CENTS,
    )


def assert_credit_position(account: Dict[str, Any], used_cents: int, available_cents: int) -> None:
    assert account["credit_used_cents"] == used_cents
    assert account["credit_available_cents"] == available_cents
    assert account["credit_available_cents"] == account["credit_limit_cents"] - account["credit_used_cents"]


def assert_deposit_liability_conserved(container_return: Dict[str, Any]) -> None:
    """Refunded plus forfeited never exceeds the deposit that went out."""
    issued_total = container_return["issued_count"] * container_return["deposit_per_unit_cents"]
    assert container_return["refund_cents"] + container_return["forfeited_cents"] <= issued_total


def assert_deposit_fully_resolved(container_return: Dict[str, Any]) -> None:
    """Once a return row is closed out, every issued cent is either refunded or forfeited."""
    issued_total = container_return["issued_count"] * container_return["deposit_per_unit_cents"]
    assert container_return["refund_cents"] + container_return["forfeited_cents"] == issued_total


def assert_claim_waterfall_sums(claim: Dict[str, Any]) -> None:
    """The three waterfall buckets add up to the payable amount."""
    assert (
        claim["invoice_offset_cents"] + claim["deposit_offset_cents"] + claim["goodwill_credit_cents"]
        == claim["payable_cents"]
    )


def assert_charge_assembly(order: Dict[str, Any], total_cents: int) -> None:
    """The published money breakdown reproduces the stated total."""
    assembled = (
        order["bulk_subtotal_cents"]
        - order["volume_discount_cents"]
        + order["bagged_subtotal_cents"]
        + order["min_load_fee_cents"]
        + order["delivery_fee_cents"]
    )
    assert assembled == total_cents


def assert_queue_positions(tickets: List[Dict[str, Any]], expected: Dict[str, Optional[int]]) -> None:
    """Compare each ticket's queue position against an id -> position mapping."""
    actual = {ticket["id"]: ticket["queue_position"] for ticket in tickets}
    for ticket_id, position in expected.items():
        assert actual[ticket_id] == position


__all__ = [
    "CENTS",
    "assert_common_fields",
    "assert_response_meta",
    "normalize_instant",
    "assert_instant_equals",
    "assert_material",
    "assert_price_schedule",
    "assert_inventory_lot",
    "assert_contractor_account",
    "assert_job_purchase_order",
    "assert_prebuy_contract",
    "assert_material_order",
    "assert_order_line",
    "assert_delivery_truck",
    "assert_delivery_load",
    "assert_will_call_ticket",
    "assert_claim_case",
    "assert_container_return",
    "expected_effective_density",
    "assert_effective_density",
    "assert_credit_position",
    "assert_deposit_liability_conserved",
    "assert_deposit_fully_resolved",
    "assert_claim_waterfall_sums",
    "assert_charge_assembly",
    "assert_queue_positions",
]
