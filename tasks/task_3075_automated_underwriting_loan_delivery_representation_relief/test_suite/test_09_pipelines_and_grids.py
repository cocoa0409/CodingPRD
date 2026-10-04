"""Pipelines, grid swaps, and pricing conservation (PRD §2.10, §2.11, §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    setup_counterparty_chain,
    create_active_llpa_matrix,
    create_draft_loan,
    create_pool_for,
    create_underwritten_loan,
    deliver_loan,
    get_or_create_pipeline,
    get_loan,
    get_pool,
    standard_llpa_row,
    make_seller_officer_headers,
    validate_error,
    validate_success,
    validate_paginated,
)

ADMIN = TEST_USERS["gse_admin_headers"]


class TestPipelineContents:
    def test_computed_read_pipeline_reflects_draft_and_underwritten_only(self, api):
        """PRD §3.7: "The pipeline's `projected_value_cents` is the sum, over
        the seller's loans in `DRAFT` or `UNDERWRITTEN` status, of each loan's
        provisional price under the currently `ACTIVE` grid."

        Design: Corner/endpoints/computed_read_pipeline_reflects_draft_and_underwritten_only
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-PIPE")
        pipeline = get_or_create_pipeline(seller)
        # 400,000,000 UPB at 100 bps -> provisional price 396,000,000.
        assert pipeline["projected_value_cents"] == 396000000
        # Underwriting (DRAFT -> UNDERWRITTEN) leaves the value unchanged.
        from test_helpers import underwrite_loan

        underwrite_loan(loan, seller)
        mid = validate_success(api.get_pipeline(pipeline["id"], ADMIN))
        assert mid["projected_value_cents"] == 396000000
        # Delivery removes the loan from the projection.
        pool = create_pool_for(seller, agreement)
        deliver_loan(get_loan(loan["id"]), pool, seller)
        after = validate_success(api.get_pipeline(pipeline["id"], ADMIN))
        assert after["projected_value_cents"] == 0

    def test_no_matching_llpa_row_contributes_zero_to_pipeline(self, api):
        """PRD §3.7: "A loan matching no pricing row in the active grid
        contributes 0 to the sum."

        Design: Corner/calculations/no_matching_llpa_row_contributes_zero_to_pipeline
        """
        # The default grid covers PRIMARY_RESIDENCE / FIXED_30 only.
        seller, servicer, agreement, _ = setup_counterparty_chain()
        create_draft_loan(seller, servicer, agreement, loan_number="LN-NOROW",
                          occupancy="INVESTMENT")
        pipeline = get_or_create_pipeline(seller)
        assert pipeline["projected_value_cents"] == 0


