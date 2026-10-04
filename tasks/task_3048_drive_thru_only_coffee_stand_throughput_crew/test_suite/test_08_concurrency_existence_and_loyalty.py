"""Optimistic concurrency (stale stand/shift versions), existence-before-state
ordering, loyalty points accrual and SILVER rounding, lane-occupancy
reconciliation, and entity-backed ownership checks."""
from test_helpers import (
    ApiErrorId,
    PA,
    add_assignment,
    create_draft_shift,
    create_loyalty_account,
    make_crew_member_headers,
    make_loyalty_customer_headers,
    make_shift_lead_headers,
    place_app_order,
    place_window_order,
    serve_window_order,
    setup_in_progress_shift,
    setup_open_stand_with_menu,
    stand_version,
    validate_error,
    validate_success,
)

GHOST_ID = "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"


class TestExistenceBeforeState:
    def test_existence_checked_before_state_on_nested_action(self, api):
        """PRD §2.9: "3. **Existence** — path identifiers left to right, then body
        foreign keys (the resource-specific `ERR_*_NOT_FOUND` family)."
        PRD §2.6: "The system confirms the existence of each path identifier in
        order — region, stand, crew member, agreement, recipe, distribution,
        account, shift, assignment, order, item, payment, window — and rejects the
        request immediately with the `404 Not Found` error corresponding to the
        first identifier that does not exist (for example `ERR_STAND_NOT_FOUND`
        before `ERR_ORDER_NOT_FOUND` is ever considered)."

        Design: Corner/validations/existence_checked_before_state_on_nested_action
        """
        setup_open_stand_with_menu()
        resp = api.abandon_order(
            GHOST_ID, make_shift_lead_headers("any-lead-id")
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_FOUND, 404)

    def test_abandon_of_unknown_order_never_surfaces_a_state_error(self, api):
        """PRD §2.9: "3. **Existence** — path identifiers left to right, then body
        foreign keys (the resource-specific `ERR_*_NOT_FOUND` family)."

        Design: Corner/validations/existence_checked_before_state_on_nested_action
        """
        ctx = setup_open_stand_with_menu()
        # Use the real lead identity (role is valid) so only existence can fail.
        resp = api.abandon_order(
            GHOST_ID, make_shift_lead_headers(ctx["lead"]["id"])
        )
        assert resp.status_code == 404
        assert resp.json()["data"]["error_id"] == "ERR_ORDER_NOT_FOUND"


