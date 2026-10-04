"""Settlement: dual-variant venue share, royalty waterfall, dispute loop, OCC."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_date_avail,
    create_engagement,
    create_license_agreement,
    create_ticket_scale,
    reconcile_engagement,
    record_ticket_sale,
    setup_confirmed_engagement,
    setup_in_performance_engagement,
    setup_reconciled_settlement,
    setup_tour_and_venue,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)

TM = TEST_USERS["tour_manager_headers"]
VB = TEST_USERS["venue_booker_headers"]
LM = TEST_USERS["licensing_manager_headers"]


class TestVenueShareDualVariant:
    def test_flat_rent_ignores_gross(self):
        """PRD §3.9: "Under a `FLAT_RENT` deal, `venue_share_cents` is simply
        `agreed_rent_cents`, regardless of gross."

        Design: Difficulty/dual_variant_calc/venue_share_flat_rent_vs_percentage_floor_binds
        """
        ctx = setup_reconciled_settlement(
            engagement_overrides={"deal_type": "FLAT_RENT", "agreed_rent_cents": 4000000},
        )
        settlement = ctx["settlement"]
        assert settlement["gross_ticket_cents"] == 10000000
        assert settlement["venue_share_cents"] == 4000000

    def test_percentage_floor_binds_when_pct_share_below_rent(self):
        """PRD §3.9: "Under a `PERCENTAGE` deal, the gross is multiplied by the
        venue's `percentage_share_pct`, rounded half-up to integer cents after
        the multiplication (never per line), and the venue takes the larger of
        that percentage share and `agreed_rent_cents` — the contracted rent is a
        floor the venue never falls below, even on a zero-sales engagement."

        Design: Difficulty/dual_variant_calc/venue_share_flat_rent_vs_percentage_floor_binds
        """
        ctx = setup_reconciled_settlement(
            engagement_overrides={"deal_type": "PERCENTAGE", "agreed_rent_cents": 4000000},
            venue_overrides={"percentage_share_pct": 0.30},
        )
        settlement = ctx["settlement"]
        # max(4000000, round(10000000 * 0.30)=3000000) = 4000000 — floor binds.
        assert settlement["gross_ticket_cents"] == 10000000
        assert settlement["venue_share_cents"] == 4000000

    def test_percentage_share_exceeds_floor_when_gross_high(self):
        """PRD §3.9: "Under a `PERCENTAGE` deal, the gross is multiplied by the
        venue's `percentage_share_pct`, rounded half-up to integer cents after
        the multiplication (never per line), and the venue takes the larger of
        that percentage share and `agreed_rent_cents` — the contracted rent is a
        floor the venue never falls below, even on a zero-sales engagement."

        Design: Difficulty/dual_variant_calc/venue_share_flat_rent_vs_percentage_floor_binds
        """
        ctx = setup_reconciled_settlement(
            gross_quantity=2000,
            engagement_overrides={"deal_type": "PERCENTAGE", "agreed_rent_cents": 4000000},
            venue_overrides={"percentage_share_pct": 0.30},
        )
        settlement = ctx["settlement"]
        # max(4000000, round(20000000 * 0.30)=6000000) = 6000000 — pct wins.
        assert settlement["gross_ticket_cents"] == 20000000
        assert settlement["venue_share_cents"] == 6000000


class TestRoyaltyWithheldCombinatorial:
    def test_royalty_max_of_pct_and_guarantee_then_capped_by_reserve(self):
        """PRD §3.9: "first, each agreement's percentage piece is computed
        individually as the gross multiplied by its `royalty_pct`, rounded
        half-up to cents per agreement, and the pieces are summed; second, the
        guarantee piece spreads each agreement's `minimum_guarantee_cents`
        evenly across the count of the parent tour's engagements in `CONFIRMED`,
        `IN_LOAD`, `SHOW_READY`, `IN_PERFORMANCE`, or `SETTLED` at reconcile
        time, with each agreement's division rounded half-up to cents once and
        the per-agreement results summed; third, the withheld amount is the
        larger of the percentage sum and the guarantee sum, and if the tour's
        `royalty_reserve_pct` is greater than 0, the withholding is capped at
        the gross multiplied by `royalty_reserve_pct` rounded half-up — the cap
        is the third and final rounding."

        Design: Difficulty/combinatorial_formula/royalty_withheld_pct_vs_guarantee_proration_with_reserve_cap
        """
        ctx = setup_in_performance_engagement(
            tour_overrides={"royalty_reserve_pct": 0.10},
            engagement_overrides={"deal_type": "FLAT_RENT", "agreed_rent_cents": 4000000},
            with_approved_plan=False,
        )
        create_license_agreement(
            ctx, activate=True, royalty_pct=0.08, minimum_guarantee_cents=2000000,
        )
        scale = create_ticket_scale(ctx)
        record_ticket_sale(ctx, scale["id"], 1000)
        reconcile_engagement(ctx)

        settlement = ctx["settlement"]
        # pct_part = round(10000000 * 0.08) = 800000
        # guarantee_part = round(2000000 / 1) = 2000000
        # uncapped = 2000000; cap = round(10000000 * 0.10) = 1000000
        assert settlement["gross_ticket_cents"] == 10000000
        assert settlement["royalty_withheld_cents"] == 1000000
        assert settlement["venue_share_cents"] == 4000000
        assert settlement["labor_total_cents"] == 0
        assert settlement["promoter_net_cents"] == 10000000 - 4000000 - 1000000 - 0

    def test_royalty_zero_when_no_active_license_in_window(self):
        """PRD §3.9: "The eligible set is the license agreements on the parent
        tour in `ACTIVE` status whose window brackets the reconcile instant —
        `starts_on` at or before the reconcile clock and `ends_on` strictly
        after it. If the set is empty, `royalty_withheld_cents` is 0."

        Design: Difficulty/combinatorial_formula/royalty_withheld_pct_vs_guarantee_proration_with_reserve_cap
        """
        ctx = setup_in_performance_engagement(
            tour_overrides={"royalty_reserve_pct": 0.10},
            engagement_overrides={"deal_type": "FLAT_RENT", "agreed_rent_cents": 4000000},
            with_approved_plan=False,
        )
        # A DRAFT license (never activated) is not in the eligible set.
        create_license_agreement(
            ctx, activate=False, royalty_pct=0.08, minimum_guarantee_cents=2000000,
        )
        scale = create_ticket_scale(ctx)
        record_ticket_sale(ctx, scale["id"], 1000)
        reconcile_engagement(ctx)

        settlement = ctx["settlement"]
        assert settlement["royalty_withheld_cents"] == 0
        assert settlement["promoter_net_cents"] == 10000000 - 4000000 - 0 - 0


class TestSettlementDisputeLoop:
    def test_dispute_then_resolve_returns_to_reconciled_and_recomputes(self):
        """PRD §3.9: "A `VenueBooker` who disputes the figures opens a dispute,
        moving the settlement `RECONCILED → DISPUTED`; resolving the dispute is
        a `TourManager` action that returns it `DISPUTED → RECONCILED` and
        recomputes `venue_share_cents`, `royalty_withheld_cents`, and
        `promoter_net_cents` from the current gross."
        PRD §3.9: "Under a `FLAT_RENT` deal, `venue_share_cents` is simply
        `agreed_rent_cents`, regardless of gross."

        Design: Difficulty/non_linear_state_machine/settlement_dispute_reconcile_loop
        """
        ctx = setup_reconciled_settlement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]
        settle = ctx["settlement"]

        disputed = validate_success(api_client.dispute_settlement(tour_id, eng_id, VB))
        assert disputed["status"] == "DISPUTED"

        resolved = validate_success(api_client.resolve_dispute(tour_id, eng_id, TM))
        assert resolved["status"] == "RECONCILED"
        assert resolved["venue_share_cents"] == settle["venue_share_cents"] == 4000000

    def test_dispute_resolve_loop_then_mark_paid_with_fresh_version(self):
        """PRD §3.9: "A `VenueBooker` who disputes the figures opens a dispute,
        moving the settlement `RECONCILED → DISPUTED`; resolving the dispute is
        a `TourManager` action that returns it `DISPUTED → RECONCILED` and
        recomputes `venue_share_cents`, `royalty_withheld_cents`, and
        `promoter_net_cents` from the current gross."
        PRD §3.9: "Payment is the terminal step: a `TourManager` marks a
        `RECONCILED` settlement paid — any other status is rejected with
        `ERR_SETTLEMENT_NOT_RECONCILED` (HTTP 409)"

        Design: Difficulty/non_linear_state_machine/settlement_dispute_reconcile_loop
        """
        ctx = setup_reconciled_settlement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]

        validate_success(api_client.dispute_settlement(tour_id, eng_id, VB))
        resolved = validate_success(api_client.resolve_dispute(tour_id, eng_id, TM))
        assert resolved["status"] == "RECONCILED"

        paid = validate_success(
            api_client.mark_settlement_paid(
                tour_id, eng_id,
                {"expected_settlement_version": resolved["version"]}, TM,
            )
        )
        assert paid["status"] == "PAID"

    def test_tour_total_gross_invariant_under_dispute_resolve_cycle(self):
        """PRD §3.9: "the tour's `total_gross_cents` and
        `total_settlement_due_cents` absorb the engagement's figures — keeping
        in mind that `total_gross_cents` is the running sum over the tour's
        closed engagements' gross ticket revenue and
        `total_settlement_due_cents` the running sum of what is owed across
        settled engagements."

        Design: Difficulty/compensating_invariant/tour_total_gross_invariant_under_dispute_resolve_cycle
        """
        ctx = setup_reconciled_settlement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]

        before = validate_success(api_client.get_tour(tour_id, TM))
        assert before["total_gross_cents"] == 10000000

        validate_success(api_client.dispute_settlement(tour_id, eng_id, VB))
        validate_success(api_client.resolve_dispute(tour_id, eng_id, TM))

        after = validate_success(api_client.get_tour(tour_id, TM))
        assert after["total_gross_cents"] == 10000000
        assert after["total_gross_cents"] == before["total_gross_cents"]

    def test_tour_total_settlement_due_invariant_under_dispute_resolve_cycle(self):
        """PRD §3.9: "the tour's `total_gross_cents` and
        `total_settlement_due_cents` absorb the engagement's figures — keeping
        in mind that `total_gross_cents` is the running sum over the tour's
        closed engagements' gross ticket revenue and
        `total_settlement_due_cents` the running sum of what is owed across
        settled engagements."

        Design: Difficulty/compensating_invariant/tour_total_gross_invariant_under_dispute_resolve_cycle
        """
        ctx = setup_reconciled_settlement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]

        before = validate_success(api_client.get_tour(tour_id, TM))
        # PRD defines total_settlement_due_cents only as "the running sum of
        # what is owed across settled engagements" — it does not uniquely pin
        # which settlement figure is owed, so no absolute value is asserted
        # here; the covered rule is the dispute/resolve-cycle invariant.
        assert before["total_settlement_due_cents"] > 0

        validate_success(api_client.dispute_settlement(tour_id, eng_id, VB))
        validate_success(api_client.resolve_dispute(tour_id, eng_id, TM))

        after = validate_success(api_client.get_tour(tour_id, TM))
        assert after["total_settlement_due_cents"] == before["total_settlement_due_cents"]


class TestConfirmToSettleCascade:
    def test_confirm_books_avail_then_reconcile_bubbles_tour_totals(self):
        """PRD §3.3: "On success, the held avail flips `HELD → BOOKED`; the
        tour's `open_engagement_count` is unchanged, because `HOLD` already
        counted."
        PRD §3.9: "the tour's `open_engagement_count` is decremented by 1, and
        the tour's `total_gross_cents` and `total_settlement_due_cents` absorb
        the engagement's figures — keeping in mind that `total_gross_cents` is
        the running sum over the tour's closed engagements' gross ticket revenue
        and `total_settlement_due_cents` the running sum of what is owed across
        settled engagements."

        Design: Difficulty/transitive_cascade/engagement_confirm_bubbles_avail_booked_then_settle_increments_tour_totals
        """
        ctx = setup_confirmed_engagement()
        tour_id = ctx["tour"]["id"]
        avail_now = validate_success(
            api_client.get_date_avail(ctx["venue"]["id"], ctx["avail"]["id"], VB)
        )
        assert avail_now["status"] == "BOOKED"

        scale = create_ticket_scale(ctx)
        record_ticket_sale(ctx, scale["id"], 1000)

        # PRD §3.7/§3.9: reaching IN_PERFORMANCE requires the show-ready gate
        # (APPROVED rigging plan) before the clock passes first_show_at.
        from test_helpers.fixtures import (
            advance_to_in_load,
            advance_to_in_performance,
            setup_rigging_plan,
        )
        setup_rigging_plan(
            ctx,
            allocations=[{"static_load_kg": 1000, "dynamic_load_kg": 0}],
            approve=True,
        )
        advance_to_in_load(ctx)
        ctx["engagement"] = validate_success(
            api_client.mark_show_ready(
                tour_id, ctx["engagement"]["id"],
                TEST_USERS["production_engineer_headers"],
            )
        )
        advance_to_in_performance(ctx)
        reconcile_engagement(ctx)

        tour = validate_success(api_client.get_tour(tour_id, TM))
        assert tour["total_gross_cents"] == 10000000
        # PRD pins total_settlement_due_cents only as "the running sum of what
        # is owed across settled engagements" without naming the owed figure,
        # so assert the covered effects: it absorbed this engagement's figures.
        assert tour["total_settlement_due_cents"] > 0
        assert tour["open_engagement_count"] == 0

    def test_confirm_leaves_open_engagement_count_unchanged(self):
        """PRD §3.3: "On success, the held avail flips `HELD → BOOKED`; the
        tour's `open_engagement_count` is unchanged, because `HOLD` already
        counted."

        Design: Difficulty/transitive_cascade/engagement_confirm_bubbles_avail_booked_then_settle_increments_tour_totals
        """
        from test_helpers import setup_held_engagement

        ctx = setup_held_engagement()
        tour_id = ctx["tour"]["id"]

        tour = validate_success(api_client.get_tour(tour_id, TM))
        assert tour["open_engagement_count"] == 1

        validate_success(
            api_client.confirm_engagement(tour_id, ctx["engagement"]["id"], TM)
        )
        tour = validate_success(api_client.get_tour(tour_id, TM))
        assert tour["open_engagement_count"] == 1


class TestOpenEngagementCountInvariant:
    def test_open_engagement_count_returns_to_baseline_after_cancel(self):
        """PRD §3.1: "A new tour is born in `PLANNING` status with its fiscal
        counters zeroed: `total_gross_cents` starts at 0,
        `total_settlement_due_cents` starts at 0, and `open_engagement_count`
        starts at 0."
        PRD §3.3: "increments the tour's `open_engagement_count` by 1"

        Design: Difficulty/compensating_invariant/open_engagement_count_invariant_under_create_and_cancel
        """
        from test_helpers import setup_held_engagement

        ctx = setup_held_engagement()
        tour_id = ctx["tour"]["id"]

        tour = validate_success(api_client.get_tour(tour_id, TM))
        assert tour["open_engagement_count"] == 1

        validate_success(api_client.cancel_engagement(tour_id, ctx["engagement"]["id"], TM))

        tour = validate_success(api_client.get_tour(tour_id, TM))
        assert tour["open_engagement_count"] == 0

    def test_open_engagement_count_counts_confirmed_and_hold(self):
        """PRD §3.1: "A new tour is born in `PLANNING` status with its fiscal
        counters zeroed: `total_gross_cents` starts at 0,
        `total_settlement_due_cents` starts at 0, and `open_engagement_count`
        starts at 0."
        PRD §3.3: "increments the tour's `open_engagement_count` by 1"

        Design: Difficulty/compensating_invariant/open_engagement_count_invariant_under_create_and_cancel
        """
        from test_helpers import create_date_avail, create_engagement, setup_tour_and_venue

        tour, venue = setup_tour_and_venue()
        tour_id = tour["id"]

        avail_1 = create_date_avail(venue["id"])
        eng_1 = create_engagement(tour_id, venue["id"], avail_1["id"], avail_1["version"])
        validate_success(api_client.confirm_engagement(tour_id, eng_1["id"], TM))

        avail_2 = create_date_avail(
            venue["id"], opens_at="2026-10-10T00:00:00Z",
            closes_at="2026-10-15T00:00:00Z",
        )
        create_engagement(
            tour_id, venue["id"], avail_2["id"], avail_2["version"],
            load_in_at="2026-10-10T08:00:00Z",
            first_show_at="2026-10-11T19:00:00Z",
            load_out_at="2026-10-13T23:00:00Z",
        )

        tour = validate_success(api_client.get_tour(tour_id, TM))
        assert tour["open_engagement_count"] == 2


class TestReconcileImmediateConsistency:
    def test_reconcile_returns_full_settlement_in_single_response(self):
        """PRD §3.9: "A successful reconcile does everything in one request:
        the settlement is created in `OPEN`, `gross_ticket_cents` is stamped as
        the sum of ticket-sale revenue recorded for the engagement before the
        reconcile instant, all computed fields are populated (below), the
        settlement advances `OPEN → RECONCILED` in the same request with
        `reconciled_at` stamped, the engagement advances `IN_PERFORMANCE →
        SETTLED`, the tour's `open_engagement_count` is decremented by 1, and
        the tour's `total_gross_cents` and `total_settlement_due_cents` absorb
        the engagement's figures"

        Design: Corner/consistency_model/reconcile_returns_full_settlement_in_single_response
        """
        ctx = setup_in_performance_engagement(with_approved_plan=False)
        scale = create_ticket_scale(ctx)
        record_ticket_sale(ctx, scale["id"], 1000)

        resp = api_client.reconcile_settlement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
        settlement = validate_success(resp)
        assert settlement["gross_ticket_cents"] == 10000000
        assert settlement["venue_share_cents"] == 4000000
        assert settlement["royalty_withheld_cents"] == 0
        assert settlement["labor_total_cents"] == 0
        assert settlement["promoter_net_cents"] == 6000000
        assert settlement["status"] == "RECONCILED"
        assert settlement["reconciled_at"] is not None


class TestSettlementOcc:
    def test_stale_settlement_version_returns_412(self):
        """PRD §2.7: "Marking a settlement paid requires a non-optional
        `expected_settlement_version` carrying the client's last observed
        `version` of the settlement; if the settlement's `version` has advanced
        since that read — for example, a dispute-resolution cascade recomputed
        the figures and bumped the version — the mark-paid is rejected with
        `ERR_STALE_SETTLEMENT_VERSION` (HTTP 412), and the client must re-read
        the settlement before retrying."

        Design: Corner/cross_cutting_layers/stale_settlement_version_returns_412
        """
        ctx = setup_reconciled_settlement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]
        settle_v1 = ctx["settlement"]["version"]

        validate_success(api_client.dispute_settlement(tour_id, eng_id, VB))
        validate_success(api_client.resolve_dispute(tour_id, eng_id, TM))

        resp = api_client.mark_settlement_paid(
            tour_id, eng_id, {"expected_settlement_version": settle_v1}, TM
        )
        validate_error(resp, ApiErrorId.ERR_STALE_SETTLEMENT_VERSION)

        settlement = validate_success(api_client.get_settlement(tour_id, eng_id, TM))
        assert settlement["status"] == "RECONCILED"


class TestSettlementTerminalLockdown:
    def test_terminal_settlement_paid_accepts_no_further_dispute(self):
        """PRD §3.9: "A paid settlement sits in `PAID`"
        PRD §3.9: "A `VenueBooker` who disputes the figures opens a dispute,
        moving the settlement `RECONCILED → DISPUTED`"

        Design: Corner/state_machines/terminal_settlement_paid_accepts_no_further_dispute
        """
        ctx = setup_reconciled_settlement()
        tour_id = ctx["tour"]["id"]
        eng_id = ctx["engagement"]["id"]
        settle_v = ctx["settlement"]["version"]

        paid = validate_success(
            api_client.mark_settlement_paid(
                tour_id, eng_id, {"expected_settlement_version": settle_v}, TM
            )
        )
        assert paid["status"] == "PAID"

        resp = api_client.dispute_settlement(tour_id, eng_id, VB)
        # PRD §3.9 names the dispute transition (RECONCILED → DISPUTED) but does
        # not name the error_id for disputing from a non-RECONCILED state; both
        # ERR_INVALID_STATE and ERR_SETTLEMENT_NOT_RECONCILED are PRD-catalogued
        # 409 state-gate errors a faithful reader could choose here.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_INVALID_STATE, ApiErrorId.ERR_SETTLEMENT_NOT_RECONCILED],
        )

        settlement = validate_success(api_client.get_settlement(tour_id, eng_id, TM))
        assert settlement["status"] == "PAID"
