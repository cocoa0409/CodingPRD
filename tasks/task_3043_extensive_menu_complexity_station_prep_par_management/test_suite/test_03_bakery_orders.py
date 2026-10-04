"""Bakery orders: provisional vs final slice yield, budget reservation and
release, partial receipt, terminal lockdown, and role split."""

import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    ApiErrorId,
    set_clock, create_restaurant, create_bakery_order,
    create_confirmed_bakery_order, create_bakery_order_payload,
    setup_bakery_env,
    make_pastry_chef_headers, inventory_controller_headers,
    system_admin_headers,
)


class TestSliceYieldVariants:
    def test_receive_sets_provisional_slices(self, api):
        """PRD section 3.7: "When the received count equals the ordered
        count, the order moves to `RECEIVED`; when it falls short, the order
        moves to `PARTIALLY_RECEIVED`. Either way, each received cake is
        assumed to yield fourteen slices, so the order's `provisional_slices`
        is set to the received cake count multiplied by fourteen — the
        provisional yield variant, computed before sell-out is known."

        Design: Difficulty/dual_variant_calc/slice_yield_provisional_vs_final_variants
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        order = create_confirmed_bakery_order(
            env["restaurant"]["id"], env["pastry_id"], whole_cakes_ordered=10)
        received = validate_success(api.receive_bakery_order(
            order["id"], {"whole_cakes_received": 10},
            env["pastry_headers"]))
        assert received["status"] == "RECEIVED"
        assert received["provisional_slices"] == 140

    def test_reconcile_replaces_provisional_with_final(self, api):
        """PRD section 3.7: "The order moves to the terminal `RECONCILED`
        state, the `final_slice_count` is recorded as the final yield
        variant, and `yield_variance` is computed as the final count minus
        `provisional_slices`, so any divergence of actual slicing from the
        fourteen-per-cake assumption surfaces as a nonzero variance."

        Design: Difficulty/dual_variant_calc/slice_yield_provisional_vs_final_variants
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        order = create_confirmed_bakery_order(
            env["restaurant"]["id"], env["pastry_id"], whole_cakes_ordered=10)
        validate_success(api.receive_bakery_order(
            order["id"], {"whole_cakes_received": 10}, env["pastry_headers"]))
        reconciled = validate_success(api.reconcile_yield(
            order["id"], {"final_slice_count": 126}, env["pastry_headers"]))
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["final_slice_count"] == 126
        assert reconciled["yield_variance"] == -14
        assert reconciled["provisional_slices"] == 140
        assert (reconciled["provisional_slices"]
                != reconciled["final_slice_count"])

    def test_partial_receive_then_reconcile_from_partially_received(self, api):
        """PRD section 3.7: "From either `RECEIVED` or `PARTIALLY_RECEIVED` —
        any other state is `ERR_BAKERY_ORDER_INVALID_STATE` — the pastry chef
        reconciles yield by supplying the observed `final_slice_count`."

        Design: Difficulty/dual_variant_calc/slice_yield_provisional_vs_final_variants
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        order = create_confirmed_bakery_order(
            env["restaurant"]["id"], env["pastry_id"], whole_cakes_ordered=10)
        partial = validate_success(api.receive_bakery_order(
            order["id"], {"whole_cakes_received": 6}, env["pastry_headers"]))
        assert partial["status"] == "PARTIALLY_RECEIVED"
        reconciled = validate_success(api.reconcile_yield(
            order["id"], {"final_slice_count": 80}, env["pastry_headers"]))
        assert reconciled["status"] == "RECONCILED"
        assert reconciled["yield_variance"] == 80 - 84


class TestPartialReceive:
    def test_partial_receive_lands_partially_received_with_provisional(self, api):
        """PRD section 3.7: "When the received count equals the ordered
        count, the order moves to `RECEIVED`; when it falls short, the order
        moves to `PARTIALLY_RECEIVED`. Either way, each received cake is
        assumed to yield fourteen slices, so the order's `provisional_slices`
        is set to the received cake count multiplied by fourteen — the
        provisional yield variant, computed before sell-out is known."

        Design: Corner/endpoints/bakery_receive_partial_sets_partially_received
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        order = create_confirmed_bakery_order(
            env["restaurant"]["id"], env["pastry_id"],
            cheesecake_type="STRAWBERRY", whole_cakes_ordered=10)
        received = validate_success(api.receive_bakery_order(
            order["id"], {"whole_cakes_received": 6}, env["pastry_headers"]))
        assert received["status"] == "PARTIALLY_RECEIVED"
        assert received["provisional_slices"] == 84
        reconciled = validate_success(api.reconcile_yield(
            order["id"], {"final_slice_count": 84}, env["pastry_headers"]))
        assert reconciled["status"] == "RECONCILED"


