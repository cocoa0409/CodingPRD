"""Dual-variant arithmetic of the Equity Award Administration API.

Three families of computation are exercised here, all of them cases where the
PRD pins an evaluation order that two naive implementations would get wrong in
different ways: the two withholding mechanics that settle an identical tax bill
to different share splits, the two burn-rate variants that are deliberately
allowed to disagree inside one fiscal year, and the largest-remainder tax
waterfall whose per-jurisdiction amounts are rounded before they are summed.
"""

from test_helpers import (
    ADMIN,
    allocate_taxes,
    api_client,
    assert_allocations_sum_to_full_bps,
    assert_burn_rate_summary,
    assert_reserve_conservation,
    assert_round_then_sum_total,
    assert_share_split_identity,
    assert_tax_allocation,
    assert_vesting_event,
    create_approved_grant,
    create_granted_grant,
    create_mobility_assignment,
    create_open_window,
    create_participant,
    create_plan,
    read_event,
    read_grant,
    read_plan,
    read_tranche,
    set_clock,
    validate_paginated,
    validate_success,
    vest_tranche,
)

# ---------------------------------------------------------------------------
# Module-private setup chains. Every test starts from an empty database, so each
# helper rebuilds its preconditions through the endpoints the PRD declares.
# ---------------------------------------------------------------------------
_WINDOW_OPEN_AT = "2026-01-05T00:00:00Z"
_WINDOW_CLOSE_AT = "2026-03-31T00:00:00Z"


