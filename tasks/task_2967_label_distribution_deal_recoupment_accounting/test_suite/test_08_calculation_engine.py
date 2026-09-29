"""
The money engine: per-stream rate resolution, the three distributor-share
branches, the largest-remainder allocation of the distributor's cut, the
marketing cap, the artist deduction waterfall, the recoupment projection and the
audit materiality gate (PRD Sections 2.6, 3.5, 3.6, 3.8, 3.9).

Every test here translates one instance of the corner-case index section
`calculations`.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories as f
from test_helpers import (
    AGREEMENT_STATUS_AMENDMENT_PENDING,
    AGREEMENT_STATUS_SUPERSEDED,
    ANALYST,
    AUDIT_COST_BEARER_ARTIST,
    AUDIT_COST_BEARER_LABEL,
    AUDIT_STATUS_COMPLETED,
    BASIS_VARIANT_FINAL,
    BASIS_VARIANT_PROVISIONAL,
    BIZ_AFFAIRS,
    DEAL_TYPE_LABEL_SERVICES,
    DEFAULT_DSP_CODE,
    FORMAT_CD,
    LABEL_ADMIN,
    RECOUPABILITY_FULL,
    RECOUPABILITY_HALF,
    RECOUPABILITY_NONE,
    RECOUPMENT_STATUS_RECOUPED,
    RECOUPMENT_STATUS_UNRECOUPED,
    REPORT_STATUS_SUBMITTED,
    SPEND_CATEGORY_DIGITAL_ADS,
    SPEND_CATEGORY_PUBLICITY,
    SPEND_CATEGORY_VIDEO_PRODUCTION,
    SPEND_DECISION_APPROVE,
    STATEMENT_STATUS_FINALIZED,
    STATEMENT_STATUS_REVISED,
    TIER_AD_SUPPORTED,
    TIER_PREMIUM,
    VARIANT_CROSS_COLLATERALIZED,
    VARIANT_SILOED,
    assert_field,
    assert_field_money,
    assert_fields_money,
    assert_null,
    assert_pct_equals,
    assert_status,
    assert_version_is,
    deal_version,
    do_accept_report,
    do_activate_agreement,
    do_decide_spend,
    do_finalize_statement,
    do_issue_statement,
    do_manufacture,
    do_prepare_statement,
    do_propose_amendment,
    do_request_audit,
    do_set_clock,
    do_ship,
    do_submit_report,
    do_submit_spend,
    find_by_id,
    given_released_catalog,
    mk_agreement,
    mk_line,
    mk_rate_card,
    mk_report,
    mk_run,
    mk_spend,
    mk_statement,
    read_agreement,
    read_deal,
    read_release,
    validate_list,
)

FINALIZE_CLOCK_INSTANT = "2026-09-01T00:00:00.000Z"


def _three_key_rate_book(api):
    """An EXECUTED 0.1500 DISTRIBUTION_FEE deal licensed for US and GB with one
    RELEASED digital release, plus three open-ended STRM cards that differ only in
    territory and tier: US/PREMIUM 4,000 micros, US/AD_SUPPORTED 1,200 and
    GB/PREMIUM 3,000."""
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "territory_codes": ("US", "GB"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
        },
        releases=[
            {
                "title": "Triple Key",
                "planned_release_date": "2026-02-01",
                "advance_share_cents": 0,
            }
        ],
        actual_release_date="2026-02-01",
    )
    for territory, tier, rate in (
        ("US", TIER_PREMIUM, 4000),
        ("US", TIER_AD_SUPPORTED, 1200),
        ("GB", TIER_PREMIUM, 3000),
    ):
        mk_rate_card(
            api,
            dsp_code=DEFAULT_DSP_CODE,
            territory_code=territory,
            tier=tier,
            rate_micros_per_stream=rate,
            effective_from="2026-01-01",
        )
    return ctx


def test_each_line_is_priced_by_its_own_dsp_territory_and_tier_card(api):
    """Candidate cards are those "whose `dsp_code` equals the report's `dsp_code`,
    whose `territory_code` equals the line's `territory_code`, whose `tier` equals
    the line's `tier`", and each line's `resolved_revenue_cents` is its
    `stream_count` times its rate over "the ten thousand micros that make a cent".
    Three lines resolve 4,000, 1,200 and 3,000 micros for 400,000 + 60,000 +
    75,000 = 535,000 cents gross, a 0.1500 share of 80,250 and a net of 454,750.

    Design: Corner/calculations/line_rate_resolution_keys_on_the_full_dsp_territory_tier_triple
    """
    ctx = _three_key_rate_book(api)
    report = mk_report(
        api,
        ctx["deal_id"],
        ctx["partner_headers"],
        dsp_code=DEFAULT_DSP_CODE,
        period_start="2026-04-01",
        period_end="2026-06-30",
    )
    line_us_premium = mk_line(
        api,
        report["id"],
        ctx["release_id"],
        ctx["partner_headers"],
        territory_code="US",
        tier=TIER_PREMIUM,
        stream_count=1000000,
    )
    line_us_ad = mk_line(
        api,
        report["id"],
        ctx["release_id"],
        ctx["partner_headers"],
        territory_code="US",
        tier=TIER_AD_SUPPORTED,
        stream_count=500000,
    )
    line_gb_premium = mk_line(
        api,
        report["id"],
        ctx["release_id"],
        ctx["partner_headers"],
        territory_code="GB",
        tier=TIER_PREMIUM,
        stream_count=250000,
    )

    priced = validate_success(
        api.submit_report(report["id"], ctx["partner_headers"]), 200
    )
    assert_fields_money(
        priced,
        gross_receipts_cents=535000,
        distributor_share_cents=80250,
        net_receipts_cents=454750,
    )

    lines, _meta = validate_list(api.list_report_lines(report["id"], ANALYST))
    us_premium = find_by_id(lines, line_us_premium["id"])
    assert_field(us_premium, "applied_rate_micros_per_stream", 4000)
    assert_field_money(us_premium, "resolved_revenue_cents", 400000)

    us_ad = find_by_id(lines, line_us_ad["id"])
    assert_field(us_ad, "applied_rate_micros_per_stream", 1200)
    assert_field_money(us_ad, "resolved_revenue_cents", 60000)

    gb_premium = find_by_id(lines, line_gb_premium["id"])
    assert_field(gb_premium, "applied_rate_micros_per_stream", 3000)
    assert_field_money(gb_premium, "resolved_revenue_cents", 75000)


def test_pricing_a_report_books_no_receipts_and_leaves_line_nets_null(api):
    """"a line is priced when its report is submitted and allocated when its report
    is accepted, never at creation", and the second acceptance hop is the only
    place the deal's ledger moves. After submit the report reads `SUBMITTED`, every
    line still carries a null `net_receipts_cents`, and the deal's
    `net_receipts_to_date_cents` is still 0.

    Design: Corner/calculations/line_rate_resolution_keys_on_the_full_dsp_territory_tier_triple
    """
    ctx = _three_key_rate_book(api)
    report = mk_report(
        api,
        ctx["deal_id"],
        ctx["partner_headers"],
        dsp_code=DEFAULT_DSP_CODE,
        period_start="2026-04-01",
        period_end="2026-06-30",
    )
    for territory, tier, streams in (
        ("US", TIER_PREMIUM, 1000000),
        ("US", TIER_AD_SUPPORTED, 500000),
        ("GB", TIER_PREMIUM, 250000),
    ):
        mk_line(
            api,
            report["id"],
            ctx["release_id"],
            ctx["partner_headers"],
            territory_code=territory,
            tier=tier,
            stream_count=streams,
        )

    priced = validate_success(
        api.submit_report(report["id"], ctx["partner_headers"]), 200
    )
    assert_status(priced, REPORT_STATUS_SUBMITTED)

    lines, _meta = validate_list(api.list_report_lines(report["id"], ANALYST))
    assert len(lines) == 3, "expected the three appended lines, got %d" % len(lines)
    for line in lines:
        assert_null(line, "net_receipts_cents")

    assert_field_money(
        read_deal(api, ctx["deal_id"]), "net_receipts_to_date_cents", 0
    )


def _report_with_one_million_streams(api, ctx, period_start, period_end):
    report = mk_report(
        api,
        ctx["deal_id"],
        ctx["partner_headers"],
        dsp_code=DEFAULT_DSP_CODE,
        period_start=period_start,
        period_end=period_end,
    )
    line = mk_line(
        api,
        report["id"],
        ctx["release_id"],
        ctx["partner_headers"],
        territory_code="US",
        tier=TIER_PREMIUM,
        stream_count=1000000,
    )
    return report["id"], line["id"]


def test_the_card_in_force_at_period_end_prices_the_line_not_the_card_in_force_now(api):
    """Candidates are the cards "whose `effective_from` falls on or before the
    report's `period_end`, and whose `effective_to` is either null or falls strictly
    after the report's `period_end`". Three adjacent US/PREMIUM cards at 9,000,
    4,000 and 7,000 micros price two identical 1,000,000-stream lines differently:
    the Q1 report takes 4,000 for a 400,000-cent gross and the Q2 report takes
    7,000 for 700,000, even though both are submitted at the same 2026-08-01 clock
    where only the 7,000 card is live.

    Design: Corner/calculations/rate_card_window_is_evaluated_at_period_end_not_at_the_clock
    """
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
        },
        releases=[
            {
                "title": "Window Walk",
                "planned_release_date": "2026-01-15",
                "advance_share_cents": 0,
            }
        ],
        actual_release_date="2026-01-15",
    )
    for rate, effective_from, effective_to in (
        (9000, "2025-01-01", "2026-02-01"),
        (4000, "2026-02-01", "2026-04-01"),
        (7000, "2026-04-01", None),
    ):
        validate_success(
            api.create_rate_card(
                f.rate_card_payload(
                    dsp_code=DEFAULT_DSP_CODE,
                    territory_code="US",
                    tier=TIER_PREMIUM,
                    rate_micros_per_stream=rate,
                    effective_from=effective_from,
                    effective_to=effective_to,
                ),
                LABEL_ADMIN,
            ),
            201,
        )

    q1_report_id, q1_line_id = _report_with_one_million_streams(
        api, ctx, "2026-01-01", "2026-03-31"
    )
    q2_report_id, q2_line_id = _report_with_one_million_streams(
        api, ctx, "2026-04-01", "2026-06-30"
    )

    q1 = validate_success(api.submit_report(q1_report_id, ctx["partner_headers"]), 200)
    assert_fields_money(
        q1,
        gross_receipts_cents=400000,
        distributor_share_cents=60000,
        net_receipts_cents=340000,
    )
    q2 = validate_success(api.submit_report(q2_report_id, ctx["partner_headers"]), 200)
    assert_fields_money(
        q2,
        gross_receipts_cents=700000,
        distributor_share_cents=105000,
        net_receipts_cents=595000,
    )

    q1_lines, _q1_meta = validate_list(api.list_report_lines(q1_report_id, ANALYST))
    assert_field(
        find_by_id(q1_lines, q1_line_id), "applied_rate_micros_per_stream", 4000
    )
    q2_lines, _q2_meta = validate_list(api.list_report_lines(q2_report_id, ANALYST))
    assert_field(
        find_by_id(q2_lines, q2_line_id), "applied_rate_micros_per_stream", 7000
    )


def test_the_label_services_monthly_fee_scales_by_inclusive_calendar_months(api):
    """The month count "is twelve times the difference between the year of
    `period_end` and the year of `period_start`, plus the difference between the
    month of `period_end` and the month of `period_start`, plus one". Three reports
    with the same 500,000-cent gross and spans of three months, six days inside
    January and two months give shares of 50,000 + 25,000 x 3 = 125,000,
    50,000 + 25,000 = 75,000 and 50,000 + 50,000 = 100,000.

    Design: Corner/calculations/label_services_month_count_scales_the_monthly_fee_per_period
    """
    ctx = given_released_catalog(
        api,
        deal_kw={
            "deal_type": DEAL_TYPE_LABEL_SERVICES,
            "services_fee_pct": f.pct4("0.1000"),
            "services_monthly_fee_cents": 25000,
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
        },
        releases=[
            {
                "title": "Service Charge",
                "planned_release_date": "2026-01-05",
                "advance_share_cents": 0,
            }
        ],
        actual_release_date="2026-01-05",
    )
    mk_rate_card(
        api,
        dsp_code=DEFAULT_DSP_CODE,
        territory_code="US",
        tier=TIER_PREMIUM,
        rate_micros_per_stream=5000,
        effective_from="2026-01-01",
    )

    three_months, _l3 = _report_with_one_million_streams(
        api, ctx, "2026-01-01", "2026-03-31"
    )
    one_month, _l1 = _report_with_one_million_streams(
        api, ctx, "2026-01-15", "2026-01-20"
    )
    two_months, _l2 = _report_with_one_million_streams(
        api, ctx, "2026-11-01", "2026-12-31"
    )

    priced_three = validate_success(
        api.submit_report(three_months, ctx["partner_headers"]), 200
    )
    assert_fields_money(
        priced_three,
        gross_receipts_cents=500000,
        distributor_share_cents=125000,
        net_receipts_cents=375000,
    )

    priced_one = validate_success(
        api.submit_report(one_month, ctx["partner_headers"]), 200
    )
    assert_fields_money(
        priced_one,
        gross_receipts_cents=500000,
        distributor_share_cents=75000,
        net_receipts_cents=425000,
    )

    priced_two = validate_success(
        api.submit_report(two_months, ctx["partner_headers"]), 200
    )
    assert_fields_money(
        priced_two,
        gross_receipts_cents=500000,
        distributor_share_cents=100000,
        net_receipts_cents=400000,
    )


def _capped_campaign_statement(api):
    """An EXECUTED CD deal with a 600,000-cent marketing budget, one SHIPPED run
    worth 600,000 in physical net receipts against a 90,000-cent reserve, one
    ACTIVE 0.5000 agreement sharing marketing at 0.5000, three APPROVED spends of
    300,000 DIGITAL_ADS, 100,000 VIDEO_PRODUCTION and 200,000 PUBLICITY, and one
    DRAFT PROVISIONAL statement for the run's window."""
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 600000,
        },
        releases=[
            {
                "title": "Capped Campaign",
                "planned_release_date": "2026-02-01",
                "formats": (FORMAT_CD,),
                "advance_share_cents": 0,
            }
        ],
        actual_release_date="2026-02-01",
    )
    agreement = mk_agreement(
        api,
        ctx["artist_id"],
        ctx["release_id"],
        royalty_rate_pct=f.pct4("0.5000"),
        escalated_royalty_rate_pct=f.pct4("0.5000"),
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.5000"),
        marketing_recoup_share_pct=f.pct4("0.5000"),
    )
    do_activate_agreement(api, agreement["id"])

    run = mk_run(
        api,
        ctx["release_id"],
        ctx["dist_id"],
        units_planned=1200,
        unit_manufacturing_cost_cents=250,
        window_start="2026-04-01",
        window_end="2026-06-30",
        returns_reserve_pct=f.pct4("0.1000"),
    )
    do_manufacture(api, run["id"], 1200)
    ctx["run"] = do_ship(api, run["id"], 1000, 900, ctx["partner_headers"])

    ctx["spends"] = {}
    for key, category, amount, vendor in (
        ("full", SPEND_CATEGORY_DIGITAL_ADS, 300000, "Northlight Media"),
        ("half", SPEND_CATEGORY_VIDEO_PRODUCTION, 100000, "Cutroom Nine"),
        ("none", SPEND_CATEGORY_PUBLICITY, 200000, "Bright Press"),
    ):
        spend = mk_spend(
            api,
            ctx["release_id"],
            category=category,
            amount_cents=amount,
            vendor=vendor,
        )
        do_submit_spend(api, spend["id"], LABEL_ADMIN)
        ctx["spends"][key] = do_decide_spend(
            api, spend["id"], SPEND_DECISION_APPROVE, BIZ_AFFAIRS
        )

    ctx["agreement_id"] = agreement["id"]
    ctx["statement_id"] = mk_statement(
        api,
        agreement["id"],
        period_start="2026-04-01",
        period_end="2026-06-30",
        basis_variant=BASIS_VARIANT_PROVISIONAL,
    )["id"]
    return ctx


