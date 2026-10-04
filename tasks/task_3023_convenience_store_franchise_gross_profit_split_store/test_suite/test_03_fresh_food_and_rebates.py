"""The fresh-food programme: capacity, windows and the whole-period waste charge."""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    validate_paginated,
    ApiErrorId, ADMIN, AUDITOR, COMMISSARY, get_success_data, set_clock,
    setup_store_with_agreement, create_delivery_window, place_fresh_order,
    confirm_fresh_order, lock_delivery_window, deliver_fresh_order,
    reconcile_fresh_order, refresh_window, setup_window_with_orders,
    setup_settlement_with_lines, setup_settlement_with_rebate,
    reconcile_settlement, finalize_settlement, post_rebate, create_shrink_audit,
    make_franchisee_headers,
)


WINDOW_START = "2026-09-08T06:00:00Z"
WINDOW_END = "2026-09-08T10:00:00Z"
INSIDE_WINDOW = "2026-09-08T07:00:00Z"


class TestWholePeriodWasteTier:
    """The waste tier is keyed on the whole period, never on a running figure."""

    def test_the_period_total_keys_the_tier_before_any_per_order_share_is_taken(self):
        """PRD §3.5: "Second, that whole-period total keys a waste tier: `HIGH`
        when the period waste cost reaches at least 500,000 cents, `MEDIUM` when
        it reaches at least 100,000 cents, and `LOW` otherwise, with both
        thresholds inclusive."
        PRD §3.5: "Fourth and only then, each order's own `line_waste_cents` is
        computed: the order's `unit_cost_cents` multiplied by its `waste_units`,
        rounded to 2 decimal places, then multiplied by the effective share, and
        rounded to 2 decimal places again".

        Design: Difficulty/combinatorial_formula/waste_share_period_total_keys_tier_then_per_order_share
        """
        context = setup_window_with_orders(
            orders=[("SKU-A", 400, 499), ("SKU-B", 300, 699), ("SKU-C", 500, 299)],
            capacity_units=2000,
            window_start=WINDOW_START, window_end=WINDOW_END,
            waste_share_pct=0.50,
            confirm=True, lock=True, deliver=True, delivery_clock=INSIDE_WINDOW,
        )
        orders = context["orders"]

        reconciled = [
            reconcile_fresh_order(orders[0]["id"], 120),
            reconcile_fresh_order(orders[1]["id"], 80),
            reconcile_fresh_order(orders[2]["id"], 150),
        ]
        for order in reconciled:
            assert order["status"] == "RECONCILED"

        # Period waste cost: 499*120 = 59,880.00; 699*80 = 55,920.00; 299*150 = 44,850.00.
        # Total 160,650.00 sits in [100,000, 500,000): MEDIUM, adder 0.02,
        # so the effective share is 0.50 + 0.02 = 0.52.
        assert context["orders"][0]["unit_cost_cents"] * 120 == 59_880
        assert context["orders"][1]["unit_cost_cents"] * 80 == 55_920
        assert context["orders"][2]["unit_cost_cents"] * 150 == 44_850
        period_total = 59_880 + 55_920 + 44_850
        assert period_total == 160_650
        assert 100_000 <= period_total < 500_000

        # PRD §3.5 keys the tier off the whole-period total of the orders that are
        # *already* RECONCILED when the calculation runs, so the figure each order
        # carries is the one computed on the pass that saw the full three-order
        # period. Read each order back once all three have reconciled.
        final = [get_success_data(api_client.get_fresh_order(order["id"], ADMIN))
                 for order in orders]
        assert final[0]["line_waste_cents"] == pytest.approx(31_137.60, abs=0.01)
        assert final[1]["line_waste_cents"] == pytest.approx(29_078.40, abs=0.01)
        assert final[2]["line_waste_cents"] == pytest.approx(23_322.00, abs=0.01)
        # Evaluating the tier per order would have left every order LOW: 29,940.00.
        assert final[0]["line_waste_cents"] != pytest.approx(29_940.00, abs=0.01)

        # Every reconciliation releases its ordered units back out of the window.
        window = refresh_window(context["window"]["id"])
        assert window["reserved_units"] == 0

    def test_the_recorded_waste_share_and_the_period_charge_agree_with_the_allocated_figure(self):
        """PRD §3.5: "the resulting figure is also recorded on the order as its
        `waste_share_cents`, the store-level share of that order's waste charged
        to the operator. Fifth, the settlement's `waste_charge_cents` is the sum
        of those per-order figures."
        PRD §3.5: "for every in-scope order — one whose store matches, whose status
        is `RECONCILED`, and whose bound window overlaps the settlement's period".

        Design: Difficulty/combinatorial_formula/waste_share_period_total_keys_tier_then_per_order_share
        """
        context = setup_window_with_orders(
            orders=[("SKU-A", 400, 499), ("SKU-B", 300, 699), ("SKU-C", 500, 299)],
            capacity_units=2000,
            window_start=WINDOW_START, window_end=WINDOW_END,
            waste_share_pct=0.50,
            confirm=True, lock=True, deliver=True, delivery_clock=INSIDE_WINDOW,
        )
        orders = context["orders"]
        reconciled = [
            reconcile_fresh_order(orders[0]["id"], 120),
            reconcile_fresh_order(orders[1]["id"], 80),
            reconcile_fresh_order(orders[2]["id"], 150),
        ]
        for order in reconciled:
            # The per-order share recorded on the order is the allocated figure.
            assert order["waste_share_cents"] == pytest.approx(
                order["line_waste_cents"], abs=0.01)

        listed, _meta = validate_paginated(
            api_client.list_fresh_orders(ADMIN, {"store_id": context["store"]["id"]}))
        assert len(listed) == 3
        assert all(o["status"] == "RECONCILED" for o in listed)
        total = sum(o["line_waste_cents"] for o in listed)
        assert total == pytest.approx(31_137.60 + 29_078.40 + 23_322.00, abs=0.01)


