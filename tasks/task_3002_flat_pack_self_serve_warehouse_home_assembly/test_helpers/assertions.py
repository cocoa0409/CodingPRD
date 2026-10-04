"""Entity assertions and domain invariant checkers (PRD §2.2, §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    """PRD §2.4: id, created_at, updated_at, version on every resource."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be >= 1"


def assert_store(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["low_stock_threshold"], int) and data["low_stock_threshold"] >= 1


def assert_article(data: dict):
    _assert_common(data)
    assert isinstance(data["article_number"], str) and data["article_number"]
    assert data["category"] in ("FURNITURE", "FOOD", "ACCESSORY")
    assert data["pick_policy"] in ("SELF_SERVE", "FULL_SERVE")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["carton_count"], int) and data["carton_count"] >= 0
    assert isinstance(data["is_multi_carton"], bool)


def assert_carton(data: dict):
    _assert_common(data)
    assert isinstance(data["carton_seq"], int) and data["carton_seq"] >= 1
    assert isinstance(data["aisle"], str)
    assert isinstance(data["bin"], str)
    assert data["weight_kg"] > 0
    assert data["volume_m3"] > 0


def assert_bin_stock(data: dict):
    _assert_common(data)
    assert isinstance(data["on_hand"], int) and data["on_hand"] >= 0
    assert isinstance(data["reserved"], int) and data["reserved"] >= 0
    assert data["reserved"] <= data["on_hand"], (
        f"reserved {data['reserved']} must stay <= on_hand {data['on_hand']} (PRD §3.1)"
    )
    assert data["available"] == data["on_hand"] - data["reserved"], (
        "available is simply what remains when the reserved units are subtracted "
        "from what is on hand (PRD §3.1)"
    )


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert data["member_status"] in ("NONE", "ACTIVE")
    assert isinstance(data["points_balance"], int) and data["points_balance"] >= 0


def assert_order(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "PAID", "FULFILLED", "DELIVERED", "CLOSED", "CANCELLED")
    assert data["delivery_status"] in ("NONE", "WAITLISTED", "SCHEDULED", "OUT_FOR_DELIVERY", "DELIVERED")
    assert data["assembly_status"] in ("NONE", "SCHEDULED", "IN_PROGRESS", "COMPLETED")
    assert data["fulfillment_channel"] in ("CARRYOUT", "DELIVERY")
    for f in ("subtotal_cents", "discount_cents", "points_discount_cents", "total_cents", "points_earned"):
        assert isinstance(data[f], int), f"{f} must be integer cents/points"
    assert data["total_cents"] == (
        data["subtotal_cents"] - data["discount_cents"] - data["points_discount_cents"]
    ), "total_cents = subtotal - discount - points discount (PRD §3.3)"


def assert_order_line(data: dict):
    _assert_common(data)
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert data["fulfillment_mode"] in ("SELF_PICK", "PICKUP_COUNTER")
    assert isinstance(data["returned_qty"], int) and data["returned_qty"] >= 0


def assert_reservation(data: dict):
    _assert_common(data)
    assert data["status"] in ("ACTIVE", "FULFILLED", "CANCELLED", "EXPIRED")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert is_iso8601_timestamp(data.get("reserved_at", ""))
    assert is_iso8601_timestamp(data.get("expires_at", ""))


def assert_delivery_slot(data: dict):
    _assert_common(data)
    assert data["zone"] in ("ZONE_A", "ZONE_B", "ZONE_C")
    assert data["capacity_weight_kg"] > 0
    assert data["capacity_volume_m3"] > 0
    assert data["used_weight_kg"] >= 0
    assert data["used_volume_m3"] >= 0
    assert data["posture"] in ("OPEN", "FULL")
    assert data["used_weight_kg"] <= data["capacity_weight_kg"], "slot weight invariant (PRD §3.5)"
    assert data["used_volume_m3"] <= data["capacity_volume_m3"], "slot volume invariant (PRD §3.5)"


def assert_delivery_booking(data: dict):
    _assert_common(data)
    assert data["status"] in ("CONFIRMED", "WAITLISTED", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED")
    assert data["access_type"] in ("ELEVATOR", "WALKUP_LOW", "WALKUP_HIGH")
    assert isinstance(data["floor"], int) and data["floor"] >= 0
    assert isinstance(data["fee_cents"], int)


def assert_assembly_standard(data: dict):
    _assert_common(data)
    assert isinstance(data["minutes_per_unit"], int) and data["minutes_per_unit"] > 0
    assert isinstance(data["crew_size"], int) and data["crew_size"] >= 1


def assert_assembly_job(data: dict):
    _assert_common(data)
    assert data["status"] in ("REQUESTED", "DISPATCHED", "IN_PROGRESS", "ON_HOLD", "COMPLETED", "CANCELLED")
    assert isinstance(data["provider_id"], str) and data["provider_id"]
    assert isinstance(data["estimated_minutes"], int) and data["estimated_minutes"] >= 0


def assert_spare_part_claim(data: dict):
    _assert_common(data)
    assert data["status"] in ("SUBMITTED", "APPROVED", "DENIED", "SHIPPED")
    assert isinstance(data["part_value_cents"], int) and data["part_value_cents"] >= 0


def assert_return_request(data: dict):
    _assert_common(data)
    assert data["status"] in ("DRAFT", "SUBMITTED", "GRADING", "SETTLED", "DISPUTED")
    assert isinstance(data["receipted"], bool)
    assert isinstance(data["refund_total_cents"], int) and data["refund_total_cents"] >= 0
    assert isinstance(data["writeoff_total_cents"], int) and data["writeoff_total_cents"] >= 0


def assert_return_line(data: dict):
    _assert_common(data)
    assert data["assembly_state"] in ("UNOPENED", "PARTIALLY_ASSEMBLED", "ASSEMBLED")
    assert isinstance(data["qty"], int) and data["qty"] >= 1
    assert isinstance(data["restocked_units"], int) and data["restocked_units"] >= 0
