"""The complementary half of each boundary and ordering claim.

Each test here is the counterpart of one in the earlier files: where the first
half pins the refusal edge, this half pins the acceptance edge, the opposite
interval direction, or the isolated single-rule scenario the ordering claim
implies.
"""

import pytest

from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated, get_success_data,
    ApiErrorId, ADMIN, COMMISSARY, set_clock, create_franchisee, create_store,
    create_agreement, create_open_settlement, add_revenue_lines, create_draw,
    create_delivery_window, place_fresh_order, confirm_fresh_order,
    lock_delivery_window, deliver_fresh_order, reconcile_settlement,
    refresh_window, refresh_store, refresh_franchisee, setup_store_with_agreement,
    setup_settlement_with_lines, setup_window_with_orders, make_franchisee_headers,
)

WINDOW_START = "2026-09-08T06:00:00Z"
WINDOW_END = "2026-09-08T10:00:00Z"
INSIDE_WINDOW = "2026-09-08T07:00:00Z"


class TestCapacityBoundaryIsPerWindow:
    """Each window carries its own capacity; the boundary is not shared."""

    def test_each_window_accepts_its_own_capacity_and_refuses_one_unit_past_it(self):
        """PRD §3.5: "The booking must not exceed capacity — the window's
        `reserved_units` plus the `ordered_units` being booked must be at most
        the window's `capacity_units`, with the exact boundary permitted".

        Design: Difficulty/boundary_precision_check/delivery_window_capacity_boundary_is_inclusive_and_order_quantity_one_over_is_rejected
        """
        set_clock("2026-09-01T12:00:00Z")
        context = setup_store_with_agreement(
            clock="2026-09-01T12:00:00Z",
            store_overrides={"cold_chain_certified": True})
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]

        small = create_delivery_window(
            store_id, "2026-09-11T06:00:00Z", "2026-09-11T10:00:00Z", 100,
            commissary_code="COMM-A")
        place_fresh_order(store_id, small["id"], franchisee_id, "SKU-A", 100, 100)
        assert refresh_window(small["id"])["reserved_units"] == 100

        past = api_client.create_fresh_order(
            {"store_id": store_id, "delivery_window_id": small["id"],
             "sku_code": "SKU-A2", "ordered_units": 1, "unit_cost_cents": 100},
            make_franchisee_headers(franchisee_id))
        validate_error(past, ApiErrorId.ERR_WINDOW_CAPACITY_EXCEEDED, expected_status=409)

        # A second window keeps its own independent allowance.
        other = create_delivery_window(
            store_id, "2026-09-12T06:00:00Z", "2026-09-12T10:00:00Z", 50,
            commissary_code="COMM-B")
        place_fresh_order(store_id, other["id"], franchisee_id, "SKU-B", 50, 100)
        assert refresh_window(other["id"])["reserved_units"] == 50
        assert refresh_window(small["id"])["reserved_units"] == 100


class TestDrawOutstandingAggregatesOnlyLiveDraws:
    """Only ISSUED and PARTIALLY_RECOVERED advances count toward the figure."""

    def test_reversed_and_recovered_draws_both_drop_out_of_the_outstanding_figure(self):
        """PRD §2.7: "The `draw_outstanding_cents` figure is the sum, across every
        draw advance belonging to that operator that is in status `ISSUED` or
        `PARTIALLY_RECOVERED`, of the advance's `amount_cents` minus its
        `recovered_cents`."

        Design: Difficulty/compensating_invariant/franchisee_draw_outstanding_cents_restored_by_reversal_and_guarded_after_recovery
        """
        set_clock("2026-09-20T00:00:00Z")
        context = setup_settlement_with_lines(
            lines=[("MERCHANDISE", 4_000_000, 2_000_000)],
            split_pct=0.50, rebate_pass_pct=1.0, trailing_avg=1_000_000,
            clock="2026-09-20T00:00:00Z",
        )
        franchisee_id = context["franchisee"]["id"]
        store_id = context["store"]["id"]
        settle_id = context["settlement"]["id"]

        reversed_draw = create_draw(franchisee_id, store_id, 1_500_000,
                                    drawn_on="2026-09-02T00:00:00Z")
        covered_draw = create_draw(franchisee_id, store_id, 1_000_000,
                                   drawn_on="2026-09-03T00:00:00Z")
        assert refresh_franchisee(franchisee_id)["draw_outstanding_cents"] == 2_500_000

        validate_success(api_client.reverse_draw(reversed_draw["id"], ADMIN), 200)

        reconcile_settlement(settle_id)
        frozen = reconcile_settlement(settle_id)
        # A split base of 2,000,000 at 0.50 pays 1,000,000.00, covering the whole draw.
        assert frozen["net_settlement_cents"] == pytest.approx(1_000_000.00, abs=0.01)
        set_clock("2026-09-16T12:00:00Z")
        validated = validate_success(api_client.finalize_settlement(settle_id, ADMIN), 200)

        covered_after = get_success_data(api_client.get_draw(covered_draw["id"], ADMIN))
        assert covered_after["status"] == "RECOVERED"
        assert covered_after["recovered_cents"] == covered_after["amount_cents"]

        # Neither a REVERSED draw nor a RECOVERED one contributes anything.
        operator = refresh_franchisee(franchisee_id)
        assert operator["draw_outstanding_cents"] == 0
        assert validated["draw_recovery_cents"] == pytest.approx(1_000_000.00, abs=0.01)


