"""Settlement batches: cutoff-day assignment, pinned acquirer-fee rounding,
gross vs net positions, reconciliation and disputes, and data deliveries."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    make_retailer_system_headers,
    validate_error,
    validate_success,
)
from test_helpers import assertions as A
from test_helpers import factories as f
from test_helpers import fixtures as fx

ADMIN = TEST_USERS["state_admin_headers"]


class TestBatchFigures:
    def test_acquirer_fee_round_per_txn_then_sum(self, api):
        """PRD §3.9: "For each settled transaction, the fee is the transaction's
        `total_cents` multiplied by the contract's `acquirer_fee_basis_points`
        (75 basis points by default) and divided by 10000, rounded half up to
        whole cents; the batch's `acquirer_fee_cents` is the sum of those
        per-transaction fees. This round-per-transaction-then-sum order is
        pinned. Summing the transaction totals first and rounding once is
        forbidden because it yields different cents: five 67-cent transactions
        produce a 5-cent total fee under the pinned rule against 3 cents under
        the forbidden one."

        Design: Difficulty/combinatorial_formula/acquirer_fee_round_per_txn_then_sum
        """
        ctx = fx.setup_settled_batch(
            api, purchase_specs=[{"unit_price_cents": 67}] * 5)
        batch = ctx.batch
        A.assert_settlement_batch(batch)
        # round_half_up(67 * 75 / 10000) = round_half_up(0.5025) = 1 per txn.
        A.assert_batch_position(batch, gross_settled_cents=335,
                                acquirer_fee_cents=5, adjustment_total_cents=0,
                                net_position_cents=330)
        assert batch["txn_count"] == 5

    def test_acquirer_fee_rounds_half_up_per_transaction(self, api):
        """PRD §2.6: "Where a computation produces a fractional cent, the rule
        is round half up to the nearest whole cent, and rounding happens at
        exactly two places in the system: first-month benefit proration, which
        rounds the prorated amount half up exactly once (Section 3.4), and the
        acquirer fee, which rounds each transaction's fee half up before the
        per-transaction fees are summed (Section 3.9)."

        Design: Difficulty/combinatorial_formula/acquirer_fee_round_per_txn_then_sum
        """
        # 200 * 75 / 10000 = 1.5 -> 2 (half up); 100 * 75 / 10000 = 0.75 -> 1.
        # Pinned per-transaction sum: 3. Sum-then-round would give
        # round_half_up(2.25) = 2.
        ctx = fx.setup_settled_batch(
            api, purchase_specs=[{"unit_price_cents": 200},
                                 {"unit_price_cents": 100}])
        batch = ctx.batch
        A.assert_batch_position(batch, gross_settled_cents=300,
                                acquirer_fee_cents=3, adjustment_total_cents=0,
                                net_position_cents=297)
        assert batch["txn_count"] == 2

    def test_settlement_gross_vs_net_position_with_adjustments(self, api):
        """PRD §3.9: "`adjustment_total_cents` is the signed sum of
        `adjustment_cents` over the batch's `UPHELD` disputes — positive meaning
        an additional amount owed to the retailer — and starts at 0.
        `net_position_cents` is the gross settled amount minus the acquirer fee
        plus the adjustment total."

        Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_position_with_adjustments
        """
        ctx = fx.setup_settled_batch(
            api, purchase_specs=[{"unit_price_cents": 67}] * 5)
        batch = ctx.batch
        # GROSS variant vs NET variant diverge through the fee alone.
        A.assert_batch_position(batch, gross_settled_cents=335,
                                acquirer_fee_cents=5, adjustment_total_cents=0,
                                net_position_cents=330)
        dispute = fx.file_dispute(api, batch["id"], ctx.retailer["id"], 100,
                                  reason="short payment review")
        fx.decide_dispute(api, dispute["id"], to="UPHELD", adjustment_cents=-100)
        batch = fx.get_batch(api, batch["id"])
        A.assert_batch_position(batch, gross_settled_cents=335,
                                acquirer_fee_cents=5, adjustment_total_cents=-100,
                                net_position_cents=230)
        assert batch["gross_settled_cents"] != batch["net_position_cents"]

    def test_reconcile_at_adjusted_net_reconciles_and_keeps_figures(self, api):
        """PRD §3.9: "If `actual_settled_cents` equals the batch's
        `net_position_cents` at reconcile time, a `CUTOFF` or `DISPUTED` batch
        flips to `RECONCILED` — terminal — with `reconciled_at` stamped."
        PRD §3.9: "Two batch figures are computed at cutoff and are immutable
        thereafter: `gross_settled_cents`, the sum of the settled transactions'
        `total_cents`, and `txn_count`, their count."

        Design: Difficulty/dual_variant_calc/settlement_gross_vs_net_position_with_adjustments
        """
        ctx = fx.setup_settled_batch(
            api, purchase_specs=[{"unit_price_cents": 67}] * 5)
        batch = ctx.batch
        dispute = fx.file_dispute(api, batch["id"], ctx.retailer["id"], 100,
                                  reason="short payment review")
        fx.decide_dispute(api, dispute["id"], to="UPHELD", adjustment_cents=-100)
        # Net position is now 230; reconciling with exactly that succeeds.
        reconciled = fx.reconcile_batch(api, batch["id"], 230)
        assert reconciled["batch_status"] == "RECONCILED"
        assert reconciled["reconciled_at"] is not None
        A.assert_batch_position(reconciled, gross_settled_cents=335,
                                acquirer_fee_cents=5, adjustment_total_cents=-100,
                                net_position_cents=230)


class TestSettlementDayBoundary:
    def test_settlement_day_boundary_half_open_assignment(self, api):
        """PRD §3.9: "A settlement day runs from the contract's
        `settlement_cutoff_hour_utc` (hour 0 by default) on one day to the same
        hour on the next, including the start instant and excluding the end
        instant."
        PRD §3.9: "The batch records the `settlement_date` (the ISO date of the
        day that closed) and the `cutoff_at` (the clock instant of the cutoff
        boundary that created it, at the start of the following day)."

        Design: Corner/calculations/settlement_day_boundary_half_open_assignment
        """
        ctx = fx.setup_pos_ready(api)
        fx.set_clock(api, "2026-09-03T00:00:00Z")  # closes the (empty) 09-02 day
        # A purchase at exactly the cutoff instant opens the new day 2026-09-03.
        fx.place_purchases(api, ctx, [{"unit_price_cents": 700}])
        fx.set_clock(api, "2026-09-04T00:00:00Z")  # closes 2026-09-03
        batches = fx.list_batches(api, contract_id=ctx.contract["id"])
        assert len(batches) == 1, f"expected exactly one batch, got {len(batches)}"
        batch = batches[0]
        assert batch["settlement_date"] == "2026-09-03"
        assert batch["txn_count"] == 1
        assert batch["gross_settled_cents"] == 700

    def test_pre_cutoff_void_leaves_batch_gross_unchanged(self, api):
        """PRD §3.9: "When the clock crosses a cutoff boundary — step 6 of the
        sweep pipeline — every transaction still `AUTHORIZED` whose settlement
        day has just closed flips to `SETTLED`."
        PRD §3.9: "Two batch figures are computed at cutoff and are immutable
        thereafter: `gross_settled_cents`, the sum of the settled transactions'
        `total_cents`, and `txn_count`, their count."

        Design: Difficulty/compensating_invariant/pre_cutoff_void_leaves_batch_gross_unchanged
        """
        ctx = fx.setup_pos_ready(api)
        t1, t2 = fx.place_purchases(
            api, ctx, [{"unit_price_cents": 500}, {"unit_price_cents": 700}])
        # Same-day void of T1: the compensating pair cancels it out of the day.
        fx.void_authorization(api, t1["id"], ctx.retailer["id"])
        fx.settle_authorizations(api, ctx)
        batch = fx.first_batch(api, ctx.contract["id"])
        # gross is exactly as if only the 700-cent authorization had happened.
        A.assert_batch_position(batch, gross_settled_cents=700,
                                acquirer_fee_cents=5, adjustment_total_cents=0,
                                net_position_cents=695)
        assert batch["txn_count"] == 1

    def test_voided_transaction_never_enters_settled_id_list(self, api):
        """PRD §3.9: "The settled transactions are grouped per contract and
        `acquirer_reference` into a settlement batch born with `batch_status`
        `CUTOFF`; each transaction's `batch_id` is set to its batch, and the
        batch's `settled_authorization_ids` lists the settled transaction ids in
        `created_at` ascending order."

        Design: Difficulty/compensating_invariant/pre_cutoff_void_leaves_batch_gross_unchanged
        """
        ctx = fx.setup_pos_ready(api)
        t1, t2, t3 = fx.place_purchases(
            api, ctx, [{"unit_price_cents": 500}, {"unit_price_cents": 700},
                       {"unit_price_cents": 900}])
        fx.void_authorization(api, t2["id"], ctx.retailer["id"])
        fx.settle_authorizations(api, ctx)
        batch = fx.first_batch(api, ctx.contract["id"])
        assert batch["settled_authorization_ids"] == [t1["id"], t3["id"]]
        # Fees: round_half_up(3.75) = 4 and round_half_up(6.75) = 7 -> 11.
        A.assert_batch_position(batch, gross_settled_cents=1400,
                                acquirer_fee_cents=11, adjustment_total_cents=0,
                                net_position_cents=1389)
        assert batch["txn_count"] == 2


class TestReconcileAndDisputes:
    def test_reconcile_mismatch_creates_dispute_and_disputes_batch(self, api):
        """PRD §3.9: "On a mismatch, no error is raised for the amount itself:
        instead the batch moves to `DISPUTED` — or stays there, since a
        mismatched reconcile against an already-disputed batch keeps it in
        `DISPUTED` — and the system creates a settlement dispute of
        `dispute_type` `RECONCILIATION_MISMATCH` in `OPEN`, whose
        `disputed_amount_cents` is the actual settled amount minus the net
        position and whose `retailer_id` and `filed_by_user_id` are null because
        the system filed it."

        Design: Corner/validations/reconcile_mismatch_creates_dispute_and_disputes_batch
        """
        ctx = fx.setup_settled_batch(api)  # one 1000-cent txn: net 992
        batch = ctx.batch
        resp = api.reconcile_batch(batch["id"], f.reconcile_payload(900), ADMIN)
        data = validate_success(resp, 200)  # a mismatch is a transition, not an error
        assert data["batch_status"] == "DISPUTED"
        disputes = fx.list_batch_disputes(api, batch["id"])
        assert len(disputes) == 1
        dispute = disputes[0]
        A.assert_settlement_dispute(dispute)
        assert dispute["dispute_type"] == "RECONCILIATION_MISMATCH"
        assert dispute["disputed_amount_cents"] == -92  # 900 - 992
        assert dispute["dispute_status"] == "OPEN"
        assert dispute["retailer_id"] is None
        assert dispute["filed_by_user_id"] is None

    def test_matched_reconcile_blocked_while_dispute_open(self, api):
        """PRD §3.9: "The batch must first have zero `OPEN` disputes — any open
        dispute rejects the reconcile with `ERR_BATCH_HAS_OPEN_DISPUTES`, and
        this check fires before any amount comparison, so a mismatched reconcile
        attempted while a dispute is open still surfaces the dispute error."
        PRD §3.9: "If `actual_settled_cents` equals the batch's
        `net_position_cents` at reconcile time, a `CUTOFF` or `DISPUTED` batch
        flips to `RECONCILED` — terminal — with `reconciled_at` stamped."

        Design: Difficulty/cross_entity_state_dependency/reconcile_blocked_while_dispute_open
        """
        ctx = fx.setup_settled_batch(api)  # net 992
        batch = ctx.batch
        dispute = fx.file_dispute(api, batch["id"], ctx.retailer["id"], 992,
                                  reason="statement review")
        # Even a reconcile whose amount MATCHES net is rejected while OPEN.
        resp = api.reconcile_batch(batch["id"], f.reconcile_payload(992), ADMIN)
        validate_error(resp, ApiErrorId.ERR_BATCH_HAS_OPEN_DISPUTES)
        fx.decide_dispute(api, dispute["id"], to="OVERTURNED")
        resp2 = api.reconcile_batch(batch["id"], f.reconcile_payload(992), ADMIN)
        data = validate_success(resp2, 200)
        assert data["batch_status"] == "RECONCILED"

    def test_mismatched_reconcile_still_surfaces_open_dispute_error(self, api):
        """PRD §3.9: "The batch must first have zero `OPEN` disputes — any open
        dispute rejects the reconcile with `ERR_BATCH_HAS_OPEN_DISPUTES`, and
        this check fires before any amount comparison, so a mismatched reconcile
        attempted while a dispute is open still surfaces the dispute error."

        Design: Difficulty/cross_entity_state_dependency/reconcile_blocked_while_dispute_open
        """
        ctx = fx.setup_settled_batch(api)  # net 992
        batch = ctx.batch
        fx.file_dispute(api, batch["id"], ctx.retailer["id"], 992,
                        reason="statement review")
        # 900 != 992, but the open-dispute gate fires before any comparison.
        resp = api.reconcile_batch(batch["id"], f.reconcile_payload(900), ADMIN)
        validate_error(resp, ApiErrorId.ERR_BATCH_HAS_OPEN_DISPUTES)
        # No additional mismatch dispute was created behind the error.
        disputes = fx.list_batch_disputes(api, batch["id"])
        assert len(disputes) == 1
        assert disputes[0]["dispute_type"] == "RETAILER_DISPUTE"

    def test_adjudicate_decided_dispute_rejected(self, api):
        """PRD §3.9: "Overturning applies no adjustment and leaves the batch
        totals unchanged. `UPHELD` and `OVERTURNED` are terminal, and
        adjudicating an already-decided dispute is rejected with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/adjudicate_decided_dispute_rejected
        """
        ctx = fx.setup_settled_batch(api)
        dispute = fx.file_dispute(api, ctx.batch["id"], ctx.retailer["id"], 992,
                                  reason="review")
        fx.decide_dispute(api, dispute["id"], to="OVERTURNED")
        resp = api.set_dispute_status(
            dispute["id"],
            f.dispute_status_payload("UPHELD", adjustment_cents=50),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        batch = fx.get_batch(api, ctx.batch["id"])
        assert batch["adjustment_total_cents"] == 0, (
            "the rejected decision must apply no adjustment"
        )

    def test_dispute_window_inclusive_boundary(self, api):
        """PRD §3.9: "The filing window is the contract's `dispute_window_days`
        (15 days by default) after the batch's `cutoff_at`, with an inclusive
        boundary; filing later is rejected with `ERR_DISPUTE_WINDOW_EXPIRED`."

        Design: Corner/validations/dispute_window_inclusive_boundary
        """
        ctx = fx.setup_settled_batch(api)  # cutoff_at 2026-09-03T00:00:00Z
        batch = ctx.batch
        retailer_id = ctx.retailer["id"]
        # Exactly cutoff_at + 15 days: the inclusive boundary, still accepted.
        fx.set_clock(api, "2026-09-18T00:00:00Z")
        dispute = fx.file_dispute(api, batch["id"], retailer_id, 992,
                                  reason="at boundary")
        assert dispute["dispute_status"] == "OPEN"
        # One second later: outside the window.
        fx.set_clock(api, "2026-09-18T00:00:01Z")
        resp = api.file_dispute(
            f.dispute_payload(batch["id"], 1, reason="one second late"),
            make_retailer_system_headers(retailer_id),
        )
        validate_error(resp, ApiErrorId.ERR_DISPUTE_WINDOW_EXPIRED)


class TestDataDelivery:
    def test_daily_transaction_file_generated_at_cutoff(self, api):
        """PRD §3.10: "The settlement-cutoff sweep (step 6) also emits each
        contract's daily transaction file: a data delivery with `delivery_type`
        `DAILY_TRANSACTION_FILE` whose `period` is the settled date, carrying
        `txn_count` — the transactions settled on that period across all
        acquirers — plus `settled_food_cents` and `settled_cash_cents`, the sums
        of `food_charge_cents` and `cash_charge_cents` over the period's settled
        transactions."
        PRD §3.10: "Every delivery is created with `delivery_status` `GENERATED`
        and flips to `DELIVERED` in the same sweep that creates it."

        Design: Corner/cross_cutting_layers/daily_transaction_file_generated_at_cutoff
        """
        ctx = fx.setup_pos_ready(
            api, program_types=("FOOD", "CASH"),
            allotments={"FOOD": 30000, "CASH": 20000},
            item_entries=[
                f.item_entry(),
                f.item_entry(upc=f.DEFAULTS["NON_FOOD_UPC"], food_eligible=False),
            ])
        fx.place_purchase(api, ctx.retailer["id"], ctx.card["id"],
                          items=[f.purchase_item(unit_price_cents=500)])
        fx.place_purchase(api, ctx.retailer["id"], ctx.card["id"],
                          items=[f.purchase_item(upc=f.DEFAULTS["NON_FOOD_UPC"],
                                                 unit_price_cents=300)])
        fx.settle_authorizations(api, ctx)  # 2026-09-03T00:00:00Z closes 09-02
        deliveries = fx.list_data_deliveries(api, ctx.contract["id"],
                                             delivery_type="DAILY_TRANSACTION_FILE")
        # PRD §3.10 emits each contract's daily file at every crossed cutoff
        # boundary (no activity condition stated), so the card-activation clock
        # jump legitimately emitted a zero-transaction file for period 09-01.
        # Select the file for the settled period this test drives.
        by_period = {d["period"]: d for d in deliveries}
        assert "2026-09-02" in by_period
        daily = by_period["2026-09-02"]
        A.assert_data_delivery(daily)
        assert daily["txn_count"] == 2
        assert daily["settled_food_cents"] == 500
        assert daily["settled_cash_cents"] == 300
        assert daily["delivery_status"] == "DELIVERED"

    def test_monthly_integrity_report_counts_lenient_exceptions(self, api):
        """PRD §3.10: "When a clock advance crosses a month boundary, step 7 of
        the pipeline emits the `MONTHLY_INTEGRITY_REPORT` for the calendar month
        that just ended — the half-open window from the first instant of that
        month to the first instant of the next — carrying `expunged_cents` (the
        sum of `EXPUNGE_DEBIT` amounts created in the month), `expired_cents`
        (the sum of `EXPIRY_DEBIT` amounts created in the month),
        `substantiated_claims_count` (claims of the contract decided in the
        month with `investigation_status` `SUBSTANTIATED`),
        `provisional_credits_outstanding_cents` (the sum of
        `provisional_credit_cents` over claims whose `credit_status` is
        `PROVISIONAL` at the month-end instant), `retailer_suspensions_count`
        (retailers of the contract whose transition from `APPROVED` to
        `SUSPENDED` occurred in the month), and `lenient_exceptions_count` (the
        sum of `exception_flag_count` over the contract's transactions created
        in the month)."

        Design: Corner/cross_cutting_layers/monthly_integrity_report_counts_lenient_exceptions
        """
        ctx = fx.setup_pos_ready(
            api,
            program_overrides={"FOOD": {"item_restriction_mode": "LENIENT"}})
        # One LENIENT exception purchase in September (unknown UPC).
        txn = fx.place_purchase(api, ctx.retailer["id"], ctx.card["id"],
                                items=[f.purchase_item(upc="999999999999",
                                                       unit_price_cents=100)])
        assert txn["exception_flag_count"] == 1
        fx.set_clock(api, "2026-10-01T00:00:00Z")  # September just ended
        reports = fx.list_data_deliveries(api, ctx.contract["id"],
                                          delivery_type="MONTHLY_INTEGRITY_REPORT")
        assert len(reports) == 1
        report = reports[0]
        A.assert_data_delivery(report)
        assert report["period"] == "2026-09"
        assert report["lenient_exceptions_count"] == 1
        assert report["delivery_status"] == "DELIVERED"
