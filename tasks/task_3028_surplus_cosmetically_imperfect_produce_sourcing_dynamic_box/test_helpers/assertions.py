"""Entity assertions and domain invariant checkers.

Field presence/type assertions are applied to the resources the PRD declares
inline (for example the created fulfillment center), not to every serialised
row — the PRD does not force a `get`-by-id response to echo every derived
figure, so only figures the PRD names as returned are asserted.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_customer(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "Customer.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["email"], str) and "@" in data["email"]
    assert data["service_region"] in ("NE", "MW", "SO", "WE")
    assert isinstance(data["home_fulfillment_center_id"], str)
    assert isinstance(data["dietary_allergy_codes"], list)
    assert isinstance(data["grandfathered_service_fee"], bool)


def assert_fulfillment_center(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "FulfillmentCenter.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert data["region"] in ("NE", "MW", "SO", "WE")
    assert data["insulation_profile"] in ("LIGHT", "MEDIUM", "HEAVY")
    assert data["forward_posture"] in ("OPEN", "CONSTRAINED", "DEGRADED")
    assert isinstance(data["is_active"], bool)
    assert isinstance(data["serving_cycle_index"], int)
    assert isinstance(data["max_concurrent_building_cycles"], int)
    assert isinstance(data["open_claim_count"], int)


def assert_supplier(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "Supplier.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert data["relationship_status"] in ("PREFERRED", "STANDARD", "ON_WATCH", "SUSPENDED")
    assert 0 <= data["reliability_score_bp"] <= 10000


def assert_supply_lot(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "SupplyLot.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in (
        "QUOTED", "AWARDED", "READY", "COMMITTED", "DEPLETED", "EXPIRED"
    )
    assert data["quality_status"] in (
        "PENDING_INSPECTION", "PASS", "INVESTIGATION", "REJECTED"
    )
    assert data["category"] in (
        "FRUIT", "VEGETABLE", "DAIRY", "BAKERY", "PANTRY", "BEVERAGE"
    )
    assert isinstance(data["quantity_available"], int)
    assert isinstance(data["shelf_life_days"], int)


def assert_box_order(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "BoxOrder.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in (
        "DRAFT", "AWAITING_WINDOW", "READY_TO_BUILD", "BUILDING",
        "REROUTED", "CRASHED", "PACKED", "SHIPPED",
    )
    assert data["pricing_status"] in ("UNPRICED", "PRICED", "REVISED")
    assert isinstance(data["cutoff_met"], bool)
    assert isinstance(data["build_blocked"], bool)
    assert isinstance(data["cold_chain_selected"], bool)


def assert_cold_chain_pack(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "ColdChainPack.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    # ColdChainPack is created once and never modified: no updated_at, no version.
    assert "updated_at" not in data, "ColdChainPack must not carry updated_at"
    assert "version" not in data, "ColdChainPack must not carry version"
    assert data["insulation_grade"] in ("LIGHT", "MEDIUM", "HEAVY")
    assert data["selection_status"] in ("SELECTED", "NOT_REQUIRED")
    assert isinstance(data["coolant_units"], int)
    assert isinstance(data["lane_transit_days"], int)
    assert isinstance(data["cold_item_weight_grams"], int)


def assert_quality_claim(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "QualityClaim.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in ("IN_REVIEW", "UNDER_REVIEW", "CLOSED", "UPHELD", "REJECTED")
    assert data["reason_code"] in ("SPOILED", "DAMAGED", "MISSING_ITEM", "TEMPERATURE_ABUSE")
    assert isinstance(data["requested_credit_cents"], int)
    assert isinstance(data["credited_cents"], int)


def assert_subscription(data: dict) -> None:
    assert is_valid_uuid(data.get("id", "")), "Subscription.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert data["status"] in ("ACTIVE", "SKIPPED", "AUTO_SKIPPED", "PAUSED", "CANCELLED")
    assert data["cadence"] in ("WEEKLY", "BIWEEKLY", "MONTHLY")
    assert 0 <= data["pause_count"] <= 4


def assert_box_order_pricing_invariants(data: dict) -> None:
    """Order-level arithmetic identities the PRD pins in §3.6."""
    assert data["subtotal_cents"] == data["lines_total_cents"] - data["order_discount_cents"], (
        "subtotal_cents must be the merchandise total less the order discount"
    )
    assert data["shipped_total_cents"] == (
        data["subtotal_cents"] + data["tax_cents"] + data["service_fee_cents"]
    ), "shipped_total_cents must be subtotal + tax + service fee"
    assert data["lines_total_cents"] >= 0
    assert data["weight_total_grams"] >= 0


def assert_lot_quantity_never_negative(data: dict) -> None:
    assert data["quantity_available"] >= 0, "quantity_available is a conserved count"


def count_rows(response) -> int:
    """Return the number of rows in a list response, asserting the envelope."""
    body = response.json()
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    assert body.get("response_type") == "array", "Expected response_type 'array'"
    return len(body["data"])