def test_the_thirty_percent_marketing_cap_binds_and_publicity_contributes_nothing(api):
    """The raw pool multiplies "its basis amount by the recoupability factor of its
    `recoupability` - 1.0000 for `FULLY_RECOUPABLE`, 0.5000 for `HALF_RECOUPABLE`,
    0.0000 for `NON_RECOUPABLE`", giving 300,000 + 50,000 + 0 = 350,000, while the
    cap is "thirty percent of that figure, rounded half up" = 180,000 of the
    600,000-cent period net receipts. The artist's 0.5000 share of the capped
    180,000 makes the observable `marketing_applied_cents` 90,000 - not 350,000,
    175,000, 180,000 or 300,000.

    Design: Corner/calculations/marketing_cap_binds_and_non_recoupable_category_contributes_zero
    """
    ctx = _capped_campaign_statement(api)
    assert_field(ctx["spends"]["full"], "recoupability", RECOUPABILITY_FULL)
    assert_field(ctx["spends"]["half"], "recoupability", RECOUPABILITY_HALF)
    assert_field(ctx["spends"]["none"], "recoupability", RECOUPABILITY_NONE)
    assert_fields_money(
        ctx["run"], reserve_initial_cents=90000, physical_net_receipts_cents=600000
    )

    prepared = validate_success(
        api.prepare_statement(ctx["statement_id"], ANALYST), 200
    )
    assert_fields_money(
        prepared,
        digital_royalty_base_cents=0,
        physical_royalty_base_cents=600000,
        marketing_applied_cents=90000,
    )


