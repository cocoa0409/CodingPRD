"""Menu/catalog integrity: retired items and size-option requirements."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_location,
    create_menu_item,
    create_service_target,
    create_stall,
    intercom_checkin,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestRetiredMenuItemRejected:
    def test_menu_item_retire_then_add_line_rejected(self, api, platform_admin_headers):
        """PRD: "retiring one flips its `status` to `RETIRED`, after which it
        cannot be added to new orders or placed, though it remains visible on
        historical orders."

        Design: Corner/entities/menu_item_retire_then_add_line_rejected
        """
        location = create_location(code="CRN-01A", stall_capacity=2)
        shift_manager_headers = TEST_USERS["shift_manager_headers"]
        create_service_target(location["id"])
        item = create_menu_item(sku="RET-1", name="Retired", base_price_cents=500)
        validate_success(api.retire_menu_item(item["id"], platform_admin_headers), 200)
        stall = create_stall(location["id"], stall_number=1)
        order = intercom_checkin(location["id"], stall["id"])

        resp = api.add_order_line(
            location["id"], order["id"],
            {"menu_item_id": item["id"], "quantity": 1},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MENU_ITEM_RETIRED)

    def test_retired_item_rejected_even_with_quantity_above_one(
        self, api, platform_admin_headers
    ):
        """PRD: "retiring one flips its `status` to `RETIRED`, after which it
        cannot be added to new orders or placed, though it remains visible on
        historical orders."

        Design: Corner/entities/menu_item_retire_then_add_line_rejected
        """
        location = create_location(code="CRN-01B", stall_capacity=2)
        shift_manager_headers = TEST_USERS["shift_manager_headers"]
        create_service_target(location["id"])
        item = create_menu_item(sku="RET-2", name="Retired Too", base_price_cents=500)
        validate_success(api.retire_menu_item(item["id"], platform_admin_headers), 200)
        stall = create_stall(location["id"], stall_number=1)
        order = intercom_checkin(location["id"], stall["id"])

        resp = api.add_order_line(
            location["id"], order["id"],
            {"menu_item_id": item["id"], "quantity": 3},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_MENU_ITEM_RETIRED)


class TestSizeRequired:
    def test_size_required_for_drink_sizes_item(self, api, shift_manager_headers):
        """PRD: "When the menu item's `size_scheme` is `DRINK_SIZES`, the line
        must also carry a `size_option_code` naming a size option; omitting it
        is rejected with `ERR_SIZE_REQUIRED` (HTTP 422)."

        Design: Corner/entities/size_required_for_drink_sizes_item
        """
        location = create_location(code="CRN-02A", stall_capacity=2)
        create_service_target(location["id"])
        item = create_menu_item(
            sku="SIZED", name="Sized Drink", category="DRINK",
            base_price_cents=300, size_scheme="DRINK_SIZES",
        )
        stall = create_stall(location["id"], stall_number=1)
        order = intercom_checkin(location["id"], stall["id"])

        resp = api.add_order_line(
            location["id"], order["id"],
            {"menu_item_id": item["id"], "quantity": 1},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_SIZE_REQUIRED)

    def test_drink_sizes_item_with_size_option_accepted(self, api, shift_manager_headers):
        """PRD: "When the menu item's `size_scheme` is `DRINK_SIZES`, the line
        must also carry a `size_option_code` naming a size option; omitting it
        is rejected with `ERR_SIZE_REQUIRED` (HTTP 422)."

        Design: Corner/entities/size_required_for_drink_sizes_item
        """
        location = create_location(code="CRN-02B", stall_capacity=2)
        create_service_target(location["id"])
        item = create_menu_item(
            sku="SIZED-OK", name="Sized Drink OK", category="DRINK",
            base_price_cents=300, size_scheme="DRINK_SIZES",
        )
        validate_success(
            api.create_customization_option(
                {
                    "code": "L",
                    "applies_to_category": "ANY",
                    "price_cents": 0,
                    "is_size": True,
                    "size_upcharge_cents": 80,
                },
                ADMIN,
            ),
            201,
        )
        stall = create_stall(location["id"], stall_number=1)
        order = intercom_checkin(location["id"], stall["id"])

        resp = api.add_order_line(
            location["id"], order["id"],
            {"menu_item_id": item["id"], "quantity": 1, "size_option_code": "L"},
            shift_manager_headers,
        )
        line = validate_success(resp, expected_status=201)
        assert line["unit_price_cents"] == 300 + 80
        assert line["extended_price_cents"] == 380