def _two_method_settlement_scenario():
    """One RSU award with two identical 1000-share tranches, both VESTED at an
    fmv of 5000 cents and both tax-allocated over a single 4000 bps jurisdiction,
    one electing SHARE_WITHHOLD and the other SELL_TO_COVER.
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Plan A 2026",
        total_authorized_shares=10_000_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=1000,
        next_earnings_release_at="2026-02-10T21:00:00Z",
    )
    participant = create_participant(
        full_name="Ada Vest",
        employee_number="E-2882-01",
        home_country_code="US",
        home_state_code="CA",
        hire_date="2020-03-02",
        birth_date="1985-04-11",
        insider_status="NON_INSIDER",
    )
    create_open_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at=_WINDOW_OPEN_AT, close_at=_WINDOW_CLOSE_AT,
    )
    grant, tranches = create_granted_grant(
        plan["id"], participant["id"],
        award_type="RSU", target_shares=2000,
        tranches=[
            {"tranche_index": 1, "vest_type": "TIME",
             "scheduled_vest_date": "2026-07-01", "target_shares": 1000},
            {"tranche_index": 2, "vest_type": "TIME",
             "scheduled_vest_date": "2026-07-01", "target_shares": 1000},
        ],
    )
    create_mobility_assignment(
        participant["id"], jurisdiction_code="US-CA", tax_rate_bps=4000,
        start_date="2026-01-06", end_date="2026-06-30", workdays=250,
    )
    set_clock("2026-07-01T12:00:00Z")
    event_sw = vest_tranche(
        tranches[0]["id"], fmv_per_share_cents=5000,
        withholding_method="SHARE_WITHHOLD",
    )
    event_stc = vest_tranche(
        tranches[1]["id"], fmv_per_share_cents=5000,
        withholding_method="SELL_TO_COVER",
    )
    return {
        "plan": plan,
        "participant": participant,
        "grant": grant,
        "tranches": tranches,
        "event_share_withhold": allocate_taxes(event_sw["id"]),
        "event_sell_to_cover": allocate_taxes(event_stc["id"]),
    }


class TestWithholdingMethodDivergence:
    """The SHARE_WITHHOLD and SELL_TO_COVER mechanics against one tax bill."""

    def test_share_withhold_covers_the_tax_bill_with_no_commission(self):
        """PRD §3.7: "Under `SHARE_WITHHOLD`, `shares_withheld` is the total tax divided by the fair market value per share, rounded up to the next whole share; `shares_sold` is 0; `net_shares_delivered` is `gross_shares` minus `shares_withheld`; `residual_cash_cents` is `shares_withheld` multiplied by the fair market value per share, minus the total tax — the over-withholding refunded to the participant; and `cash_due_cents` is 0."

        Design: Difficulty/dual_variant_calc/withholding_method_divergence_share_withhold_vs_sell_to_cover
        """
        scenario = _two_method_settlement_scenario()
        event = scenario["event_share_withhold"]
        assert event["taxable_income_cents"] == 5000000, (
            "1000 gross shares at 5000 cents is 5000000 cents of taxable income"
        )
        assert event["total_tax_cents"] == 2000000, (
            "a single 4000 bps jurisdiction taxes 5000000 cents at 2000000 cents"
        )
        assert event["blended_rate_bps"] == 4000

        settled = validate_success(
            api_client.settle_vesting_event(event["id"], ADMIN), 200
        )
        assert settled["withholding_method"] == "SHARE_WITHHOLD"
        assert settled["shares_withheld"] == 400, (
            "2000000 cents of tax over an fmv of 5000 cents withholds 400 shares"
        )
        assert settled["shares_sold"] == 0, "SHARE_WITHHOLD sells nothing"
        assert settled["net_shares_delivered"] == 600
        assert settled["residual_cash_cents"] == 0, (
            "400 shares at 5000 cents exactly covers the 2000000-cent bill"
        )
        assert settled["cash_due_cents"] == 0
        assert settled["gross_shares"] == 1000
        assert_share_split_identity(settled)
        assert_vesting_event(settled)

        tranche = read_tranche(scenario["tranches"][0]["id"])
        assert tranche["status"] == "SETTLED", (
            "settling moves the owning tranche from VESTED to SETTLED"
        )
        grant = read_grant(scenario["grant"]["id"])
        assert grant["outstanding_shares"] == 1000, (
            "the settled tranche leaves the outstanding pool, the still-VESTED "
            "sibling tranche stays in it"
        )
        assert grant["weighted_reserve_shares"] == 3000, (
            "a SETTLED tranche remains committed against the reserve"
        )

    def test_sell_to_cover_nets_the_commission_before_dividing(self):
        """PRD §3.7: "The net proceeds per share are computed first, as the fair market value per share minus the 25-cent commission. The share count is computed second: `shares_sold` is the total tax divided by those net proceeds per share, rounded up to the next whole share. The realised proceeds are computed third, as `shares_sold` multiplied by the net proceeds per share. Then `shares_withheld` is 0, `net_shares_delivered` is `gross_shares` minus `shares_sold`, `residual_cash_cents` is the realised proceeds minus the total tax, and `cash_due_cents` is 0."

        Design: Difficulty/dual_variant_calc/withholding_method_divergence_share_withhold_vs_sell_to_cover
        """
        scenario = _two_method_settlement_scenario()
        event = scenario["event_sell_to_cover"]
        assert event["total_tax_cents"] == 2000000

        settled = validate_success(
            api_client.settle_vesting_event(event["id"], ADMIN), 200
        )
        assert settled["withholding_method"] == "SELL_TO_COVER"
        assert settled["shares_withheld"] == 0, "SELL_TO_COVER withholds nothing"
        assert settled["shares_sold"] == 403, (
            "2000000 cents of tax over net proceeds of 4975 cents per share "
            "rounds up to 403 shares sold"
        )
        assert settled["net_shares_delivered"] == 597
        assert settled["residual_cash_cents"] == 4925, (
            "403 shares at 4975 cents realises 2004925 cents against a "
            "2000000-cent bill"
        )
        assert settled["cash_due_cents"] == 0
        assert settled["gross_shares"] == 1000
        assert_share_split_identity(settled)

        tranche = read_tranche(scenario["tranches"][1]["id"])
        assert tranche["status"] == "SETTLED"

    def test_the_two_methods_deliver_different_net_shares_and_residual_cash(self):
        """PRD §3.7: "Because it rounds up against a smaller per-share figure, this method always sells at least as many shares as `SHARE_WITHHOLD` would have withheld and usually strictly more, so for identical gross shares, fair market value, and tax the two methods deliver a different `net_shares_delivered` **and** a different `residual_cash_cents`."

        Design: Difficulty/dual_variant_calc/withholding_method_divergence_share_withhold_vs_sell_to_cover
        """
        scenario = _two_method_settlement_scenario()
        share_withhold = validate_success(
            api_client.settle_vesting_event(
                scenario["event_share_withhold"]["id"], ADMIN
            ), 200,
        )
        sell_to_cover = validate_success(
            api_client.settle_vesting_event(
                scenario["event_sell_to_cover"]["id"], ADMIN
            ), 200,
        )
        assert share_withhold["gross_shares"] == sell_to_cover["gross_shares"] == 1000
        assert (
            share_withhold["fmv_per_share_cents"]
            == sell_to_cover["fmv_per_share_cents"] == 5000
        )
        assert share_withhold["total_tax_cents"] == sell_to_cover["total_tax_cents"]
        assert (
            share_withhold["net_shares_delivered"]
            != sell_to_cover["net_shares_delivered"]
        ), "identical inputs must still deliver a different net share count"
        assert (
            share_withhold["residual_cash_cents"]
            != sell_to_cover["residual_cash_cents"]
        ), "identical inputs must still leave a different residual cash figure"
        assert (
            sell_to_cover["shares_sold"] - share_withhold["shares_withheld"] == 3
        ), "the commission costs three extra shares on this bill"
        assert_share_split_identity(share_withhold)
        assert_share_split_identity(sell_to_cover)


def _approved_nso_grant_scenario():
    """A 20000-share NSO award APPROVED on the BOARD path against a 1000000-share
    float, so the fiscal-year gross accumulator carries exactly 20000 shares.
    """
    set_clock("2026-02-02T10:00:00Z")
    plan = create_plan(
        name="Plan B Float",
        total_authorized_shares=5_000_000,
        common_shares_outstanding=1_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=10000,
        fungible_ratio_full_value_bps=10000,
        low_reserve_threshold_bps=0,
    )
    participant = create_participant(
        full_name="Ben Float",
        employee_number="E-2882-02",
        home_country_code="US",
        home_state_code="NY",
        hire_date="2019-06-17",
        birth_date="1980-01-09",
    )
    grant, tranches = create_approved_grant(
        plan["id"], participant["id"],
        award_type="NSO", target_shares=20000, exercise_price_cents=3000,
        tranches=[
            {"tranche_index": 1, "vest_type": "TIME",
             "scheduled_vest_date": "2027-02-02", "target_shares": 20000},
        ],
    )
    return {"plan": plan, "participant": participant, "grant": grant,
            "tranches": tranches}


def _burn_rate_summary(plan_id):
    return validate_success(api_client.get_burn_rate_summary(plan_id, ADMIN), 200)


class TestBurnRateGrossVersusNetDivergence:
    """The GROSS and NET burn-rate variants across an approval and its
    compensating cancellation."""

    def test_cancellation_leaves_gross_burn_rate_standing_and_drops_net_to_zero(self):
        """PRD §3.4: "When the grant had a non-zero `weighted_reserve_shares`, that exact figure is added to the plan's `shares_returned_cumulative` and to its `fiscal_year_returned_shares`, after which the reserve ledger, `reserve_posture`, and the net burn rate are recomputed — the gross burn rate is deliberately **not** unwound."

        PRD §3.1: "The variants are deliberately allowed to disagree: `GROSS` ignores forfeitures and cancellations entirely and therefore never decreases inside a fiscal year, while `NET` falls as shares come back."

        Design: Difficulty/dual_variant_calc/burn_rate_gross_vs_net_divergence
        """
        scenario = _approved_nso_grant_scenario()
        plan_id = scenario["plan"]["id"]

        before = _burn_rate_summary(plan_id)
        assert before["gross_burn_rate_bps"] == 200, (
            "20000 weighted shares against a 1000000-share float is 200 bps"
        )
        assert before["net_burn_rate_bps"] == 200, (
            "nothing has come back yet, so the two variants agree"
        )

        cancelled = validate_success(
            api_client.cancel_grant(
                scenario["grant"]["id"], {"cancel_reason": "OFFER_RESCINDED"}, ADMIN
            ), 200,
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["weighted_reserve_shares"] == 0

        after = _burn_rate_summary(plan_id)
        assert after["gross_burn_rate_bps"] == 200, (
            "the gross variant never decreases inside a fiscal year"
        )
        assert after["net_burn_rate_bps"] == 0, (
            "the net variant falls to zero once the shares come back"
        )
        assert after["gross_burn_rate_bps"] != after["net_burn_rate_bps"], (
            "the two variants are permitted to disagree"
        )

        plan = read_plan(plan_id)
        assert plan["fiscal_year_gross_granted_shares"] == 20000
        assert plan["fiscal_year_returned_shares"] == 20000
        assert plan["shares_committed_cumulative"] == 20000
        assert plan["shares_returned_cumulative"] == 20000
        assert plan["available_reserve_shares"] == 5000000, (
            "the cancellation credits back exactly what the approval debited"
        )
        assert plan["gross_burn_rate_bps"] == 200
        assert plan["net_burn_rate_bps"] == 0
        assert_reserve_conservation(plan)

    def test_burn_rate_summary_exposes_both_variants_with_unchanged_headroom(self):
        """PRD §3.1: "A computed read exposes both variants side by side for a plan, together with `plan_id`, `fiscal_year_gross_granted_shares`, `fiscal_year_returned_shares`, `burn_rate_limit_bps`, `available_reserve_shares`, `reserve_posture`, and a `headroom_shares` figure. `headroom_shares` is the `burn_rate_limit_bps` multiplied by `common_shares_outstanding`, divided by 10000 and rounded **down** to a whole number of shares, minus `fiscal_year_gross_granted_shares`, and the result is floored at 0 so that an over-budget plan reports zero headroom rather than a negative one."

        Design: Difficulty/dual_variant_calc/burn_rate_gross_vs_net_divergence
        """
        scenario = _approved_nso_grant_scenario()
        plan_id = scenario["plan"]["id"]

        before = _burn_rate_summary(plan_id)
        assert before["plan_id"] == plan_id
        assert before["fiscal_year_gross_granted_shares"] == 20000
        assert before["fiscal_year_returned_shares"] == 0
        assert before["burn_rate_limit_bps"] == 10000
        assert before["headroom_shares"] == 980000, (
            "a 10000 bps limit on a 1000000-share float budgets 1000000 shares, "
            "of which 20000 are already granted"
        )
        assert_burn_rate_summary(before, read_plan(plan_id))

        validate_success(
            api_client.cancel_grant(
                scenario["grant"]["id"], {"cancel_reason": "OFFER_RESCINDED"}, ADMIN
            ), 200,
        )

        after = _burn_rate_summary(plan_id)
        assert after["fiscal_year_gross_granted_shares"] == 20000, (
            "the gross accumulator is never decremented by a cancellation"
        )
        assert after["fiscal_year_returned_shares"] == 20000
        assert after["headroom_shares"] == 980000, (
            "headroom is measured against the gross accumulator alone, so the "
            "returned shares do not restore fiscal-year budget"
        )
        assert after["available_reserve_shares"] == 5000000
        assert_burn_rate_summary(after, read_plan(plan_id))


def _three_jurisdiction_vested_event():
    """One 1000-share tranche VESTED at 5000 cents whose sourcing period fully
    contains three assignment periods carrying 3, 2 and 2 workdays.
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Plan C Mobility",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=0,
    )
    participant = create_participant(
        full_name="Cleo Mobile",
        employee_number="E-2882-03",
        home_country_code="US",
        home_state_code="CA",
        hire_date="2021-09-13",
        birth_date="1990-02-27",
    )
    create_open_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at=_WINDOW_OPEN_AT, close_at=_WINDOW_CLOSE_AT,
    )
    grant, tranches = create_granted_grant(
        plan["id"], participant["id"],
        award_type="RSU", target_shares=1000,
        tranches=[
            {"tranche_index": 1, "vest_type": "TIME",
             "scheduled_vest_date": "2026-07-01", "target_shares": 1000},
        ],
    )
    create_mobility_assignment(
        participant["id"], jurisdiction_code="US-CA", tax_rate_bps=4728,
        start_date="2026-01-06", end_date="2026-03-05", workdays=3,
    )
    create_mobility_assignment(
        participant["id"], jurisdiction_code="US-NY", tax_rate_bps=4484,
        start_date="2026-03-06", end_date="2026-04-30", workdays=2,
    )
    create_mobility_assignment(
        participant["id"], jurisdiction_code="GB", tax_rate_bps=4500,
        start_date="2026-05-01", end_date="2026-06-30", workdays=2,
    )
    set_clock("2026-07-01T12:00:00Z")
    event = vest_tranche(
        tranches[0]["id"], fmv_per_share_cents=5000,
        withholding_method="CASH_REMITTANCE",
    )
    return {"plan": plan, "participant": participant, "grant": grant,
            "tranches": tranches, "event": event}