def test_the_capped_marketing_charge_flows_through_the_rest_of_the_waterfall(api):
    """"`net_payable_cents` is what is left after the three buckets and the
    reserve", and `reserve_withheld_cents` is the reserve basis "multiplied by
    `applied_royalty_rate_pct`, rounded half up". A 300,000-cent gross royalty with
    empty advance and recording buckets, a 90,000-cent marketing charge and a
    45,000-cent withholding on the full 90,000 PROVISIONAL reserve nets 165,000,
    while the deal's committed marketing sits exactly on its 600,000 budget.

    Design: Corner/calculations/marketing_cap_binds_and_non_recoupable_category_contributes_zero
    """
    ctx = _capped_campaign_statement(api)

    prepared = validate_success(
        api.prepare_statement(ctx["statement_id"], ANALYST), 200
    )
    assert_pct_equals(
        prepared["applied_royalty_rate_pct"],
        f.pct4("0.5000"),
        field="applied_royalty_rate_pct",
    )
    assert_fields_money(
        prepared,
        gross_royalty_cents=300000,
        advance_applied_cents=0,
        recording_applied_cents=0,
        marketing_applied_cents=90000,
        reserve_withheld_cents=45000,
        net_payable_cents=165000,
    )

    assert_field_money(
        read_deal(api, ctx["deal_id"]), "marketing_committed_cents", 600000
    )