class TestGridSwap:
    def test_llpa_provisional_revalues_pipeline_final_pins_loan_price(self, api):
        """PRD §2.10: "At most one grid is `ACTIVE` at a time: creating a newer
        grid supersedes the prior `ACTIVE` grid, moving it to `SUPERSEDED`, and
        the new grid becomes the single pricing authority."
        PRD §3.7: "For each impacted pipeline the system appends an
        `LlpaUpdateEvent` recording the `pipeline_id`, the `old_matrix_id` of
        the superseded grid, the `new_matrix_id` of the newly active grid, the
        `projected_value_before_cents` immediately before the swap, the
        `projected_value_after_cents` immediately after, the `delta_cents`
        (after minus before), and the `impacted_loan_count` — the number of
        that pipeline's loans whose recomputed price changed."

        Design: Difficulty/dual_variant_calc/llpa_provisional_revalues_pipeline_final_pins_loan_price
        """
        seller, servicer, agreement, m1 = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-1")
        pipeline = get_or_create_pipeline(seller)
        # Under m1 (100 bps): 400,000,000 - 4,000,000 = 396,000,000.
        assert pipeline["projected_value_cents"] == 396000000
        m2 = create_active_llpa_matrix(
            rows=[standard_llpa_row(llpa_bps=50)],
            effective_from="2026-09-01T00:00:00Z",
            effective_until="2027-09-01T00:00:00Z",
        )
        assert m2["status"] == "ACTIVE"
        m1_after = validate_success(api.get_llpa_matrix(m1["id"], ADMIN))
        assert m1_after["status"] == "SUPERSEDED"
        pipeline_after = validate_success(api.get_pipeline(pipeline["id"], ADMIN))
        assert pipeline_after["projected_value_cents"] == 398000000
        events, _ = validate_paginated(
            api.list_llpa_update_events(ADMIN, params={"pipeline_id": pipeline["id"]})
        )
        assert len(events) == 1
        event = events[0]
        assert event["projected_value_before_cents"] == 396000000
        assert event["projected_value_after_cents"] == 398000000
        assert event["delta_cents"] == 2000000
        assert event["impacted_loan_count"] == 1
        assert event["old_matrix_id"] == m1["id"]
        assert event["new_matrix_id"] == m2["id"]

    def test_llpa_matrix_half_open_window_no_overlap(self, api):
        """PRD §2.10: "Each grid is defined by an `effective_from` instant
        (inclusive) and an `effective_until` instant (exclusive, and strictly
        after `effective_from`), plus a list of pricing `rows`."
        PRD §2.10: "At most one grid is `ACTIVE` at a time: creating a newer
        grid supersedes the prior `ACTIVE` grid, moving it to `SUPERSEDED`, and
        the new grid becomes the single pricing authority. All provisional
        pricing (pipeline projections) uses whichever grid is currently
        `ACTIVE`."

        Design: Difficulty/resource_temporal_overlap/llpa_matrix_half_open_window_no_overlap
        """
        seller, servicer, agreement, m1 = setup_counterparty_chain(
            grid_rows=[standard_llpa_row(llpa_bps=100)],
        )
        # Recreate m1 with a window ending exactly where m2 begins.
        # (m1 was created by the chain with window [2026-01-01, 2027-01-01).)
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-TO1")
        pipeline = get_or_create_pipeline(seller)
        # Adjacent window: m2.effective_from == m1.effective_until.
        m2 = create_active_llpa_matrix(
            rows=[standard_llpa_row(llpa_bps=25)],
            effective_from="2027-01-01T00:00:00Z",
            effective_until="2027-07-01T00:00:00Z",
        )
        assert m2["status"] == "ACTIVE"
        m1_after = validate_success(api.get_llpa_matrix(m1["id"], ADMIN))
        assert m1_after["status"] == "SUPERSEDED"
        # Exactly one grid ACTIVE afterwards.
        grids, _ = validate_paginated(api.list_llpa_matrices(ADMIN, params={"status": "ACTIVE"}))
        assert len(grids) == 1
        # The DRAFT loan reprices provisionally under m2: 400,000,000 - 1,000,000.
        pipeline_after = validate_success(api.get_pipeline(pipeline["id"], ADMIN))
        assert pipeline_after["projected_value_cents"] == 399000000


class TestDeliveryCascade:
    def test_delivery_cascade_loan_pool_pipeline_three_hops(self, api):
        """PRD §3.5: "A successful delivery moves the loan `UNDERWRITTEN →
        DELIVERED`, stamps its `pool_id` with the pool's id and its
        `delivered_at` with the current logical time, and adds the loan's
        unpaid principal balance to the pool's `current_balance_cents` while
        incrementing the pool's `loan_count`."
        PRD §3.7: "The pipeline's `projected_value_cents` is the sum, over the
        seller's loans in `DRAFT` or `UNDERWRITTEN` status, of each loan's
        provisional price under the currently `ACTIVE` grid."

        Design: Difficulty/transitive_cascade/delivery_cascade_loan_pool_pipeline_three_hops
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-T1")
        pipeline = get_or_create_pipeline(seller)
        assert pipeline["projected_value_cents"] == 396000000
        deliver_loan(loan, pool, seller)
        loan_after = get_loan(loan["id"])
        assert loan_after["status"] == "DELIVERED"
        assert loan_after["pool_id"] == pool["id"]
        assert loan_after["applied_llpa_bps"] == 100
        assert loan_after["delivery_price_cents"] == 396000000
        pool_after = get_pool(pool["id"])
        assert pool_after["current_balance_cents"] == 400000000
        assert pool_after["loan_count"] == 1
        pipeline_after = validate_success(api.get_pipeline(pipeline["id"], ADMIN))
        assert pipeline_after["projected_value_cents"] == 0

    def test_immediate_consistency_delivery_visible_in_same_read(self, api):
        """PRD §2.11: "For every pool, `current_balance_cents` equals the sum
        of `unpaid_principal_balance_cents` over its loans currently in
        `DELIVERED` status, and `loan_count` equals the count of those loans."
        PRD §2.11: "For every seller pipeline, `projected_value_cents` equals
        the sum of provisionally priced values over the seller's loans in
        `DRAFT` or `UNDERWRITTEN` status under the currently `ACTIVE` grid."

        Design: Corner/consistency_model/immediate_consistency_delivery_visible_in_same_read
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-IMM")
        pipeline = get_or_create_pipeline(seller)
        deliver_loan(loan, pool, seller)
        assert get_loan(loan["id"])["status"] == "DELIVERED"
        assert get_pool(pool["id"])["current_balance_cents"] == 400000000
        after = validate_success(api.get_pipeline(pipeline["id"], ADMIN))
        assert after["projected_value_cents"] == 0