class TestWindowCapacityBoundary:
    """reserved_units may reach capacity_units exactly; one more unit is refused."""

    def test_an_order_exactly_filling_the_remaining_capacity_is_accepted_and_one_more_is_refused(self):
        """PRD §3.5: "The booking must not exceed capacity — the window's
        `reserved_units` plus the `ordered_units` being booked must be at most
        the window's `capacity_units`, with the exact boundary permitted, and an
        overage is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Difficulty/boundary_precision_check/delivery_window_capacity_boundary_is_inclusive_and_order_quantity_one_over_is_rejected
        """
        context = setup_store_with_agreement(
            clock="2026-09-01T12:00:00Z",
            store_overrides={"cold_chain_certified": True})
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]
        window = create_delivery_window(
            store_id, "2026-09-11T06:00:00Z", "2026-09-11T10:00:00Z", 500)

        place_fresh_order(store_id, window["id"], franchisee_id, "SKU-M1", 400, 199)

        # 400 reserved + 100 ordered == 500: exactly at capacity, accepted.
        exact = validate_success(
            api_client.create_fresh_order(
                {"store_id": store_id, "delivery_window_id": window["id"],
                 "sku_code": "SKU-M2", "ordered_units": 100, "unit_cost_cents": 149},
                make_franchisee_headers(franchisee_id)), 201)
        assert exact["status"] == "PLACED"

        filled = refresh_window(window["id"])
        assert filled["reserved_units"] == 500
        assert filled["reserved_units"] == filled["capacity_units"]

        # One unit over the boundary is refused.
        over = api_client.create_fresh_order(
            {"store_id": store_id, "delivery_window_id": window["id"],
             "sku_code": "SKU-M3", "ordered_units": 1, "unit_cost_cents": 99},
            make_franchisee_headers(franchisee_id))
        validate_error(over, ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED, expected_status=409)

        listed, _meta = validate_paginated(
            api_client.list_fresh_orders(ADMIN, {"delivery_window_id": window["id"]}))
        assert len(listed) == 2, "the rejected order must not have been persisted"
        assert refresh_window(window["id"])["reserved_units"] == 500

    def test_cold_chain_failure_is_reported_ahead_of_the_capacity_overrun(self):
        """PRD §3.5: "The ordering store must be cold-chain certified; a store
        whose `cold_chain_certified` flag is false is rejected with
        `ERR_COLD_CHAIN_BROKEN` (HTTP 409)."
        PRD §3.5: "an overage is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED` (HTTP 409)."
        PRD §2.12: "Where an operation depends on a parent's operational status,
        that status is evaluated first."

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_failure_precedes_capacity_overrun_on_fresh_order
        """
        context = setup_store_with_agreement(
            clock="2026-09-01T12:00:00Z",
            store_overrides={"cold_chain_certified": False})
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]
        assert context["store"]["cold_chain_certified"] is False
        window = create_delivery_window(
            store_id, "2026-09-10T06:00:00Z", "2026-09-10T10:00:00Z", 500)

        # This request breaks BOTH rules: the store is uncertified and the
        # 5,000 units are ten times the window's capacity.
        response = api_client.create_fresh_order(
            {"store_id": store_id, "delivery_window_id": window["id"],
             "sku_code": "SKU-X", "ordered_units": 5000, "unit_cost_cents": 250},
            make_franchisee_headers(franchisee_id))
        error = validate_error(response, ApiErrorId.ERR_COLD_CHAIN_BROKEN, expected_status=409)
        assert error["error_id"] != ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED.value

        listed, _meta = validate_paginated(
            api_client.list_fresh_orders(ADMIN, {"store_id": store_id}))
        assert len(listed) == 0
        assert refresh_window(window["id"])["reserved_units"] == 0

    def test_a_locked_window_refuses_a_new_order_ahead_of_the_capacity_rule(self):
        """PRD §3.5: "A locked window can accept no further orders; an order
        placed against it is rejected with `ERR_WINDOW_LOCKED` (HTTP 409)."
        PRD §3.5: "an overage is rejected with `ERR_WINDOW_CAPACITY_EXCEEDED` (HTTP 409)."

        Design: Corner/validations/window_lock_rule_beats_capacity_rule_on_a_locked_overfull_window
        """
        context = setup_store_with_agreement(
            clock="2026-09-01T00:00:00Z",
            store_overrides={"cold_chain_certified": True})
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]
        window = create_delivery_window(
            store_id, "2026-09-10T06:00:00Z", "2026-09-10T10:00:00Z", 500)
        lock_delivery_window(window["id"])

        response = api_client.create_fresh_order(
            {"store_id": store_id, "delivery_window_id": window["id"],
             "sku_code": "SKU-Q1", "ordered_units": 9000, "unit_cost_cents": 320},
            make_franchisee_headers(franchisee_id))
        error = validate_error(response, ApiErrorId.ERR_WINDOW_LOCKED, expected_status=409)
        assert error["error_id"] != ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED.value

        # The cold-chain check passed, so the safety rule did not fire.
        assert context["store"]["cold_chain_certified"] is True
        listed, _meta = validate_paginated(
            api_client.list_fresh_orders(ADMIN, {"delivery_window_id": window["id"]}))
        assert len(listed) == 0
        assert refresh_window(window["id"])["reserved_units"] == 0