def _report_with_three_awkward_lines(api):
    """A SUBMITTED report whose three lines price to 400,000, 300,000 and 100,001
    cents, so the 0.1500 distributor share of the 800,001-cent gross is 120,000 and
    the largest-remainder split has two leftover cents to place."""
    ctx = _three_key_rate_book(api)
    report = mk_report(
        api,
        ctx["deal_id"],
        ctx["partner_headers"],
        dsp_code=DEFAULT_DSP_CODE,
        period_start="2026-04-01",
        period_end="2026-06-30",
    )
    ctx["report_id"] = report["id"]
    ctx["line_ids"] = []
    for territory, tier, streams in (
        ("US", TIER_PREMIUM, 1000001),
        ("US", TIER_AD_SUPPORTED, 2500003),
        ("GB", TIER_PREMIUM, 333338),
    ):
        ctx["line_ids"].append(
            mk_line(
                api,
                report["id"],
                ctx["release_id"],
                ctx["partner_headers"],
                territory_code=territory,
                tier=tier,
                stream_count=streams,
            )["id"]
        )
    ctx["submitted"] = do_submit_report(api, report["id"], ctx["partner_headers"])
    return ctx


def test_the_two_leftover_allocation_cents_go_to_the_largest_fractional_parts(api):
    """"that leftover is distributed one cent at a time to the lines ranked by the
    fractional part of their exact share descending". Splitting a 120,000-cent
    share over weights 400,000 / 300,000 / 100,001 gives exact parts of
    59,999.925, 44,999.944 and 15,000.131, so the two leftover cents go to the
    second line and then the first, leaving line nets of 340,000, 255,000 and
    85,001 - never 340,001 / 255,001 / 84,999.

    Design: Corner/calculations/leftover_allocation_cents_follow_the_largest_fractional_parts
    """
    ctx = _report_with_three_awkward_lines(api)
    assert_fields_money(
        ctx["submitted"],
        gross_receipts_cents=800001,
        distributor_share_cents=120000,
        net_receipts_cents=680001,
    )

    accepted = validate_success(
        api.accept_report(
            ctx["report_id"],
            f.accept_report_payload(deal_version(api, ctx["deal_id"])),
            ANALYST,
        ),
        200,
    )
    assert_field_money(accepted, "net_receipts_cents", 680001)

    lines, _meta = validate_list(api.list_report_lines(ctx["report_id"], ANALYST))
    nets = []
    for line_id, expected in zip(ctx["line_ids"], (340000, 255000, 85001)):
        line = find_by_id(lines, line_id)
        assert_field_money(line, "net_receipts_cents", expected)
        nets.append(line["net_receipts_cents"])
    assert sum(nets) == 680001, (
        "line nets must conserve the report net exactly, got %r" % (nets,)
    )


def test_accepting_the_report_rolls_the_allocated_nets_up_to_release_and_deal(api):
    """The second hop increases each release's `net_receipts_to_date_cents` "by the
    sum of its own lines' `net_receipts_cents`" and the deal's by "the report's
    `net_receipts_cents`". With every line on one release both ancestors read the
    same 680,001 cents, which is only true if no allocation cent was lost or
    duplicated.

    Design: Corner/calculations/leftover_allocation_cents_follow_the_largest_fractional_parts
    """
    ctx = _report_with_three_awkward_lines(api)
    assert_field_money(
        read_release(api, ctx["release_id"]), "net_receipts_to_date_cents", 0
    )

    validate_success(
        api.accept_report(
            ctx["report_id"],
            f.accept_report_payload(deal_version(api, ctx["deal_id"])),
            ANALYST,
        ),
        200,
    )
    assert_field_money(
        read_release(api, ctx["release_id"]), "net_receipts_to_date_cents", 680001
    )
    assert_field_money(
        read_deal(api, ctx["deal_id"]), "net_receipts_to_date_cents", 680001
    )