class TestMobilityAllocationRoundThenSum:
    """The largest-remainder waterfall and the pinned round-then-sum order."""

    def test_largest_remainder_waterfall_awards_the_leftover_basis_point(self):
        """PRD §3.7: "First, each group receives a floor allocation: its workday figure multiplied by 10000, divided by `total_workdays`, rounded **down** to a whole number of basis points. The integer remainder retained for the tie-break is that group's workday figure multiplied by 10000, minus its floor allocation multiplied by `total_workdays`. Second, the leftover basis points — 10000 minus the sum of all floor allocations — are distributed one basis point at a time to the groups ordered by descending remainder, with ties broken by ascending `jurisdiction_code`, until the leftover is exhausted. Each group's `allocation_bps` is its floor allocation plus one if it received a leftover basis point. The allocations therefore sum to exactly 10000, always."

        Design: Difficulty/combinatorial_formula/mobility_allocation_round_then_sum
        """
        scenario = _three_jurisdiction_vested_event()
        event = validate_success(
            api_client.allocate_taxes(scenario["event"]["id"], ADMIN), 200
        )
        assert event["taxable_income_cents"] == 5000000
        assert event["total_workdays"] == 7, "3 plus 2 plus 2 sourced workdays"

        rows, meta = validate_paginated(
            api_client.list_event_tax_allocations(scenario["event"]["id"], ADMIN)
        )
        assert meta["total_count"] == 3, (
            "one immutable tax row per contributing jurisdiction"
        )
        by_code = {row["jurisdiction_code"]: row for row in rows}
        assert set(by_code) == {"US-CA", "US-NY", "GB"}

        assert by_code["US-CA"]["workdays_in_period"] == 3
        assert by_code["US-CA"]["allocation_bps"] == 4286, (
            "the floor of 4285 plus the single leftover basis point, which the "
            "largest remainder of 5 wins"
        )
        assert by_code["US-NY"]["workdays_in_period"] == 2
        assert by_code["US-NY"]["allocation_bps"] == 2857
        assert by_code["GB"]["workdays_in_period"] == 2
        assert by_code["GB"]["allocation_bps"] == 2857
        assert_allocations_sum_to_full_bps(rows)
        for row in rows:
            assert_tax_allocation(row)

    def test_per_jurisdiction_amounts_are_rounded_before_they_are_summed(self):
        """PRD §3.7: "Third, each group's `tax_amount_cents` is the settlement's `taxable_income_cents` multiplied by that group's `allocation_bps` multiplied by that group's rate, divided by 100000000, rounded half up to whole cents; the division is evaluated once over the exact product, with no intermediate rounding after the allocation step. Fourth, the settlement's `total_tax_cents` is the sum of those already-rounded per-jurisdiction amounts — round first, then sum. Summing the exact per-jurisdiction values and rounding once at the end is explicitly not the pinned order and can differ by a cent. Finally, `blended_rate_bps` is `total_tax_cents` multiplied by 10000, divided by `taxable_income_cents`, rounded half up to whole basis points."

        Design: Difficulty/combinatorial_formula/mobility_allocation_round_then_sum
        """
        scenario = _three_jurisdiction_vested_event()
        event = validate_success(
            api_client.allocate_taxes(scenario["event"]["id"], ADMIN), 200
        )
        rows, _ = validate_paginated(
            api_client.list_event_tax_allocations(scenario["event"]["id"], ADMIN)
        )
        by_code = {row["jurisdiction_code"]: row for row in rows}

        assert by_code["US-CA"]["tax_rate_bps"] == 4728
        assert by_code["US-CA"]["tax_amount_cents"] == 1013210
        assert by_code["US-NY"]["tax_rate_bps"] == 4484
        assert by_code["US-NY"]["tax_amount_cents"] == 640539
        assert by_code["GB"]["tax_rate_bps"] == 4500
        assert by_code["GB"]["tax_amount_cents"] == 642825

        assert event["total_tax_cents"] == 2296574, (
            "the round-then-sum order totals 2296574 cents"
        )
        assert event["total_tax_cents"] != 2296575, (
            "summing the exact per-jurisdiction values and rounding once at the "
            "end is not the pinned order"
        )
        assert event["blended_rate_bps"] == 4593
        assert_round_then_sum_total(event, rows)

        assert event["tax_status"] == "ALLOCATED"
        assert event["settlement_status"] == "PENDING_TAX", (
            "allocating taxes moves only the tax dimension"
        )
        stored = read_event(scenario["event"]["id"])
        assert stored["total_tax_cents"] == 2296574
        assert stored["blended_rate_bps"] == 4593