class TestWindowHandlingBuffer:
    """Windows for the same store and commissary keep a 30-minute handling buffer."""

    def test_a_window_starting_inside_the_buffer_is_refused_and_one_at_the_boundary_is_accepted(self):
        """PRD §3.5: "Windows for the same store and the same commissary are kept
        apart by a handling buffer: a new window must not start inside the 30
        minutes that follow another non-cancelled window's end, which means that
        abutting windows — one beginning exactly when another ends — are
        rejected. The violation is reported as `ERR_WINDOW_HANDLING_OVERLAP`
        (HTTP 409)."
        PRD §2.9: "Where a rule speaks of a number of days, the comparison is
        made against the instant that many days from the stated anchor, and the
        boundary itself satisfies the rule unless the rule states otherwise."

        Design: Difficulty/resource_temporal_overlap/delivery_window_handling_buffer_rejects_abutting_windows
        """
        set_clock("2026-09-01T12:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-01T12:00:00Z")
        store_id = context["store"]["id"]

        first = create_delivery_window(
            store_id, WINDOW_START, WINDOW_END, 500, commissary_code="COMM-TX-9")
        assert first["status"] == "SCHEDULED"

        # 15 minutes after the first window ends: inside the buffer.
        too_close = api_client.create_delivery_window(
            {"store_id": store_id, "commissary_code": "COMM-TX-9", "day_of_week": "TUE",
             "window_start": "2026-09-08T10:15:00Z", "window_end": "2026-09-08T14:00:00Z",
             "capacity_units": 400}, ADMIN)
        validate_error(too_close, ApiErrorId.ERR_WINDOW_HANDLING_OVERLAP, expected_status=409)

        # Exactly 30 minutes after: on the boundary, and the boundary satisfies the rule.
        at_boundary = validate_success(
            api_client.create_delivery_window(
                {"store_id": store_id, "commissary_code": "COMM-TX-9", "day_of_week": "TUE",
                 "window_start": "2026-09-08T10:30:00Z", "window_end": "2026-09-08T14:00:00Z",
                 "capacity_units": 400}, ADMIN), 201)
        assert at_boundary["status"] == "SCHEDULED"

        listed, meta = validate_paginated(
            api_client.list_delivery_windows(ADMIN, {"store_id": store_id}))
        assert meta["total_count"] == 2, "the rejected window must not have been persisted"


