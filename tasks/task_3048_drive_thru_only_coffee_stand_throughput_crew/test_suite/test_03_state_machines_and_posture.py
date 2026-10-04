"""Stand posture lifecycle, handoff side effects and preconditions, shift
terminal lockdown, distribution cycling, and the order's parallel dimensions."""
from test_helpers import (
    ApiErrorId,
    add_recipe,
    authorize_order,
    build_item_ready,
    create_loyalty_account,
    list_items_of_order,
    make_crew_member_headers,
    make_loyalty_customer_headers,
    make_shift_lead_headers,
    make_stand_operator_headers,
    place_app_order,
    place_window_order,
    serve_window_order,
    setup_open_stand_with_menu,
    stand_version,
    validate_error,
    validate_success,
)


class TestStandTerminalPosture:
    def test_closed_stand_is_terminal_and_rejects_resume(self, api):
        """PRD §3.1: "Permanent closure is also the operator's call, from either
        `OPEN` or `THROTTLED`, but only when the queue is fully drained: if any
        order at the stand still has `queue_status` of `QUEUED`, `MERGED`, or
        `AT_WINDOW`, the close is rejected with `ERR_STAND_INVALID_TRANSITION`.
        `CLOSED` is terminal."
        PRD §2.5: "Any guard on a stand transition that is violated — an action
        attempted from the wrong posture, or a close attempted while cars are
        still in the queue — is rejected with `ERR_STAND_INVALID_TRANSITION`."

        Design: Corner/state_machines/closed_stand_is_terminal_and_rejects_resume
        """
        ctx = setup_open_stand_with_menu()
        op_headers = ctx["operator_headers"]
        closed = validate_success(api.close_stand(ctx["stand"]["id"], op_headers), 200)
        assert closed["status"] == "CLOSED"

        resume = api.resume_stand(
            ctx["stand"]["id"], make_shift_lead_headers(ctx["op"]["id"])
        )
        validate_error(resume, ApiErrorId.ERR_STAND_INVALID_TRANSITION, 409)

        reopen = api.open_stand(ctx["stand"]["id"], op_headers)
        validate_error(reopen, ApiErrorId.ERR_STAND_INVALID_TRANSITION, 409)

    def test_closed_stand_rejects_throttle_as_well(self, api):
        """PRD §3.1: "`CLOSED` is terminal."

        Design: Corner/state_machines/closed_stand_is_terminal_and_rejects_resume
        """
        ctx = setup_open_stand_with_menu()
        validate_success(api.close_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200)
        throttle = api.throttle_stand(
            ctx["stand"]["id"], make_shift_lead_headers(ctx["lead"]["id"])
        )
        validate_error(throttle, ApiErrorId.ERR_STAND_INVALID_TRANSITION, 409)
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["status"] == "CLOSED"

    def test_stand_close_blocked_while_queue_not_drained(self, api):
        """PRD §3.1: "Permanent closure is also the operator's call, from either
        `OPEN` or `THROTTLED`, but only when the queue is fully drained: if any
        order at the stand still has `queue_status` of `QUEUED`, `MERGED`, or
        `AT_WINDOW`, the close is rejected with `ERR_STAND_INVALID_TRANSITION`."

        Design: Corner/state_machines/stand_close_blocked_while_queue_not_drained
        """
        ctx = setup_open_stand_with_menu()
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        resp = api.close_stand(ctx["stand"]["id"], ctx["operator_headers"])
        validate_error(resp, ApiErrorId.ERR_STAND_INVALID_TRANSITION, 409)
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["status"] == "OPEN", "the blocked close must leave the stand OPEN"

    def test_stand_close_succeeds_after_queue_drains(self, api):
        """PRD §3.1: "Permanent closure is also the operator's call, from either
        `OPEN` or `THROTTLED`, but only when the queue is fully drained"

        Design: Corner/state_machines/stand_close_blocked_while_queue_not_drained
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.abandon_order(order["id"], lead), 200)
        closed = validate_success(
            api.close_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert closed["status"] == "CLOSED"


class TestHandoffLifecycle:
    def test_handoff_side_effects_fire_in_full(self, api):
        """PRD §3.8: "A successful handoff stamps `handoff_at` with the current
        logical clock — the timestamp that later feeds throughput windows and
        royalty attribution — moves `build_status` to `HANDED_OFF`, and releases
        the lane slot, decrementing the stand's `lane_occupancy` for that lane."

        Design: Corner/state_machines/handoff_side_effects_fire_in_full
        """
        from test_helpers import set_clock

        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        for item in list_items_of_order(ctx, order["id"]):
            build_item_ready(ctx, item["id"])
        payment = authorize_order(ctx, order["id"])
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.call_to_window(order["id"], lead), 200)
        validate_success(api.capture_payment(payment["id"], lead), 200)
        set_clock("2026-09-01T07:30:00Z")
        handed = validate_success(api.handoff_order(order["id"], lead), 200)
        assert handed["queue_status"] == "SERVED"
        assert handed["build_status"] == "HANDED_OFF"
        assert handed["handoff_at"] == "2026-09-01T07:30:00Z", (
            f"handoff_at must be the logical clock, got {handed['handoff_at']}"
        )
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], lead), 200
        )
        assert stand["lane_occupancy"].get("A", 0) == 0, "slot released"

    def test_handoff_sets_all_terminal_dimensions(self, api):
        """PRD §3.8: "Queue advancement and handoff belong to the `ShiftLead`.
        Calling a `MERGED` order to the window moves it `MERGED → AT_WINDOW`.
        Handoff is the terminal act, `AT_WINDOW → SERVED`"

        Design: Corner/state_machines/handoff_side_effects_fire_in_full
        """
        ctx = setup_open_stand_with_menu()
        served = serve_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        order = served["order"]
        assert order["queue_status"] == "SERVED"
        assert order["build_status"] == "HANDED_OFF"
        assert order["handoff_at"] is not None
        payment = validate_success(
            api.get_payment(served["payment"]["id"], make_shift_lead_headers(ctx["lead"]["id"])),
            200,
        )
        assert payment["status"] == "CAPTURED"

    def test_handoff_without_capture_rejected(self, api):
        """PRD §3.8: "Handoff is the terminal act, `AT_WINDOW → SERVED`, and it
        demands both money and product: the order's `payment_status` must be
        `CAPTURED` (otherwise `ERR_PAYMENT_INVALID_STATE`) and its `build_status`
        must be `READY` (otherwise `ERR_ORDER_INVALID_STATE`)."

        Design: Corner/state_machines/handoff_without_capture_rejected
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        for item in list_items_of_order(ctx, order["id"]):
            build_item_ready(ctx, item["id"])
        authorize_order(ctx, order["id"])  # AUTHORIZED, never captured
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.call_to_window(order["id"], lead), 200)
        resp = api.handoff_order(order["id"], lead)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID_STATE, 409)
        order_after = validate_success(api.get_order(order["id"], lead), 200)
        assert order_after["queue_status"] == "AT_WINDOW"

    def test_handoff_with_unpaid_order_also_rejected(self, api):
        """PRD §3.8: "the order's `payment_status` must be `CAPTURED` (otherwise
        `ERR_PAYMENT_INVALID_STATE`)"

        Design: Corner/state_machines/handoff_without_capture_rejected
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        for item in list_items_of_order(ctx, order["id"]):
            build_item_ready(ctx, item["id"])
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.call_to_window(order["id"], lead), 200)
        resp = api.handoff_order(order["id"], lead)
        validate_error(resp, ApiErrorId.ERR_PAYMENT_INVALID_STATE, 409)


class TestPaymentCreationNonIdempotent:
    def test_second_authorize_on_paid_order_is_rejected(self, api):
        """PRD §3.7: "Authorization creates the order's single `Payment` —
        exactly one per order, bound to it by the payment's `order_id` — for the
        order's current `total_cents`."

        Design: Corner/state_machines/second_authorize_on_paid_order_is_rejected
        """
        from test_helpers import validate_paginated

        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        authorize_order(ctx, order["id"])
        second = api.authorize_payment(
            order["id"], {"card_token": "VISA-OK"},
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(second, ApiErrorId.ERR_ORDER_INVALID_STATE, 409)
        payments, meta = validate_paginated(
            api.list_payments(
                make_crew_member_headers(ctx["taker"]["id"]),
                params={"order_id": order["id"]},
            )
        )
        assert len(payments) == 1, (
            f"exactly one payment per order, got {len(payments)}"
        )

    def test_reauthorized_payment_remains_the_single_row(self, api):
        """PRD §3.7: "Authorization creates the order's single `Payment` —
        exactly one per order, bound to it by the payment's `order_id`"

        Design: Corner/state_machines/second_authorize_on_paid_order_is_rejected
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        payment = authorize_order(ctx, order["id"])
        assert payment["status"] == "AUTHORIZED"
        second = api.authorize_payment(
            order["id"], {"card_token": "VISA-OK"},
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(second, ApiErrorId.ERR_ORDER_INVALID_STATE, 409)
        fetched = validate_success(
            api.get_payment(payment["id"], make_crew_member_headers(ctx["taker"]["id"])),
            200,
        )
        assert fetched["status"] == "AUTHORIZED"
        assert fetched["order_id"] == order["id"]


class TestOrderParallelDimensions:
    def test_order_parallel_dimensions_evolve_independently(self, api):
        """PRD §3.7: "Payment follows the order as a mirrored dimension: an
        order's `payment_status` begins `UNPAID` and tracks its payment's own
        status throughout."
        PRD §3.8: "Abandonment voids an `AUTHORIZED` payment (moving it to
        `VOIDED`), releases the lane slot if one was assigned (recomputing
        `lane_occupancy`), cancels every child item still `PENDING` or `BUILDING`"

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_evolve_independently
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        item = list_items_of_order(ctx, order["id"])[0]
        build_item_ready(ctx, item["id"])

        mid = validate_success(
            api.get_order(order["id"], make_crew_member_headers(ctx["taker"]["id"])), 200
        )
        assert mid["queue_status"] == "MERGED"
        assert mid["payment_status"] == "UNPAID"
        assert mid["build_status"] == "READY", (
            "build can reach READY while payment is UNPAID and queue is MERGED"
        )

        authorize_order(ctx, order["id"])
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        abandoned = validate_success(api.abandon_order(order["id"], lead), 200)
        assert abandoned["queue_status"] == "ABANDONED"
        assert abandoned["payment_status"] == "VOIDED"
        after = validate_success(api.get_order(order["id"], lead), 200)
        assert after["build_status"] == "READY", (
            "abandonment does not rewrite the build dimension of an already-READY order"
        )

    def test_build_ready_precedes_payment_and_queue_advancement(self, api):
        """PRD §3.8: "Completing a `BUILDING` item moves it to `READY`, recomputes
        the order's outstanding build seconds, and when every sibling item on the
        order is `READY`, the order's `build_status` becomes `READY`."

        Design: Difficulty/non_linear_state_machine/order_parallel_dimensions_evolve_independently
        """
        ctx = setup_open_stand_with_menu()
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        item = list_items_of_order(ctx, order["id"])[0]
        build_item_ready(ctx, item["id"])
        order_mid = validate_success(
            api.get_order(order["id"], make_crew_member_headers(ctx["taker"]["id"])), 200
        )
        assert order_mid["build_status"] == "READY"
        assert order_mid["queue_status"] == "MERGED"
        assert order_mid["payment_status"] == "UNPAID"
        assert order_mid["outstanding_build_seconds"] == 0


class TestDistributionCycling:
    def test_recipe_distribution_cycles_between_activated_and_suspended(self, api):
        """PRD §3.3: "activation moves a `STAGED` or `SUSPENDED` distribution to
        `ACTIVATED` (but never for a recipe that has been retired — activating a
        distribution of a `RETIRED` recipe is rejected with
        `ERR_DISTRIBUTION_INVALID_STATE`), suspension moves `ACTIVATED →
        `SUSPENDED`"
        PRD §3.3: "While a distribution is `SUSPENDED`, new orders containing the
        recipe are rejected the same way."

        Design: Difficulty/non_linear_state_machine/recipe_distribution_cycles_between_activated_and_suspended
        """
        ctx = setup_open_stand_with_menu()
        dist_id = ctx["dist"]["id"]
        op_headers = ctx["operator_headers"]

        suspended1 = validate_success(api.suspend_distribution(dist_id, op_headers), 200)
        assert suspended1["status"] == "SUSPENDED"

        version = stand_version(ctx)
        rejected = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(rejected, ApiErrorId.ERR_DISTRIBUTION_NOT_ACTIVE, 409)

        act2 = validate_success(api.activate_distribution(dist_id, op_headers), 200)
        assert act2["status"] == "ACTIVATED"
        susp2 = validate_success(api.suspend_distribution(dist_id, op_headers), 200)
        assert susp2["status"] == "SUSPENDED"
        act3 = validate_success(api.activate_distribution(dist_id, op_headers), 200)
        assert act3["status"] == "ACTIVATED"

        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        assert order["queue_status"] == "MERGED"

    def test_order_during_suspend_rejected_then_succeeds_after_reactivation(self, api):
        """PRD §3.3: "Orderability at a stand requires the distribution to be
        `ACTIVATED` at that stand at order time; an order item referencing a
        recipe with no `ACTIVATED` distribution there is rejected with
        `ERR_DISTRIBUTION_NOT_ACTIVE`."

        Design: Difficulty/non_linear_state_machine/recipe_distribution_cycles_between_activated_and_suspended
        """
        ctx = setup_open_stand_with_menu()
        dist_id = ctx["dist"]["id"]
        validate_success(api.suspend_distribution(dist_id, ctx["operator_headers"]), 200)
        version = stand_version(ctx)
        rejected = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(rejected, ApiErrorId.ERR_DISTRIBUTION_NOT_ACTIVE, 409)
        validate_success(api.activate_distribution(dist_id, ctx["operator_headers"]), 200)
        order = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        assert order["queue_status"] == "MERGED"


class TestShiftTerminalLockdown:
    def test_shift_terminal_lockdown_after_lock(self, api):
        """PRD §3.5: "Finally, the operator locks the shift (`RECONCILED →
        `LOCKED`), which is terminal."
        PRD §3.5: "reconciling early is `ERR_SHIFT_INVALID_STATE`"

        Design: Corner/state_machines/shift_terminal_lockdown_after_lock
        """
        from test_helpers import (
            add_assignment,
            create_draft_shift,
            set_clock,
            setup_in_progress_shift,
        )

        ctx = setup_open_stand_with_menu()
        shift, assignments = setup_in_progress_shift(ctx, [(ctx["lead"], "LEAD")])
        validate_success(
            api.check_in_assignment(
                assignments[0]["id"], make_crew_member_headers(ctx["lead"]["id"])
            ),
            200,
        )
        set_clock("2026-09-01T09:00:00Z")
        op_headers = ctx["operator_headers"]
        validate_success(api.reconcile_shift(shift["id"], op_headers), 200)
        locked = validate_success(api.lock_shift(shift["id"], op_headers), 200)
        assert locked["status"] == "LOCKED"

        re_reconcile = api.reconcile_shift(shift["id"], op_headers)
        validate_error(re_reconcile, ApiErrorId.ERR_SHIFT_INVALID_STATE, 409)

    def test_locked_shift_rejects_start_and_publish(self, api):
        """PRD §3.5: "Finally, the operator locks the shift (`RECONCILED →
        `LOCKED`), which is terminal."

        Design: Corner/state_machines/shift_terminal_lockdown_after_lock
        """
        from test_helpers import set_clock, setup_in_progress_shift

        ctx = setup_open_stand_with_menu()
        shift, assignments = setup_in_progress_shift(ctx, [(ctx["lead"], "LEAD")])
        validate_success(
            api.check_in_assignment(
                assignments[0]["id"], make_crew_member_headers(ctx["lead"]["id"])
            ),
            200,
        )
        set_clock("2026-09-01T09:00:00Z")
        op_headers = ctx["operator_headers"]
        validate_success(api.reconcile_shift(shift["id"], op_headers), 200)
        validate_success(api.lock_shift(shift["id"], op_headers), 200)

        publish = api.publish_shift(shift["id"], op_headers)
        validate_error(publish, ApiErrorId.ERR_SHIFT_INVALID_STATE, 409)
        start = api.start_shift(shift["id"], op_headers)
        validate_error(start, ApiErrorId.ERR_SHIFT_INVALID_STATE, 409)