def _two_rates_on_one_shipped_run(api):
    """One SHIPPED run worth 600,000 in physical net receipts against a 90,000-cent
    reserve, read by two ACTIVE agreements on the same release that differ only in
    royalty rate - 0.5000 and 0.0100 - each carrying a 150,000-cent advance and a
    50,000-cent recoupable recording balance, with one DRAFT PROVISIONAL statement
    apiece."""
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
        },
        releases=[
            {
                "title": "Bucket Order",
                "planned_release_date": "2026-02-01",
                "formats": (FORMAT_CD,),
                "advance_share_cents": 0,
            }
        ],
        actual_release_date="2026-02-01",
    )
    run = mk_run(
        api,
        ctx["release_id"],
        ctx["dist_id"],
        units_planned=1200,
        unit_manufacturing_cost_cents=250,
        window_start="2026-04-01",
        window_end="2026-06-30",
        returns_reserve_pct=f.pct4("0.1000"),
    )
    do_manufacture(api, run["id"], 1200)
    ctx["run"] = do_ship(api, run["id"], 1000, 900, ctx["partner_headers"])

    for key, rate in (("big", "0.5000"), ("small", "0.0100")):
        agreement = mk_agreement(
            api,
            ctx["artist_id"],
            ctx["release_id"],
            royalty_rate_pct=f.pct4(rate),
            escalated_royalty_rate_pct=f.pct4(rate),
            advance_amount_cents=150000,
            recording_costs_cents=100000,
            recording_recoupable_pct=f.pct4("0.5000"),
            marketing_recoup_share_pct=f.pct4("0.5000"),
        )
        do_activate_agreement(api, agreement["id"])
        ctx[key + "_agreement_id"] = agreement["id"]
        ctx[key + "_statement_id"] = mk_statement(
            api,
            agreement["id"],
            period_start="2026-04-01",
            period_end="2026-06-30",
            basis_variant=BASIS_VARIANT_PROVISIONAL,
        )["id"]
    return ctx


def test_the_advance_bucket_fills_before_the_recording_bucket(api):
    """"`advance_applied_cents` takes the lesser of the gross royalty and the
    agreement's `unrecouped_artist_advance_cents`. What remains after that flows to
    `recording_applied_cents`". A 300,000-cent gross fills the whole 150,000
    advance and then the whole 50,000 recording balance, leaving 100,000 against
    which the 45,000-cent reserve withholding nets 55,000 payable.

    Design: Corner/calculations/deduction_buckets_fill_in_order_and_the_net_floors_at_zero
    """
    ctx = _two_rates_on_one_shipped_run(api)
    assert_fields_money(
        ctx["run"], reserve_initial_cents=90000, physical_net_receipts_cents=600000
    )

    prepared = validate_success(
        api.prepare_statement(ctx["big_statement_id"], ANALYST), 200
    )
    assert_fields_money(
        prepared,
        digital_royalty_base_cents=0,
        physical_royalty_base_cents=600000,
        gross_royalty_cents=300000,
        advance_applied_cents=150000,
        recording_applied_cents=50000,
        marketing_applied_cents=0,
        reserve_withheld_cents=45000,
        net_payable_cents=55000,
    )


def test_a_thin_gross_is_swallowed_by_the_advance_and_the_net_floors_at_zero(api):
    """The buckets are "filled strictly in order, each taking the smaller of what
    remains and its own ceiling", and "`net_payable_cents` is what is left after the
    three buckets and the reserve, floored at zero". A 6,000-cent gross is taken
    entirely by the advance bucket, so recording applies 0 despite a 50,000
    outstanding balance, and the 900-cent reserve withholding reports 0 rather than
    -900. Nothing in the agreement's ledger moves, because "the debits happen only
    at finalization".

    Design: Corner/calculations/deduction_buckets_fill_in_order_and_the_net_floors_at_zero
    """
    ctx = _two_rates_on_one_shipped_run(api)

    prepared = validate_success(
        api.prepare_statement(ctx["small_statement_id"], ANALYST), 200
    )
    assert_fields_money(
        prepared,
        gross_royalty_cents=6000,
        advance_applied_cents=6000,
        recording_applied_cents=0,
        marketing_applied_cents=0,
        reserve_withheld_cents=900,
        net_payable_cents=0,
    )

    assert_fields_money(
        read_agreement(api, ctx["small_agreement_id"]),
        unrecouped_artist_advance_cents=150000,
        unrecouped_recording_cents=50000,
    )


def _deal_one_accept_from_recoupment(api):
    """A 100,000-cent advance deal with two releases, three agreements - a
    SUPERSEDED 0.1000/0.2000 predecessor and an ACTIVE 0.1200/0.1800 successor on
    the reported release, plus an AMENDMENT_PENDING 0.1100/0.1900 agreement on the
    unreported one - and a SUBMITTED report whose single line nets 340,000."""
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 100000,
            "marketing_budget_cents": 0,
        },
        releases=[
            {
                "title": "Escalator One",
                "planned_release_date": "2026-02-01",
                "advance_share_cents": 60000,
            },
            {
                "title": "Escalator Two",
                "planned_release_date": "2026-05-01",
                "advance_share_cents": 40000,
            },
        ],
        actual_release_date="2026-02-01",
        release_indexes=[0],
    )
    reported_release_id = ctx["releases"][0]["id"]
    quiet_release_id = ctx["releases"][1]["id"]

    old = mk_agreement(
        api,
        ctx["artist_id"],
        reported_release_id,
        royalty_rate_pct=f.pct4("0.1000"),
        escalated_royalty_rate_pct=f.pct4("0.2000"),
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
        marketing_recoup_share_pct=f.pct4("0.0000"),
    )
    do_activate_agreement(api, old["id"])
    new = mk_agreement(
        api,
        ctx["artist_id"],
        reported_release_id,
        royalty_rate_pct=f.pct4("0.1200"),
        escalated_royalty_rate_pct=f.pct4("0.1800"),
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
        marketing_recoup_share_pct=f.pct4("0.0000"),
        supersedes_agreement_id=old["id"],
    )
    do_activate_agreement(api, new["id"])
    amending = mk_agreement(
        api,
        ctx["artist_id"],
        quiet_release_id,
        royalty_rate_pct=f.pct4("0.1100"),
        escalated_royalty_rate_pct=f.pct4("0.1900"),
        advance_amount_cents=0,
        recording_costs_cents=0,
        recording_recoupable_pct=f.pct4("0.0000"),
        marketing_recoup_share_pct=f.pct4("0.0000"),
    )
    do_activate_agreement(api, amending["id"])
    do_propose_amendment(api, amending["id"], f.pct4("0.1300"), 0)

    mk_rate_card(
        api,
        dsp_code=DEFAULT_DSP_CODE,
        territory_code="US",
        tier=TIER_PREMIUM,
        rate_micros_per_stream=4000,
        effective_from="2026-01-01",
    )
    report = mk_report(
        api,
        ctx["deal_id"],
        ctx["partner_headers"],
        dsp_code=DEFAULT_DSP_CODE,
        period_start="2026-04-01",
        period_end="2026-06-30",
    )
    mk_line(
        api,
        report["id"],
        reported_release_id,
        ctx["partner_headers"],
        territory_code="US",
        tier=TIER_PREMIUM,
        stream_count=1000000,
    )
    ctx["submitted"] = do_submit_report(api, report["id"], ctx["partner_headers"])
    ctx["report_id"] = report["id"]
    ctx["old_agreement_id"] = old["id"]
    ctx["new_agreement_id"] = new["id"]
    ctx["amending_agreement_id"] = amending["id"]
    ctx["reported_release_id"] = reported_release_id
    ctx["quiet_release_id"] = quiet_release_id
    return ctx