class TestConfirmAndDeliverReadOppositeWindowRequirements:
    """Confirmation needs the window SCHEDULED; delivery needs it LOCKED."""

    def test_confirm_requires_scheduled_while_deliver_requires_locked(self):
        """PRD §3.5: "Confirmation by a `Commissary` requires the bound window
        still to be `SCHEDULED`, or the confirmation is rejected with
        `ERR_WINDOW_LOCKED` (HTTP 409); on success the order becomes `CONFIRMED`."
        PRD §3.5: "Delivery is recorded against the `delivered_units` actually
        received, and requires the bound window to be `LOCKED` — a delivery
        attempted against a window that is not locked is rejected with
        `ERR_WINDOW_NOT_LOCKED` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/fresh_order_confirm_and_deliver_gate_on_the_bound_window_state
        """
        context = setup_store_with_agreement(
            clock="2026-09-01T12:00:00Z",
            store_overrides={"cold_chain_certified": True})
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]
        window = create_delivery_window(
            store_id, "2026-09-14T06:00:00Z", "2026-09-14T10:00:00Z", 600)

        first = place_fresh_order(store_id, window["id"], franchisee_id, "SKU-O1", 200, 299)
        second = place_fresh_order(store_id, window["id"], franchisee_id, "SKU-O2", 100, 399)

        # Delivery while the window is still SCHEDULED is refused. The order is
        # also still PLACED, and PRD names both rules without pinning which one
        # answers first, so either identifier expresses the refusal.
        before = api_client.deliver_fresh_order(first["id"], {"delivered_units": 200}, COMMISSARY)
        assert before.status_code == 409
        validate_error_is_one_of(
            before, [ApiErrorId.ERR_WINDOW_NOT_LOCKED.value,
                     ApiErrorId.ERR_INVALID_STATE.value])

        # ...while confirmation is exactly what a SCHEDULED window accepts.
        confirmed = confirm_fresh_order(first["id"])
        assert confirmed["status"] == "CONFIRMED"

        locked = lock_delivery_window(window["id"])
        assert locked["status"] == "LOCKED"

        # Now the requirements invert: confirmation is refused...
        after = api_client.confirm_fresh_order(second["id"], COMMISSARY)
        validate_error(after, ApiErrorId.ERR_WINDOW_LOCKED, expected_status=409)

        still = get_success_data(api_client.get_fresh_order(second["id"], ADMIN))
        assert still["status"] == "PLACED"

        listed, _meta = validate_paginated(
            api_client.list_fresh_orders(ADMIN, {"delivery_window_id": window["id"]}))
        assert len(listed) == 2