class TestBudgetReservationConservation:
    def test_confirm_reserves_then_cancel_releases_exactly(self, api):
        """PRD section 3.7: "Cancelling a `CONFIRMED` order releases its
        reservation: the whole-cake count times 2500 is subtracted from the
        restaurant's `weekly_bakery_budget_spent_cents` as a compensating
        action, returning the spent figure to its pre-confirm value."

        Design: Difficulty/compensating_invariant/bakery_budget_confirm_then_cancel_conserves_spent
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        rest_id = env["restaurant"]["id"]
        order = create_bakery_order(rest_id, env["pastry_id"],
                                    cheesecake_type="CHOCOLATE",
                                    whole_cakes_ordered=10)
        validate_success(api.submit_bakery_order(
            order["id"], env["pastry_headers"]))
        validate_success(api.confirm_bakery_order(
            order["id"], inventory_controller_headers()))
        rest_mid = validate_success(api.get_restaurant(
            rest_id, inventory_controller_headers()))
        assert rest_mid["weekly_bakery_budget_spent_cents"] == 25000
        cancelled = validate_success(api.cancel_bakery_order(
            order["id"], inventory_controller_headers()))
        assert cancelled["status"] == "CANCELLED"
        rest_after = validate_success(api.get_restaurant(
            rest_id, inventory_controller_headers()))
        assert rest_after["weekly_bakery_budget_spent_cents"] == 0

    def test_cancel_of_draft_touches_no_budget(self, api):
        """PRD section 3.7: "Cancelling a `DRAFT` or `SUBMITTED` order
        touches no budget."

        Design: Difficulty/compensating_invariant/bakery_budget_confirm_then_cancel_conserves_spent
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        rest_id = env["restaurant"]["id"]
        order = create_bakery_order(rest_id, env["pastry_id"],
                                    whole_cakes_ordered=10)
        cancelled = validate_success(api.cancel_bakery_order(
            order["id"], env["pastry_headers"]))
        assert cancelled["status"] == "CANCELLED"
        rest_after = validate_success(api.get_restaurant(
            rest_id, inventory_controller_headers()))
        assert rest_after["weekly_bakery_budget_spent_cents"] == 0


class TestConfirmStateBeatsFiscal:
    def test_confirm_of_draft_order_reports_state_not_budget(self, api):
        """PRD section 2.6: "Fifth, state preconditions on the target and
        its cross-entity guardians are enforced. Only after all of these do
        business-safety gates (allergen review, modification policy,
        segregation of duties), business constraints (certification, overlap,
        rack capacity, budget, active prep-item references), temporal checks,
        and optimistic-concurrency checks run, in that relative order. A
        request that fails an earlier rung never surfaces a later rung's
        error."
        PRD section 3.7: "The order must be `SUBMITTED`, failing which
        `ERR_BAKERY_ORDER_INVALID_STATE` again applies."

        Design: Difficulty/priority_pair_validation_conflict/bakery_confirm_state_beats_fiscal
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        rest_id = env["restaurant"]["id"]
        order = create_bakery_order(rest_id, env["pastry_id"],
                                    cheesecake_type="SEASONAL",
                                    whole_cakes_ordered=100)
        resp = api.confirm_bakery_order(order["id"],
                                        inventory_controller_headers())
        # 100 x 2500 == 250000 > 100000 budget, but the DRAFT state check
        # (earlier rung) masks the budget breach.
        validate_error(resp, ApiErrorId.ERR_BAKERY_ORDER_INVALID_STATE, 409)
        order_now = validate_success(api.get_bakery_order(
            order["id"], env["pastry_headers"]))
        assert order_now["status"] == "DRAFT"
        rest_now = validate_success(api.get_restaurant(
            rest_id, inventory_controller_headers()))
        assert rest_now["weekly_bakery_budget_spent_cents"] == 0

    def test_confirm_of_submitted_over_budget_reports_budget(self, api):
        """PRD section 3.7: "Each whole cake carries a unit cost of 2500
        cents, so confirmation is permitted only while the restaurant's
        `weekly_bakery_budget_spent_cents` plus the order's whole-cake count
        times 2500 does not exceed the restaurant's
        `weekly_bakery_budget_cents`; breaching the cap is rejected with
        `ERR_BAKERY_BUDGET_EXCEEDED`."

        Design: Difficulty/priority_pair_validation_conflict/bakery_confirm_state_beats_fiscal
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        order = create_bakery_order(env["restaurant"]["id"], env["pastry_id"],
                                    cheesecake_type="SEASONAL",
                                    whole_cakes_ordered=100)
        validate_success(api.submit_bakery_order(
            order["id"], env["pastry_headers"]))
        resp = api.confirm_bakery_order(order["id"],
                                        inventory_controller_headers())
        validate_error(resp, ApiErrorId.ERR_BAKERY_BUDGET_EXCEEDED, 402)


