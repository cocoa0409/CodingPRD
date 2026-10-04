"""Stall cyclic lifecycle, equipment-fault cascades, and weather gates."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    assert_stall,
    create_location,
    create_stall,
    intercom_checkin,
    make_carhop_headers,
    set_clock,
    setup_delivered_order,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]
CARHOP = TEST_USERS["carhop_headers"]


class TestStallCyclicLoop:
    def test_stall_cyclic_occupied_idle_out_of_service_loop(self, api):
        """PRD: "Returning a stall to service requires a clean bill of health:
        any `OPEN` fault on the stall blocks the return with
        `ERR_FAULT_STILL_OPEN`, and a successful return moves the stall back
        to `IDLE`, restores `intercom_functional` to true, and recomputes
        `stalls_available`."

        The same stall completes a full occupancy cycle (order delivered),
        faults out via a MENU_BOARD_DEAD report, is resolved, returns to
        service, and ends IDLE with a working intercom and no current order.

        Design: Difficulty/non_linear_state_machine/stall_cyclic_occupied_idle_out_of_service_loop
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_delivered_order(
            code="DIFF-CYCLE1", item_price=500, stall_capacity=2,
            carhop_name="Hop A", carhop_zone="NORTH",
        )
        location_id = ctx["location"]["id"]
        stall_id = ctx["stall"]["id"]
        carhop_id = ctx["carhop"]["id"]

        # Delivery released the stall: first cycle OCCUPIED -> IDLE done.
        stall = validate_success(api.get_stall(location_id, stall_id, MANAGER), 200)
        assert stall["status"] == "IDLE"
        assert stall["current_order_id"] is None

        # Fault the stall out (menu board dead drives it OUT_OF_SERVICE).
        fault = validate_success(
            api.report_fault(
                location_id, stall_id,
                {"kind": "MENU_BOARD_DEAD", "note": "board dark", "reported_by_role": "CARHOP"},
                make_carhop_headers(carhop_id),
            ),
            201,
        )
        stall = validate_success(api.get_stall(location_id, stall_id, MANAGER), 200)
        assert stall["status"] == "OUT_OF_SERVICE"
        assert stall["intercom_functional"] is False

        validate_success(api.resolve_fault(location_id, stall_id, fault["id"], MANAGER), 200)
        returned = validate_success(
            api.return_to_service(location_id, stall_id, MANAGER), 200
        )
        assert returned["status"] == "IDLE"
        assert returned["intercom_functional"] is True
        assert returned["current_order_id"] is None

    def test_stall_accepts_new_checkin_after_full_cycle(self, api):
        """PRD: "A guest visit begins at check-in... Intercom check-in
        requires the stall to be `IDLE`"

        After a full OCCUPIED -> IDLE -> OUT_OF_SERVICE -> IDLE cycle the same
        stall accepts a fresh intercom check-in, proving the cyclic machine is
        not a one-shot pipeline.

        Design: Difficulty/non_linear_state_machine/stall_cyclic_occupied_idle_out_of_service_loop
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_delivered_order(
            code="DIFF-CYCLE2", item_price=500, stall_capacity=2,
            carhop_name="Hop A2", carhop_zone="NORTH",
        )
        location_id = ctx["location"]["id"]
        stall_id = ctx["stall"]["id"]
        carhop_id = ctx["carhop"]["id"]

        fault = validate_success(
            api.report_fault(
                location_id, stall_id,
                {"kind": "MENU_BOARD_DEAD", "note": "board dark", "reported_by_role": "CARHOP"},
                make_carhop_headers(carhop_id),
            ),
            201,
        )
        validate_success(api.resolve_fault(location_id, stall_id, fault["id"], MANAGER), 200)
        validate_success(api.return_to_service(location_id, stall_id, MANAGER), 200)

        second_order = intercom_checkin(location_id, stall_id)
        assert second_order["status"] == "DRAFT"
        assert second_order["channel"] == "STALL_INTERCOM"
        stall = validate_success(api.get_stall(location_id, stall_id, MANAGER), 200)
        assert stall["status"] == "OCCUPIED"
        assert stall["current_order_id"] == second_order["id"]


class TestMenuBoardFaultCascade:
    def test_menu_board_fault_cascades_stall_out_of_service_posture(self, api):
        """PRD: "Every open fault flips the stall's `intercom_functional` to
        false — the speaker is presumed untrustworthy until proven repaired —
        and a `MENU_BOARD_DEAD` fault additionally drives the stall straight
        to `OUT_OF_SERVICE` with `stalls_available` recomputed."

        A one-stall location loses its only stall to a menu-board fault:
        stalls_available drops to 0 and the lane goes CURBSIDE_ONLY.

        Design: Difficulty/transitive_cascade/menu_board_fault_cascades_stall_out_of_service_posture
        """
        from test_helpers import create_carhop

        location = create_location(code="DIFF-FAULT1", stall_capacity=1)
        stall = create_stall(location["id"], stall_number=1)
        carhop = create_carhop(location["id"], name="Hop C")

        validate_success(
            api.report_fault(
                location["id"], stall["id"],
                {"kind": "MENU_BOARD_DEAD", "note": "dead board", "reported_by_role": "CARHOP"},
                make_carhop_headers(carhop["id"]),
            ),
            201,
        )
        stall_after = validate_success(api.get_stall(location["id"], stall["id"], MANAGER), 200)
        assert stall_after["status"] == "OUT_OF_SERVICE"
        assert stall_after["intercom_functional"] is False

        location_after = validate_success(api.get_location(location["id"], MANAGER), 200)
        assert location_after["stalls_available"] == 0
        assert location_after["lane_posture"] == "CURBSIDE_ONLY"

    def test_intercom_fault_alone_keeps_stall_idle_but_disables_intercom(self, api):
        """PRD: "Every open fault flips the stall's `intercom_functional` to
        false — the speaker is presumed untrustworthy until proven repaired —
        and a `MENU_BOARD_DEAD` fault additionally drives the stall straight
        to `OUT_OF_SERVICE` with `stalls_available` recomputed."

        An INTERCOM_DEAD fault disables the intercom but leaves an IDLE stall
        in service: stalls_available stays at capacity and the lane stays OPEN.

        Design: Difficulty/transitive_cascade/menu_board_fault_cascades_stall_out_of_service_posture
        """
        from test_helpers import create_carhop

        # Capacity 5 keeps the lane OPEN: after the fault every stall remains
        # IDLE, so stalls_available stays 5, and the CONGESTED threshold is
        # ceil(5 * 0.20) = 1 (PRD 2.4: "less than or equal to the stall
        # capacity multiplied by 0.20 and rounded up").
        location = create_location(code="DIFF-FAULT2", stall_capacity=5)
        stall = create_stall(location["id"], stall_number=1)
        carhop = create_carhop(location["id"], name="Hop C2")

        validate_success(
            api.report_fault(
                location["id"], stall["id"],
                {"kind": "INTERCOM_DEAD", "note": "speaker dead", "reported_by_role": "CARHOP"},
                make_carhop_headers(carhop["id"]),
            ),
            201,
        )
        stall_after = validate_success(api.get_stall(location["id"], stall["id"], MANAGER), 200)
        assert stall_after["status"] == "IDLE"
        assert stall_after["intercom_functional"] is False

        location_after = validate_success(api.get_location(location["id"], MANAGER), 200)
        assert location_after["stalls_available"] == 5
        assert location_after["lane_posture"] == "OPEN"


class TestHeatAdvisoryPatioGate:
    def test_weather_heat_advisory_blocks_patio_checkin(self, api, shift_manager_headers):
        """PRD: "A `HEAT_ADVISORY` closes every patio position to new
        check-ins, rejected with `ERR_STALL_WEATHER_CLOSED`."

        Design: Corner/cross_cutting_layers/weather_heat_advisory_blocks_patio_checkin
        """
        location = create_location(code="CRN-WX1", stall_capacity=2)
        patio = create_stall(location["id"], stall_number=9, kind="PATIO")
        validate_success(
            api.set_weather(location["id"], {"weather_mode": "HEAT_ADVISORY"}, shift_manager_headers),
            200,
        )
        version = validate_success(api.get_location(location["id"], shift_manager_headers), 200)[
            "version"
        ]
        resp = api.checkin(
            location["id"], patio["id"],
            {"expected_location_version": version},
            shift_manager_headers,
        )
        validate_error(resp, ApiErrorId.ERR_STALL_WEATHER_CLOSED)

    def test_heat_advisory_still_admits_drive_in_stall_checkin(self, api, shift_manager_headers):
        """PRD: "A `HEAT_ADVISORY` closes every patio position to new
        check-ins, rejected with `ERR_STALL_WEATHER_CLOSED`."

        The same advisory leaves drive-in stalls open: an intercom check-in at
        a STALL succeeds under HEAT_ADVISORY.

        Design: Corner/cross_cutting_layers/weather_heat_advisory_blocks_patio_checkin
        """
        location = create_location(code="CRN-WX2", stall_capacity=2)
        drive_in = create_stall(location["id"], stall_number=1, kind="STALL")
        validate_success(
            api.set_weather(location["id"], {"weather_mode": "HEAT_ADVISORY"}, shift_manager_headers),
            200,
        )
        order = intercom_checkin(location["id"], drive_in["id"])
        assert order["status"] == "DRAFT"
        assert order["channel"] == "STALL_INTERCOM"
        stall = validate_success(
            api.get_stall(location["id"], drive_in["id"], shift_manager_headers), 200
        )
        assert_stall(stall)
        assert stall["status"] == "OCCUPIED"