def test_the_recouped_flip_reprices_every_accountable_agreement_of_the_deal(api):
    """"every artist agreement whose status is `ACTIVE`, `AMENDMENT_PENDING` or
    `POST_TERM` on any release of this deal has its `active_royalty_rate_pct`
    recomputed". A 340,000-cent pool clears the whole 100,000 advance, so the ACTIVE
    agreement moves to its escalated 0.1800 and the AMENDMENT_PENDING one - on a
    release that contributed no line at all - moves to 0.1900, with its parked
    0.1300 and its base 0.1100 untouched.

    Design: Corner/calculations/recouped_flip_reprices_active_and_pending_agreements_only
    """
    ctx = _deal_one_accept_from_recoupment(api)
    assert_field_money(ctx["submitted"], "net_receipts_cents", 340000)

    validate_success(
        api.accept_report(
            ctx["report_id"],
            f.accept_report_payload(deal_version(api, ctx["deal_id"])),
            ANALYST,
        ),
        200,
    )

    deal = read_deal(api, ctx["deal_id"])
    assert_fields_money(
        deal, advance_recouped_cents=100000, unrecouped_advance_cents=0
    )
    assert_field(deal, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)

    successor = read_agreement(api, ctx["new_agreement_id"])
    assert_pct_equals(
        successor["active_royalty_rate_pct"],
        f.pct4("0.1800"),
        field="active_royalty_rate_pct",
    )
    assert_pct_equals(
        successor["royalty_rate_pct"], f.pct4("0.1200"), field="royalty_rate_pct"
    )

    amending = read_agreement(api, ctx["amending_agreement_id"])
    assert_status(amending, AGREEMENT_STATUS_AMENDMENT_PENDING)
    assert_pct_equals(
        amending["active_royalty_rate_pct"],
        f.pct4("0.1900"),
        field="active_royalty_rate_pct",
    )
    assert_pct_equals(
        amending["proposed_royalty_rate_pct"],
        f.pct4("0.1300"),
        field="proposed_royalty_rate_pct",
    )
    assert_pct_equals(
        amending["royalty_rate_pct"], f.pct4("0.1100"), field="royalty_rate_pct"
    )


def test_a_superseded_agreement_is_left_out_of_the_re_rating(api):
    """"Only agreements whose status is `ACTIVE`, `AMENDMENT_PENDING` or `POST_TERM`
    participate", so the SUPERSEDED predecessor keeps the 0.1000 it was rated at and
    never reaches its own escalated 0.2000. Under the cross-collateralized arm the
    whole 100,000 lands on the release that earned, leaving its
    `unrecouped_advance_share_cents` at 0 while the quiet release still shows
    40,000.

    Design: Corner/calculations/recouped_flip_reprices_active_and_pending_agreements_only
    """
    ctx = _deal_one_accept_from_recoupment(api)
    predecessor_before = read_agreement(api, ctx["old_agreement_id"])
    assert_status(predecessor_before, AGREEMENT_STATUS_SUPERSEDED)
    assert_pct_equals(
        predecessor_before["active_royalty_rate_pct"],
        f.pct4("0.1000"),
        field="active_royalty_rate_pct",
    )

    validate_success(
        api.accept_report(
            ctx["report_id"],
            f.accept_report_payload(deal_version(api, ctx["deal_id"])),
            ANALYST,
        ),
        200,
    )

    predecessor_after = read_agreement(api, ctx["old_agreement_id"])
    assert_status(predecessor_after, AGREEMENT_STATUS_SUPERSEDED)
    assert_pct_equals(
        predecessor_after["active_royalty_rate_pct"],
        f.pct4("0.1000"),
        field="active_royalty_rate_pct",
    )

    assert_field_money(
        read_release(api, ctx["reported_release_id"]),
        "unrecouped_advance_share_cents",
        0,
    )
    assert_field_money(
        read_release(api, ctx["quiet_release_id"]),
        "unrecouped_advance_share_cents",
        40000,
    )


def _deal_with_one_accepted_report_and_two_advance_shares(api):
    """A cross-collateralized 100,000-cent advance deal whose two releases carry
    lopsided 20,000 and 80,000 advance shares, with one ACCEPTED report whose two
    lines net 170,000 and 3,400 - a 173,400-cent pool on which the two recoupment
    arms disagree."""
    ctx = given_released_catalog(
        api,
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 100000,
            "marketing_budget_cents": 0,
            "cross_collateralized": True,
        },
        releases=[
            {
                "title": "Loud Side",
                "planned_release_date": "2026-02-01",
                "advance_share_cents": 20000,
            },
            {
                "title": "Quiet Side",
                "planned_release_date": "2026-02-01",
                "advance_share_cents": 80000,
            },
        ],
        actual_release_date="2026-02-01",
    )
    mk_rate_card(
        api,
        dsp_code=DEFAULT_DSP_CODE,
        territory_code="US",
        tier=TIER_PREMIUM,
        rate_micros_per_stream=4000,
        effective_from="2026-01-01",
    )
    report = mk_report(
        api,
        ctx["deal_id"],
        ctx["partner_headers"],
        dsp_code=DEFAULT_DSP_CODE,
        period_start="2026-04-01",
        period_end="2026-06-30",
    )
    for release, streams in zip(ctx["releases"], (500000, 10000)):
        mk_line(
            api,
            report["id"],
            release["id"],
            ctx["partner_headers"],
            territory_code="US",
            tier=TIER_PREMIUM,
            stream_count=streams,
        )
    do_submit_report(api, report["id"], ctx["partner_headers"])
    do_accept_report(api, report["id"], deal_version(api, ctx["deal_id"]))
    ctx["loud_release_id"] = ctx["releases"][0]["id"]
    ctx["quiet_release_id"] = ctx["releases"][1]["id"]
    return ctx