class TestStoreCascadeIsTheThirdReleasePath:
    """The store-level cascade releases reserved capacity just as cancellation does."""

    def test_terminating_the_operator_releases_the_reserved_units_of_its_store(self):
        """PRD §3.5: "every path by which an order leaves the reserved set —
        cancellation, reconciliation, or the store-level cascade — releases the
        same `ordered_units` back out of `reserved_units`."
        PRD §3.8: "Every fresh order for that store still in `PLACED`,
        `CONFIRMED` or `DELIVERED` is cancelled, and each cancellation releases
        the order's `ordered_units` from its bound window's `reserved_units`."

        Design: Difficulty/compensating_invariant/window_reserved_units_returns_to_zero_by_cancel_and_by_reconcile
        """
        set_clock("2026-09-01T00:00:00Z")
        context = setup_store_with_agreement(
            clock="2026-09-01T00:00:00Z",
            store_overrides={"cold_chain_certified": True})
        store_id = context["store"]["id"]
        window = create_delivery_window(store_id, WINDOW_START, WINDOW_END, 1000)
        order = place_fresh_order(store_id, window["id"], context["franchisee"]["id"],
                                 "SKU-C1", 400, 300)
        assert refresh_window(window["id"])["reserved_units"] == 400

        validate_success(
            api_client.terminate_franchisee(context["franchisee"]["id"], ADMIN), 200)

        assert get_success_data(
            api_client.get_fresh_order(order["id"], ADMIN))["status"] == "CANCELLED"
        assert refresh_window(window["id"])["reserved_units"] == 0
        assert refresh_store(store_id)["status"] == "TERMINATED"


class TestAgreementActivationAccepted:
    """The acceptance edge of the store-state gate on activation."""

    def test_an_agreement_on_an_active_store_with_a_cleared_floor_activates_and_starts_standard(self):
        """PRD §3.2: "On success the agreement enters `ACTIVE`, its
        `performance_tier` is set to `STANDARD`, and the operator's
        `audit_adjusted_net_worth_cents` is recomputed".
        PRD §3.2: "the operator's `stated_net_worth_cents` must be at least the
        agreement's `minimum_net_worth_cents`".

        Design: Difficulty/cross_entity_state_dependency/agreement_activate_requires_the_covering_store_to_be_active
        """
        set_clock("2026-09-01T12:00:00Z")
        franchisee = create_franchisee(stated_net_worth_cents=20_000_000)
        store = create_store(franchisee["id"])
        agreement = create_agreement(
            franchisee["id"], store["id"], activate=False,
            minimum_net_worth_cents=10_000_000)
        assert agreement["status"] == "DRAFT"

        activated = validate_success(
            api_client.activate_agreement(agreement["id"], ADMIN), 200)
        assert activated["status"] == "ACTIVE"
        assert activated["performance_tier"] == "STANDARD"
        assert activated["royalty_pct"] == 0.0
        assert activated["version"] > agreement["version"]
        assert refresh_store(store["id"])["status"] == "ACTIVE"


