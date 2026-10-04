"""Delivery dispatch: run sequencing, payment gating, delivery cascades, and
run-void compensation."""
from test_helpers import (
    TEST_DEFAULTS,
    TEST_USERS,
    ApiErrorId,
    add_line,
    create_carhop,
    create_location,
    create_menu_item,
    create_service_target,
    create_stall,
    intercom_checkin,
    make_carhop_headers,
    place_and_ready,
    authorize_and_capture,
    set_clock,
    setup_out_for_delivery,
    setup_ready_order_on_stall,
    setup_captured_ready_order,
    stage_run,
    depart_run,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["shift_manager_headers"]


def _second_ready_order(location_id, item_id, stall_number=4):
    """Check in a second stall, add one line, place, and ready the order."""
    stall = create_stall(location_id, stall_number=stall_number)
    order = intercom_checkin(location_id, stall["id"])
    add_line(location_id, order["id"], item_id)
    ready = place_and_ready(location_id, order["id"])
    authorize_and_capture(location_id, order["id"])
    return stall, ready


class TestRunSequenceViolation:
    def test_deliver_out_of_run_position_order_rejected(self, api):
        """PRD: "Delivering an order requires the order's payment to be
        `CAPTURED` (`ERR_PAYMENT_NOT_CAPTURED` otherwise) and requires that
        every order on the same run with a smaller `run_position` already be
        `DELIVERED` or `CANCELLED` — skipping ahead in the route is rejected
        with `ERR_RUN_SEQUENCE_VIOLATION`."

        On a two-order run, delivering the position-2 order first is rejected.

        Design: Corner/state_machines/deliver_out_of_run_position_order_rejected
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_captured_ready_order(code="CRN-SEQ1", item_price=500, stall_capacity=4)
        location_id = ctx["location"]["id"]
        _, second = _second_ready_order(location_id, ctx["item"]["id"])

        run = stage_run(
            location_id, ctx["carhop"], order_ids=[ctx["order"]["id"], second["id"]]
        )
        depart_run(location_id, run["id"], ctx["carhop"]["id"])

        # Determine which order holds run_position 2, then try to deliver it first.
        first_order = validate_success(
            api.get_order(location_id, ctx["order"]["id"], MANAGER), 200
        )
        second_order = validate_success(api.get_order(location_id, second["id"], MANAGER), 200)
        ahead = second_order if second_order["run_position"] == 2 else first_order

        resp = api.deliver_order(
            location_id, run["id"], ahead["id"], make_carhop_headers(ctx["carhop"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RUN_SEQUENCE_VIOLATION)
        still_out = validate_success(api.get_order(location_id, ahead["id"], MANAGER), 200)
        assert still_out["status"] == "OUT_FOR_DELIVERY"

    def test_in_sequence_delivery_succeeds_after_earlier_position_delivered(self, api):
        """PRD: "Delivering an order requires the order's payment to be
        `CAPTURED` (`ERR_PAYMENT_NOT_CAPTURED` otherwise) and requires that
        every order on the same run with a smaller `run_position` already be
        `DELIVERED` or `CANCELLED`"

        Delivering position 1 then position 2 succeeds in order, and both
        orders reach DELIVERED.

        Design: Corner/state_machines/deliver_out_of_run_position_order_rejected
        """
        from test_helpers import deliver_order

        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_captured_ready_order(code="CRN-SEQ2", item_price=500, stall_capacity=4)
        location_id = ctx["location"]["id"]
        _, second = _second_ready_order(location_id, ctx["item"]["id"])

        run = stage_run(
            location_id, ctx["carhop"], order_ids=[ctx["order"]["id"], second["id"]]
        )
        depart_run(location_id, run["id"], ctx["carhop"]["id"])

        first_order = validate_success(
            api.get_order(location_id, ctx["order"]["id"], MANAGER), 200
        )
        second_order = validate_success(api.get_order(location_id, second["id"], MANAGER), 200)
        ordered = sorted([first_order, second_order], key=lambda o: o["run_position"])

        for order in ordered:
            delivered = deliver_order(location_id, run["id"], order["id"], ctx["carhop"]["id"])
            assert delivered["status"] == "DELIVERED"

        run_after = validate_success(api.get_delivery_run(location_id, run["id"], MANAGER), 200)
        assert run_after["status"] == "COMPLETED"


class TestDeliverDependsOnPaymentAxis:
    def test_deliver_depends_on_payment_axis_and_run_sequence(self, api):
        """PRD: "Delivering an order requires the order's payment to be
        `CAPTURED` (`ERR_PAYMENT_NOT_CAPTURED` otherwise)"

        An OUT_FOR_DELIVERY order whose payment is still AUTHORIZED cannot be
        delivered; the fulfillment transition is gated by the payment axis.

        Design: Difficulty/cross_entity_state_dependency/deliver_depends_on_payment_axis_and_run_sequence
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_ready_order_on_stall(code="DIFF-PAY1", item_price=500)
        location_id = ctx["location"]["id"]
        # Authorize but do NOT capture.
        validate_success(
            api.authorize_payment(location_id, ctx["order"]["id"], MANAGER), 200
        )
        run = stage_run(location_id, ctx["carhop"], order_ids=[ctx["order"]["id"]])
        depart_run(location_id, run["id"], ctx["carhop"]["id"])

        resp = api.deliver_order(
            location_id, run["id"], ctx["order"]["id"],
            make_carhop_headers(ctx["carhop"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED)

        order = validate_success(api.get_order(location_id, ctx["order"]["id"], MANAGER), 200)
        assert order["status"] == "OUT_FOR_DELIVERY"
        assert order["payment_status"] == "AUTHORIZED"

    def test_deliver_with_unpaid_order_also_rejected(self, api):
        """PRD: "Delivering an order requires the order's payment to be
        `CAPTURED` (`ERR_PAYMENT_NOT_CAPTURED` otherwise)"

        An order that never authorized payment at all is equally undeliverable.

        Design: Difficulty/cross_entity_state_dependency/deliver_depends_on_payment_axis_and_run_sequence
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_ready_order_on_stall(code="DIFF-PAY2", item_price=500)
        location_id = ctx["location"]["id"]
        run = stage_run(location_id, ctx["carhop"], order_ids=[ctx["order"]["id"]])
        depart_run(location_id, run["id"], ctx["carhop"]["id"])

        resp = api.deliver_order(
            location_id, run["id"], ctx["order"]["id"],
            make_carhop_headers(ctx["carhop"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_PAYMENT_NOT_CAPTURED)

        order = validate_success(api.get_order(location_id, ctx["order"]["id"], MANAGER), 200)
        assert order["status"] == "OUT_FOR_DELIVERY"
        assert order["payment_status"] == "UNPAID"


class TestDeliverCascade:
    def test_deliver_cascades_stall_posture_run_completion_carhop_load(self, api):
        """PRD: "A successful delivery stamps `delivered_at`, computes
        `late_flag` as in §3.5, and, when the delivered order is its stall's
        current order (channels `STALL_INTERCOM`, `APP_CHECKIN`, and `PATIO`),
        clears the stall's `current_order_id` and returns the stall to `IDLE`,
        after which `stalls_available` and `lane_posture` are recomputed.
        When the last open order on a run resolves — every order `DELIVERED`
        or `CANCELLED` — the run completes automatically (`OUT` → `COMPLETED`)
        and the carhop's `active_run_load` decreases by the run's
        `order_count`."

        A capacity-2 location sits CONGESTED with one stall out on a run;
        delivery flips the stall IDLE, the lane OPEN, completes the run, and
        returns the carhop's load to 0.

        Design: Difficulty/transitive_cascade/deliver_cascades_stall_posture_run_completion_carhop_load
        """
        from test_helpers import deliver_order

        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_out_for_delivery(
            code="DIFF-CASC1", item_price=500, stall_capacity=2,
            carhop_name="Hop B", carhop_zone="NORTH",
        )
        location_id = ctx["location"]["id"]

        location_mid = validate_success(api.get_location(location_id, MANAGER), 200)
        assert location_mid["stalls_available"] == 1
        assert location_mid["lane_posture"] == "CONGESTED"

        delivered = deliver_order(
            location_id, ctx["run"]["id"], ctx["order"]["id"], ctx["carhop"]["id"]
        )
        assert delivered["status"] == "DELIVERED"

        stall_after = validate_success(
            api.get_stall(location_id, ctx["stall"]["id"], MANAGER), 200
        )
        assert stall_after["status"] == "IDLE"
        assert stall_after["current_order_id"] is None

        location_after = validate_success(api.get_location(location_id, MANAGER), 200)
        assert location_after["stalls_available"] == 2
        assert location_after["lane_posture"] == "OPEN"

        run_after = validate_success(
            api.get_delivery_run(location_id, ctx["run"]["id"], MANAGER), 200
        )
        assert run_after["status"] == "COMPLETED"

        carhop_after = validate_success(
            api.get_carhop(location_id, ctx["carhop"]["id"], MANAGER), 200
        )
        assert carhop_after["active_run_load"] == 0

    def test_deliver_stamps_delivered_at_and_computes_late_flag(self, api):
        """PRD: "A successful delivery stamps `delivered_at`, computes
        `late_flag` as in §3.5"

        A delivery made within the same logical instant as placement has zero
        elapsed seconds against a 600s target, so late_flag is false and
        delivered_at equals placed_at.

        Design: Difficulty/transitive_cascade/deliver_cascades_stall_posture_run_completion_carhop_load
        """
        from test_helpers import deliver_order

        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_out_for_delivery(
            code="DIFF-CASC2", item_price=500, stall_capacity=2,
            carhop_name="Hop B2", carhop_zone="NORTH", target_seconds=600,
        )
        location_id = ctx["location"]["id"]

        delivered = deliver_order(
            location_id, ctx["run"]["id"], ctx["order"]["id"], ctx["carhop"]["id"]
        )
        assert delivered["status"] == "DELIVERED"
        assert delivered["delivered_at"] is not None
        assert delivered["placed_at"] is not None
        assert delivered["delivered_at"] == delivered["placed_at"]
        assert delivered["late_flag"] is False
        assert delivered["service_target_seconds"] == 600


class TestRunVoidCompensation:
    def test_run_void_restores_carhop_load_and_order_readiness(self, api):
        """PRD: "Voiding a `LOADED` run moves it to `VOIDED`, strips every
        staged order of its `delivery_run_id` and `run_position` while leaving
        each in `READY`, and decrements the carhop's `active_run_load` by the
        run's `order_count`."

        Staging raises the carhop's load to 1; voiding returns it to 0 and
        leaves the order READY and unstaged.

        Design: Difficulty/compensating_invariant/run_void_restores_carhop_load_and_order_readiness
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_ready_order_on_stall(code="DIFF-VOID1", item_price=500)
        location_id = ctx["location"]["id"]

        run = stage_run(location_id, ctx["carhop"], order_ids=[ctx["order"]["id"]])
        carhop_mid = validate_success(
            api.get_carhop(location_id, ctx["carhop"]["id"], MANAGER), 200
        )
        assert carhop_mid["active_run_load"] == 1

        validate_success(api.void_run(location_id, run["id"], MANAGER), 200)

        carhop_after = validate_success(
            api.get_carhop(location_id, ctx["carhop"]["id"], MANAGER), 200
        )
        assert carhop_after["active_run_load"] == 0

        order_after = validate_success(
            api.get_order(location_id, ctx["order"]["id"], MANAGER), 200
        )
        assert order_after["status"] == "READY"
        assert order_after["delivery_run_id"] is None
        assert order_after["run_position"] is None

    def test_voided_run_is_terminal_and_reports_voided(self, api):
        """PRD: "Voiding a `LOADED` run moves it to `VOIDED`, strips every
        staged order of its `delivery_run_id` and `run_position` while leaving
        each in `READY`, and decrements the carhop's `active_run_load` by the
        run's `order_count`."

        The voided run itself reports VOIDED and its order is free to be
        staged onto a fresh run.

        Design: Difficulty/compensating_invariant/run_void_restores_carhop_load_and_order_readiness
        """
        set_clock(TEST_DEFAULTS["CLOCK_0800_LOCAL"])
        ctx = setup_ready_order_on_stall(code="DIFF-VOID2", item_price=500)
        location_id = ctx["location"]["id"]

        run = stage_run(location_id, ctx["carhop"], order_ids=[ctx["order"]["id"]])
        voided = validate_success(api.void_run(location_id, run["id"], MANAGER), 200)
        assert voided["status"] == "VOIDED"

        # The order is READY again and can be staged on a new run.
        run_two = stage_run(location_id, ctx["carhop"], order_ids=[ctx["order"]["id"]])
        assert run_two["status"] == "LOADED"
        assert run_two["id"] != run["id"]
        order_after = validate_success(
            api.get_order(location_id, ctx["order"]["id"], MANAGER), 200
        )
        assert order_after["delivery_run_id"] == run_two["id"]