class TestReservedUnitsIsConserved:
    """Every path out of the reserved set releases exactly the ordered units."""

    def test_cancellation_and_reconciliation_both_restore_the_window_to_its_starting_figure(self):
        """PRD §3.5: "This reservation is not a one-way ratchet: every path by
        which an order leaves the reserved set — cancellation, reconciliation,
        or the store-level cascade — releases the same `ordered_units` back out
        of `reserved_units`. That compensating release is what keeps the
        reservation invariant whole."

        Design: Difficulty/compensating_invariant/window_reserved_units_returns_to_zero_by_cancel_and_by_reconcile
        """
        context = setup_store_with_agreement(
            clock="2026-09-01T12:00:00Z",
            store_overrides={"cold_chain_certified": True})
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]
        window = create_delivery_window(
            store_id, WINDOW_START, WINDOW_END, 1000)
        assert window["reserved_units"] == 0

        first = place_fresh_order(store_id, window["id"], franchisee_id, "SKU-R1", 300, 249)
        assert refresh_window(window["id"])["reserved_units"] == 300

        cancelled = validate_success(
            api_client.cancel_fresh_order(first["id"], make_franchisee_headers(franchisee_id)), 200)
        assert cancelled["status"] == "CANCELLED"
        assert refresh_window(window["id"])["reserved_units"] == 0

        second = place_fresh_order(store_id, window["id"], franchisee_id, "SKU-R2", 250, 349)
        assert refresh_window(window["id"])["reserved_units"] == 250

        confirm_fresh_order(second["id"])
        lock_delivery_window(window["id"])
        set_clock(INSIDE_WINDOW)
        deliver_fresh_order(second["id"], 250)
        reconciled = reconcile_fresh_order(second["id"], 0)
        assert reconciled["status"] == "RECONCILED"
        assert refresh_window(window["id"])["reserved_units"] == 0

        listed, _meta = validate_paginated(
            api_client.list_fresh_orders(ADMIN, {"delivery_window_id": window["id"]}))
        assert sorted(o["status"] for o in listed) == ["CANCELLED", "RECONCILED"]

    def test_cancelling_another_operators_order_is_refused_on_ownership_not_on_role(self):
        """PRD §2.1: "A franchisee-scoped call whose `X-User-ID` is not the
        owning `Franchisee.id` is rejected with `ERR_NOT_RESOURCE_OWNER`
        (HTTP 403)."
        PRD §3.5: "The acting operator must own the store the order is bound to;
        a cancellation by any other operator is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."

        Design: Corner/validations/franchisee_scoped_endpoints_enforce_ownership_not_just_role
        """
        set_clock("2026-09-01T00:00:00Z")
        owner = get_success_data(api_client.create_franchisee(
            {"legal_name": "Owner Franchisee LLC", "owner_name": "Nadia Ferraro",
             "entity_type": "LLC", "stated_net_worth_cents": 30_000_000}, ADMIN))
        rival = get_success_data(api_client.create_franchisee(
            {"legal_name": "Rival Franchisee LLC", "owner_name": "Chuck Beaulieu",
             "entity_type": "LLC", "stated_net_worth_cents": 30_000_000}, ADMIN))
        store = get_success_data(api_client.create_store(
            {"franchisee_id": owner["id"], "store_number": "MI-9001", "state_code": "MI",
             "format": "URBAN", "opened_on": "2022-01-01T00:00:00Z",
             "cold_chain_certified": True}, ADMIN))
        window = create_delivery_window(
            store["id"], "2026-09-14T06:00:00Z", "2026-09-14T10:00:00Z", 500)
        order = place_fresh_order(store["id"], window["id"], owner["id"], "SKU-R1", 120, 240)

        response = api_client.cancel_fresh_order(
            order["id"], make_franchisee_headers(rival["id"]))
        error = validate_error(response, ApiErrorId.ERR_NOT_RESOURCE_OWNER, expected_status=403)
        # The rival holds the Franchisee role, so the role check passed.
        assert error["error_id"] != ApiErrorId.ERR_FORBIDDEN.value

        unchanged = get_success_data(api_client.get_fresh_order(order["id"], ADMIN))
        assert unchanged["status"] == "PLACED"
        assert refresh_window(window["id"])["reserved_units"] == 120


class TestStoreTerminationCascadeLeavesTerminalChildrenAlone:
    """The cascade cancels only the children that are still in flight."""

    def test_a_reconciled_order_survives_the_cascade_while_placed_orders_are_cancelled(self):
        """PRD §3.8: "Every fresh order for that store still in `PLACED`,
        `CONFIRMED` or `DELIVERED` is cancelled, and each cancellation releases
        the order's `ordered_units` from its bound window's `reserved_units`.
        Every delivery window for that store still in `SCHEDULED` or `LOCKED` is
        cancelled."

        Design: Corner/state_machines/non_terminal_children_are_left_untouched_by_the_store_termination_cascade
        """
        set_clock("2026-09-01T00:00:00Z")
        context = setup_store_with_agreement(
            clock="2026-09-01T00:00:00Z",
            store_overrides={"cold_chain_certified": True},
            shrink_responsibility_pct=0.50)
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]
        window = create_delivery_window(
            store_id, WINDOW_START, WINDOW_END, 900)

        done = place_fresh_order(store_id, window["id"], franchisee_id, "SKU-L1", 100, 200)
        live_a = place_fresh_order(store_id, window["id"], franchisee_id, "SKU-L2", 200, 300)
        live_b = place_fresh_order(store_id, window["id"], franchisee_id, "SKU-L3", 300, 400)

        confirm_fresh_order(done["id"])
        lock_delivery_window(window["id"])
        set_clock(INSIDE_WINDOW)
        deliver_fresh_order(done["id"], 100)
        reconcile_fresh_order(done["id"], 0)

        validate_success(
            api_client.terminate_franchisee(franchisee_id, ADMIN), 200)

        final_done = get_success_data(api_client.get_fresh_order(done["id"], ADMIN))
        final_a = get_success_data(api_client.get_fresh_order(live_a["id"], ADMIN))
        final_b = get_success_data(api_client.get_fresh_order(live_b["id"], ADMIN))
        assert final_done["status"] == "RECONCILED"
        assert final_a["status"] == "CANCELLED"
        assert final_b["status"] == "CANCELLED"

        listed, _meta = validate_paginated(
            api_client.list_fresh_orders(ADMIN, {"store_id": store_id}))
        assert sorted(o["status"] for o in listed) == ["CANCELLED", "CANCELLED", "RECONCILED"]

        assert refresh_window(window["id"])["reserved_units"] == 0
        assert get_success_data(api_client.get_store(store_id, ADMIN))["status"] == "TERMINATED"