def _sell_to_cover_commission_scenario():
    """One 1500-share tranche VESTED at 3200 cents electing SELL_TO_COVER, taxed
    at a single 3700 bps jurisdiction so the bill is 1776000 cents.
    """
    set_clock("2026-01-05T09:00:00Z")
    plan = create_plan(
        name="Plan D Commission",
        total_authorized_shares=1_000_000,
        common_shares_outstanding=200_000_000,
        fiscal_year_start_date="2026-01-01",
        current_fiscal_year_label="FY2026",
        burn_rate_limit_bps=500,
        fungible_ratio_full_value_bps=15000,
        low_reserve_threshold_bps=0,
    )
    participant = create_participant(
        full_name="Dan Cover",
        employee_number="E-2882-04",
        home_country_code="US",
        home_state_code="NY",
        hire_date="2018-04-02",
        birth_date="1988-11-30",
    )
    create_open_window(
        plan["id"], quarter_label="FY2026-Q1",
        open_at=_WINDOW_OPEN_AT, close_at=_WINDOW_CLOSE_AT,
    )
    grant, tranches = create_granted_grant(
        plan["id"], participant["id"],
        award_type="RSU", target_shares=1500,
        tranches=[
            {"tranche_index": 1, "vest_type": "TIME",
             "scheduled_vest_date": "2026-07-01", "target_shares": 1500},
        ],
    )
    create_mobility_assignment(
        participant["id"], jurisdiction_code="US-NY", tax_rate_bps=3700,
        start_date="2026-01-06", end_date="2026-06-30", workdays=120,
    )
    set_clock("2026-07-01T12:00:00Z")
    event = vest_tranche(
        tranches[0]["id"], fmv_per_share_cents=3200,
        withholding_method="SELL_TO_COVER",
    )
    return {"plan": plan, "participant": participant, "grant": grant,
            "tranches": tranches, "event": allocate_taxes(event["id"])}


