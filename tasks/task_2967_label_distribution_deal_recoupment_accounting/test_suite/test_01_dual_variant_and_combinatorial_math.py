"""
Dual-variant divergences and the pinned combinatorial arithmetic: the
cross-collateralized versus siloed advance waterfall and its zero-baseline
projection, the PROVISIONAL versus FINAL statement basis, per-line rounding
order, the profit-share distributor cut, and the marketing cap's acyclicity cut
(PRD Sections 3.5, 3.6, 3.7, 3.8).

Every test here translates one instance of the difficulty index rules
`dual_variant_calc` and `combinatorial_formula`.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import (
    ANALYST,
    BASIS_VARIANT_FINAL,
    BASIS_VARIANT_PROVISIONAL,
    DEAL_TYPE_DISTRIBUTION_FEE,
    DEAL_TYPE_PROFIT_SHARE,
    FORMAT_DIGITAL,
    FORMAT_VINYL,
    RECOUPMENT_STATUS_RECOUPED,
    RECOUPMENT_STATUS_UNRECOUPED,
    REPORT_STATUS_ACCEPTED,
    REPORT_STATUS_SUBMITTED,
    RESERVE_STATUS_PARTIALLY_LIQUIDATED,
    SPEND_CATEGORY_DIGITAL_ADS,
    SPEND_CATEGORY_VIDEO_PRODUCTION,
    STATEMENT_STATUS_PREPARED,
    TIER_PREMIUM,
    VARIANT_CROSS_COLLATERALIZED,
    VARIANT_SILOED,
    assert_advance_conserved,
    assert_field_money,
    assert_fields,
    assert_fields_money,
    assert_pct_equals,
    assert_reserve_conserved,
    assert_status,
    do_liquidate,
    do_prepare_statement,
    do_set_clock,
    given_accepted_report,
    given_active_agreement,
    given_released_catalog,
    given_settled_spend,
    given_shipped_run,
    given_submitted_report,
    mk_statement,
    read_deal,
    read_release,
    read_report_lines,
    read_run,
    run_version,
)

# The two-release catalog both advance-variant instances are read against: a
# 650,000-cent deal advance carved 600,000 / 50,000 across two releases.
_ADVANCE_CATALOG_RELEASES = (
    {
        "title": "Glass Harbour",
        "advance_share_cents": 600000,
        "formats": (FORMAT_DIGITAL, FORMAT_VINYL),
    },
    {
        "title": "Salt Line",
        "advance_share_cents": 50000,
        "planned_release_date": "2026-02-15",
    },
)

# STRM/US/PREMIUM at four tenths of a cent and STRM/GB/PREMIUM at three tenths.
_TWO_TERRITORY_CARDS = (
    {
        "territory_code": "US",
        "tier": TIER_PREMIUM,
        "rate_micros_per_stream": 4000,
        "effective_from": "2026-01-01",
    },
    {
        "territory_code": "GB",
        "tier": TIER_PREMIUM,
        "rate_micros_per_stream": 3000,
        "effective_from": "2026-01-01",
    },
)

# 1,000,000 US streams price at 400,000 cents, 1,000,000 GB streams at 300,000,
# and 250,002 US streams at 250,002 * 4000 / 10,000 = 100,000.8 -> 100,001.
# Per-line rounding therefore yields a gross of exactly 800,001 cents.
_GROSS_800001_LINES = (
    {
        "release_index": 0,
        "territory_code": "US",
        "tier": TIER_PREMIUM,
        "stream_count": 1000000,
    },
    {
        "release_index": 0,
        "territory_code": "GB",
        "tier": TIER_PREMIUM,
        "stream_count": 1000000,
    },
    {
        "release_index": 1,
        "territory_code": "US",
        "tier": TIER_PREMIUM,
        "stream_count": 250002,
    },
)


def _advance_catalog(api, *, cross_collateralized):
    """A two-release DISTRIBUTION_FEE catalog carrying a 650,000-cent advance."""
    return given_released_catalog(
        api,
        deal_kw={
            "deal_type": DEAL_TYPE_DISTRIBUTION_FEE,
            "distribution_fee_pct": f.pct4("0.1500"),
            "cross_collateralized": cross_collateralized,
            "advance_amount_cents": 650000,
            # PRD 3.4: approving a spend requires the deal's already-committed
            # marketing plus the spend's amount to sit inside
            # marketing_budget_cents, so the catalog must carry a budget wide
            # enough for the 110,000 cents of marketing staged downstream.
            "marketing_budget_cents": 500000,
            "territory_codes": ("US", "GB"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
        releases=[dict(spec) for spec in _ADVANCE_CATALOG_RELEASES],
    )


def _accept_800001_report(api, ctx):
    """Price and accept the 800,001-cent gross period on that catalog."""
    return given_accepted_report(
        api,
        ctx,
        report_kw={"period_start": "2026-04-01", "period_end": "2026-06-30"},
        cards=[dict(card) for card in _TWO_TERRITORY_CARDS],
        lines=[dict(line) for line in _GROSS_800001_LINES],
    )


def test_cross_collateralized_and_siloed_projections_diverge_on_identical_data(api):
    """The projection "is always recomputed from a zero baseline", so forcing each
    variant on one accepted 680,001-cent period yields two different answers:
    CROSS_COLLATERALIZED pools everything and applies the whole 650,000 advance,
    leaving 0 unrecouped and 30,001 post-recoupment, while SILOED caps the weak
    release at its own 50,000 slice and applies only 645,000, leaving 5,000
    unrecouped and 35,001 post-recoupment. Neither read persists anything.

    Design: Difficulty/dual_variant_calc/cross_collateralized_vs_siloed_advance_recoupment
    """
    ctx = _advance_catalog(api, cross_collateralized=True)
    ctx = _accept_800001_report(api, ctx)

    report = ctx["report"]
    assert_status(report, REPORT_STATUS_ACCEPTED)
    assert_fields_money(
        report,
        gross_receipts_cents=800001,
        distributor_share_cents=120000,
        net_receipts_cents=680001,
        advance_applied_cents=650000,
    )

    before = read_deal(api, ctx["deal_id"])

    cross = validate_success(
        api.get_recoupment_summary(
            ctx["deal_id"], ANALYST, VARIANT_CROSS_COLLATERALIZED
        ),
        200,
    )
    assert_fields(cross, variant=VARIANT_CROSS_COLLATERALIZED)
    assert_fields_money(
        cross,
        pool_net_receipts_cents=680001,
        advance_amount_cents=650000,
        advance_applied_cents=650000,
        unrecouped_advance_cents=0,
        post_recoupment_net_receipts_cents=30001,
    )
    assert_status(cross, RECOUPMENT_STATUS_RECOUPED, field="recoupment_status")

    siloed = validate_success(
        api.get_recoupment_summary(ctx["deal_id"], ANALYST, VARIANT_SILOED), 200
    )
    assert_fields(siloed, variant=VARIANT_SILOED)
    assert_fields_money(
        siloed,
        pool_net_receipts_cents=680001,
        advance_amount_cents=650000,
        advance_applied_cents=645000,
        unrecouped_advance_cents=5000,
        post_recoupment_net_receipts_cents=35001,
    )
    assert_status(siloed, RECOUPMENT_STATUS_UNRECOUPED, field="recoupment_status")

    # "Nothing is persisted by this read."
    after = read_deal(api, ctx["deal_id"])
    assert after == before, (
        "the recoupment projection must not persist anything, but the deal moved "
        "from %r to %r" % (before, after)
    )


def test_cross_collateralized_advance_splits_back_by_largest_remainder(api):
    """Under the cross-collateralized variant one deal-level bucket absorbs the
    whole period and "that total is then split back across the releases by the
    same largest-remainder method used for the lines". Splitting 650,000 by
    contributions of 595,000 and 85,001 out of 680,001 gives exact shares of
    568,749.1636 and 81,250.8364, so the whole parts are 568,749 and 81,250 and
    the single leftover cent goes to the larger fraction: 568,749 and 81,251.

    Design: Difficulty/dual_variant_calc/cross_collateralized_vs_siloed_advance_recoupment
    """
    ctx = _advance_catalog(api, cross_collateralized=True)
    ctx = _accept_800001_report(api, ctx)

    assert_field_money(ctx["report"], "advance_applied_cents", 650000)

    deal = read_deal(api, ctx["deal_id"])
    assert_fields_money(
        deal,
        advance_amount_cents=650000,
        advance_recouped_cents=650000,
        unrecouped_advance_cents=0,
        net_receipts_to_date_cents=680001,
        post_recoupment_net_receipts_cents=30001,
    )
    assert_status(deal, RECOUPMENT_STATUS_RECOUPED, field="recoupment_status")
    assert_advance_conserved(deal)

    strong = read_release(api, ctx["releases"][0]["id"])
    assert_fields_money(
        strong,
        net_receipts_to_date_cents=595000,
        release_advance_recouped_cents=568749,
        unrecouped_advance_share_cents=31251,
    )

    weak = read_release(api, ctx["releases"][1]["id"])
    assert_fields_money(
        weak,
        net_receipts_to_date_cents=85001,
        release_advance_recouped_cents=81251,
        unrecouped_advance_share_cents=0,
    )

    # The split is an attribution of the single bucket, so it must exhaust it.
    assert (
        strong["release_advance_recouped_cents"]
        + weak["release_advance_recouped_cents"]
        == 650000
    ), "the largest-remainder split must distribute every applied cent"


def test_siloed_recoupment_strands_the_weak_releases_surplus(api):
    """With `cross_collateralized` false "each release has its own bucket capped at
    its own slice of the advance", so the 85,001-cent release stops at its 50,000
    slice and the deal applies only 595,000 + 50,000 = 645,000, leaving 5,000
    unrecouped and 35,001 post-recoupment. Omitting `variant` reproduces that
    645,000, while forcing CROSS_COLLATERALIZED reports 650,000 because the
    projection never reads the persisted balances.

    Design: Difficulty/dual_variant_calc/cross_collateralized_vs_siloed_advance_recoupment
    """
    ctx = _advance_catalog(api, cross_collateralized=False)
    ctx = _accept_800001_report(api, ctx)

    assert_field_money(ctx["report"], "advance_applied_cents", 645000)

    deal = read_deal(api, ctx["deal_id"])
    assert_fields_money(
        deal,
        advance_recouped_cents=645000,
        unrecouped_advance_cents=5000,
        post_recoupment_net_receipts_cents=35001,
    )
    assert_status(deal, RECOUPMENT_STATUS_UNRECOUPED, field="recoupment_status")
    assert_advance_conserved(deal)

    strong = read_release(api, ctx["releases"][0]["id"])
    assert_fields_money(
        strong,
        release_advance_recouped_cents=595000,
        unrecouped_advance_share_cents=5000,
    )

    weak = read_release(api, ctx["releases"][1]["id"])
    assert_fields_money(
        weak,
        net_receipts_to_date_cents=85001,
        release_advance_recouped_cents=50000,
        unrecouped_advance_share_cents=0,
    )

    # "omitting it evaluates the deal's own cross_collateralized setting"
    default_arm = validate_success(
        api.get_recoupment_summary(ctx["deal_id"], ANALYST), 200
    )
    assert_fields(default_arm, variant=VARIANT_SILOED)
    assert_fields_money(
        default_arm,
        pool_net_receipts_cents=680001,
        advance_applied_cents=645000,
        unrecouped_advance_cents=5000,
        post_recoupment_net_receipts_cents=35001,
    )
    assert_status(
        default_arm, RECOUPMENT_STATUS_UNRECOUPED, field="recoupment_status"
    )

    # "the persisted advance_recouped_cents and release_advance_recouped_cents
    # balances are never read" - the forced arm starts from zero, not from 645,000.
    forced_cross = validate_success(
        api.get_recoupment_summary(
            ctx["deal_id"], ANALYST, VARIANT_CROSS_COLLATERALIZED
        ),
        200,
    )
    assert_fields(forced_cross, variant=VARIANT_CROSS_COLLATERALIZED)
    assert_fields_money(
        forced_cross,
        pool_net_receipts_cents=680001,
        advance_applied_cents=650000,
        unrecouped_advance_cents=0,
        post_recoupment_net_receipts_cents=30001,
    )
    assert_status(forced_cross, RECOUPMENT_STATUS_RECOUPED, field="recoupment_status")


def _statement_basis_catalog(api):
    """The PRD Section 3.8 worked example, staged row by row.

    A recouped deal escalates the agreement to 0.1800; the accepted period leaves
    the release a 595,000-cent digital base; a 1,000-unit shipment at 900 cents
    against a 390,000-cent pressing leaves a 510,000-cent physical base and a
    135,000-cent reserve; and two marketing spends give a PROVISIONAL raw pool of
    80,000 against a FINAL raw pool of 45,000.
    """
    ctx = _advance_catalog(api, cross_collateralized=True)
    ctx = given_active_agreement(
        api,
        ctx,
        release_index=0,
        agreement_kw={
            "royalty_rate_pct": f.pct4("0.1200"),
            "escalated_royalty_rate_pct": f.pct4("0.1800"),
            "advance_amount_cents": 50000,
            "recording_costs_cents": 100000,
            "recording_recoupable_pct": f.pct4("0.5000"),
            "marketing_recoup_share_pct": f.pct4("0.5000"),
        },
    )
    ctx = _accept_800001_report(api, ctx)

    ctx = given_shipped_run(
        api,
        ctx,
        release_index=0,
        run_kw={
            "units_planned": 1300,
            "unit_manufacturing_cost_cents": 300,
            "returns_reserve_pct": f.pct4("0.1500"),
            "window_start": "2026-04-01",
            "window_end": "2026-06-30",
        },
        units_manufactured=1300,
        units_shipped=1000,
        wholesale_unit_price_cents=900,
    )

    # PROVISIONAL values the commitment (50,000 + half of 60,000 = 80,000);
    # FINAL values only the invoice actually paid (45,000).
    ctx = given_settled_spend(
        api,
        ctx,
        release_index=0,
        spend_kw={"category": SPEND_CATEGORY_DIGITAL_ADS, "amount_cents": 50000},
        settled_amount_cents=45000,
    )
    ctx = given_settled_spend(
        api,
        ctx,
        release_index=0,
        spend_kw={
            "category": SPEND_CATEGORY_VIDEO_PRODUCTION,
            "amount_cents": 60000,
        },
        stop_after="APPROVED",
    )
    return ctx


def _prepare_basis_statement(api, ctx, basis_variant):
    statement = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-04-01",
        period_end="2026-06-30",
        basis_variant=basis_variant,
    )
    return do_prepare_statement(api, statement["id"])


def test_provisional_and_final_statements_diverge_on_marketing_and_reserve(api):
    """Both divergences at once: "A `PROVISIONAL` statement takes spends whose
    status is `APPROVED` or `SETTLED` and values each at its `amount_cents`" while
    FINAL takes only settled invoices, and "a `PROVISIONAL` statement uses the
    **full** reserve ... while a `FINAL` statement uses only the **unliquidated**
    reserve". On a 198,900-cent gross royalty with 50,000 of advance and 50,000 of
    recording taken, PROVISIONAL charges 40,000 of marketing and withholds 24,300
    of the full 135,000 reserve for 34,600 payable, while FINAL charges 22,500 and
    withholds 14,580 of the 81,000 still held for 61,820 - a 27,220-cent gap.

    Design: Difficulty/dual_variant_calc/provisional_vs_final_statement_net_payable
    """
    ctx = _statement_basis_catalog(api)

    run = do_liquidate(
        api, ctx["run_id"], run_version(api, ctx["run_id"]), f.pct4("0.4000")
    )
    assert_fields_money(
        run,
        reserve_initial_cents=135000,
        reserve_held_cents=81000,
        reserve_liquidated_cents=54000,
    )
    assert_status(run, RESERVE_STATUS_PARTIALLY_LIQUIDATED, field="reserve_status")
    assert_reserve_conserved(run)

    provisional = _prepare_basis_statement(api, ctx, BASIS_VARIANT_PROVISIONAL)
    assert_status(provisional, STATEMENT_STATUS_PREPARED)
    assert_pct_equals(
        provisional["applied_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="applied_royalty_rate_pct",
    )
    assert_fields_money(
        provisional,
        digital_royalty_base_cents=595000,
        physical_royalty_base_cents=510000,
        gross_royalty_cents=198900,
        advance_applied_cents=50000,
        recording_applied_cents=50000,
        marketing_applied_cents=40000,
        reserve_withheld_cents=24300,
        net_payable_cents=34600,
    )

    final = _prepare_basis_statement(api, ctx, BASIS_VARIANT_FINAL)
    assert_status(final, STATEMENT_STATUS_PREPARED)
    assert_pct_equals(
        final["applied_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="applied_royalty_rate_pct",
    )
    assert_fields_money(
        final,
        digital_royalty_base_cents=595000,
        physical_royalty_base_cents=510000,
        gross_royalty_cents=198900,
        advance_applied_cents=50000,
        recording_applied_cents=50000,
        marketing_applied_cents=22500,
        reserve_withheld_cents=14580,
        net_payable_cents=61820,
    )

    assert final["net_payable_cents"] - provisional["net_payable_cents"] == 27220, (
        "the two variants must diverge by 27,220 cents on identical stored rows"
    )


def test_final_reserve_basis_equals_the_provisional_one_until_liquidation(api):
    """"Liquidating a reserve therefore raises the `FINAL` net payable without
    moving the `PROVISIONAL` figure by a cent" - so with nothing liquidated both
    variants withhold the same 24,300 cents against the same 135,000, and the only
    gap left is the marketing basis: 40,000 charged on the commitment against
    22,500 on the invoice, for 34,600 payable against 52,100.

    Design: Difficulty/dual_variant_calc/provisional_vs_final_statement_net_payable
    """
    ctx = _statement_basis_catalog(api)

    held = read_run(api, ctx["run_id"])
    assert_fields_money(
        held, reserve_initial_cents=135000, reserve_held_cents=135000
    )

    provisional = _prepare_basis_statement(api, ctx, BASIS_VARIANT_PROVISIONAL)
    assert_fields_money(
        provisional,
        gross_royalty_cents=198900,
        marketing_applied_cents=40000,
        reserve_withheld_cents=24300,
        net_payable_cents=34600,
    )

    final = _prepare_basis_statement(api, ctx, BASIS_VARIANT_FINAL)
    assert_fields_money(
        final,
        gross_royalty_cents=198900,
        marketing_applied_cents=22500,
        reserve_withheld_cents=24300,
        net_payable_cents=52100,
    )

    assert (
        final["reserve_withheld_cents"] == provisional["reserve_withheld_cents"]
    ), "with nothing liquidated the two reserve bases are the same rows"


def _one_release_fee_catalog(api):
    """A single-release DISTRIBUTION_FEE catalog at a 0.1500 fee and no advance."""
    return given_released_catalog(
        api,
        deal_kw={
            "deal_type": DEAL_TYPE_DISTRIBUTION_FEE,
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "territory_codes": ("US", "GB"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
    )


def test_gross_receipts_sum_per_line_rounded_figures_not_the_rounded_sum(api):
    """"rounding is applied once per line and never to the sum" - two lines of
    250,001 US streams at 4,000 micros each price at a raw 100,000.4, so each line
    rounds down to 100,000 and the report's gross is exactly 200,000. Summing the
    raw values first would round 200,000.8 up to 200,001, one cent too high, and
    would drag the 0.1500 fee and the net figure with it.

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_beats_sum_then_round
    """
    ctx = _one_release_fee_catalog(api)
    ctx = given_submitted_report(
        api,
        ctx,
        report_kw={"period_start": "2026-04-01", "period_end": "2026-06-30"},
        cards=[dict(card) for card in _TWO_TERRITORY_CARDS],
        lines=[
            {
                "territory_code": "US",
                "tier": TIER_PREMIUM,
                "stream_count": 250001,
            },
            {
                "territory_code": "US",
                "tier": TIER_PREMIUM,
                "stream_count": 250001,
            },
        ],
    )

    lines = read_report_lines(api, ctx["report_id"])
    assert len(lines) == 2, "the report must carry both appended lines"
    for line in lines:
        assert_fields(line, applied_rate_micros_per_stream=4000)
        assert_field_money(line, "resolved_revenue_cents", 100000)

    report = ctx["report"]
    assert_status(report, REPORT_STATUS_SUBMITTED)
    assert_fields_money(
        report,
        gross_receipts_cents=200000,
        distributor_share_cents=30000,
        net_receipts_cents=170000,
    )
    assert report["gross_receipts_cents"] != 200001, (
        "200,001 is the sum-then-round answer the pinned order forbids"
    )


def test_two_half_cent_lines_each_round_up_before_they_are_added(api):
    """The same pinned order in the opposite direction, with half-up biting on the
    exact midpoint: "a raw value of 400000.5 becomes 400001". Two lines of 333,335
    GB streams at 3,000 micros each price at a raw 100,000.5, so each rounds up to
    100,001 and the gross is 200,002 - one cent more than the 200,001 a
    sum-then-round implementation would report from a raw total of 200,001.0. The
    0.1500 fee on 200,002 is 30,000.3, which rounds back down to 30,000.

    Design: Difficulty/combinatorial_formula/per_line_rounding_order_beats_sum_then_round
    """
    ctx = _one_release_fee_catalog(api)
    ctx = given_submitted_report(
        api,
        ctx,
        report_kw={"period_start": "2026-04-01", "period_end": "2026-06-30"},
        cards=[dict(card) for card in _TWO_TERRITORY_CARDS],
        lines=[
            {
                "territory_code": "GB",
                "tier": TIER_PREMIUM,
                "stream_count": 333335,
            },
            {
                "territory_code": "GB",
                "tier": TIER_PREMIUM,
                "stream_count": 333335,
            },
        ],
    )

    lines = read_report_lines(api, ctx["report_id"])
    assert len(lines) == 2, "the report must carry both appended lines"
    for line in lines:
        assert_fields(line, applied_rate_micros_per_stream=3000)
        assert_field_money(line, "resolved_revenue_cents", 100001)

    report = ctx["report"]
    assert_fields_money(
        report,
        gross_receipts_cents=200002,
        distributor_share_cents=30000,
        net_receipts_cents=170002,
    )
    assert report["gross_receipts_cents"] != 200001, (
        "200,001 is the sum-then-round answer the pinned order forbids"
    )


# The same 800,001-cent gross as _GROSS_800001_LINES, attributed to one release.
_GROSS_800001_ONE_RELEASE_LINES = (
    {"territory_code": "US", "tier": TIER_PREMIUM, "stream_count": 1000000},
    {"territory_code": "GB", "tier": TIER_PREMIUM, "stream_count": 1000000},
    {"territory_code": "US", "tier": TIER_PREMIUM, "stream_count": 250002},
)


def _profit_share_period(
    api, *, settled_amount_cents, approve_clock, spend_amount_cents=150000
):
    """A PROFIT_SHARE period with two recoverable inputs and one 800,001 gross.

    A 1,000-unit pressing at 300 cents books 300,000 of manufacturing cost inside
    a window ending 2026-03-31, and one marketing spend is approved at
    ``approve_clock`` and settled at ``settled_amount_cents``.
    """
    ctx = given_released_catalog(
        api,
        clock=approve_clock,
        deal_kw={
            "deal_type": DEAL_TYPE_PROFIT_SHARE,
            "profit_share_label_pct": f.pct4("0.6000"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 500000,
            "territory_codes": ("US", "GB"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
        releases=[
            {"title": "Glass Harbour", "formats": (FORMAT_DIGITAL, FORMAT_VINYL)}
        ],
    )
    ctx = given_shipped_run(
        api,
        ctx,
        run_kw={
            "units_planned": 1000,
            "unit_manufacturing_cost_cents": 300,
            "window_start": "2026-01-01",
            "window_end": "2026-03-31",
        },
        units_manufactured=1000,
        units_shipped=900,
        wholesale_unit_price_cents=900,
    )
    ctx = given_settled_spend(
        api,
        ctx,
        spend_kw={
            "category": SPEND_CATEGORY_DIGITAL_ADS,
            "amount_cents": spend_amount_cents,
        },
        settled_amount_cents=settled_amount_cents,
    )
    do_set_clock(api, "2026-08-01T00:00:00.000Z")
    return given_submitted_report(
        api,
        ctx,
        report_kw={"period_start": "2026-04-01", "period_end": "2026-06-30"},
        cards=[dict(card) for card in _TWO_TERRITORY_CARDS],
        lines=[dict(line) for line in _GROSS_800001_ONE_RELEASE_LINES],
    )


def test_profit_share_distributor_cut_is_gross_less_the_half_up_label_share(api):
    """Three inputs feed one non-linear figure: "The profit base is the gross
    receipts less those recoverable costs, floored at zero" and "the raw
    distributor share is the gross receipts less that label share". 120,000 of
    settled marketing approved before the period plus 300,000 of manufacturing
    make 420,000 of recoverable costs, so the base is 800,001 - 420,000 = 380,001,
    the label's 0.6000 share is 228,000.6 rounding half up to 228,001, and the
    distributor keeps 800,001 - 228,001 = 572,000, leaving 228,001 net.

    Design: Difficulty/combinatorial_formula/profit_share_distributor_share_three_input_nonlinear
    """
    ctx = _profit_share_period(
        api, settled_amount_cents=120000, approve_clock="2026-03-01T00:00:00.000Z"
    )

    assert_field_money(ctx["run"], "manufacturing_cost_cents", 300000)
    assert_field_money(ctx["spend"], "settled_amount_cents", 120000)

    report = ctx["report"]
    assert_status(report, REPORT_STATUS_SUBMITTED)
    assert_fields_money(
        report,
        gross_receipts_cents=800001,
        distributor_share_cents=572000,
        net_receipts_cents=228001,
    )


def test_one_extra_cent_of_recoverable_cost_moves_the_distributor_share_by_one(api):
    """The label's share is "rounded half up to whole cents", so a single extra
    cent of recoverable cost is not absorbed: settling 120,001 instead of 120,000
    drops the profit base to exactly 380,000, whose 0.6000 share is 228,000.0
    rather than 228,000.6, and the distributor's cut rises by one cent to 572,001
    while net receipts fall to 228,000.

    Design: Difficulty/combinatorial_formula/profit_share_distributor_share_three_input_nonlinear
    """
    ctx = _profit_share_period(
        api, settled_amount_cents=120001, approve_clock="2026-03-01T00:00:00.000Z"
    )

    assert_field_money(ctx["spend"], "settled_amount_cents", 120001)

    report = ctx["report"]
    assert_fields_money(
        report,
        gross_receipts_cents=800001,
        distributor_share_cents=572001,
        net_receipts_cents=228000,
    )


def _marketing_cap_period(api, *, spend_amount_cents, approve_clock):
    """A PROFIT_SHARE period whose marketing spend is approved at ``approve_clock``.

    The period runs 2026-07-01 to 2026-09-30, so an approval stamped inside it is
    excluded from the distributor's recoverable costs while an approval stamped
    before 2026-07-01 is included. A 900-unit shipment at 900 cents against a
    300,000-cent pressing leaves a 510,000-cent physical base and an 81,000-cent
    reserve at the run's own 0.1000 rate.
    """
    ctx = given_released_catalog(
        api,
        deal_kw={
            "deal_type": DEAL_TYPE_PROFIT_SHARE,
            "profit_share_label_pct": f.pct4("0.6000"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 1000000,
            "territory_codes": ("US", "GB"),
            "term_start_date": "2026-01-01",
            "term_end_date": "2026-12-31",
        },
        releases=[
            {"title": "Glass Harbour", "formats": (FORMAT_DIGITAL, FORMAT_VINYL)}
        ],
    )
    ctx = given_active_agreement(
        api,
        ctx,
        agreement_kw={
            "royalty_rate_pct": f.pct4("0.1200"),
            "escalated_royalty_rate_pct": f.pct4("0.1800"),
            "advance_amount_cents": 0,
            "recording_costs_cents": 0,
            "marketing_recoup_share_pct": f.pct4("0.5000"),
        },
    )
    ctx = given_shipped_run(
        api,
        ctx,
        run_kw={
            "units_planned": 1000,
            "unit_manufacturing_cost_cents": 300,
            "returns_reserve_pct": f.pct4("0.1000"),
            "window_start": "2026-07-01",
            "window_end": "2026-09-30",
        },
        units_manufactured=1000,
        units_shipped=900,
        wholesale_unit_price_cents=900,
    )

    do_set_clock(api, approve_clock)
    ctx = given_settled_spend(
        api,
        ctx,
        spend_kw={
            "category": SPEND_CATEGORY_DIGITAL_ADS,
            "amount_cents": spend_amount_cents,
        },
        settled_amount_cents=spend_amount_cents,
    )
    do_set_clock(api, "2026-08-01T00:00:00.000Z")

    return given_accepted_report(
        api,
        ctx,
        report_kw={"period_start": "2026-07-01", "period_end": "2026-09-30"},
        cards=[dict(card) for card in _TWO_TERRITORY_CARDS],
        lines=[dict(line) for line in _GROSS_800001_ONE_RELEASE_LINES],
    )


def _prepare_final_q3_statement(api, ctx):
    statement = mk_statement(
        api,
        ctx["agreement_id"],
        period_start="2026-07-01",
        period_end="2026-09-30",
        basis_variant=BASIS_VARIANT_FINAL,
    )
    return do_prepare_statement(api, statement["id"])


def test_marketing_inside_the_period_is_excluded_from_costs_yet_capped_after(api):
    """The acyclicity cut and the cap it enables, in one chain: "marketing approved
    *inside* the period being reported never reduces the distributor's share for
    that same period", so 400,000 of settled marketing approved 2026-08-01 leaves
    recoverable costs at just the 300,000 pressing, the base at 500,001, the label
    share at 300,000.6 -> 300,001 and the distributor at 500,000 for 300,001 net.
    Only afterwards does that marketing meet its ceiling: "The cap,
    `marketing_cap_cents`, is thirty percent of that figure, rounded half up", so
    30% of 810,001 is 243,000.3 -> 243,000, the artist's half is 121,500, and the
    145,800-cent gross royalty nets 9,720 after a 14,580 reserve withholding.

    Design: Difficulty/combinatorial_formula/marketing_cap_cycle_broken_by_pinned_evaluation_order
    """
    ctx = _marketing_cap_period(
        api,
        spend_amount_cents=400000,
        approve_clock="2026-08-01T00:00:00.000Z",
    )

    report = ctx["report"]
    assert_status(report, REPORT_STATUS_ACCEPTED)
    assert_fields_money(
        report,
        gross_receipts_cents=800001,
        distributor_share_cents=500000,
        net_receipts_cents=300001,
    )

    statement = _prepare_final_q3_statement(api, ctx)
    assert_status(statement, STATEMENT_STATUS_PREPARED)
    assert_pct_equals(
        statement["applied_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="applied_royalty_rate_pct",
    )
    assert_fields_money(
        statement,
        digital_royalty_base_cents=300001,
        physical_royalty_base_cents=510000,
        gross_royalty_cents=145800,
        advance_applied_cents=0,
        recording_applied_cents=0,
        marketing_applied_cents=121500,
        reserve_withheld_cents=14580,
        net_payable_cents=9720,
    )
    assert statement["marketing_applied_cents"] < 400000, (
        "an uncapped implementation would charge the artist half of the whole "
        "400,000 raw pool and wipe the net payable out entirely"
    )


def test_marketing_cap_does_not_bind_when_the_raw_pool_sits_below_it(api):
    """"The recoupable pool is the smaller of that raw pool and the cap" - with only
    200,000 of settled marketing the raw pool is under the same 243,000 ceiling, so
    the artist's half is 100,000 rather than 121,500 and the net payable rises to
    145,800 - 100,000 - 14,580 = 31,220. The report figures are untouched at
    500,000 and 300,001 because this spend was also approved inside the period.

    Design: Difficulty/combinatorial_formula/marketing_cap_cycle_broken_by_pinned_evaluation_order
    """
    ctx = _marketing_cap_period(
        api,
        spend_amount_cents=200000,
        approve_clock="2026-08-01T00:00:00.000Z",
    )

    assert_fields_money(
        ctx["report"],
        gross_receipts_cents=800001,
        distributor_share_cents=500000,
        net_receipts_cents=300001,
    )

    statement = _prepare_final_q3_statement(api, ctx)
    assert_fields_money(
        statement,
        digital_royalty_base_cents=300001,
        physical_royalty_base_cents=510000,
        gross_royalty_cents=145800,
        marketing_applied_cents=100000,
        reserve_withheld_cents=14580,
        net_payable_cents=31220,
    )


def test_marketing_approved_before_the_period_does_reduce_the_distributor_share(api):
    """The other side of the cut: recoverable costs include "the
    `settled_amount_cents` of every marketing spend ... whose `approved_at` falls
    strictly before the midnight that opens the report's `period_start`". Moving
    the same 400,000 approval from 2026-08-01 to 2026-06-15 lifts recoverable costs
    to 700,000, drops the base to 100,001, makes the label's 0.6000 share 60,000.6
    -> 60,001 and hands the distributor 740,000 instead of 500,000, leaving 60,001
    net rather than 300,001.

    Design: Difficulty/combinatorial_formula/marketing_cap_cycle_broken_by_pinned_evaluation_order
    """
    ctx = _marketing_cap_period(
        api,
        spend_amount_cents=400000,
        approve_clock="2026-06-15T00:00:00.000Z",
    )

    assert_fields_money(
        ctx["report"],
        gross_receipts_cents=800001,
        distributor_share_cents=740000,
        net_receipts_cents=60001,
    )
