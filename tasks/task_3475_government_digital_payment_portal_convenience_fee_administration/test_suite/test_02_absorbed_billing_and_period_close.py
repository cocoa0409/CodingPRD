"""Self-funding period close: absorbed tiered billing, pool waterfall,
dual ACCRUAL/CASH portal-cost recognition.

Note on absorbed-model processing costs: PRD §3.4 pins "their fee is zero in
every variant" for ABSORBED services, and `final_fee_cents` is the FINAL
variant, so absorbed transactions contribute zero to `processing_costs_cents`
(`processing_costs_cents` sums `final_fee_cents`). All pool figures below are
derived from that PRD reading.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_ledger_entry,
    assert_pool_conservation,
    capture_series,
    close_period,
    list_ledger_entries,
    set_clock,
    setup_absorbed_checkout,
    setup_captured_echeck,
    setup_september_pool_scenario,
    validate_error,
)

TO = TEST_USERS["treasury_officer_headers"]


class TestAbsorbedInvoiceVariants:
    def test_absorbed_invoice_bills_marginal_chronological_lines(self, api):
        """PRD §3.8: "The line fee is that unrounded amount rounded half-up to
        whole cents, plus the `per_txn_cents` of the band containing the span's
        first cent, and the counter then advances to the span's last cent."

        Design: Difficulty/dual_variant_calc/absorbed_invoice_marginal_chronological_vs_flat_retroactive
        """
        ctx = setup_absorbed_checkout()
        capture_series(
            ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"],
            [300000, 300000, 300000],
        )
        entry = close_period("2026-09")
        assert_ledger_entry(entry)
        # lines: 300000@250bp+20 = 7520; straddle 200000@250bp + 100000@190bp + 20 = 6920;
        # 300000@190bp + 15 = 5715 -> 20155
        assert entry["absorbed_billed_cents"] == 20155

    def test_absorbed_invoice_flat_retroactive_audit_differs(self, api):
        """PRD §3.8: "the month's total volume selects a single band whose
        rate applies to all volume — the total times that band's `rate_bp` per
        ten thousand, rounded half-up, plus the transaction count times that
        band's `per_txn_cents`."
        PRD §3.4: "`ABSORBED` services skip all four steps: their fee is zero
        in every variant."

        Design: Difficulty/dual_variant_calc/absorbed_invoice_marginal_chronological_vs_flat_retroactive
        """
        ctx = setup_absorbed_checkout()
        capture_series(
            ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"],
            [300000, 300000, 300000],
        )
        entry = close_period("2026-09")
        # flat: 900000 lands in band 2 -> round_half_up(900000*0.019) + 3*15 == 17145
        assert entry["absorbed_billed_flat_cents"] == 17145
        assert entry["absorbed_billed_cents"] != entry["absorbed_billed_flat_cents"]
        # absorbed fees are zero in every variant, so no processing cost accrues here
        assert entry["processing_costs_cents"] == 0


class TestPerLineRoundingOrder:
    def test_absorbed_invoice_rounds_per_line_then_sums(self, api):
        """PRD §3.8: "The invoice is the sum of the per-transaction lines —
        each line is rounded first and only then summed as integers; the
        aggregate is never rounded."

        Design: Difficulty/combinatorial_formula/absorbed_invoice_round_per_line_then_sum
        """
        ctx = setup_absorbed_checkout()
        capture_series(
            ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"],
            [333, 333],
        )
        entry = close_period("2026-09")
        # each line: round_half_up(333*0.025)=8 + 20 == 28 -> 28 + 28 == 56
        assert entry["absorbed_billed_cents"] == 56
        # flat reading of the same month: round_half_up(666*0.025) + 2*20 == 57
        assert entry["absorbed_billed_flat_cents"] == 57

    def test_rounding_order_flows_into_pool_waterfall(self, api):
        """PRD §3.8: "the closing balance equals the prior balance plus the
        available pool minus the recovery minus the surplus, with zero
        remainder — every cent lands in exactly one bucket."

        Design: Difficulty/combinatorial_formula/absorbed_invoice_round_per_line_then_sum
        """
        ctx = setup_absorbed_checkout()
        capture_series(
            ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"],
            [333, 333],
        )
        entry = close_period("2026-09")
        # pool available = 0 fees + 56 billed - 0 costs = 56; cash recovery takes it all
        assert entry["cash_portal_recovery_cents"] == 56
        assert entry["surplus_remitted_cents"] == 0
        assert entry["pool_balance_after_cents"] == 0
        assert_pool_conservation(entry)


class TestTierCoverageBoundary:
    def test_tier_coverage_inclusive_max_lands_without_gap(self, api):
        """PRD §3.2: "a null `volume_max_cents` marks the unbounded top band —
        the marginal `rate_bp` in basis points applied to volume portions
        inside the band" and the bands are "closed-interval volume bands".

        Design: Difficulty/boundary_precision_check/tier_coverage_inclusive_max_exact_lands_no_gap
        """
        ctx = setup_absorbed_checkout(top_unbounded=False)
        capture_series(
            ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"],
            [1000000, 1000000],
        )
        entry = close_period("2026-09")  # cumulative 2000000 == band 2 inclusive max: covered
        assert_ledger_entry(entry)
        # line 1 straddles: 500000@250bp + 500000@190bp + 20 == 22020; line 2: 19000 + 15 == 19015
        assert entry["absorbed_billed_cents"] == 41035

    def test_inclusive_max_close_cash_recovery(self, api):
        """PRD §3.8: "`cash_portal_recovery_cents` is the lesser of the
        accrual recognition and the pool available when that pool is positive,
        and zero when it is not".

        Design: Difficulty/boundary_precision_check/tier_coverage_inclusive_max_exact_lands_no_gap
        """
        ctx = setup_absorbed_checkout(top_unbounded=False)
        capture_series(
            ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"],
            [1000000, 1000000],
        )
        entry = close_period("2026-09")
        # pool available = 41035 billed (absorbed fees are zero in every variant)
        assert entry["cash_portal_recovery_cents"] == 41035
        assert entry["pool_balance_after_cents"] == 0
        assert_pool_conservation(entry)


class TestDualBasisCostRecognition:
    def test_period_close_accrual_basis_full_amortization(self, api):
        """PRD §3.8: "`accrual_portal_recovery_cents` is the lesser of 200000
        and the total cost minus all prior periods' accrual recognition".

        Design: Difficulty/dual_variant_calc/portal_cost_recognition_accrual_vs_cash
        """
        setup_september_pool_scenario()
        entry = close_period("2026-09")
        assert_ledger_entry(entry)
        assert entry["accrual_portal_recovery_cents"] == 200000
        assert entry["portal_cost_remaining_accrual_cents"] == 11800000

    def test_period_close_cash_basis_limited_by_pool(self, api):
        """PRD §3.8: "`cash_portal_recovery_cents` is the lesser of the
        accrual recognition and the pool available when that pool is positive,
        and zero when it is not — shortfalls defer, they never vanish — and
        `portal_cost_remaining_cash_cents` is the total cost minus all cash
        recovery including this period's."

        Design: Difficulty/dual_variant_calc/portal_cost_recognition_accrual_vs_cash
        """
        setup_september_pool_scenario()
        entry = close_period("2026-09")
        # pool = fees 2824 + billed 20155 - costs 2092 (absorbed fees are zero
        # in every variant, so costs come only from the CF transactions)
        assert entry["fees_collected_cents"] == 2824
        assert entry["processing_costs_cents"] == 2092
        assert entry["cash_portal_recovery_cents"] == 20887
        assert entry["portal_cost_remaining_cash_cents"] == 11979113
        assert (
            entry["portal_cost_remaining_cash_cents"]
            - entry["portal_cost_remaining_accrual_cents"]
            == 179113
        )


class TestPoolSweepConservation:
    def test_pool_sweep_conserves_every_cent(self, api):
        """PRD §3.8: "the conservation invariant holds exactly: the closing
        balance equals the prior balance plus the available pool minus the
        recovery minus the surplus, with zero remainder — every cent lands in
        exactly one bucket."

        Design: Difficulty/compensating_invariant/pool_sweep_zero_remainder_conservation
        """
        setup_september_pool_scenario()
        entry = close_period("2026-09")
        assert entry["fees_collected_cents"] == 2824
        assert entry["absorbed_billed_cents"] == 20155
        assert entry["processing_costs_cents"] == 2092
        assert entry["cash_portal_recovery_cents"] == 20887
        assert entry["surplus_remitted_cents"] == 0
        assert entry["pool_balance_after_cents"] == 0
        assert_pool_conservation(entry, prior_pool_balance_cents=0)

    def test_period_close_second_time_rejected(self, api):
        """PRD §3.8: "A period may be closed only once — a second close for
        the same period is rejected with `ERR_PERIOD_ALREADY_CLOSED`".

        Design: Difficulty/compensating_invariant/pool_sweep_zero_remainder_conservation
        """
        setup_september_pool_scenario()
        close_period("2026-09")
        resp = api_client.close_period({"period": "2026-09"}, TO)
        validate_error(resp, ApiErrorId.ERR_PERIOD_ALREADY_CLOSED)


class TestCornerPeriodCloseCases:
    def test_absorbed_straddle_exact_split_arithmetic(self, api):
        """PRD §3.8: "every transaction is priced at the band or bands its own
        cumulative span touches, and a span straddling a band boundary splits
        across both."

        Design: Corner/calculations/absorbed_straddle_exact_split_arithmetic
        """
        ctx = setup_absorbed_checkout()
        capture_series(
            ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"],
            [499000, 2000],
        )
        entry = close_period("2026-09")
        # line 1: 499000@250bp = 12475 + 20 == 12495
        # line 2 straddle: 1000@250bp + 1000@190bp = 44 + 20 (first cent in band 1) == 64
        assert entry["absorbed_billed_cents"] == 12559
        # flat: 501000 in band 2 -> 501000*0.019 == 9519 + 2*15 == 9549
        assert entry["absorbed_billed_flat_cents"] == 9549

    def test_tier_coverage_gap_aborts_whole_close(self, api):
        """PRD §3.8: "If an agency has absorbed captures in the period but its
        bands for the month do not cover the cumulative volume reached, the
        entire close is aborted with `ERR_TIER_COVERAGE_GAP`."

        Design: Corner/errors/err_tier_coverage_gap
        """
        ctx = setup_absorbed_checkout(top_unbounded=False)
        capture_series(
            ctx["service"]["id"], ctx["payer"]["id"], ctx["echeck"]["id"],
            [1000000, 1000000, 1],  # cumulative 2000001 — one cent past the top band
        )
        resp = api_client.close_period({"period": "2026-09"}, TO)
        validate_error(resp, ApiErrorId.ERR_TIER_COVERAGE_GAP)
        assert list_ledger_entries("2026-09") == [], "the close is atomic — no partial entry"

    def test_second_period_close_advances_epoch(self, api):
        """PRD §2.10: "its build-out cost is a fixed total of 12000000 cents,
        amortized straight-line over 60 months at 200000 cents per month,
        recovered from the fee pool that transaction activity accumulates."

        Design: Corner/cross_cutting/ops_run_second_period_close_advances_epoch
        """
        ctx = setup_captured_echeck(50000, capture_clock="2026-09-10T00:00:00Z")
        entry_sep = close_period("2026-09")
        assert entry_sep["fees_collected_cents"] == 150
        assert entry_sep["processing_costs_cents"] == 150
        assert entry_sep["cash_portal_recovery_cents"] == 0
        assert entry_sep["surplus_remitted_cents"] == 0
        assert entry_sep["pool_balance_after_cents"] == 0
        assert entry_sep["portal_cost_remaining_accrual_cents"] == 11800000

        entry_oct = close_period("2026-10")
        assert_ledger_entry(entry_oct)
        assert entry_oct["fees_collected_cents"] == 0
        assert entry_oct["processing_costs_cents"] == 0
        # accrual keeps recognizing a full month even though the pool is empty
        assert entry_oct["accrual_portal_recovery_cents"] == 200000
        assert entry_oct["cash_portal_recovery_cents"] == 0
        assert entry_oct["portal_cost_remaining_accrual_cents"] == 11600000
        assert entry_oct["portal_cost_remaining_cash_cents"] == 12000000
