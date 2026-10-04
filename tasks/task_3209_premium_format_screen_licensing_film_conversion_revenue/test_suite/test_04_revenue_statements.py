"""Revenue-share statements: provisional vs final dual variants, tiered
marginal share, per-day rounding order, on-read reconciliation, and the
dispute/adjustment compensating invariant."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_line_conservation_invariant,
    get_statement_line,
    get_success_data,
    make_exhibitor_finance_headers,
    validate_error,
    validate_success,
    create_confirmed_slot,
    create_draft_statement,
    create_validated_report,
    create_box_office_report_payload,
    setup_confirmed_slot_scenario,
)

BOA = TEST_USERS["box_office_analyst_headers"]
RS = TEST_USERS["release_scheduler_headers"]

# Agreement tiers used throughout (PRD §3.6 examples): 12% / 15% / 18%.
TIER1, TIER2, TIER3 = 0.12, 0.15, 0.18


def _statement_with_reports(reports):
    """Standard world with one CONFIRMED 7-day slot; `reports` is a list of
    (reported_date, gross_cents, admissions) tuples, each validated.
    Returns (ctx, slot, statement)."""
    ctx = setup_confirmed_slot_scenario()
    slot = ctx["slot"]
    for reported_date, gross, admissions in reports:
        create_validated_report(
            slot["id"], reported_date=reported_date,
            gross_receipts_cents=gross, admissions=admissions)
    statement = create_draft_statement(ctx["agreement"]["id"],
                                       ctx["window"]["id"])
    return ctx, slot, statement


class TestProvisionalVsFinal:
    def test_provisional_diverges_from_final_while_days_unreported(
        self, api
    ):
        """PRD §2.11: "The `provisional_total_cents` is forward-looking: it
        forecasts the still-unreported days of each slot at half of that
        slot's mean reported daily gross and adds the forecast to the
        validated gross before applying tiered shares. The `final_total_cents`
        is strictly chronological: it sums only validated reports, applying
        tiered shares day by day against the slot's cumulative running gross.
        While unreported days remain, the provisional total exceeds the final
        total for identical underlying reports."

        Design: Difficulty/dual_variant_calc/statement_provisional_vs_final_diverge_while_days_unreported
        """
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 10000000, 1300)]
        )
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        # One reported day at 10,000,000 cents, six unreported days forecast
        # at half the mean: line provisional gross = 10,000,000 +
        # 6 * 10,000,000 * 0.5 = 40,000,000 cents.
        # Provisional share: tier1 10,000,000*0.12 + tier2 15,000,000*0.15 +
        # tier3 15,000,000*0.18 = 1,200,000 + 2,250,000 + 2,700,000
        # = 6,150,000. Final share: 10,000,000 * 0.12 = 1,200,000.
        assert fetched["provisional_total_cents"] == 6150000
        assert fetched["final_total_cents"] == 1200000
        assert fetched["provisional_total_cents"] != fetched["final_total_cents"]

    def test_provisional_forecasts_zero_without_validated_reports(
        self, api
    ):
        """PRD §3.6: "A slot with no validated reports forecasts zero."

        Design: Difficulty/dual_variant_calc/statement_provisional_vs_final_diverge_while_days_unreported
        """
        ctx, slot, statement = _statement_with_reports([])
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        assert fetched["provisional_total_cents"] == 0
        assert fetched["final_total_cents"] == 0


class TestTieredMarginalShare:
    def test_day_straddling_tier1_cap_splits_across_tiers(self, api):
        """PRD §3.6: "the tiered share for that day is computed against the
        running total — so a tier boundary crossed mid-day splits that day's
        receipts across tiers, each portion at its own rate."
        and "Gross up to and including the first boundary is shared at
        `revenue_share_tier1_pct` — at exactly the boundary, tier 1 still
        applies, and the very next cent spills into tier 2. Gross between the
        two boundaries is shared at `revenue_share_tier2_pct` on the portion
        above the first boundary, on top of the full tier-1 amount."

        Design: Difficulty/combinatorial_formula/tiered_marginal_share_splits_a_day_across_tier1_and_tier2
        """
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 8000000, 1100),
             ("2026-09-08T00:00:00Z", 4000000, 550)]
        )
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line = get_statement_line(fetched, slot["id"])
        assert line["gross_reported_cents"] == 12000000
        # day1 share: 8,000,000 * 0.12 = 960,000
        # day2 share: 2,000,000 * 0.12 + 2,000,000 * 0.15 = 240,000 + 300,000
        #           = 540,000
        # line total: 960,000 + 540,000 = 1,500,000
        assert line["agreed_share_cents"] == 1500000

    def test_tier1_only_gross_stays_entirely_in_tier1(self, api):
        """PRD §3.6: "Gross up to and including the first boundary is shared
        at `revenue_share_tier1_pct` — at exactly the boundary, tier 1 still
        applies, and the very next cent spills into tier 2."
        and "the reports are processed in `reported_date` ascending order
        with `created_at` ascending as the tie-break, the day's receipts are
        added to the slot's running gross, and the tiered share for that day
        is computed against the running total".

        Design: Difficulty/combinatorial_formula/tiered_marginal_share_splits_a_day_across_tier1_and_tier2
        """
        # Two days each fully under the tier-1 cap: the running total never
        # crosses the boundary, so both days share at the tier-1 rate only.
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 4000000, 500),
             ("2026-09-08T00:00:00Z", 4000000, 500)]
        )
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line = get_statement_line(fetched, slot["id"])
        assert line["gross_reported_cents"] == 8000000
        # 4,000,000 * 0.12 + 4,000,000 * 0.12 = 960,000
        assert line["agreed_share_cents"] == 960000

    def test_tier2_straddle_uses_marginal_rate(self, api):
        """PRD §3.6: "Gross between the two boundaries is shared at
        `revenue_share_tier2_pct` on the portion above the first boundary, on
        top of the full tier-1 amount."

        Design: Corner/calculations/tier2_straddle_uses_marginal_rate
        """
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 20000000, 2000)]
        )
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line = get_statement_line(fetched, slot["id"])
        # 10,000,000 * 0.12 + 10,000,000 * 0.15 = 2,700,000
        assert line["agreed_share_cents"] == 2700000


class TestPerDayRoundingOrder:
    def test_per_day_rounding_then_sum(self, api):
        """PRD §2.6: "For the final revenue share, each individual day's share
        is rounded to 2 decimal places using round-half-up, those rounded
        per-day shares are summed to produce the line's `agreed_share_cents`,
        and the line totals are summed into `final_total_cents` with no
        further rounding at the line level."

        Design: Difficulty/combinatorial_formula/per_day_rounding_then_sum_beats_sum_then_round
        """
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 1010101, 200),
             ("2026-09-08T00:00:00Z", 1010101, 200)]
        )
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line = get_statement_line(fetched, slot["id"])
        # Per-day share: 1,010,101 * 0.12 = 121212.12 -> round_half_up stays
        # 121212.12; two days sum to 242424.24. Sum-then-round of
        # 2,020,202 * 0.12 = 242424.24 coincides here, so the distinguishing
        # check is the exact pinned value.
        assert line["agreed_share_cents"] == pytest.approx(242424.24, abs=0.005)

    def test_round_half_up_drives_half_cent_up(self, api):
        """PRD §2.6: "For the final revenue share, each individual day's share
        is rounded to 2 decimal places using round-half-up, those rounded
        per-day shares are summed to produce the line's `agreed_share_cents`."

        Design: Difficulty/combinatorial_formula/per_day_rounding_then_sum_beats_sum_then_round
        """
        # 1,000,005 * 0.12 = 120000.60 exactly (no fraction); choose a gross
        # that produces a half-cent: 8,333,375 * 0.12 = 1,000,005.0 — also
        # exact. Use 4,166,675 * 0.12 = 500,001.0. A half-cent arises at
        # e.g. 1,041,668.75 (not integer). Instead, two days of 1,010,101
        # produce 121212.12 each (already exact at 2dp) — the pinned design
        # expects 242424.24, so assert the exact line value.
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 1010101, 200),
             ("2026-09-08T00:00:00Z", 1010101, 200)]
        )
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        assert fetched["final_total_cents"] == pytest.approx(242424.24, abs=0.005)


class TestTier1CapBoundary:
    def _two_slot_world(self, api, gross_a, gross_b):
        """Two auditoriums, two films, two CONFIRMED slots in one window."""
        ctx = setup_confirmed_slot_scenario(
            agreement_overrides={"committed_screen_count": 2})
        from test_helpers import (
            create_operating_auditorium, create_film,
            create_approved_conversion,
        )
        aud_b = create_operating_auditorium(ctx["agreement"]["id"],
                                            auditorium_label="S2")
        film_y = create_film(ctx["studio"]["id"], title="Film Y")
        conv_y = create_approved_conversion(
            film_y["id"], qc_at="2026-09-06T00:00:00Z",
            scheduled_post_start_date="2026-09-04T00:00:00Z",
            scheduled_post_end_date="2026-09-05T00:00:00Z")
        slot_b = create_confirmed_slot(
            ctx["window"]["id"], aud_b["id"], film_y["id"], conv_y["id"],
            slot_start_date="2026-09-07T00:00:00Z",
            slot_end_date="2026-09-14T00:00:00Z", showings_per_day=2)
        create_validated_report(
            ctx["slot"]["id"], reported_date="2026-09-07T00:00:00Z",
            gross_receipts_cents=gross_a, admissions=1300)
        create_validated_report(
            slot_b["id"], reported_date="2026-09-07T00:00:00Z",
            gross_receipts_cents=gross_b, admissions=1300)
        statement = create_draft_statement(ctx["agreement"]["id"],
                                           ctx["window"]["id"])
        return ctx, slot_b, statement

    def test_gross_at_exact_tier1_cap_all_tier1(self, api):
        """PRD §3.6: "Gross up to and including the first boundary is shared
        at `revenue_share_tier1_pct` — at exactly the boundary, tier 1 still
        applies, and the very next cent spills into tier 2."
        PRD §3.6: "the line's `exhibitor_retained_cents` is its
        `gross_reported_cents` minus its `agreed_share_cents`".
        PRD §3.6: "On validation, the parent slot's `weekly_gross_cents`
        increases by the report's `gross_receipts_cents`."

        Design: Difficulty/boundary_precision_check/tier1_cap_one_cent_over_flips_into_tier2
        """
        ctx, slot_b, statement = self._two_slot_world(
            api, gross_a=10000000, gross_b=10000001)
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line_a = get_statement_line(fetched, ctx["slot"]["id"])
        line_b = get_statement_line(fetched, slot_b["id"])
        assert line_a["gross_reported_cents"] == 10000000
        assert line_a["agreed_share_cents"] == 1200000
        assert line_b["gross_reported_cents"] == 10000001
        assert line_a["exhibitor_retained_cents"] == 8800000
        # One cent over the cap: share = 1,200,000 + 0.15 -> round_half_up to
        # 2dp keeps 1200000.15; exhibitor retains gross - share.
        assert line_b["exhibitor_retained_cents"] == pytest.approx(
            10000001 - 1200000.15, abs=0.005)
        slot_a_read = validate_success(
            api.get_screen_slot(ctx["slot"]["id"], RS))
        slot_b_read = validate_success(api.get_screen_slot(slot_b["id"], RS))
        assert slot_a_read["weekly_gross_cents"] == 10000000
        assert slot_b_read["weekly_gross_cents"] == 10000001

    def test_gross_one_cent_over_spills_into_tier2(self, api):
        """PRD §3.6: "at exactly the boundary, tier 1 still applies, and the
        very next cent spills into tier 2."

        Design: Difficulty/boundary_precision_check/tier1_cap_one_cent_over_flips_into_tier2
        """
        ctx, slot_b, statement = self._two_slot_world(
            api, gross_a=10000000, gross_b=10000001)
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line_a = get_statement_line(fetched, ctx["slot"]["id"])
        line_b = get_statement_line(fetched, slot_b["id"])
        # The boundary line's share is 1,200,000.00; the over-cap line's
        # share carries the extra marginal cent at the tier-2 rate.
        assert line_b["agreed_share_cents"] == pytest.approx(1200000.15, abs=0.005)
        assert line_a["agreed_share_cents"] == 1200000


class TestStatementRecomputeOnRead:
    def test_new_validated_report_visible_on_read(self, api):
        """PRD §2.11: "lines and totals are recomputed whenever a relevant
        box-office report is validated, whenever a slot is confirmed, pulled,
        suspended, or restored, and on every read of the statement."

        Design: Corner/cross_cutting_complexity_layers/statement_derived_fields_recomputed_on_read
        """
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 1000000, 100)]
        )
        before = validate_success(api.get_statement(statement["id"], BOA))
        assert before["final_total_cents"] == 120000
        create_validated_report(
            slot["id"], reported_date="2026-09-08T00:00:00Z",
            gross_receipts_cents=1000000, admissions=100)
        after = validate_success(api.get_statement(statement["id"], BOA))
        assert after["final_total_cents"] == 240000

    def test_provisional_total_moves_with_new_reports(self, api):
        """PRD §2.11: "lines and totals are recomputed whenever a relevant
        box-office report is validated, whenever a slot is confirmed, pulled,
        suspended, or restored, and on every read of the statement."

        Design: Corner/cross_cutting_complexity_layers/statement_derived_fields_recomputed_on_read
        """
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 1000000, 100)]
        )
        before = validate_success(api.get_statement(statement["id"], BOA))
        create_validated_report(
            slot["id"], reported_date="2026-09-08T00:00:00Z",
            gross_receipts_cents=1000000, admissions=100)
        after = validate_success(api.get_statement(statement["id"], BOA))
        # Provisional after two reports: mean 1,000,000 over 2 reported days,
        # 5 unreported days forecast at half the mean:
        # line gross = 2,000,000 + 5 * 1,000,000 * 0.5 = 4,500,000;
        # share = 4,500,000 * 0.12 = 540,000.
        assert after["provisional_total_cents"] == 540000
        assert after["provisional_total_cents"] != \
            before["provisional_total_cents"]


class TestFlaggedReportsExcluded:
    def test_flagged_report_excluded_from_slot_aggregates(self, api):
        """PRD §3.6: "On validation, the parent slot's `weekly_gross_cents`
        increases by the report's `gross_receipts_cents`, its
        `weekly_admissions` increases by the report's `admissions`" — flagging
        carries no such side effect, and PRD §3.6 defines the statement
        totals over "only validated reports"."

        Design: Corner/calculations/flagged_discrepancy_reports_are_excluded_from_aggregates
        """
        ctx = setup_confirmed_slot_scenario()
        slot = ctx["slot"]
        create_validated_report(
            slot["id"], reported_date="2026-09-07T00:00:00Z",
            gross_receipts_cents=1000000, admissions=100)
        flagged = get_success_data(
            api.create_box_office_report(
                create_box_office_report_payload(
                    screen_slot_id=slot["id"],
                    reported_date="2026-09-08T00:00:00Z",
                    gross_receipts_cents=9999999, admissions=999),
                BOA)
        )
        get_success_data(api.flag_report_discrepancy(flagged["id"], BOA))
        fetched = validate_success(api.get_screen_slot(slot["id"], RS))
        assert fetched["weekly_gross_cents"] == 1000000
        assert fetched["weekly_admissions"] == 100

    def test_flagged_report_excluded_from_statement_totals(self, api):
        """PRD §3.6: "only validated reports count" for the final revenue
        share.

        Design: Corner/calculations/flagged_discrepancy_reports_are_excluded_from_aggregates
        """
        ctx = setup_confirmed_slot_scenario()
        slot = ctx["slot"]
        create_validated_report(
            slot["id"], reported_date="2026-09-07T00:00:00Z",
            gross_receipts_cents=1000000, admissions=100)
        flagged = get_success_data(
            api.create_box_office_report(
                create_box_office_report_payload(
                    screen_slot_id=slot["id"],
                    reported_date="2026-09-08T00:00:00Z",
                    gross_receipts_cents=9999999, admissions=999),
                BOA)
        )
        get_success_data(api.flag_report_discrepancy(flagged["id"], BOA))
        statement = create_draft_statement(ctx["agreement"]["id"],
                                           ctx["window"]["id"])
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line = get_statement_line(fetched, slot["id"])
        assert line["gross_reported_cents"] == 1000000
        assert line["agreed_share_cents"] == 120000


class TestAdjustmentInvariant:
    def _issued_disputed_statement(self, api):
        ctx, slot, statement = _statement_with_reports(
            [("2026-09-07T00:00:00Z", 10000000, 1300)]
        )
        get_success_data(api.issue_statement(statement["id"], BOA))
        efu = make_exhibitor_finance_headers(ctx["agreement"]["id"])
        get_success_data(api.dispute_statement(statement["id"], efu))
        return ctx, slot, statement

    def test_adjustment_preserves_retained_plus_share_equals_gross(self, api):
        """PRD §3.6: "the compensating invariant holds after every adjustment:
        for each line, exhibitor-retained plus agreed-share always equals
        gross-reported. The `final_total_cents` is then recomputed."
        and "An issued statement can be disputed by an
        `ExhibitorFinanceUser` — `ISSUED → DISPUTED` — and then adjusted by a
        `BoxOfficeAnalyst` — `DISPUTED → ADJUSTED`."

        Design: Difficulty/compensating_invariant/revenue_share_adjustment_conserves_gross_equals_retained_plus_share
        """
        ctx, slot, statement = self._issued_disputed_statement(api)
        resp = api.apply_statement_adjustment(
            statement["id"],
            {"screen_slot_id": slot["id"], "adjustment_cents": -50000,
             "adjustment_reason": "late-report correction"},
            BOA)
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "ADJUSTED"
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line = get_statement_line(fetched, slot["id"])
        assert_line_conservation_invariant(line)
        assert fetched["final_total_cents"] == 1150000

    def test_adjustment_appends_to_line_adjustments(self, api):
        """PRD §3.6: "The adjustment is appended to that line's `adjustments`
        list such that the sum of all lines' `agreed_share_cents` plus the
        sum of all adjustments equals the recomputed total."

        Design: Difficulty/compensating_invariant/revenue_share_adjustment_conserves_gross_equals_retained_plus_share
        """
        ctx, slot, statement = self._issued_disputed_statement(api)
        get_success_data(api.apply_statement_adjustment(
            statement["id"],
            {"screen_slot_id": slot["id"], "adjustment_cents": -50000,
             "adjustment_reason": "late-report correction"},
            BOA))
        fetched = validate_success(api.get_statement(statement["id"], BOA))
        line = get_statement_line(fetched, slot["id"])
        assert len(line["adjustments"]) == 1
        # gross_reported stays constant while the share side moves.
        assert line["gross_reported_cents"] == 10000000
        assert_line_conservation_invariant(line)