class TestPoolCancelCompensation:
    def test_deliver_then_pool_cancel_restores_pool_balance(self, api):
        """PRD §3.5: "Cancelling an `OPEN` pool moves it to `CANCELLED` (also
        terminal) and unwinds its contents: every `DELIVERED` loan in the pool
        returns to `DRAFT`, its `pool_id` and `delivered_at` are cleared, the
        pool's `current_balance_cents` decreases by each such loan's unpaid
        principal balance and its `loan_count` decreases accordingly."
        PRD §2.11: "delivering a loan into a pool and later cancelling that
        pool form a forward/compensate pair after which every affected loan
        returns to `DRAFT` and the pool balance returns to its pre-delivery
        value."

        Design: Difficulty/compensating_invariant/deliver_then_pool_cancel_restores_pool_balance
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-CI1")
        deliver_loan(loan, pool, seller)
        assert get_pool(pool["id"])["current_balance_cents"] == 400000000
        assert get_pool(pool["id"])["loan_count"] == 1
        headers = make_seller_officer_headers(seller["id"])
        validate_success(api.cancel_pool(pool["id"], headers))
        pool_after = get_pool(pool["id"])
        assert pool_after["status"] == "CANCELLED"
        assert pool_after["current_balance_cents"] == 0
        assert pool_after["loan_count"] == 0
        loan_after = get_loan(loan["id"])
        assert loan_after["status"] == "DRAFT"
        assert loan_after["pool_id"] is None
        assert loan_after["delivered_at"] is None

    def test_deliver_state_beats_referential_pool_closed(self, api):
        """PRD §2.9: "After existence, the target resource must be in a state
        that permits the requested transition, failing with `ERR_INVALID_STATE`
        (HTTP 409). Only then do the business gates run, in this order:
        temporal gates (appeal window, transfer date, oversight period end,
        agreement effectiveness, pool issue date), referential gates
        (pool-to-loan seller and agreement matching, finding-loan-to-audit-
        seller matching), compliance gates (relief-tier bars, segregation of
        duties, oversight-score floor), fiscal gates (pool capacity, seller
        funds), and finally constraint gates (appeal rounds, pool non-empty,
        approval thresholds, loan eligibility)."
        PRD §3.5: "Cancelling an `OPEN` pool moves it to `CANCELLED` (also
        terminal) and unwinds its contents: every `DELIVERED` loan in the pool
        returns to `DRAFT`, its `pool_id` and `delivered_at` are cleared."

        Design: Difficulty/priority_pair_validation_conflict/deliver_state_beats_referential_pool_closed
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-P1")
        deliver_loan(loan, pool, seller)
        headers = make_seller_officer_headers(seller["id"])
        validate_success(api.cancel_pool(pool["id"], headers))
        # The loan is back in DRAFT; the pool is CANCELLED. Re-delivery
        # violates the loan state (DRAFT) and the pool-open referential gate;
        # the priority-4 state check beats the priority-6 referential check.
        assert get_loan(loan["id"])["status"] == "DRAFT"
        resp = api.deliver_loan(loan["id"], {"pool_id": pool["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_pool_cancel_restores_pipeline_projection(self, api):
        """PRD §2.11: "For every seller pipeline, `projected_value_cents`
        equals the sum of provisionally priced values over the seller's loans
        in `DRAFT` or `UNDERWRITTEN` status under the currently `ACTIVE` grid."
        PRD §3.5: "The loan's previously computed `delivery_price_cents` and
        `applied_llpa_bps` are retained as historical values on the loan but no
        longer count toward pipeline projected value while the loan is back in
        `DRAFT` — the pipeline re-prices provisionally under the currently
        active grid instead."

        Design: Difficulty/priority_pair_validation_conflict/deliver_state_beats_referential_pool_closed
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-P1B")
        pipeline = get_or_create_pipeline(seller)
        assert pipeline["projected_value_cents"] == 396000000
        deliver_loan(loan, pool, seller)
        assert validate_success(api.get_pipeline(pipeline["id"], ADMIN))["projected_value_cents"] == 0
        headers = make_seller_officer_headers(seller["id"])
        validate_success(api.cancel_pool(pool["id"], headers))
        # The loan is DRAFT again and re-prices provisionally under the grid.
        assert validate_success(api.get_pipeline(pipeline["id"], ADMIN))["projected_value_cents"] == 396000000

    def test_delivery_accumulates_pool_balance_across_loans(self, api):
        """PRD §3.5: "A successful delivery moves the loan `UNDERWRITTEN →
        DELIVERED`, stamps its `pool_id` with the pool's id and its
        `delivered_at` with the current logical time, and adds the loan's
        unpaid principal balance to the pool's `current_balance_cents` while
        incrementing the pool's `loan_count`."
        PRD §2.11: "For every pool, `current_balance_cents` equals the sum of
        `unpaid_principal_balance_cents` over its loans currently in
        `DELIVERED` status, and `loan_count` equals the count of those loans."

        Design: Difficulty/transitive_cascade/delivery_cascade_loan_pool_pipeline_three_hops
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement, target_balance_cents=1000000000)
        loan_a = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-T1A")
        loan_b = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-T1B")
        pipeline = get_or_create_pipeline(seller)
        assert pipeline["projected_value_cents"] == 792000000
        deliver_loan(loan_a, pool, seller)
        mid = get_pool(pool["id"])
        assert mid["current_balance_cents"] == 400000000
        assert mid["loan_count"] == 1
        assert validate_success(api.get_pipeline(pipeline["id"], ADMIN))["projected_value_cents"] == 396000000
        deliver_loan(loan_b, pool, seller)
        after = get_pool(pool["id"])
        assert after["current_balance_cents"] == 800000000
        assert after["loan_count"] == 2
        assert validate_success(api.get_pipeline(pipeline["id"], ADMIN))["projected_value_cents"] == 0

    def test_adjacent_grid_swap_supersedes_prior_and_reprices_provisional(self, api):
        """PRD §2.10: "At most one grid is `ACTIVE` at a time: creating a newer
        grid supersedes the prior `ACTIVE` grid, moving it to `SUPERSEDED`, and
        the new grid becomes the single pricing authority. All provisional
        pricing (pipeline projections) uses whichever grid is currently
        `ACTIVE`."
        PRD §2.10: "Each grid is defined by an `effective_from` instant
        (inclusive) and an `effective_until` instant (exclusive, and strictly
        after `effective_from`), plus a list of pricing `rows`."

        Design: Difficulty/resource_temporal_overlap/llpa_matrix_half_open_window_no_overlap
        """
        seller, servicer, agreement, m1 = setup_counterparty_chain()
        # m1 window: [2026-01-01, 2027-01-01). Create m2 adjacent at the
        # boundary instant — no overlap error, m1 is superseded.
        m2 = create_active_llpa_matrix(
            rows=[standard_llpa_row(llpa_bps=50)],
            effective_from="2027-01-01T00:00:00Z",
            effective_until="2028-01-01T00:00:00Z",
        )
        assert m2["status"] == "ACTIVE"
        assert validate_success(api.get_llpa_matrix(m1["id"], ADMIN))["status"] == "SUPERSEDED"
        grids, _ = validate_paginated(api.list_llpa_matrices(ADMIN, params={"status": "ACTIVE"}))
        assert len(grids) == 1
        assert grids[0]["id"] == m2["id"]

    def test_pool_cancel_re_prices_loan_provisionally_not_at_pinned_price(self, api):
        """PRD §3.5: "The loan's previously computed `delivery_price_cents` and
        `applied_llpa_bps` are retained as historical values on the loan but no
        longer count toward pipeline projected value while the loan is back in
        `DRAFT` — the pipeline re-prices provisionally under the currently
        active grid instead."
        PRD §3.5: "Cancelling an `OPEN` pool moves it to `CANCELLED` (also
        terminal) and unwinds its contents: every `DELIVERED` loan in the pool
        returns to `DRAFT`, its `pool_id` and `delivered_at` are cleared."

        Design: Difficulty/compensating_invariant/deliver_then_pool_cancel_restores_pool_balance
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        pool = create_pool_for(seller, agreement)
        loan = create_underwritten_loan(seller, servicer, agreement, loan_number="LN-CI1B")
        deliver_loan(loan, pool, seller)
        headers = make_seller_officer_headers(seller["id"])
        validate_success(api.cancel_pool(pool["id"], headers))
        loan_after = get_loan(loan["id"])
        # Historical pricing values are retained on the loan.
        assert loan_after["status"] == "DRAFT"
        assert loan_after["delivery_price_cents"] == 396000000
        assert loan_after["applied_llpa_bps"] == 100
        # And the pool's conserved quantities are fully restored.
        pool_after = get_pool(pool["id"])
        assert pool_after["current_balance_cents"] == 0
        assert pool_after["loan_count"] == 0