class TestSellToCoverCommissionPin:
    """The commission-per-share dependency resolved by the pinned closed form."""

    def test_share_count_divides_by_net_proceeds_rather_than_by_fair_market_value(self):
        """PRD §3.7: "Under `SELL_TO_COVER`, a broker commission of 25 cents is charged on every share sold, which makes the share count and the cost it must cover look mutually dependent; the evaluation order is therefore pinned to a closed form."

        PRD §3.7: "The net proceeds per share are computed first, as the fair market value per share minus the 25-cent commission. The share count is computed second: `shares_sold` is the total tax divided by those net proceeds per share, rounded up to the next whole share. The realised proceeds are computed third, as `shares_sold` multiplied by the net proceeds per share. Then `shares_withheld` is 0, `net_shares_delivered` is `gross_shares` minus `shares_sold`, `residual_cash_cents` is the realised proceeds minus the total tax, and `cash_due_cents` is 0."

        Design: Difficulty/combinatorial_formula/sell_to_cover_commission_circular_pin
        """
        scenario = _sell_to_cover_commission_scenario()
        event = scenario["event"]
        assert event["taxable_income_cents"] == 4800000
        assert event["total_tax_cents"] == 1776000
        assert event["blended_rate_bps"] == 3700

        settled = validate_success(
            api_client.settle_vesting_event(event["id"], ADMIN), 200
        )
        assert settled["shares_sold"] == 560, (
            "1776000 cents of tax over net proceeds of 3175 cents per share "
            "rounds up to 560 shares"
        )
        assert settled["shares_sold"] != 555, (
            "dividing by the gross fair market value of 3200 cents would sell "
            "only 555 shares and leave the bill uncovered"
        )
        assert settled["shares_withheld"] == 0
        assert settled["net_shares_delivered"] == 940
        assert settled["residual_cash_cents"] == 2000, (
            "560 shares at 3175 cents realises 1778000 cents against a "
            "1776000-cent bill"
        )
        assert settled["cash_due_cents"] == 0
        assert_share_split_identity(settled)

    def test_settling_sell_to_cover_moves_the_tranche_and_recomputes_outstanding(self):
        """PRD §3.7: "Settling records the `withholding_method` in force, writes the five derived figures, moves `settlement_status` to `SETTLED`, and moves the owning tranche from `VESTED` to `SETTLED`, which causes the grant's `outstanding_shares` to be recomputed — a `SETTLED` tranche leaves the outstanding pool while remaining committed against the reserve."

        Design: Difficulty/combinatorial_formula/sell_to_cover_commission_circular_pin
        """
        scenario = _sell_to_cover_commission_scenario()
        settled = validate_success(
            api_client.settle_vesting_event(scenario["event"]["id"], ADMIN), 200
        )
        assert settled["withholding_method"] == "SELL_TO_COVER"
        assert settled["settlement_status"] == "SETTLED"
        assert settled["tax_status"] == "ALLOCATED", (
            "settling moves only the settlement dimension"
        )

        tranche = read_tranche(scenario["tranches"][0]["id"])
        assert tranche["status"] == "SETTLED"
        assert tranche["shares"] == 1500, "settling never rewrites the share count"

        grant = read_grant(scenario["grant"]["id"])
        assert grant["outstanding_shares"] == 0, (
            "the only tranche has left the outstanding pool"
        )
        assert grant["weighted_reserve_shares"] == 2250, (
            "1500 shares weighted at 15000 bps stay committed against the reserve"
        )
        plan = read_plan(scenario["plan"]["id"])
        assert plan["shares_committed_cumulative"] == 2250
        assert plan["shares_returned_cumulative"] == 0
        assert_reserve_conservation(plan)