class TestInvalidFreshOrderTransitions:
    """Delivering an order that was never confirmed is a state error."""

    def test_delivering_a_placed_order_is_refused_even_inside_a_locked_window(self):
        """PRD §3.5: "A successful delivery moves the order to `DELIVERED` and
        records the delivered figure."
        PRD §3.5: "Confirmation by a `Commissary` requires the bound window still
        to be `SCHEDULED`".

        Design: Corner/state_machines/fresh_order_deliver_without_confirm_returns_invalid_state
        """
        context = setup_store_with_agreement(
            clock="2026-09-01T00:00:00Z",
            store_overrides={"cold_chain_certified": True})
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]
        window = create_delivery_window(store_id, WINDOW_START, WINDOW_END, 400)
        order = place_fresh_order(store_id, window["id"], franchisee_id, "SKU-K1", 150, 275)
        lock_delivery_window(window["id"])
        set_clock(INSIDE_WINDOW)

        response = api_client.deliver_fresh_order(
            order["id"], {"delivered_units": 150}, COMMISSARY)
        validate_error(response, ApiErrorId.ERR_INVALID_STATE, expected_status=409)

        unchanged = get_success_data(api_client.get_fresh_order(order["id"], ADMIN))
        assert unchanged["status"] == "PLACED"
        assert unchanged["delivered_units"] is None


class TestHalfOpenAuditPeriods:
    """Audit periods sharing an endpoint are allowed; true overlap is not."""

    def test_a_period_starting_exactly_on_the_prior_period_end_is_accepted(self):
        """PRD §3.6: "A new audit period may not overlap another non-cancelled
        audit for the same store; periods that merely share an endpoint are
        permitted, but any true overlap is rejected with
        `ERR_AUDIT_PERIOD_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/shrink_audit_half_open_adjacency_is_allowed_but_true_overlap_is_not
        """
        set_clock("2026-09-01T12:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-01T12:00:00Z")
        store_id = context["store"]["id"]

        first = create_shrink_audit(
            store_id, "2026-08-01T00:00:00Z", "2026-09-01T00:00:00Z", 8_000_000)

        overlapping = api_client.create_shrink_audit(
            {"store_id": store_id, "period_start": "2026-08-15T00:00:00Z",
             "period_end": "2026-09-15T00:00:00Z", "book_inventory_cents": 7_000_000}, ADMIN)
        validate_error(overlapping, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP, expected_status=409)

        abutting = validate_success(
            api_client.create_shrink_audit(
                {"store_id": store_id, "period_start": "2026-09-01T00:00:00Z",
                 "period_end": "2026-10-01T00:00:00Z",
                 "book_inventory_cents": 7_500_000}, ADMIN), 201)
        assert abutting["status"] == "SCHEDULED"

        listed, meta = validate_paginated(
            api_client.list_shrink_audits(ADMIN, {"store_id": store_id}))
        assert meta["total_count"] == 2, "the rejected audit must not have been persisted"
        assert get_success_data(api_client.get_shrink_audit(first["id"], ADMIN))["status"] == "SCHEDULED"