class TestOptimisticConcurrency:
    def test_stale_stand_version_rejected_on_order_create(self, api):
        """PRD §2.7: "Creating an order requires `expected_stand_version` matching
        the stand's current `version`. Order creation legitimately mutates the
        stand — allocating `lane_seq`, reserving a lane slot for window orders,
        and bumping the stand's `version` — so a create carrying a version from
        before the client's last read is rejected with `ERR_STALE_VERSION`
        (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/stale_stand_version_rejected_on_order_create
        """
        ctx = setup_open_stand_with_menu()
        stale_version = stand_version(ctx)
        # First create succeeds against the read version and bumps the stand.
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        # A second create carrying the pre-mutation version is stale.
        stale = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": stale_version,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        # Retry with the fresh version succeeds.
        fresh = place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        assert fresh["queue_status"] == "MERGED"

    def test_order_create_with_fresh_version_succeeds_after_stale_rejection(self, api):
        """PRD §2.7: "Creating an order requires `expected_stand_version` matching
        the stand's current `version`."

        Design: Corner/cross_cutting_complexity_layers/stale_stand_version_rejected_on_order_create
        """
        ctx = setup_open_stand_with_menu()
        v1 = stand_version(ctx)
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        stale = api.create_order(
            {
                "stand_id": ctx["stand"]["id"],
                "source": "WINDOW",
                "lane_code": "A",
                "items": [
                    {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                ],
                "expected_stand_version": v1,
            },
            make_crew_member_headers(ctx["taker"]["id"]),
        )
        assert stale.status_code == 412
        v2 = stand_version(ctx)
        ok = validate_success(
            api.create_order(
                {
                    "stand_id": ctx["stand"]["id"],
                    "source": "WINDOW",
                    "lane_code": "A",
                    "items": [
                        {"recipe_id": ctx["recipe"]["id"], "quantity": 1, "modifier_names": []}
                    ],
                    "expected_stand_version": v2,
                },
                make_crew_member_headers(ctx["taker"]["id"]),
            ),
            201,
        )
        assert ok["lane_seq"] == 2

    def test_stale_stand_version_rejected_on_merge(self, api):
        """PRD §2.7: "Merging an app-ahead order into a lane likewise requires
        `expected_stand_version`; a merge against a stand whose `version` has
        advanced since the client last read it is rejected with
        `ERR_STALE_VERSION` (HTTP 412), because the client's picture of the queue
        epoch is superseded."

        Design: Corner/cross_cutting_complexity_layers/stale_stand_version_rejected_on_merge
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="App Amy")
        order = place_app_order(ctx, ctx["recipe"]["id"], account["id"])
        customer = make_loyalty_customer_headers(account["id"])

        stale_version = stand_version(ctx)
        # An intervening window order bumps the stand version.
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")

        stale_merge = api.merge_order(
            order["id"], {"expected_stand_version": stale_version}, customer
        )
        validate_error(stale_merge, ApiErrorId.ERR_STALE_VERSION, 412)
        mid = validate_success(api.get_order(order["id"], customer), 200)
        assert mid["queue_status"] == "QUEUED", "the rejected merge leaves the order QUEUED"

        merged = validate_success(
            api.merge_order(
                order["id"], {"expected_stand_version": stand_version(ctx)}, customer
            ),
            200,
        )
        assert merged["queue_status"] == "MERGED"
        assert merged["lane_code"] == "B", (
            f"lane A carries 60s outstanding build; lane B's projected clear is 0, got {merged['lane_code']}"
        )

    def test_merge_retries_successfully_with_fresh_version(self, api):
        """PRD §2.7: "a merge against a stand whose `version` has advanced since
        the client last read it is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross_cutting_complexity_layers/stale_stand_version_rejected_on_merge
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="App Amy")
        order = place_app_order(ctx, ctx["recipe"]["id"], account["id"])
        customer = make_loyalty_customer_headers(account["id"])
        stale_version = stand_version(ctx)
        place_window_order(ctx, ctx["recipe"]["id"], lane_code="A")
        resp = api.merge_order(order["id"], {"expected_stand_version": stale_version}, customer)
        assert resp.status_code == 412
        fresh = validate_success(
            api.merge_order(
                order["id"], {"expected_stand_version": stand_version(ctx)}, customer
            ),
            200,
        )
        assert fresh["queue_status"] == "MERGED"

    def test_stale_shift_version_rejected_on_assignment_add(self, api):
        """PRD §2.7: "Adding an assignment to a shift requires
        `expected_shift_version` matching the shift's current `version`; a
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), since each
        successful addition increments `Shift.version` by one and a plan read
        before that increment is stale."

        Design: Corner/cross_cutting_complexity_layers/stale_shift_version_rejected_on_assignment_add
        """
        ctx = setup_open_stand_with_menu()
        shift = create_draft_shift(ctx)
        stale_version = shift["version"]
        # First addition bumps the shift version.
        add_assignment(ctx, shift["id"], ctx["op"]["id"], role="LEAD")
        stale = api.create_assignment(
            shift["id"],
            {
                "crew_member_id": ctx["taker"]["id"],
                "role": "TAKER",
                "starts_at": "2026-09-01T07:00:00Z",
                "ends_at": "2026-09-01T09:00:00Z",
                "expected_shift_version": stale_version,
            },
            ctx["operator_headers"],
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, 412)
        fresh = add_assignment(ctx, shift["id"], ctx["taker"]["id"], role="TAKER")
        assert fresh["status"] == "ASSIGNED"

    def test_assignment_add_with_fresh_version_succeeds_after_stale_rejection(self, api):
        """PRD §2.7: "Adding an assignment to a shift requires
        `expected_shift_version` matching the shift's current `version`"

        Design: Corner/cross_cutting_complexity_layers/stale_shift_version_rejected_on_assignment_add
        """
        ctx = setup_open_stand_with_menu()
        shift = create_draft_shift(ctx)
        stale_version = shift["version"]
        add_assignment(ctx, shift["id"], ctx["op"]["id"], role="LEAD")
        resp = api.create_assignment(
            shift["id"],
            {
                "crew_member_id": ctx["taker"]["id"],
                "role": "TAKER",
                "starts_at": "2026-09-01T07:00:00Z",
                "ends_at": "2026-09-01T09:00:00Z",
                "expected_shift_version": stale_version,
            },
            ctx["operator_headers"],
        )
        assert resp.status_code == 412
        refreshed = validate_success(
            api.get_shift(shift["id"], ctx["operator_headers"]), 200
        )
        assert refreshed["version"] == stale_version + 1
        ok = add_assignment(ctx, shift["id"], ctx["taker"]["id"], role="TAKER")
        assert ok["status"] == "ASSIGNED"


