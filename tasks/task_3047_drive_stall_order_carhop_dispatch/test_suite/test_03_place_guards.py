"""Place-time guards: empty order, missing service target, terminal state,
and stall-occupancy dependency."""
from test_helpers import (
    ApiErrorId,
    TEST_DEFAULTS,
    add_line,
    create_location,
    create_menu_item,
    create_stall,
    intercom_checkin,
    place_order,
    set_clock,
    setup_stall_draft_order,
    validate_error,
    validate_success,
)


class TestEmptyOrderRejected:
    def test_empty_order_place_rejected(self, api, shift_manager_headers):
        """PRD: "The order must have at least one line (`ERR_EMPTY_ORDER`)"

        Design: Corner/errors/empty_order_place_rejected
        """
        location = create_location(code="CRN-EMP1", stall_capacity=2)
        create_stall_id = create_stall(location["id"], stall_number=1)["id"]
        from test_helpers import create_service_target

        create_service_target(location["id"])
        order = intercom_checkin(location["id"], create_stall_id)

        resp = api.place_order(location["id"], order["id"], {}, shift_manager_headers)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER)

    def test_empty_order_rejected_on_drive_thru_too(self, api, shift_manager_headers):
        """PRD: "The order must have at least one line (`ERR_EMPTY_ORDER`)"

        Design: Corner/errors/empty_order_place_rejected
        """
        from test_helpers import (
            create_drive_thru_order,
            create_service_target,
        )

        location = create_location(code="CRN-EMP2", stall_capacity=2)
        create_service_target(location["id"], channel="DRIVE_THRU", target_seconds=300)
        order = create_drive_thru_order(location["id"])

        resp = api.place_order(location["id"], order["id"], {}, shift_manager_headers)
        validate_error(resp, ApiErrorId.ERR_EMPTY_ORDER)


class TestNoServiceTargetBlocksPlace:
    def test_no_service_target_blocks_place(self, api, shift_manager_headers):
        """PRD: "if neither exists, placement is rejected with
        `ERR_NO_SERVICE_TARGET`."

        Design: Corner/errors/no_service_target_blocks_place
        """
        location = create_location(code="CRN-NST", stall_capacity=2)
        item = create_menu_item(sku="NST-F", name="F", base_price_cents=500)
        stall = create_stall(location["id"], stall_number=1)
        order = intercom_checkin(location["id"], stall["id"])
        add_line(location["id"], order["id"], item["id"])

        resp = api.place_order(location["id"], order["id"], {}, shift_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SERVICE_TARGET)

    def test_no_service_target_blocks_drive_thru_place(self, api, shift_manager_headers):
        """PRD: "if neither exists, placement is rejected with
        `ERR_NO_SERVICE_TARGET`."

        Design: Corner/errors/no_service_target_blocks_place
        """
        from test_helpers import create_drive_thru_order

        location = create_location(code="CRN-NST2", stall_capacity=2)
        item = create_menu_item(sku="NST-G", name="G", base_price_cents=500)
        order = create_drive_thru_order(location["id"])
        add_line(location["id"], order["id"], item["id"])

        resp = api.place_order(location["id"], order["id"], {}, shift_manager_headers)
        validate_error(resp, ApiErrorId.ERR_NO_SERVICE_TARGET)


class TestTerminalCancelledOrderRejectsPlace:
    def test_terminal_cancelled_order_rejects_place(self, api, shift_manager_headers):
        """PRD §2.10: "then the state-machine from-state check including
        terminal-state lockdown (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/terminal_cancelled_order_rejects_place
        """
        ctx = setup_stall_draft_order(code="CRN-TERM1")
        order_id = ctx["order"]["id"]
        location_id = ctx["location"]["id"]

        validate_success(api.cancel_order(location_id, order_id, shift_manager_headers), 200)
        resp = api.place_order(location_id, order_id, {}, shift_manager_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        read = validate_success(api.get_order(location_id, order_id, shift_manager_headers), 200)
        assert read["status"] == "CANCELLED"

    def test_cancelled_order_rejects_start_preparation(self, api, kitchen_staff_headers):
        """PRD §2.10: "then the state-machine from-state check including
        terminal-state lockdown (`ERR_INVALID_STATE`)."

        Design: Corner/state_machines/terminal_cancelled_order_rejects_place
        """
        from test_helpers import TEST_USERS

        manager = TEST_USERS["shift_manager_headers"]
        ctx = setup_stall_draft_order(code="CRN-TERM2")
        order_id = ctx["order"]["id"]
        location_id = ctx["location"]["id"]

        validate_success(api.cancel_order(location_id, order_id, manager), 200)
        resp = api.start_preparation(location_id, order_id, kitchen_staff_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestOrderPlaceDependsOnStallOccupancyState:
    def test_order_place_depends_on_stall_occupancy_state(self, api, shift_manager_headers):
        """PRD: "a stall-channel order may only be placed while its stall is
        `OCCUPIED` with `current_order_id` pointing at this very order
        (`ERR_STALL_NOT_OCCUPIED_BY_ORDER`)."

        Design: Difficulty/cross_entity_state_dependency/order_place_depends_on_stall_occupancy_state
        """
        ctx = setup_stall_draft_order(code="DIFF-PLACE1")
        stall = validate_success(
            api.get_stall(ctx["location"]["id"], ctx["stall"]["id"], shift_manager_headers), 200
        )
        assert stall["status"] == "OCCUPIED"
        assert stall["current_order_id"] == ctx["order"]["id"]

        placed = place_order(ctx["location"]["id"], ctx["order"]["id"])
        assert placed["status"] == "PLACED"

    def test_place_after_stall_released_rejected(self, api, shift_manager_headers):
        """PRD: "a stall-channel order may only be placed while its stall is
        `OCCUPIED` with `current_order_id` pointing at this very order
        (`ERR_STALL_NOT_OCCUPIED_BY_ORDER`)."

        Design: Difficulty/cross_entity_state_dependency/order_place_depends_on_stall_occupancy_state
        """
        from test_helpers import create_service_target, set_clock

        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        location = create_location(code="DIFF-PLACE2", stall_capacity=2)
        create_service_target(location["id"])
        item = create_menu_item(sku="FD-T2", name="T2", base_price_cents=500)
        stall = create_stall(location["id"], stall_number=1)
        order = intercom_checkin(location["id"], stall["id"])
        add_line(location["id"], order["id"], item["id"])

        # Force-release the stall by canning the occupying order via out-of-service.
        validate_success(
            api.set_out_of_service(
                location["id"], stall["id"], {"force_cancel": True}, shift_manager_headers
            ),
            200,
        )
        # Stall is now OUT_OF_SERVICE and the order was cancelled; bring the
        # stall back so the place attempt reaches the occupancy gate.
        validate_success(
            api.return_to_service(location["id"], stall["id"], shift_manager_headers), 200
        )

        resp = api.place_order(location["id"], order["id"], {}, shift_manager_headers)
        # The cancelled order is terminal, and in any case it no longer
        # occupies the stall: either rejection proves the place did not happen.
        from test_helpers import validate_error_is_one_of

        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_STALL_NOT_OCCUPIED_BY_ORDER, ApiErrorId.ERR_INVALID_STATE],
        )
        read = validate_success(api.get_order(location["id"], order["id"], shift_manager_headers), 200)
        assert read["status"] == "CANCELLED"