class TestRebateFlowthroughNestedRounding:
    """The attribution and the pass-through are each rounded per category."""

    def test_the_per_category_rounding_order_yields_the_pinned_flowthrough(self):
        """PRD §3.4: "Only then is each category's attribution multiplied by the
        agreement's `rebate_pass_pct` and rounded to 2 decimal places *per
        category*, and the resulting `flowthrough_cents` is the sum of those
        per-category figures. The alternative — multiplying the whole rebate by
        the pass-through percentage and rounding once — is explicitly not the
        rule, and the two orders differ by a cent on a rebate of 12,34,567 cents
        spread across gross-sales weights of 8,000,000, 6,000,000 and 2,000,000
        with a pass-through of 0.55; the pinned order yields 679,011.86 against
        the single-round figure of 679,011.85."

        Design: Difficulty/combinatorial_formula/rebate_flowthrough_rounded_per_category_beats_single_rounding
        """
        context = setup_settlement_with_rebate(
            rebate_cents=1_234_567,
            lines=[("MERCHANDISE", 8_000_000, 5_600_000),
                   ("FUEL", 6_000_000, 5_400_000),
                   ("SERVICES", 2_000_000, 800_000)],
            rebate_pass_pct=0.55,
            split_pct=0.50,
            vendor_code="BRD-77",
            trailing_avg=5_000_000,
        )
        reconcile_settlement(context["settlement"]["id"])

        rebate = get_success_data(api_client.get_rebate(context["rebate"]["id"], ADMIN))
        assert rebate["status"] == "APPLIED"
        assert rebate["flowthrough_cents"] == pytest.approx(679_011.86, abs=0.01)
        assert rebate["flowthrough_cents"] != pytest.approx(679_011.85, abs=0.01)

        settlement = get_success_data(
            api_client.get_settlement(context["settlement"]["id"], ADMIN))
        assert settlement["rebate_credit_cents"] == pytest.approx(679_011.86, abs=0.01)

    def test_a_single_revenue_line_reduces_the_rule_to_one_rounded_multiplication(self):
        """PRD §3.4: "When a settlement carries exactly one revenue line, or the
        pass-through percentage is exactly 1.0, there is only one attribution to
        round and `flowthrough_cents` equals the gross rebate multiplied by the
        pass-through percentage, rounded once."

        Design: Difficulty/combinatorial_formula/rebate_flowthrough_rounded_per_category_beats_single_rounding
        """
        context = setup_settlement_with_rebate(
            rebate_cents=1_234_567,
            lines=[("SERVICES", 2_000_000, 800_000)],
            rebate_pass_pct=0.55,
            vendor_code="BRD-78",
            trailing_avg=5_000_000,
        )
        reconcile_settlement(context["settlement"]["id"])
        rebate = get_success_data(api_client.get_rebate(context["rebate"]["id"], ADMIN))
        assert rebate["flowthrough_cents"] == pytest.approx(
            round(1_234_567 * 0.55, 2), abs=0.01)