class TestLoyaltyAccrualAndDiscount:
    def test_points_accrual_floor_division_on_capture(self, api):
        """PRD §3.4: "When a payment is captured for an order carrying a
        `loyalty_account_id`, the account earns one point per whole dollar
        captured — the captured cents divided by one hundred, rounded down — and
        `lifetime_captured_cents` grows by the captured amount."

        Design: Corner/calculations/points_accrual_floor_division_on_capture
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Floor Fred")
        order = place_window_order(
            ctx, ctx["recipe"]["id"], lane_code="A", loyalty_account_id=account["id"]
        )
        from test_helpers import authorize_order

        payment = authorize_order(ctx, order["id"])
        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.call_to_window(order["id"], lead), 200)
        validate_success(api.capture_payment(payment["id"], lead), 200)

        after = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert after["points"] == 4, (
            f"floor(450/100) = 4, got {after['points']}"
        )
        assert after["lifetime_captured_cents"] == 450
        assert after["tier"] == "NONE"

    def test_capture_accrues_whole_dollar_points_only(self, api):
        """PRD §3.4: "the account earns one point per whole dollar captured — the
        captured cents divided by one hundred, rounded down"

        Design: Corner/calculations/points_accrual_floor_division_on_capture
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Floor Fred")
        served = serve_window_order(
            ctx, ctx["recipe"]["id"], lane_code="A", loyalty_account_id=account["id"]
        )
        assert served["order"]["queue_status"] == "SERVED"
        after = validate_success(
            api.get_loyalty_account(account["id"], ctx["operator_headers"]), 200
        )
        assert after["points"] == 4
        assert after["lifetime_captured_cents"] == 450

    def test_silver_tier_applies_five_percent_per_line(self, api):
        """PRD §3.6: "The loyalty discount is computed **per line, rounded first**:
        `line_discount_cents` is the line gross multiplied by the account's tier
        percentage — ten percent for `GOLD`, five percent for `SILVER`, zero
        otherwise and always zero when the order has no loyalty account — rounded
        half-up to a whole cent"

        Design: Corner/calculations/silver_tier_applies_five_percent_per_line
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Silver Sid")
        validate_success(
            api.adjust_points(account["id"], {"delta_points": 200, "reason": "goodwill"}, PA),
            200,
        )
        order = place_window_order(
            ctx, ctx["recipe"]["id"], lane_code="A", loyalty_account_id=account["id"]
        )
        assert order["discount_cents"] == 23, (
            f"round_half_up(450 * 0.05) = round_half_up(22.5) = 23, got {order['discount_cents']}"
        )
        assert order["total_cents"] == 427
        assert order["subtotal_cents"] == 450

    def test_silver_discount_rounds_half_up_at_half_cent_boundary(self, api):
        """PRD §2.8: "Where a calculation produces a fractional cent, the result
        is rounded **half-up** to the nearest whole cent."

        Design: Corner/calculations/silver_tier_applies_five_percent_per_line
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Silver Sid")
        validate_success(
            api.adjust_points(account["id"], {"delta_points": 200, "reason": "goodwill"}, PA),
            200,
        )
        order = place_window_order(
            ctx, ctx["recipe"]["id"], lane_code="A", loyalty_account_id=account["id"]
        )
        from test_helpers import list_items_of_order

        item = list_items_of_order(ctx, order["id"])[0]
        assert item["line_gross_cents"] == 450
        assert item["line_discount_cents"] == 23
        assert item["line_net_cents"] == 427


