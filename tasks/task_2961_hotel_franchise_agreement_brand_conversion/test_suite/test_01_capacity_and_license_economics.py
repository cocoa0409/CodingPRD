"""Owner capacity variants, license drafting clamps and the fee ledger's
rounding order."""

from test_helpers import (
    BSD_HEADERS,
    FDM_HEADERS,
    assert_capacity_bands,
    assert_integer,
    assert_instant,
    assert_money,
    fixtures,
    get_success_data,
)


# ─── Both capacity variants are produced from one owner row (PRD §2.11, §3.2) ──

def test_thin_portfolio_owner_scores_lower_on_the_portfolio_adjusted_variant(api):
    """PRD §3.2: the PORTFOLIO_ADJUSTED variant subtracts 250,000.00 of reserve
    for each existing unit before the liquidity component is scored, so an
    owner whose liquidity is not yet at the benchmark scores strictly lower on
    the adjusted variant than on the standalone one, while the experience
    bonus of 1.5 per unit is not enough to make up the difference.

    Design: Difficulty/dual_variant_calc/owner_capacity_standalone_vs_portfolio_adjusted_diverges_in_both_directions
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    owner = fixtures.create_owner(
        api,
        legal_name="Cascade Thin Portfolio LLC",
        contact_email="thin@cascadethin.example",
        liquid_assets_amount=2_400_000.00,
        net_worth_amount=7_500_000.00,
        credit_score=680,
        existing_units_count=3,
    )

    assert_money(owner["capacity_score_standalone"], 51.60, "capacity_score_standalone")
    assert_money(
        owner["capacity_score_portfolio_adjusted"], 49.35, "capacity_score_portfolio_adjusted"
    )
    assert owner["capacity_band_standalone"] == "INSUFFICIENT"
    assert owner["capacity_band_portfolio_adjusted"] == "INSUFFICIENT"
    assert owner["capacity_score_portfolio_adjusted"] < owner["capacity_score_standalone"], (
        "the reserve deduction must pull the adjusted score below the standalone score "
        f"for a thin portfolio: {owner['capacity_score_portfolio_adjusted']} vs "
        f"{owner['capacity_score_standalone']}"
    )
    assert_capacity_bands(owner)
    assert_integer(owner["financial_profile_revision"], 0, "financial_profile_revision")
    assert owner["status"] == "PROSPECT"


def test_strong_portfolio_owner_scores_higher_on_the_portfolio_adjusted_variant(api):
    """PRD §3.2: when the reserve deduction still leaves liquidity at or above
    the 5,000,000.00 benchmark the liquidity component stays capped at 100.00,
    so the experience bonus of 1.5 for each of up to five existing units is
    pure upside and the adjusted variant overtakes the standalone one - both
    capped at 100.00 after the bonus.

    Design: Difficulty/dual_variant_calc/owner_capacity_standalone_vs_portfolio_adjusted_diverges_in_both_directions
    """
    fixtures.set_clock(api, "2026-08-01T00:00:00Z")
    owner = fixtures.create_strong_owner(api)

    assert_money(owner["capacity_score_standalone"], 96.67, "capacity_score_standalone")
    assert_money(
        owner["capacity_score_portfolio_adjusted"], 100.00, "capacity_score_portfolio_adjusted"
    )
    assert owner["capacity_band_standalone"] == "STRONG"
    assert owner["capacity_band_portfolio_adjusted"] == "STRONG"
    assert owner["capacity_score_portfolio_adjusted"] > owner["capacity_score_standalone"], (
        "the experience bonus must lift the adjusted score above the standalone score "
        f"when the reserve does not bite: {owner['capacity_score_portfolio_adjusted']} vs "
        f"{owner['capacity_score_standalone']}"
    )
    assert_capacity_bands(owner)


# ─── Liquidated damages on a consensual exit (PRD §3.9) ──────────────

def test_mutual_termination_prices_liquidated_damages_at_discounted_present_value(api):
    """PRD §3.9: a MUTUAL cause selects DISCOUNTED_PV.  The basis is the sum of
    royalty_fee plus marketing_fee over the surviving revenue periods with
    reservation_fee excluded, the trailing average is that basis divided by
    reported_period_count, the remaining span is the month-index difference to
    expiry, and the amount is the sum of one term per month up to the frozen
    cap of 36, each term rounded to two decimals before it enters the sum.

    Design: Difficulty/dual_variant_calc/liquidated_damages_discounted_pv_on_mutual_termination
    """
    world = fixtures.setup_agreement_with_two_revenue_periods(api)
    world = fixtures.setup_termination_pending_agreement(
        api, world, cause="MUTUAL", terminate_clock="2027-03-01T00:00:00Z"
    )
    agreement = world["agreement"]

    assert agreement["liquidated_damages_formula"] == "DISCOUNTED_PV"
    # 44000.02 royalty + 20000.00 marketing = 64000.02 over two periods.
    assert_money(agreement["trailing_avg_monthly_fee"], 32000.01, "trailing_avg_monthly_fee")
    # Expiry 2046-10 minus termination 2027-03 on month indices.
    assert_integer(
        agreement["remaining_term_months_at_termination"],
        235,
        "remaining_term_months_at_termination",
    )
    assert_money(agreement["liquidated_damages_amount"], 1_051_872.86, "liquidated_damages_amount")


def test_mutual_termination_arms_every_post_termination_obligation(api):
    """PRD §3.9: termination moves the license OPEN -> TERMINATION_PENDING,
    stamps terminated_at from the logical clock, arms de-identification with a
    thirty-day deadline, opens the post-termination file, suspends a CONNECTED
    channel and suspends an IN_PROGRESS improvement plan, while leaving the
    fee ledger exactly as it was.

    Design: Difficulty/dual_variant_calc/liquidated_damages_discounted_pv_on_mutual_termination
    """
    world = fixtures.setup_agreement_with_two_revenue_periods(api)
    world = fixtures.setup_termination_pending_agreement(
        api, world, cause="MUTUAL", terminate_clock="2027-03-01T00:00:00Z"
    )
    agreement = world["agreement"]

    assert agreement["status"] == "TERMINATION_PENDING"
    assert agreement["termination_cause"] == "MUTUAL"
    assert_instant(agreement["terminated_at"], "2027-03-01T00:00:00.000Z", "terminated_at")
    assert agreement["de_identification_status"] == "PENDING"
    assert_instant(
        agreement["de_identification_deadline"],
        "2027-03-31T00:00:00.000Z",
        "de_identification_deadline",
    )
    assert agreement["channel_status"] == "SUSPENDED"
    assert agreement["post_termination_status"] == "OPEN"
    assert_money(agreement["total_fees_assessed"], 78_000.02, "total_fees_assessed")

    plan = get_success_data(api.get_pip(world["plan_id"], BSD_HEADERS))
    assert plan["status"] == "SUSPENDED", (
        f"an IN_PROGRESS plan must be suspended by termination, got {plan['status']}"
    )


# ─── Three independent clamps bind at once (PRD §3.6) ────────────────

def _aurora_world(api):
    """A LUXURY brand at the 7.00 royalty ceiling with a 100-room incumbent
    two miles out, and a 120-room COMPETITOR conversion asking 25 years."""
    world = fixtures.setup_reviewable_application(
        api,
        brand_overrides={
            "code": "AURORA",
            "name": "Aurora Grand",
            "tier": "LUXURY",
            "base_royalty_rate_pct": 7.00,
            "marketing_fund_rate_pct": 2.80,
            "protected_radius_miles": 5.00,
            "min_room_count": 80,
            "standard_term_years": 20,
        },
        existing_units=[
            {
                "unit_name": "Aurora Grand Lakeside",
                "market_code": "SEADT",
                "x_miles": 1.20,
                "y_miles": 1.60,
                "room_count": 100,
                "adr_amount": 310.00,
                "occupancy_pct": 72.00,
                "territory_start_date": "2016-06-01",
                "territory_end_date": "2026-09-30",
            }
        ],
        application_overrides={
            "property_name": "Lakeside Tower Hotel",
            "building_age_years": 22,
            "requested_term_years": 25,
        },
    )
    world = fixtures.setup_reviewed_application(api, world)
    fixtures.set_clock(api, "2026-09-01T00:00:00Z")
    world["application"] = fixtures.decide_application(
        api,
        world["application_id"],
        "APPROVE",
        decision_notes="Approved with an encroachment waiver.",
        encroachment_waiver_granted=True,
    )
    fixtures.set_clock(api, "2026-09-05T00:00:00Z")
    agreement = fixtures.draft_agreement(api, world["application_id"], "2026-10-01")
    world["agreement"] = agreement
    world["agreement_id"] = agreement["id"]
    return world


def test_draft_license_binds_the_royalty_ceiling_and_the_marketing_ceiling(api):
    """PRD §3.6: the royalty rate is the brand base plus the COMPETITOR
    conversion adjustment of 0.75 minus the STRONG portfolio discount of 0.50,
    then floored at 3.50 and capped at 7.00; the marketing rate takes the
    +0.50 surcharge because the final impact score reaches 12.00, then is
    capped at 3.00.  Both ceilings bind here, so neither arithmetic detail is
    observable in the rate alone - the review snapshot and the confirmed
    verdict pin the inputs.

    Design: Difficulty/combinatorial_formula/license_terms_three_independent_clamps_all_bind_at_draft
    """
    world = _aurora_world(api)
    application = get_success_data(api.get_application(world["application_id"], FDM_HEADERS))

    assert_money(application["capacity_score_at_review"], 100.00, "capacity_score_at_review")
    assert application["capacity_band_at_review"] == "STRONG"
    assert_money(application["final_impact_score"], 32.73, "final_impact_score")
    assert application["encroachment_verdict"] == "ENCROACHMENT_CONFIRMED"

    agreement = world["agreement"]
    assert_money(agreement["royalty_rate_pct"], 7.00, "royalty_rate_pct")
    assert_money(agreement["marketing_fund_rate_pct"], 3.00, "marketing_fund_rate_pct")


def test_draft_license_binds_the_term_clamp_and_freezes_the_brand_terms(api):
    """PRD §3.6: the term is the greater of the requested years and 15, then
    reduced to the brand's standard_term_years, so a 25-year request against a
    20-year brand is drafted at 20; the expiry date is the effective date
    advanced by that many calendar years; and the draft freezes the brand code
    and the 36-month liquidated damages cap.

    Design: Difficulty/combinatorial_formula/license_terms_three_independent_clamps_all_bind_at_draft
    """
    world = _aurora_world(api)
    agreement = world["agreement"]

    assert_integer(agreement["term_years"], 20, "term_years")
    assert agreement["effective_date"] == "2026-10-01"
    assert agreement["expiry_date"] == "2046-10-01", (
        f"expiry is the effective date plus the term in calendar years, got {agreement['expiry_date']}"
    )
    assert agreement["status"] == "DRAFT"
    assert agreement["brand_code"] == "AURORA"
    assert_integer(agreement["liquidated_damages_cap_months"], 36, "liquidated_damages_cap_months")


# ─── The fee ledger rounds each period before summing (PRD §3.8) ──────

def test_marketing_fund_total_rounds_each_period_before_summing(api):
    """PRD §2.6 and §3.8: each period's marketing_fee is rounded to two
    decimals as it is assessed and the running total is the exact sum of those
    rounded lines, never a re-rounding of the raw products.  Revenues of
    320000.16 and 480000.16 at 2.50 percent give 8000.00 and 12000.00, so the
    total is 20000.00; summing the unrounded products first yields 20000.01.

    Design: Difficulty/combinatorial_formula/marketing_fund_total_rounds_per_period_then_sums
    """
    world = fixtures.setup_agreement_with_two_revenue_periods(api)
    agreement = world["agreement"]
    periods = agreement["revenue_periods"]

    assert len(periods) == 2, f"expected two ledger entries, got {len(periods)}"
    assert_money(periods[0]["marketing_fee"], 8_000.00, "revenue_periods[0].marketing_fee")
    assert_money(periods[1]["marketing_fee"], 12_000.00, "revenue_periods[1].marketing_fee")
    assert_money(
        agreement["marketing_fund_contributed_total"], 20_000.00, "marketing_fund_contributed_total"
    )
    assert round(agreement["marketing_fund_contributed_total"], 2) != 20_000.01, (
        "20000.01 is the sum-then-round result, which PRD §2.6 forbids"
    )


def test_progressive_royalty_and_reservation_totals_are_exact_sums_of_rounded_periods(api):
    """PRD §3.8: the royalty on a period is assessed in three progressive
    slices - the base rate to 200,000.00, the rate plus 0.50 to 500,000.00 and
    the rate plus 1.00 above that - each slice rounded then summed, and the
    reservation fee is a flat 1.75 percent.  Every running total and
    total_fees_assessed are exact sums over the surviving periods.

    Design: Difficulty/combinatorial_formula/marketing_fund_total_rounds_per_period_then_sums
    """
    world = fixtures.setup_agreement_with_two_revenue_periods(api)
    agreement = world["agreement"]
    periods = agreement["revenue_periods"]

    assert_money(periods[0]["royalty_fee"], 17_400.01, "revenue_periods[0].royalty_fee")
    assert_money(periods[1]["royalty_fee"], 26_600.01, "revenue_periods[1].royalty_fee")
    assert_money(agreement["royalty_fee_to_date"], 44_000.02, "royalty_fee_to_date")
    assert_money(agreement["reservation_fee_to_date"], 14_000.00, "reservation_fee_to_date")
    assert_money(periods[1]["period_total_fee"], 47_000.01, "revenue_periods[1].period_total_fee")
    assert_money(agreement["total_fees_assessed"], 78_000.02, "total_fees_assessed")
    assert_integer(agreement["reported_period_count"], 2, "reported_period_count")