class TestConfirmAndDeliverSucceedWhenTheirWindowIsRight:
    """The acceptance edge of the opposite window requirements."""

    def test_confirming_under_a_scheduled_window_then_delivering_under_a_locked_one_completes(self):
        """PRD §3.5: "on success the order becomes `CONFIRMED`."
        PRD §3.5: "A successful delivery moves the order to `DELIVERED` and
        records the delivered figure."

        Design: Difficulty/cross_entity_state_dependency/fresh_order_confirm_and_deliver_gate_on_the_bound_window_state
        """
        context = setup_window_with_orders(
            orders=[("SKU-O1", 200, 299)],
            window_start=WINDOW_START, window_end=WINDOW_END,
            confirm=True, lock=True, deliver=True, delivery_clock=INSIDE_WINDOW,
        )
        order = context["orders"][0]
        assert order["status"] == "DELIVERED"
        assert order["delivered_units"] == 200

        read = get_success_data(api_client.get_fresh_order(order["id"], ADMIN))
        assert read["status"] == "DELIVERED"
        assert read["delivered_units"] == 200
        assert read["unit_cost_cents"] == 299
        assert refresh_window(context["window"]["id"])["status"] == "LOCKED"


class TestColdChainRuleInIsolation:
    """The safety rule fires on its own, without any capacity breach."""

    def test_an_uncertified_store_is_refused_within_capacity_bounds(self):
        """PRD §3.5: "The ordering store must be cold-chain certified; a store
        whose `cold_chain_certified` flag is false is rejected with
        `ERR_COLD_CHAIN_BROKEN` (HTTP 409)."
        PRD §3.1: "The `cold_chain_certified` flag is a live gate rather than an
        annotation — it is re-checked at the moment a fresh-food order is placed,
        not merely at store creation".

        Design: Difficulty/priority_pair_validation_conflict/cold_chain_failure_precedes_capacity_overrun_on_fresh_order
        """
        set_clock("2026-09-01T12:00:00Z")
        context = setup_store_with_agreement(
            clock="2026-09-01T12:00:00Z",
            store_overrides={"cold_chain_certified": False})
        store_id = context["store"]["id"]
        franchisee_id = context["franchisee"]["id"]
        window = create_delivery_window(store_id, WINDOW_START, WINDOW_END, 1000)

        # Well inside capacity, so only the certification rule can fire.
        response = api_client.create_fresh_order(
            {"store_id": store_id, "delivery_window_id": window["id"],
             "sku_code": "SKU-T1", "ordered_units": 10, "unit_cost_cents": 100},
            make_franchisee_headers(franchisee_id))
        validate_error(response, ApiErrorId.ERR_COLD_CHAIN_BROKEN, expected_status=409)
        assert refresh_window(window["id"])["reserved_units"] == 0


class TestNetWorthFloorInIsolation:
    """The fiscal rule fires on its own, with the store in good standing."""

    def test_a_short_stated_net_worth_blocks_activation_on_a_store_that_is_active(self):
        """PRD §3.2: "Only then is the operator's fiscal floor examined: the
        operator's `stated_net_worth_cents` must be at least the agreement's
        `minimum_net_worth_cents`, and a shortfall is rejected with
        `ERR_MIN_NET_WORTH_NOT_MET` (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/stated_net_worth_failure_precedes_store_not_active_on_agreement_activate
        """
        set_clock("2026-09-01T12:00:00Z")
        franchisee = create_franchisee(stated_net_worth_cents=9_000_000)
        store = create_store(franchisee["id"])
        assert refresh_store(store["id"])["status"] == "ACTIVE"

        agreement = create_agreement(
            franchisee["id"], store["id"], activate=False,
            minimum_net_worth_cents=10_000_000)

        response = api_client.activate_agreement(agreement["id"], ADMIN)
        error = validate_error(response, ApiErrorId.ERR_MIN_NET_WORTH_NOT_MET, expected_status=409)
        assert error["error_id"] != ApiErrorId.ERR_STORE_NOT_ACTIVE.value
        assert get_success_data(
            api_client.get_agreement(agreement["id"], ADMIN))["status"] == "DRAFT"


class TestHandlingBufferIsScopedToTheSameCommissary:
    """The buffer compares windows of the same store and commissary only."""

    def test_a_window_of_a_different_commissary_may_start_alongside_an_existing_one(self):
        """PRD §3.5: "Windows for the same store and the same commissary are kept
        apart by a handling buffer: a new window must not start inside the 30
        minutes that follow another non-cancelled window's end".

        Design: Difficulty/resource_temporal_overlap/delivery_window_handling_buffer_rejects_abutting_windows
        """
        set_clock("2026-09-01T12:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-01T12:00:00Z")
        store_id = context["store"]["id"]

        create_delivery_window(store_id, WINDOW_START, WINDOW_END, 500,
                               commissary_code="COMM-TX-9")

        # A different commissary is not buffered against the first.
        alongside = validate_success(
            api_client.create_delivery_window(
                {"store_id": store_id, "commissary_code": "COMM-TX-10",
                 "day_of_week": "TUE", "window_start": "2026-09-08T10:05:00Z",
                 "window_end": "2026-09-08T14:00:00Z", "capacity_units": 400}, ADMIN), 201)
        assert alongside["status"] == "SCHEDULED"
        assert alongside["commissary_code"] == "COMM-TX-10"

        listed, meta = validate_paginated(
            api_client.list_delivery_windows(ADMIN, {"store_id": store_id}))
        assert meta["total_count"] == 2


