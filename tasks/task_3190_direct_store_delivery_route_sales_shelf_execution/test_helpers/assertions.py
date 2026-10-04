"""Entity assertions and domain invariant checkers.

Every assert_{entity}(data) checks the fields the PRD declares for that
resource: server-minted UUID id, ISO-8601 created_at/updated_at, integer
version (absent on OrderLine), plus the entity's own fields.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(
        data.get("created_at", "")
    ), f"{entity}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(
        data.get("updated_at", "")
    ), f"{entity}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity}.version must be an integer >= 1"
    )


def assert_rep(data: dict):
    _assert_common(data, "RouteSalesRepresentative")
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert isinstance(data["home_depot"], str) and data["home_depot"]
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_store(data: dict):
    _assert_common(data, "Store")
    assert isinstance(data["store_code"], str) and data["store_code"]
    assert isinstance(data["name"], str) and data["name"]
    assert data["format"] in ("CONVENIENCE", "GROCERY", "SUPERCENTER", "DOLLAR")
    assert data["credit_policy"] in ("FULL_RETAIL", "SALVAGE_RATE")
    assert isinstance(data["delivery_window_start_minute"], int)
    assert isinstance(data["delivery_window_end_minute"], int)
    assert isinstance(data["store_credit_cap_cents"], int)
    assert data["store_credit_cap_cents"] >= 0
    assert isinstance(data["promo_rebate_balance_cents"], int)
    assert data["promo_rebate_balance_cents"] >= 0
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_product(data: dict):
    _assert_common(data, "Product")
    assert isinstance(data["sku"], str) and data["sku"]
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["case_price_cents"], int) and data["case_price_cents"] > 0
    assert isinstance(data["shelf_life_days"], int) and data["shelf_life_days"] > 0
    assert isinstance(data["promo_eligible"], bool)


def assert_route(data: dict):
    _assert_common(data, "Route")
    assert isinstance(data["territory_code"], str) and data["territory_code"]
    assert isinstance(data["rsr_id"], str) and data["rsr_id"]
    assert isinstance(data["base_capacity_cases"], int) and data["base_capacity_cases"] > 0
    assert isinstance(data["truck_cap_cases"], int) and data["truck_cap_cases"] > 0
    assert data["performance_flag"] in ("CLEAR", "PERFORMANCE_WATCH")
    assert data["status"] in ("ACTIVE", "SUSPENDED")


def assert_assignment(data: dict):
    _assert_common(data, "RouteStoreAssignment")
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    weekdays = data["service_weekdays"]
    assert isinstance(weekdays, list) and len(weekdays) >= 1
    assert all(w in ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN") for w in weekdays)
    assert isinstance(data["stop_sequence"], int) and data["stop_sequence"] >= 1
    assert data["status"] in ("ACTIVE", "RETIRED")


def assert_route_day(data: dict):
    _assert_common(data, "RouteDay")
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert isinstance(data["service_date"], str) and len(data["service_date"]) == 10
    assert isinstance(data["is_event_day"], bool)
    assert isinstance(data["event_surge_cases"], int)
    assert isinstance(data["capacity_cases"], int)
    assert isinstance(data["loaded_cases"], int) and data["loaded_cases"] >= 0
    assert isinstance(data["delivered_cases"], int) and data["delivered_cases"] >= 0
    assert isinstance(data["stale_pulled_cases"], int) and data["stale_pulled_cases"] >= 0
    assert data["status"] in ("PLANNED", "LOADED", "IN_PROGRESS", "SETTLED", "CANCELLED")


def assert_truck_lot(data: dict):
    _assert_common(data, "TruckInventoryLot")
    assert is_valid_uuid(data.get("route_day_id", "")), "route_day_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert isinstance(data["expiration_date"], str)
    assert isinstance(data["loaded_cases"], int) and data["loaded_cases"] > 0
    assert isinstance(data["delivered_cases"], int) and data["delivered_cases"] >= 0
    assert isinstance(data["stale_pulled_cases"], int) and data["stale_pulled_cases"] >= 0
    assert isinstance(data["returned_cases"], int) and data["returned_cases"] >= 0
    assert data["status"] in ("SEALED", "OPEN", "CLOSED")


def assert_lot_conservation(lot: dict):
    """Lot conservation invariant: remaining == loaded - delivered - stale_pulled - returned."""
    remaining = lot.get("remaining_cases")
    expected = (
        lot["loaded_cases"]
        - lot["delivered_cases"]
        - lot["stale_pulled_cases"]
        - lot["returned_cases"]
    )
    assert remaining == expected, (
        f"lot conservation violated: remaining_cases {remaining} != "
        f"loaded {lot['loaded_cases']} - delivered {lot['delivered_cases']} "
        f"- stale_pulled {lot['stale_pulled_cases']} - returned {lot['returned_cases']}"
    )
    assert remaining >= 0, "remaining_cases must never be negative"


def assert_order(data: dict):
    _assert_common(data, "StoreOrder")
    assert is_valid_uuid(data.get("route_day_id", "")), "route_day_id must be a UUID"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert data["order_type"] in ("STANDARD", "EVENT_SURGE")
    assert data["status"] in ("DRAFT", "SUBMITTED", "DELIVERED", "CANCELLED")
    assert isinstance(data["gross_total_cents"], int) and data["gross_total_cents"] >= 0


def assert_order_line(data: dict):
    # OrderLine is an immutable sub-record: id + created_at only, no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), "OrderLine.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "OrderLine.created_at must be ISO 8601"
    )
    assert is_valid_uuid(data.get("order_id", "")), "order_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["qty_ordered_cases"], int) and data["qty_ordered_cases"] > 0
    assert isinstance(data["qty_delivered_cases"], int) and data["qty_delivered_cases"] >= 0
    assert isinstance(data["line_total_cents"], int) and data["line_total_cents"] >= 0
    assert isinstance(data["line_seq"], int) and data["line_seq"] >= 1


def assert_shelf_execution(data: dict):
    _assert_common(data, "ShelfExecution")
    assert is_valid_uuid(data.get("route_day_id", "")), "route_day_id must be a UUID"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["qty_placed_cases"], int) and data["qty_placed_cases"] >= 0
    assert isinstance(data["rotated"], bool)
    assert isinstance(data["display_built"], bool)
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["status"] in ("RECORDED", "VERIFIED", "REJECTED")


def assert_stale_credit(data: dict):
    _assert_common(data, "StaleCredit")
    assert is_valid_uuid(data.get("route_day_id", "")), "route_day_id must be a UUID"
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["qty_cases"], int) and data["qty_cases"] > 0
    assert data["pricing_variant"] in ("FULL_RETAIL", "SALVAGE_RATE")
    assert isinstance(data["credit_cents"], int) and data["credit_cents"] >= 0
    assert isinstance(data["created_by_user_id"], str) and data["created_by_user_id"]
    assert data["status"] in ("PENDING_APPROVAL", "APPROVED", "REJECTED")


def assert_promo_agreement(data: dict):
    _assert_common(data, "PromoAgreement")
    assert is_valid_uuid(data.get("store_id", "")), "store_id must be a UUID"
    assert is_valid_uuid(data.get("product_id", "")), "product_id must be a UUID"
    assert isinstance(data["window_start"], str)
    assert isinstance(data["window_end"], str)
    assert data["display_type"] in ("ENDCAP", "AISLE", "DUMP_BIN", "COUNTER")
    assert isinstance(data["rebate_cents"], int) and data["rebate_cents"] >= 0
    assert data["status"] in ("SCHEDULED", "ACTIVE", "COMPLETED", "BREACHED", "EXPIRED")


def assert_promo_execution(data: dict):
    _assert_common(data, "PromoExecution")
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert is_valid_uuid(data.get("route_day_id", "")), "route_day_id must be a UUID"
    assert isinstance(data["photo_url"], str) and data["photo_url"]
    assert isinstance(data["built_by_user_id"], str) and data["built_by_user_id"]
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED")


def assert_settlement(data: dict):
    _assert_common(data, "RouteSettlement")
    assert is_valid_uuid(data.get("route_day_id", "")), "route_day_id must be a UUID"
    assert data["status"] in ("OPEN", "BALANCED", "DISPUTED", "POSTED")
    assert isinstance(data["gross_delivered_cents"], int)
    assert isinstance(data["credits_cents"], int)
    assert isinstance(data["forward_expected_cents"], int)
    assert isinstance(data["chronological_expected_cents"], int)
    assert isinstance(data["recon_delta_cents"], int)


def assert_settlement_recon_invariants(data: dict):
    """Ledger identities that must hold on every settlement view."""
    assert (
        data["chronological_expected_cents"]
        == data["gross_delivered_cents"] - data["credits_cents"]
    ), "chronological variant must equal gross minus credits"
    assert (
        data["recon_delta_cents"]
        == data["forward_expected_cents"] - data["chronological_expected_cents"]
    ), "recon delta must equal forward minus chronological"


def assert_service_level_snapshot(data: dict):
    _assert_common(data, "ServiceLevelSnapshot")
    assert is_valid_uuid(data.get("route_id", "")), "route_id must be a UUID"
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["orders_count"], int) and data["orders_count"] >= 0
    assert data["service_grade"] in ("GOLD", "SILVER", "BRONZE")
    assert data["performance_flag_result"] in ("CLEAR", "PERFORMANCE_WATCH")