def test_the_variant_parameter_forces_the_arm_and_omitting_it_follows_the_deal(api):
    """"omitting it evaluates the deal's own `cross_collateralized` setting, and
    supplying one forces that arm so that the two can be compared on identical
    stored data", each arm being "recomputed from a **zero baseline**". On a
    173,400-cent pool the siloed arm is capped release by release at 20,000 + 3,400
    = 23,400 and stays `UNRECOUPED` with 76,600 outstanding, while the
    cross-collateralized arm pools the lot and applies the whole 100,000; the
    parameter-less read reproduces the cross figures because the deal is
    cross-collateralized.

    Design: Corner/calculations/recoupment_summary_variant_parameter_selects_the_arm_read_only
    """
    ctx = _deal_with_one_accepted_report_and_two_advance_shares(api)

    siloed = validate_success(
        api.get_recoupment_summary(ctx["deal_id"], ANALYST, variant=VARIANT_SILOED), 200
    )
    assert_field(siloed, "variant", VARIANT_SILOED)
    assert_fields_money(
        siloed,
        pool_net_receipts_cents=173400,
        advance_amount_cents=100000,
        advance_applied_cents=23400,
        unrecouped_advance_cents=76600,
        post_recoupment_net_receipts_cents=150000,
    )
    assert_field(siloed, "recoupment_status", RECOUPMENT_STATUS_UNRECOUPED)
    assert len(siloed["release_breakdown"]) == 2, (
        "expected one attribution entry per release, got %r"
        % (siloed["release_breakdown"],)
    )

    crossed = validate_success(
        api.get_recoupment_summary(
            ctx["deal_id"], ANALYST, variant=VARIANT_CROSS_COLLATERALIZED
        ),
        200,
    )
    assert_field(crossed, "variant", VARIANT_CROSS_COLLATERALIZED)
    assert_fields_money(
        crossed,
        pool_net_receipts_cents=173400,
        advance_amount_cents=100000,
        advance_applied_cents=100000,
        unrecouped_advance_cents=0,
        post_recoupment_net_receipts_cents=73400,
    )
    assert_field(crossed, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)

    defaulted = validate_success(
        api.get_recoupment_summary(ctx["deal_id"], ANALYST), 200
    )
    assert_field(defaulted, "variant", VARIANT_CROSS_COLLATERALIZED)
    assert_fields_money(
        defaulted, advance_applied_cents=100000, unrecouped_advance_cents=0
    )
    assert_field(defaulted, "recoupment_status", RECOUPMENT_STATUS_RECOUPED)


def test_projecting_both_arms_persists_nothing_on_the_deal_or_its_releases(api):
    """"Nothing is persisted by this read", and "the persisted
    `advance_recouped_cents` and `release_advance_recouped_cents` balances are never
    read". The acceptance had already written the cross split 98,039 / 1,961 onto the
    two releases; projecting the siloed arm, the cross arm and the deal's own arm in
    turn leaves those balances and the deal's `version` exactly where they were.

    Design: Corner/calculations/recoupment_summary_variant_parameter_selects_the_arm_read_only
    """
    ctx = _deal_with_one_accepted_report_and_two_advance_shares(api)
    deal_before = read_deal(api, ctx["deal_id"])
    assert_fields_money(
        deal_before, advance_recouped_cents=100000, unrecouped_advance_cents=0
    )
    assert_field_money(
        read_deal(api, ctx["deal_id"]), "net_receipts_to_date_cents", 173400
    )
    assert_field_money(
        read_release(api, ctx["loud_release_id"]), "release_advance_recouped_cents", 98039
    )
    assert_field_money(
        read_release(api, ctx["quiet_release_id"]), "release_advance_recouped_cents", 1961
    )

    validate_success(
        api.get_recoupment_summary(ctx["deal_id"], ANALYST, variant=VARIANT_SILOED), 200
    )
    validate_success(
        api.get_recoupment_summary(
            ctx["deal_id"], ANALYST, variant=VARIANT_CROSS_COLLATERALIZED
        ),
        200,
    )
    validate_success(api.get_recoupment_summary(ctx["deal_id"], ANALYST), 200)

    deal_after = read_deal(api, ctx["deal_id"])
    assert_version_is(deal_after, deal_before["version"], entity="deal")
    assert_fields_money(
        deal_after, advance_recouped_cents=100000, unrecouped_advance_cents=0
    )
    assert_field_money(
        read_release(api, ctx["loud_release_id"]), "release_advance_recouped_cents", 98039
    )
    assert_field_money(
        read_release(api, ctx["quiet_release_id"]), "release_advance_recouped_cents", 1961
    )


