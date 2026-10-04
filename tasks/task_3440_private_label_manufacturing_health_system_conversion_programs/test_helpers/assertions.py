"""Entity assertions and embedded-record finders (PRD §2.5, §3).

Assertions check the common resource envelope (UUID id, ISO 8601 timestamps,
integer version) plus enum membership of status fields. Nullable computed
fields are checked with .get() so a faithful serializer that omits null
computed fields still passes.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be a positive integer"
    )


def assert_product(data: dict):
    _assert_common(data, "Product")
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["brand_type"] in ("BRANDED", "PRIVATE_LABEL")
    assert data["category"] in (
        "SURGICAL_INSTRUMENTS", "WOUND_CARE", "EXAM_GLOVES",
        "STERILIZATION_SUPPLIES", "UROLOGICAL", "RESPIRATORY",
    )
    assert data["registration_status"] in (
        "UNREGISTERED", "SUBMITTED", "REGISTERED", "REJECTED"
    )
    assert data["availability"] in ("ACTIVE", "DISCONTINUED")
    assert isinstance(data["units_per_case"], int) and data["units_per_case"] > 0
    assert isinstance(data["each_price_cents"], int) and data["each_price_cents"] >= 0
    assert isinstance(data["order_multiple"], int) and data["order_multiple"] >= 1
    assert isinstance(data["sterile"], bool)
    assert isinstance(data["lum_eligible"], bool)


def assert_manufacturing_lot(data: dict):
    _assert_common(data, "ManufacturingLot")
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert is_valid_uuid(data.get("product_id", ""))
    assert isinstance(data["quantity"], int) and data["quantity"] > 0
    assert data["status"] in ("AWAITING_QA", "RELEASED", "REJECTED", "QUARANTINED")
    assert data["sterility_status"] in ("PENDING", "PASSED", "FAILED", "NOT_REQUIRED")


def assert_sterilization_batch(data: dict):
    _assert_common(data, "SterilizationBatch")
    assert isinstance(data["batch_code"], str) and data["batch_code"]
    assert isinstance(data["chamber_id"], str) and data["chamber_id"]
    assert isinstance(data["lot_ids"], list)
    assert data["status"] in ("SCHEDULED", "COMPLETED")
    assert data["sterility_result"] in ("PENDING", "PASSED", "FAILED")


def assert_facility(data: dict):
    _assert_common(data, "Facility")
    assert isinstance(data["name"], str) and data["name"]
    assert data["facility_type"] in (
        "ACUTE_CARE", "SURGERY_CENTER", "CLINIC", "LONG_TERM_CARE"
    )


def assert_conversion_program(data: dict):
    _assert_common(data, "ConversionProgram")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["line_items"], list) and len(data["line_items"]) >= 1
    assert data["status"] in ("IN_EVALUATION", "IN_REVIEW", "CONVERTED")
    for item in data["line_items"]:
        assert item["evaluation_status"] in ("PENDING", "PASSED", "FAILED")
        assert isinstance(item["training_completed"], bool)


def assert_tray_template(data: dict):
    _assert_common(data, "TrayTemplate")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["components"], list) and len(data["components"]) >= 1
    assert data["status"] in ("DRAFT", "PENDING_APPROVAL", "ACTIVE", "UNDER_CHANGE")


def assert_prime_vendor_agreement(data: dict):
    _assert_common(data, "PrimeVendorAgreement")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert 0 <= data["committed_fill_rate_pct"] <= 100
    assert 1 <= data["deliveries_per_week"] <= 7
    assert isinstance(data["lum_commitment"], bool)
    assert data["status"] in ("ACTIVE", "SUSPENDED", "EXPIRED")
    assert isinstance(data["spent_cents"], int) and data["spent_cents"] >= 0


def assert_distribution_order(data: dict):
    _assert_common(data, "DistributionOrder")
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert data["status"] in ("PLACED", "PARTIALLY_SHIPPED", "SHIPPED", "RECEIVED")
    assert isinstance(data["total_price_cents"], int) and data["total_price_cents"] >= 0


def assert_rebate_claim(data: dict):
    _assert_common(data, "RebateClaim")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert isinstance(data["gpo_name"], str) and data["gpo_name"]
    assert data["status"] in ("ACCRUED", "SUBMITTED", "PAID", "DISPUTED")
    assert isinstance(data["eligible_purchase_cents"], int)
    assert data["eligible_purchase_cents"] > 0
    assert isinstance(data["provisional_amount_cents"], int)
    assert isinstance(data["compliant"], bool)


def assert_supply_disruption(data: dict):
    _assert_common(data, "SupplyDisruption")
    assert is_valid_uuid(data.get("product_id", ""))
    assert data["status"] in ("DECLARED", "MITIGATING", "RESOLVED")
    assert isinstance(data["allocations"], list)
    assert isinstance(data["substitution_requests"], list)
    assert isinstance(data["allocated_total"], int)
    assert isinstance(data["approved_sub_total"], int)
    assert isinstance(data["remaining_pool"], int)
    assert isinstance(data["covered_quantity"], int)


def assert_inventory_program(data: dict):
    _assert_common(data, "InventoryProgram")
    assert is_valid_uuid(data.get("facility_id", ""))
    assert data["program_type"] in ("STOCKROOM_MANAGED", "CRASH_CART", "OR_CORE")
    assert isinstance(data["positions"], list) and len(data["positions"]) >= 1
    assert isinstance(data["auto_replenish_enabled"], bool)
    for pos in data["positions"]:
        assert pos["reorder_status"] in ("OK", "DUE", "CRITICAL")
        assert isinstance(pos["suggested_order_qty"], int)
        assert pos["suggested_order_qty"] >= 0


def assert_disruption_partition_invariant(data: dict):
    """allocated_total + approved_sub_total + remaining_pool == disrupted_quantity."""
    assert (
        data["allocated_total"] + data["approved_sub_total"] + data["remaining_pool"]
        == data["disrupted_quantity"]
    ), (
        f"partition drift: {data['allocated_total']} + {data['approved_sub_total']} "
        f"+ {data['remaining_pool']} != {data['disrupted_quantity']}"
    )
    assert data["covered_quantity"] == data["allocated_total"] + data["approved_sub_total"]


# --- Embedded-record finders ---


def find_position(program: dict, product_id: str) -> dict:
    for pos in program["positions"]:
        if pos["product_id"] == product_id:
            return pos
    raise AssertionError(f"No position for product {product_id} in program {program['id']}")


def find_substitution_request(
    disruption: dict, request_id: str = None, facility_id: str = None,
    status: str = None,
) -> dict:
    for req in disruption["substitution_requests"]:
        if status is not None and req["status"] != status:
            continue
        if request_id is not None and req["request_id"] == request_id:
            return req
        if facility_id is not None and req["facility_id"] == facility_id:
            return req
    raise AssertionError(
        f"No substitution request (request_id={request_id}, facility_id={facility_id}, "
        f"status={status}) in disruption {disruption['id']}"
    )


def find_line_item(program: dict, line_id: str) -> dict:
    for item in program["line_items"]:
        if item["line_id"] == line_id:
            return item
    raise AssertionError(f"No line item {line_id} in program {program['id']}")


def find_order(orders: list, order_id: str) -> dict:
    for order in orders:
        if order["id"] == order_id:
            return order
    raise AssertionError(f"Order {order_id} not found in listed orders")