class TestLaneOccupancyReconciliation:
    def test_derived_lane_occupancy_tracks_every_queue_mutation(self, api):
        """PRD §3.6: "The stand's `lane_occupancy` is, at all times, the per-lane
        count of orders `MERGED` or `AT_WINDOW`."
        PRD §3.8: "Abandonment voids an `AUTHORIZED` payment (moving it to
        `VOIDED`), releases the lane slot if one was assigned (recomputing
        `lane_occupancy`), cancels every child item still `PENDING` or `BUILDING`"

        Design: Corner/cross_cutting_complexity_layers/derived_lane_occupancy_tracks_every_queue_mutation
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Occ Olivia")
        customer = make_loyalty_customer_headers(account["id"])

        app_order = place_app_order(ctx, ctx["recipe"]["id"], account["id"])
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert not stand["lane_occupancy"], (
            f"a QUEUED app order is not yet in a lane: {stand['lane_occupancy']}"
        )

        merged = validate_success(
            api.merge_order(
                app_order["id"], {"expected_stand_version": stand["version"]}, customer
            ),
            200,
        )
        assert merged["lane_code"] == "A"
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["lane_occupancy"]["A"] == 1
        assert "B" not in stand["lane_occupancy"]

        place_window_order(ctx, ctx["recipe"]["id"], lane_code="B")
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["lane_occupancy"]["A"] == 1
        assert stand["lane_occupancy"]["B"] == 1

        lead = make_shift_lead_headers(ctx["lead"]["id"])
        validate_success(api.abandon_order(app_order["id"], lead), 200)
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["lane_occupancy"].get("A", 0) == 0, "abandon releases lane A"
        assert stand["lane_occupancy"]["B"] == 1, "lane B is untouched"

    def test_queued_app_order_not_counted_until_merged(self, api):
        """PRD §3.6: "The selector considers only lanes with a free stacking slot
        — those whose occupied count (orders in the lane with `queue_status` of
        `MERGED` or `AT_WINDOW`) is below that lane's `max_stack_cars`"
        PRD §3.6: "A successful merge assigns `lane_code` and the next `lane_seq`,
        reserves the slot — the stand's `lane_occupancy` count for that lane
        rises by one — moves the order `QUEUED → MERGED`, and increments the
        stand's `version` by one."

        Design: Corner/cross_cutting_complexity_layers/derived_lane_occupancy_tracks_every_queue_mutation
        """
        ctx = setup_open_stand_with_menu()
        account = create_loyalty_account(ctx["stand"]["id"], full_name="Occ Olivia")
        app_order = place_app_order(ctx, ctx["recipe"]["id"], account["id"])
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert not stand["lane_occupancy"]
        merged = validate_success(
            api.merge_order(
                app_order["id"],
                {"expected_stand_version": stand["version"]},
                make_loyalty_customer_headers(account["id"]),
            ),
            200,
        )
        stand = validate_success(
            api.get_stand(ctx["stand"]["id"], ctx["operator_headers"]), 200
        )
        assert stand["lane_occupancy"][merged["lane_code"]] == 1


class TestOwnershipChecks:
    def test_crew_checkin_limited_to_own_assignment(self, api):
        """PRD §2.1: "When `X-User-Role` is `StandOperator`, `ShiftLead`, or
        `CrewMember`, `X-User-ID` is the `id` of the acting `CrewMember`;
        ownership checks on any resource that references a `CrewMember` compare
        the resource's foreign-key field to `X-User-ID` — most notably, a
        `StandOperator` may activate an agreement only when `X-User-ID` equals
        the agreement's `crew_member_id`, and a `CrewMember` may check in only to
        an assignment whose `crew_member_id` matches."

        Design: Corner/rbac/crew_checkin_limited_to_own_assignment
        """
        ctx = setup_open_stand_with_menu()
        shift, assignments = setup_in_progress_shift(ctx, [(ctx["lead"], "LEAD")])
        assignment = assignments[0]
        resp = api.check_in_assignment(
            assignment["id"], make_crew_member_headers(ctx["taker"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)
        after = validate_success(
            api.get_assignment(assignment["id"], ctx["operator_headers"]), 200
        )
        assert after["status"] == "ASSIGNED"

    def test_crew_checkin_succeeds_for_owning_member(self, api):
        """PRD §3.5: "During the shift, each crew member checks themself in: a
        `CrewMember` whose `X-User-ID` matches the assignment's `crew_member_id`
        moves it `ASSIGNED → CHECKED_IN`, valid only while the parent shift is
        `IN_PROGRESS` (a check-in on the wrong person is `ERR_UNAUTHORIZED_ROLE`;
        on a non-`ASSIGNED` assignment, `ERR_ASSIGNMENT_INVALID_STATE`; on a
        shift in the wrong status, `ERR_SHIFT_INVALID_STATE`)."

        Design: Corner/rbac/crew_checkin_limited_to_own_assignment
        """
        ctx = setup_open_stand_with_menu()
        shift, assignments = setup_in_progress_shift(ctx, [(ctx["lead"], "LEAD")])
        checked_in = validate_success(
            api.check_in_assignment(
                assignments[0]["id"], make_crew_member_headers(ctx["lead"]["id"])
            ),
            200,
        )
        assert checked_in["status"] == "CHECKED_IN"