class TestConfirmImmediateConsistency:
    def test_confirm_response_and_followup_get_show_debit(self, api):
        """PRD section 1: "All mutations settle their cascades immediately
        inside the request that triggered them: a menu publish that retires a
        prep item, suspends its pars, and cancels its planned batches
        completes as one atomic step."
        PRD section 3.7: "On a successful confirm, the reserved amount —
        whole cakes times 2500 — is added to
        `weekly_bakery_budget_spent_cents`."

        Design: Corner/consistency_model/immediate_consistency_visible_in_same_request_response
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        rest_id = env["restaurant"]["id"]
        order = create_bakery_order(rest_id, env["pastry_id"],
                                    whole_cakes_ordered=4)
        validate_success(api.submit_bakery_order(
            order["id"], env["pastry_headers"]))
        confirmed = validate_success(api.confirm_bakery_order(
            order["id"], inventory_controller_headers()))
        assert confirmed["status"] == "CONFIRMED"
        rest_now = validate_success(api.get_restaurant(
            rest_id, inventory_controller_headers()))
        assert rest_now["weekly_bakery_budget_spent_cents"] == 10000


class TestCancelledTerminalLockdown:
    def test_submit_on_cancelled_order_rejected(self, api):
        """PRD section 3.7: "Cancellation is available to the pastry chef from
        `DRAFT`, and to either the pastry chef or the inventory controller
        from `SUBMITTED` or `CONFIRMED`; cancelling from any other state is
        `ERR_BAKERY_ORDER_INVALID_STATE`."
        PRD section 3.7: "Orders may be listed filtered by `restaurant_id` or
        `status`, and `RECONCILED` and `CANCELLED` are the terminal states."

        Design: Corner/state_machines/bakery_order_cancelled_terminal_lockdown
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        order = create_bakery_order(env["restaurant"]["id"], env["pastry_id"],
                                    whole_cakes_ordered=5)
        validate_success(api.cancel_bakery_order(
            order["id"], env["pastry_headers"]))
        resp = api.submit_bakery_order(order["id"], env["pastry_headers"])
        validate_error(resp, ApiErrorId.ERR_BAKERY_ORDER_INVALID_STATE, 409)
        now = validate_success(api.get_bakery_order(
            order["id"], env["pastry_headers"]))
        assert now["status"] == "CANCELLED"


class TestInvalidCheesecakeType:
    def test_unknown_cheesecake_type_rejected(self, api):
        """PRD section 3.7: "A `PastryChef` drafts an order against a
        `restaurant_id` for a `cheesecake_type` of `ORIGINAL`, `CHOCOLATE`,
        `STRAWBERRY`, or `SEASONAL`, naming a `whole_cakes_ordered` count
        that must be greater than zero; the order begins in `DRAFT`."
        PRD section 2.6: "Second, the request body is validated against the
        endpoint's input schema — required fields present, types correct,
        enum values valid, and integer positivity bounds enforced"
        PRD section 2.6: "any failure here is `ERR_INVALID_REQUEST`."

        Design: Corner/entities/bakery_order_invalid_cheesecake_type_rejected
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        resp = api.create_bakery_order(
            create_bakery_order_payload(env["restaurant"]["id"],
                                        cheesecake_type="MANGO",
                                        whole_cakes_ordered=5),
            env["pastry_headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST, 400)
        data, meta = validate_paginated(api.list_bakery_orders(
            env["pastry_headers"],
            params={"restaurant_id": env["restaurant"]["id"]}))
        assert data == []
        assert meta["total_count"] == 0


class TestPastryChefCannotConfirm:
    def test_pastry_chef_denied_at_confirm(self, api):
        """PRD section 2.10: "A bakery order is drafted, submitted, received,
        and reconciled by the `PastryChef`, but the budget reservation is
        confirmed by a separate `InventoryController`; cancellation may be
        performed by either role, reflecting that unwinding a reservation is
        a shared responsibility."
        PRD section 2.1: "A request whose role is not in the endpoint's
        authorized role list is rejected with `ERR_FORBIDDEN`."

        Design: Corner/rbac/pastry_chef_cannot_confirm_bakery_order
        """
        set_clock("2026-09-01T00:00:00Z")
        env = setup_bakery_env()
        rest_id = env["restaurant"]["id"]
        order = create_bakery_order(rest_id, env["pastry_id"],
                                    whole_cakes_ordered=5)
        validate_success(api.submit_bakery_order(
            order["id"], env["pastry_headers"]))
        resp = api.confirm_bakery_order(order["id"], env["pastry_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, 403)
        order_now = validate_success(api.get_bakery_order(
            order["id"], env["pastry_headers"]))
        assert order_now["status"] == "SUBMITTED"
        rest_now = validate_success(api.get_restaurant(
            rest_id, inventory_controller_headers()))
        assert rest_now["weekly_bakery_budget_spent_cents"] == 0
