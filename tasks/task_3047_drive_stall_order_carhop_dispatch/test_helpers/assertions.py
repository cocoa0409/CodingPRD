"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_location(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["timezone"], str) and data["timezone"]
    assert data["weather_mode"] in ("NORMAL", "HEAT_ADVISORY", "STORM")
    assert isinstance(data["stall_capacity"], int) and data["stall_capacity"] > 0
    assert isinstance(data["stalls_available"], int) and data["stalls_available"] >= 0
    assert data["lane_posture"] in ("OPEN", "CONGESTED", "CURBSIDE_ONLY")
    assert isinstance(data["rush_index"], int) and data["rush_index"] >= 0


def assert_menu_item(data: dict):
    _assert_common(data)
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["category"] in ("FOOD", "DRINK", "SLUSH", "DESSERT", "ADDIN")
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] >= 0
    assert data["size_scheme"] in ("NONE", "DRINK_SIZES")
    assert isinstance(data["half_price_eligible"], bool)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_customization_option(data: dict):
    _assert_common(data)
    assert isinstance(data["code"], str) and data["code"]
    assert data["applies_to_category"] in ("DRINK", "SLUSH", "ANY")
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["is_size"], bool)
    assert isinstance(data["size_upcharge_cents"], int)
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["app_user"] is True
    assert isinstance(data["wallet_credit_cents"], int) and data["wallet_credit_cents"] >= 0


def assert_stall(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a valid UUID"
    assert isinstance(data["stall_number"], int)
    assert data["kind"] in ("STALL", "PATIO")
    assert isinstance(data["intercom_functional"], bool)
    assert data["status"] in ("IDLE", "OCCUPIED", "OUT_OF_SERVICE")


def assert_carhop(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a valid UUID"
    assert isinstance(data["name"], str) and data["name"]
    assert data["zone"] in ("NORTH", "SOUTH", "PATIO")
    assert isinstance(data["on_shift"], bool)
    assert isinstance(data["max_trays"], int) and data["max_trays"] >= 1
    assert isinstance(data["active_run_load"], int) and data["active_run_load"] >= 0
    assert isinstance(data["tips_outstanding_cents"], int)
    assert isinstance(data["tips_settled_cents"], int)


def assert_order(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a valid UUID"
    assert data["channel"] in ("STALL_INTERCOM", "APP_CHECKIN", "DRIVE_THRU", "PATIO")
    assert data["status"] in (
        "DRAFT", "PLACED", "PREPARING", "READY", "OUT_FOR_DELIVERY", "DELIVERED", "CANCELLED",
    )
    assert data["payment_status"] in ("UNPAID", "AUTHORIZED", "CAPTURED", "VOIDED", "REFUNDED")
    for f in ("subtotal_cents", "offer_discount_cents", "tax_cents", "tip_cents",
              "total_cents", "total_tendered_cents"):
        assert isinstance(data[f], int), f"{f} must be integer cents"
    assert isinstance(data["late_flag"], bool)


def assert_order_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a valid UUID"
    assert is_valid_uuid(data.get("menu_item_id", "")), "menu_item_id must be a valid UUID"
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["extended_price_cents"], int)
    assert isinstance(data["happy_hour_priced"], bool)


def assert_offer(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a valid UUID"
    assert isinstance(data["code"], str) and data["code"]
    assert data["kind"] in ("HAPPY_HOUR", "APP_ONLY", "PROMO")
    assert data["discount_type"] in ("HALF_PRICE_DRINKS", "PERCENT_OFF_ORDER", "FIXED_OFF_CENTS")
    assert isinstance(data["discount_value"], int)
    assert isinstance(data["window_start_local"], str) and data["window_start_local"]
    assert isinstance(data["window_end_local"], str) and data["window_end_local"]
    assert isinstance(data["app_only"], bool)
    assert data["status"] in ("ACTIVE", "DISABLED")


def assert_delivery_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a valid UUID"
    assert is_valid_uuid(data.get("carhop_id", "")), "carhop_id must be a valid UUID"
    assert data["status"] in ("LOADED", "OUT", "COMPLETED", "VOIDED")
    assert isinstance(data["order_count"], int) and data["order_count"] >= 0


def assert_tip_record(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a valid UUID"
    assert isinstance(data["tip_cents"], int)
    assert data["status"] in ("RECORDED", "SETTLED", "VOIDED")


def assert_equipment_fault(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("stall_id", "")), "stall_id must be a valid UUID"
    assert data["reported_by_role"] in ("CARHOP", "SHIFT_MANAGER")
    assert data["kind"] in ("INTERCOM_DEAD", "PAYMENT_TERMINAL_DEAD", "MENU_BOARD_DEAD")
    assert data["status"] in ("OPEN", "RESOLVED")


def assert_service_target_profile(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("location_id", "")), "location_id must be a valid UUID"
    assert data["channel"] in ("STALL_INTERCOM", "APP_CHECKIN", "DRIVE_THRU", "PATIO")
    assert data["weather_mode"] in ("NORMAL", "HEAT_ADVISORY", "STORM")
    assert isinstance(data["target_seconds"], int) and data["target_seconds"] > 0
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_location_posture_invariants(data: dict):
    """Derived-field invariants: stalls_available never negative; CURBSIDE_ONLY
    iff availability is zero or the weather is STORM."""
    assert data["stalls_available"] >= 0
    assert data["stalls_available"] <= data["stall_capacity"]
    if data["weather_mode"] == "STORM" or data["stalls_available"] == 0:
        assert data["lane_posture"] == "CURBSIDE_ONLY", (
            f"expected CURBSIDE_ONLY, got {data['lane_posture']} "
            f"(weather_mode={data['weather_mode']}, stalls_available={data['stalls_available']})"
        )


def assert_carhop_load_invariants(data: dict):
    """Carhop counters stay non-negative."""
    assert data["active_run_load"] >= 0
    assert data["tips_outstanding_cents"] >= 0
    assert data["tips_settled_cents"] >= 0