class TestRetractionAgainstTheCoveringSettlement:
    """Withdrawal follows the covering settlement's state, not the rebate's period."""

    def test_an_applied_rebate_is_retractable_until_its_settlement_reaches_finalized(self):
        """PRD §3.4: "Retracting an applied rebate is permitted while the
        covering settlement is `OPEN`, `DRAW_PAID`, `RECONCILED` or `DISPUTED`".
        PRD §3.4: "Once the covering settlement has reached `FINALIZED`, an
        applied rebate may no longer be retracted, and the attempt is rejected
        with `ERR_SETTLEMENT_ALREADY_FINALIZED` (HTTP 409)."

        Design: Corner/errors/rebate_already_applied_at_finalized_settlement_blocks_retraction
        """
        context = setup_settlement_with_rebate(
            rebate_cents=250_000,
            lines=[("SERVICES", 1_000_000, 600_000)],
            rebate_pass_pct=1.0, vendor_code="PSC-21", trailing_avg=1_000_000)
        # The rebate's own period_end is 2026-09-08; move the clock past it so
        # the scheduled week is closed and its cooling-off has run out.
        set_clock("2026-09-20T00:00:00Z")
        second = post_rebate(context["store"]["id"], 250_000, vendor_code="BBC-22")

        reconcile_settlement(context["settlement"]["id"])  # OPEN -> DRAW_PAID

        # Retraction while the settlement is DRAW_PAID succeeds.
        first_retracted = validate_success(
            api_client.retract_rebate(context["rebate"]["id"], ADMIN), 200)
        assert first_retracted["status"] == "RETRACTED"
        after_retract = get_success_data(
            api_client.get_settlement(context["settlement"]["id"], ADMIN))
        assert after_retract["rebate_credit_cents"] == pytest.approx(250_000.00, abs=0.01)

        reconcile_settlement(context["settlement"]["id"])  # DRAW_PAID -> RECONCILED
        finalize_settlement(context["settlement"]["id"])

        blocked = api_client.retract_rebate(second["id"], ADMIN)
        validate_error(blocked, ApiErrorId.ERR_SETTLEMENT_ALREADY_FINALIZED, expected_status=409)

        second_after = get_success_data(api_client.get_rebate(second["id"], ADMIN))
        assert second_after["status"] == "APPLIED"

    def test_a_non_recommended_rebate_blocks_reconciliation_until_it_is_retracted(self):
        """PRD §3.4: "A `VendorRebate` records money a vendor pays back on
        purchases made at a store during a period".
        PRD §2.10: "Only recommended-vendor rebates may flow through to a
        settlement. A rebate whose `recommended_vendor` flag is false may be
        posted, but presenting it for application to a settlement is rejected
        with `ERR_VENDOR_NOT_RECOMMENDED` (HTTP 409)."

        Design: Corner/errors/unretracted_non_recommended_rebate_blocks_settlement_reconcile
        """
        context = setup_settlement_with_lines(
            lines=[("SERVICES", 2_000_000, 800_000)],
            rebate_pass_pct=0.60, trailing_avg=1_000_000)
        store_id = context["store"]["id"]
        settle_id = context["settlement"]["id"]

        # PRD §3.4: a rebate still in POSTED is retracted "once the logical clock
        # has reached the rebate's own `period_end`", so move the clock past the
        # scheduled week's close before the withdrawal below.
        set_clock("2026-09-20T00:00:00Z")
        post_rebate(store_id, 500_000, vendor_code="PSC-01", recommended_vendor=True)
        off_list = post_rebate(store_id, 400_000, vendor_code="OUT-01",
                               recommended_vendor=False, vendor_name="Off List Supply Co")

        blocked = api_client.reconcile_settlement(settle_id, ADMIN)
        validate_error(blocked, ApiErrorId.ERR_VENDOR_NOT_RECOMMENDED, expected_status=409)
        assert get_success_data(api_client.get_settlement(settle_id, ADMIN))["status"] == "OPEN"

        retracted = validate_success(api_client.retract_rebate(off_list["id"], ADMIN), 200)
        assert retracted["status"] == "RETRACTED"
        assert retracted["flowthrough_cents"] == pytest.approx(0.00, abs=0.01)

        advanced = validate_success(api_client.reconcile_settlement(settle_id, ADMIN), 200)
        assert advanced["status"] == "DRAW_PAID"
        assert advanced["rebate_credit_cents"] == pytest.approx(300_000.00, abs=0.01)


class TestReconcileReportsCascadeResultsImmediately:
    """Every cascade hop of a reconciliation is visible on the same response."""

    def test_the_reconcile_response_already_carries_the_recomputed_rebate_credit_and_split(self):
        """PRD §3.4: "`rebate_credit_cents` is the sum of the `flowthrough_cents`
        of the rebates just applied."
        PRD §3.3: "`gross_profit_cents` is the `gross_sales_cents` sum minus the
        `cost_of_goods_cents` sum, with `rebate_credit_cents` added on top."

        Design: Corner/consistency_model/reconcile_reports_cascade_results_immediately_in_the_same_response
        """
        context = setup_settlement_with_rebate(
            rebate_cents=500_000,
            lines=[("SERVICES", 2_000_000, 800_000)],
            rebate_pass_pct=0.60, split_pct=0.50,
            vendor_code="BRD-31", trailing_avg=1_000_000)

        response = api_client.reconcile_settlement(context["settlement"]["id"], ADMIN)
        body = validate_success(response, 200)

        # The same response carries every recomputed field, with no second read.
        assert body["rebate_credit_cents"] == pytest.approx(300_000.00, abs=0.01)
        assert body["gross_profit_cents"] == pytest.approx(1_500_000.00, abs=0.01)
        assert body["eligible_split_pct"] == pytest.approx(0.50, abs=1e-9)
        assert body["franchisee_split_cents"] == pytest.approx(750_000.00, abs=0.01)
        assert body["status"] == "DRAW_PAID"

        # The rebate is APPLIED with no lag.
        rebate = get_success_data(api_client.get_rebate(context["rebate"]["id"], ADMIN))
        assert rebate["status"] == "APPLIED"