class TestAuditPeriodAdjacencyIsSymmetric:
    """Half-open periods may abut at either endpoint."""

    def test_a_period_ending_exactly_on_another_periods_start_is_accepted(self):
        """PRD §3.6: "A new audit period may not overlap another non-cancelled
        audit for the same store; periods that merely share an endpoint are
        permitted, but any true overlap is rejected with
        `ERR_AUDIT_PERIOD_OVERLAP` (HTTP 409)."
        PRD §2.9: "The audit cadence rule measures from an exclusive period end
        to an inclusive period start."

        Design: Difficulty/resource_temporal_overlap/shrink_audit_half_open_adjacency_is_allowed_but_true_overlap_is_not
        """
        set_clock("2026-09-01T12:00:00Z")
        context = setup_store_with_agreement(clock="2026-09-01T12:00:00Z")
        store_id = context["store"]["id"]

        # An earlier period ending exactly where the target period starts.
        earlier = validate_success(
            api_client.create_shrink_audit(
                {"store_id": store_id, "period_start": "2026-07-01T00:00:00Z",
                 "period_end": "2026-08-01T00:00:00Z",
                 "book_inventory_cents": 6_000_000}, ADMIN), 201)
        assert earlier["status"] == "SCHEDULED"

        abutting = validate_success(
            api_client.create_shrink_audit(
                {"store_id": store_id, "period_start": "2026-08-01T00:00:00Z",
                 "period_end": "2026-09-01T00:00:00Z",
                 "book_inventory_cents": 6_000_000}, ADMIN), 201)
        assert abutting["status"] == "SCHEDULED"

        # A period wholly inside an existing one is a true overlap.
        inside = api_client.create_shrink_audit(
            {"store_id": store_id, "period_start": "2026-08-10T00:00:00Z",
             "period_end": "2026-08-20T00:00:00Z",
             "book_inventory_cents": 1_000_000}, ADMIN)
        validate_error(inside, ApiErrorId.ERR_AUDIT_PERIOD_OVERLAP, expected_status=409)

        listed, meta = validate_paginated(
            api_client.list_shrink_audits(ADMIN, {"store_id": store_id}))
        assert meta["total_count"] == 2


class TestCascadeLeavesNonOpenSettlementsAlone:
    """Only OPEN and DRAW_PAID weeks are driven to FINALIZED by the cascade."""

    def test_a_reconciled_week_survives_the_termination_cascade(self):
        """PRD §3.8: "every settlement for that store still in `OPEN` or
        `DRAW_PAID` is driven straight to `FINALIZED`, which runs the draw
        recovery waterfall against those settlements' net figures."

        Design: Difficulty/transitive_cascade/franchisee_terminate_cascades_store_then_cancels_order_then_finalizes_settlement
        """
        set_clock("2026-09-01T12:00:00Z")
        franchisee = create_franchisee(stated_net_worth_cents=30_000_000)
        store = create_store(franchisee["id"], cold_chain_certified=True)
        create_agreement(franchisee["id"], store["id"], rebate_pass_pct=1.0)

        settlement = create_open_settlement(store, franchisee, trailing_avg=1_000_000)
        add_revenue_lines(settlement, [("SERVICES", 2_000_000, 1_000_000)])
        reconcile_settlement(settlement["id"])
        reconciled = reconcile_settlement(settlement["id"])
        assert reconciled["status"] == "RECONCILED"

        validate_success(api_client.terminate_franchisee(franchisee["id"], ADMIN), 200)

        # The store closed, but the already-reconciled week was not reopened.
        assert refresh_store(store["id"])["status"] == "TERMINATED"
        after = get_success_data(
            api_client.get_settlement(settlement["id"], ADMIN))
        assert after["status"] == "RECONCILED"
        assert after["provisional"] is False