def _two_finalized_statements_awaiting_audit(api):
    """One SHIPPED CD run worth 600,000 in physical net receipts behind two FINAL
    statements on the same release: a 0.5000 agreement carrying a 150,000 advance and
    a 50,000 recoupable recording balance, which nets 55,000 payable, and a 0.2500
    agreement with empty ledgers, which nets 127,500. Both are prepared by the
    analyst, issued by business affairs, finalized once the objection window has
    elapsed, and then put under an in-scope audit."""
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        deal_kw={
            "distribution_fee_pct": f.pct4("0.1500"),
            "advance_amount_cents": 0,
            "marketing_budget_cents": 0,
        },
        releases=[
            {
                "title": "Materiality",
                "planned_release_date": "2026-02-01",
                "formats": (FORMAT_CD,),
                "advance_share_cents": 0,
            }
        ],
        actual_release_date="2026-02-01",
    )
    run = mk_run(
        api,
        ctx["release_id"],
        ctx["dist_id"],
        units_planned=1200,
        unit_manufacturing_cost_cents=250,
        window_start="2026-04-01",
        window_end="2026-06-30",
        returns_reserve_pct=f.pct4("0.1000"),
    )
    do_manufacture(api, run["id"], 1200)
    do_ship(api, run["id"], 1000, 900, ctx["partner_headers"])

    for key, rate, advance, recording in (
        ("heavy", "0.5000", 150000, 100000),
        ("light", "0.2500", 0, 0),
    ):
        agreement = mk_agreement(
            api,
            ctx["artist_id"],
            ctx["release_id"],
            royalty_rate_pct=f.pct4(rate),
            escalated_royalty_rate_pct=f.pct4(rate),
            advance_amount_cents=advance,
            recording_costs_cents=recording,
            recording_recoupable_pct=f.pct4("0.5000"),
            marketing_recoup_share_pct=f.pct4("0.5000"),
        )
        do_activate_agreement(api, agreement["id"])
        statement = mk_statement(
            api,
            agreement["id"],
            period_start="2026-04-01",
            period_end="2026-06-30",
            basis_variant=BASIS_VARIANT_FINAL,
        )
        do_prepare_statement(api, statement["id"])
        do_issue_statement(api, statement["id"])
        ctx[key + "_agreement_id"] = agreement["id"]
        ctx[key + "_statement_id"] = statement["id"]

    do_set_clock(api, FINALIZE_CLOCK_INSTANT)
    for key in ("heavy", "light"):
        ctx[key + "_finalized"] = do_finalize_statement(api, ctx[key + "_statement_id"])
        # Requesting the audit is itself a mutation of the statement, so it bumps
        # the version past the finalize snapshot; keep the post-request state for
        # any caller that needs the live version counter.
        ctx[key + "_audit_requested"] = do_request_audit(
            api,
            ctx[key + "_statement_id"],
            ctx["artist_headers"],
            "2026-04-01",
            "2026-06-30",
        )
    return ctx


def test_a_finding_one_cent_under_five_percent_is_immaterial_and_costs_the_artist(api):
    """`audit_cost_bearer` "is `LABEL` when the absolute value of the finding is at
    least five percent of `net_payable_cents` ... and `ARTIST` otherwise", and "An
    immaterial finding leaves the accounting axis untouched at `FINALIZED`". Against
    a 55,000-cent net payable the threshold is 2,750, so a 2,749-cent finding falls
    one cent short: the audit axis completes, the artist pays, the statement stays
    `FINALIZED` and the finalize debits that emptied the 150,000 advance and the
    50,000 recording balance are not reversed.

    Design: Corner/calculations/audit_materiality_threshold_at_exactly_five_percent
    """
    ctx = _two_finalized_statements_awaiting_audit(api)
    assert_field_money(ctx["heavy_finalized"], "net_payable_cents", 55000)
    assert_fields_money(
        read_agreement(api, ctx["heavy_agreement_id"]),
        unrecouped_artist_advance_cents=0,
        unrecouped_recording_cents=0,
    )

    concluded = validate_success(
        api.conclude_audit(
            ctx["heavy_statement_id"], f.conclude_audit_payload(2749), BIZ_AFFAIRS
        ),
        200,
    )
    assert_status(concluded, AUDIT_STATUS_COMPLETED, field="audit_status")
    assert_status(concluded, STATEMENT_STATUS_FINALIZED)
    assert_field(concluded, "audit_cost_bearer", AUDIT_COST_BEARER_ARTIST)
    assert_field_money(concluded, "audit_findings_adjustment_cents", 2749)
    assert_field_money(concluded, "net_payable_cents", 55000)
    assert_field(concluded, "revision_count", 0)

    assert_fields_money(
        read_agreement(api, ctx["heavy_agreement_id"]),
        unrecouped_artist_advance_cents=0,
        unrecouped_recording_cents=0,
    )


def test_a_finding_exactly_on_the_five_percent_threshold_reopens_the_statement(api):
    """The threshold is inclusive - "at least five percent of `net_payable_cents` —
    that threshold being the statement's `net_payable_cents` multiplied by 0.05 and
    rounded half up" - and "A material finding also moves the **accounting** axis
    `FINALIZED → REVISED`", clearing `issued_at`, `objection_deadline` and
    `finalized_at`. On a 127,500-cent net payable the threshold is exactly 6,375, so a
    6,375-cent finding is material: the label bears the cost, the statement reopens,
    and `revision_count` is untouched because it "is incremented on the `REVISED`
    entry only" at the next preparation.

    Design: Corner/calculations/audit_materiality_threshold_at_exactly_five_percent
    """
    ctx = _two_finalized_statements_awaiting_audit(api)
    finalized = ctx["light_finalized"]
    assert_fields_money(
        finalized,
        gross_royalty_cents=150000,
        reserve_withheld_cents=22500,
        net_payable_cents=127500,
    )

    concluded = validate_success(
        api.conclude_audit(
            ctx["light_statement_id"], f.conclude_audit_payload(6375), BIZ_AFFAIRS
        ),
        200,
    )
    assert_status(concluded, AUDIT_STATUS_COMPLETED, field="audit_status")
    assert_status(concluded, STATEMENT_STATUS_REVISED)
    assert_field(concluded, "audit_cost_bearer", AUDIT_COST_BEARER_LABEL)
    assert_field_money(concluded, "audit_findings_adjustment_cents", 6375)
    assert_null(concluded, "issued_at", "objection_deadline", "finalized_at")
    assert_field(concluded, "revision_count", 0)
    # PRD 3.9: on the material edge "both the statement's and the agreement's
    # version increase by 1" - counted from the state the audit request left.
    assert_version_is(
        concluded, ctx["light_audit_requested"]["version"] + 1, entity="statement"
    )
