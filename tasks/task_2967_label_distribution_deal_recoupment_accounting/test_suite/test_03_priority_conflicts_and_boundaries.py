"""
The twelve-rank rejection ladder and the pinned arithmetic boundaries
(PRD Sections 2.6, 2.8, 3.4, 3.5, 3.7, 3.8, 3.9).

Every test here translates one instance of the difficulty index rules
`priority_pair_validation_conflict` and `boundary_precision_check`. Each
priority instance is exercised twice: once with both rules violated in a single
request, asserting the higher-ranked identifier, and once with only the higher
violation relaxed, proving the lower-ranked rule really was live but masked.
Each boundary instance asserts the value exactly at the threshold and the
nearest value on the other side of it.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import (
    BASIS_VARIANT_PROVISIONAL,
    BIZ_AFFAIRS,
    ERR_DISPUTED_AMOUNT_EXCEEDS_NET,
    ERR_INVALID_SPEND_STATE,
    ERR_INVENTORY_OBLIGATION_BREACH,
    ERR_MARKETING_BUDGET_EXCEEDED,
    ERR_OBJECTION_WINDOW_CLOSED,
    ERR_PROVISIONAL_NOT_ISSUABLE,
    ERR_SEGREGATION_OF_DUTIES,
    FORMAT_VINYL,
    LABEL_ADMIN,
    OBJECTION_REASON_COST_DISPUTE,
    RESERVE_STATUS_HELD,
    RUN_STATUS_MANUFACTURED,
    RUN_STATUS_SHIPPED,
    SPEND_DECISION_APPROVE,
    SPEND_STATUS_DRAFT,
    SPEND_STATUS_SUBMITTED,
    STATEMENT_STATUS_ISSUED,
    STATEMENT_STATUS_PREPARED,
    TIER_PREMIUM,
    USER_ANALYST,
    assert_field_money,
    assert_fields_money,
    assert_instant_equals,
    assert_null,
    assert_pct_equals,
    assert_reserve_conserved,
    assert_status,
    do_manufacture,
    do_set_clock,
    do_submit_spend,
    find_by_id,
    given_accepted_report,
    given_active_agreement,
    given_issued_statement,
    given_prepared_statement,
    given_rate_cards,
    given_released_catalog,
    given_shipped_run,
    make_biz_affairs_headers,
    mk_line,
    mk_report,
    mk_run,
    mk_spend,
    read_deal,
    read_report_lines,
    read_run,
    read_spend,
    read_statement,
)


def test_deciding_a_draft_spend_reports_the_spend_state_over_the_budget_ceiling(api):
    """The spend is still DRAFT and its 900,000 cents would blow the deal's
    500,000-cent budget, so two rules are violated at once. Rank 8 state gates
    name "ERR_INVALID_SPEND_STATE" and rank 12 fiscal ceilings come "Last of all,
    the money limits", and "no later rule is evaluated, and no later rule's
    identifier can appear" - so the 409 answers and the budget is never consulted.

    Design: Difficulty/priority_pair_validation_conflict/spend_decide_state_beats_marketing_budget
    """
    ctx = given_released_catalog(api, deal_kw={"marketing_budget_cents": 500000})
    spend = mk_spend(api, ctx["release_id"], amount_cents=900000)

    response = api.decide_spend(
        spend["id"], f.decide_spend_payload(SPEND_DECISION_APPROVE), BIZ_AFFAIRS
    )
    validate_error(response, ERR_INVALID_SPEND_STATE)

    unchanged = read_spend(api, spend["id"])
    assert_status(unchanged, SPEND_STATUS_DRAFT)
    assert_null(unchanged, "approved_at", "decided_by_user_id")
    assert_field_money(read_deal(api, ctx["deal_id"]), "marketing_committed_cents", 0)


def test_approving_a_submitted_spend_over_budget_reports_the_fiscal_ceiling(api):
    """With the rank-8 violation relaxed - the spend is now SUBMITTED, a
    declared source state - the rank-12 rule that was masked surfaces: "the
    deal's already-committed marketing plus this spend's amount_cents must not
    exceed the deal's marketing_budget_cents, otherwise
    ERR_MARKETING_BUDGET_EXCEEDED (422)". 0 committed plus 900,000 exceeds 500,000.

    Design: Difficulty/priority_pair_validation_conflict/spend_decide_state_beats_marketing_budget
    """
    ctx = given_released_catalog(api, deal_kw={"marketing_budget_cents": 500000})
    spend = mk_spend(api, ctx["release_id"], amount_cents=900000)
    do_submit_spend(api, spend["id"], headers=LABEL_ADMIN)

    response = api.decide_spend(
        spend["id"], f.decide_spend_payload(SPEND_DECISION_APPROVE), BIZ_AFFAIRS
    )
    validate_error(response, ERR_MARKETING_BUDGET_EXCEEDED)

    unchanged = read_spend(api, spend["id"])
    assert_status(unchanged, SPEND_STATUS_SUBMITTED)
    assert_null(unchanged, "approved_at")
    assert_field_money(read_deal(api, ctx["deal_id"]), "marketing_committed_cents", 0)


def test_the_preparer_issuing_a_provisional_statement_reports_segregation_first(api):
    """A PROVISIONAL statement can never be published, and here the issuer's
    X-User-ID also equals prepared_by_user_id. Segregation of duties sits at rank
    9 and ERR_PROVISIONAL_NOT_ISSUABLE among the rank-11 "Referential and
    uniqueness rules", so the 403 wins: "the acting X-User-ID must not equal the
    statement's prepared_by_user_id, otherwise ERR_SEGREGATION_OF_DUTIES (403)".

    Design: Difficulty/priority_pair_validation_conflict/statement_issue_segregation_beats_provisional_constraint
    """
    ctx = given_released_catalog(api)
    ctx = given_active_agreement(api, ctx)
    ctx = given_prepared_statement(
        api, ctx, statement_kw={"basis_variant": BASIS_VARIANT_PROVISIONAL}
    )

    response = api.issue_statement(
        ctx["statement_id"], make_biz_affairs_headers(USER_ANALYST)
    )
    validate_error(response, ERR_SEGREGATION_OF_DUTIES)

    unchanged = read_statement(api, ctx["statement_id"])
    assert_status(unchanged, STATEMENT_STATUS_PREPARED)
    assert_null(unchanged, "issued_at", "issued_by_user_id", "objection_deadline")


def test_a_provisional_statement_issued_by_a_second_operator_reports_the_variant_bar(api):
    """Relaxing only the rank-9 violation - biz-affairs-01 never prepared this
    statement - lets the masked rank-11 rule answer: "only a FINAL statement may
    be published at all; issuing a PROVISIONAL statement is refused with
    ERR_PROVISIONAL_NOT_ISSUABLE (422)". The statement stays PREPARED either way.

    Design: Difficulty/priority_pair_validation_conflict/statement_issue_segregation_beats_provisional_constraint
    """
    ctx = given_released_catalog(api)
    ctx = given_active_agreement(api, ctx)
    ctx = given_prepared_statement(
        api, ctx, statement_kw={"basis_variant": BASIS_VARIANT_PROVISIONAL}
    )

    response = api.issue_statement(ctx["statement_id"], BIZ_AFFAIRS)
    validate_error(response, ERR_PROVISIONAL_NOT_ISSUABLE)

    unchanged = read_statement(api, ctx["statement_id"])
    assert_status(unchanged, STATEMENT_STATUS_PREPARED)
    assert_null(unchanged, "issued_at", "issued_by_user_id", "objection_deadline")


def test_objecting_after_the_deadline_reports_the_window_over_the_disputed_ceiling(api):
    """The clock stands at 2026-09-01, past the 2026-07-31 deadline stamped by a
    2026-07-01 issue plus 30 days, and the claimed 99,999 cents also exceeds the
    15,300-cent ceiling (net_payable 15300 + marketing 0 + reserve 0). Rank 10
    temporal windows precede rank 12 fiscal ceilings, so "one filed strictly
    after it is refused with ERR_OBJECTION_WINDOW_CLOSED (422)" answers.

    Design: Difficulty/priority_pair_validation_conflict/objection_window_closed_beats_disputed_amount_ceiling
    """
    ctx = given_released_catalog(
        api,
        clock="2026-07-01T00:00:00.000Z",
        deal_kw={"objection_window_days": 30, "marketing_budget_cents": 500000},
    )
    ctx = given_active_agreement(api, ctx)
    ctx = given_accepted_report(api, ctx, lines=[{"stream_count": 250000}])
    ctx = given_issued_statement(api, ctx)
    issued = read_statement(api, ctx["statement_id"])
    assert_fields_money(
        issued,
        net_payable_cents=15300,
        marketing_applied_cents=0,
        reserve_withheld_cents=0,
    )
    assert_instant_equals(
        issued["objection_deadline"], "2026-07-31T00:00:00.000Z", "objection_deadline"
    )

    do_set_clock(api, "2026-09-01T00:00:00.000Z")
    response = api.object_statement(
        ctx["statement_id"],
        f.object_payload(
            OBJECTION_REASON_COST_DISPUTE, 99999, "Recording costs double-charged"
        ),
        ctx["artist_headers"],
    )
    validate_error(response, ERR_OBJECTION_WINDOW_CLOSED)

    unchanged = read_statement(api, ctx["statement_id"])
    assert_status(unchanged, STATEMENT_STATUS_ISSUED)
    assert_null(unchanged, "objection_reason_code", "objection_filed_at")
    assert_instant_equals(
        unchanged["objection_deadline"],
        "2026-07-31T00:00:00.000Z",
        "objection_deadline",
    )


def test_objecting_inside_the_window_reports_the_disputed_amount_ceiling(api):
    """The identical 99,999-cent claim filed while the clock still reads
    2026-07-01, inside the window, surfaces the rank-12 rule the closed window
    had masked: the disputed amount "may not exceed net_payable_cents plus
    marketing_applied_cents plus reserve_withheld_cents", which is
    15300 + 0 + 0 = 15300, so ERR_DISPUTED_AMOUNT_EXCEEDS_NET answers instead.

    Design: Difficulty/priority_pair_validation_conflict/objection_window_closed_beats_disputed_amount_ceiling
    """
    ctx = given_released_catalog(
        api,
        clock="2026-07-01T00:00:00.000Z",
        deal_kw={"objection_window_days": 30, "marketing_budget_cents": 500000},
    )
    ctx = given_active_agreement(api, ctx)
    ctx = given_accepted_report(api, ctx, lines=[{"stream_count": 250000}])
    ctx = given_issued_statement(api, ctx)
    assert_field_money(
        read_statement(api, ctx["statement_id"]), "net_payable_cents", 15300
    )

    response = api.object_statement(
        ctx["statement_id"],
        f.object_payload(
            OBJECTION_REASON_COST_DISPUTE, 99999, "Recording costs double-charged"
        ),
        ctx["artist_headers"],
    )
    validate_error(response, ERR_DISPUTED_AMOUNT_EXCEEDS_NET)

    unchanged = read_statement(api, ctx["statement_id"])
    assert_status(unchanged, STATEMENT_STATUS_ISSUED)
    assert_null(unchanged, "objection_reason_code", "objection_filed_at")


def test_returns_of_exactly_a_quarter_escalate_to_the_second_reserve_tier(api):
    """250 returns of 1,000 shipped is a returns_rate of exactly 0.2500, and the
    tiers are "both tested with "at least", not "more than": a returns_rate of
    0.2500 or above lifts the baseline by 0.1500". The 0.2000 baseline therefore
    becomes 0.3500 and the 900,000-cent shipped value reserves 315,000 cents,
    leaving physical net receipts of 750 * 900 - 300,000 = 375,000.

    Design: Difficulty/boundary_precision_check/returns_rate_exactly_at_tier_2_threshold
    """
    ctx = given_released_catalog(api, releases=[{"formats": (FORMAT_VINYL,)}])
    ctx = given_shipped_run(
        api, ctx, run_kw={"returns_reserve_pct": f.pct4("0.2000")}
    )
    at_ship = ctx["run"]
    assert_pct_equals(at_ship["returns_rate"], "0.0000", "returns_rate")
    assert_pct_equals(at_ship["effective_reserve_pct"], "0.2000", "effective_reserve_pct")
    assert_field_money(at_ship, "reserve_initial_cents", 180000)

    response = api.record_returns(
        ctx["run_id"], f.record_returns_payload(250), ctx["partner_headers"]
    )
    run = validate_success(response, 200)

    assert_pct_equals(run["returns_rate"], "0.2500", "returns_rate")
    assert_pct_equals(run["effective_reserve_pct"], "0.3500", "effective_reserve_pct")
    assert_fields_money(
        run,
        reserve_initial_cents=315000,
        reserve_held_cents=315000,
        reserve_liquidated_cents=0,
        physical_net_receipts_cents=375000,
    )
    assert_reserve_conserved(run)
    assert_status(run, RUN_STATUS_SHIPPED)
    assert_status(run, RESERVE_STATUS_HELD, "reserve_status")


def test_one_unit_below_the_quarter_threshold_stays_on_the_first_reserve_tier(api):
    """249 returns of 1,000 is 0.2490 - the nearest value below the 0.2500 tier
    boundary - so the "at least" test falls through to the lower tier: "otherwise
    a returns_rate of 0.1000 or above lifts it by 0.0500". The reserve is
    0.2000 + 0.0500 = 0.2500 of 900,000 = 225,000 cents, 90,000 less than the
    tier-2 arm, and physical net receipts are 751 * 900 - 300,000 = 375,900.

    Design: Difficulty/boundary_precision_check/returns_rate_exactly_at_tier_2_threshold
    """
    ctx = given_released_catalog(api, releases=[{"formats": (FORMAT_VINYL,)}])
    ctx = given_shipped_run(
        api, ctx, run_kw={"returns_reserve_pct": f.pct4("0.2000")}
    )

    response = api.record_returns(
        ctx["run_id"], f.record_returns_payload(249), ctx["partner_headers"]
    )
    run = validate_success(response, 200)

    assert_pct_equals(run["returns_rate"], "0.2490", "returns_rate")
    assert_pct_equals(run["effective_reserve_pct"], "0.2500", "effective_reserve_pct")
    assert_fields_money(
        run,
        reserve_initial_cents=225000,
        reserve_held_cents=225000,
        reserve_liquidated_cents=0,
        physical_net_receipts_cents=375900,
    )
    assert_reserve_conserved(run)
    assert_status(run, RUN_STATUS_SHIPPED)
    assert_status(run, RESERVE_STATUS_HELD, "reserve_status")


def test_a_line_worth_exactly_half_a_cent_rounds_up_and_the_gross_sums_rounded_lines(api):
    """5 streams at 1,000 micros is exactly 0.5 cents and 15 streams exactly 1.5
    cents; each is "rounded half up to a whole number of cents" per line, giving
    1 and 2, and "rounding is applied once per line and never to the sum", so
    gross_receipts_cents is 3 and not the 2 a rounded sum would report. The
    distributor's 0.1500 share of 3 cents is round_half_up(0.45) = 0, so net is 3.

    Design: Difficulty/boundary_precision_check/line_rounding_half_up_at_exact_half_cent
    """
    ctx = given_released_catalog(api, deal_kw={"territory_codes": ("US", "GB")})
    ctx = given_rate_cards(
        api,
        ctx,
        cards=[
            {"territory_code": "US", "rate_micros_per_stream": 1000},
            {"territory_code": "GB", "rate_micros_per_stream": 1000},
        ],
    )
    report = mk_report(api, ctx["deal_id"], ctx["partner_headers"])
    us_line = mk_line(
        api,
        report["id"],
        ctx["release_id"],
        ctx["partner_headers"],
        territory_code="US",
        tier=TIER_PREMIUM,
        stream_count=5,
    )
    gb_line = mk_line(
        api,
        report["id"],
        ctx["release_id"],
        ctx["partner_headers"],
        territory_code="GB",
        tier=TIER_PREMIUM,
        stream_count=15,
    )

    response = api.submit_report(report["id"], ctx["partner_headers"])
    priced = validate_success(response, 200)

    assert_fields_money(
        priced,
        gross_receipts_cents=3,
        distributor_share_cents=0,
        net_receipts_cents=3,
    )
    lines = read_report_lines(api, report["id"])
    half_cent = find_by_id(lines, us_line["id"])
    assert half_cent["applied_rate_micros_per_stream"] == 1000
    assert_field_money(half_cent, "resolved_revenue_cents", 1)
    assert_field_money(find_by_id(lines, gb_line["id"]), "resolved_revenue_cents", 2)


def test_a_line_just_below_half_a_cent_rounds_down_to_zero(api):
    """The nearest value on the other side of the same boundary: 4 streams at
    1,000 micros is 0.4 cents, and "a raw value of 400000.4 becomes 400000", so
    the line resolves to 0 while the 5-stream line at exactly 0.5 cents still
    resolves to 1. The report's gross is therefore 1 cent, not 2.

    Design: Difficulty/boundary_precision_check/line_rounding_half_up_at_exact_half_cent
    """
    ctx = given_released_catalog(api, deal_kw={"territory_codes": ("US", "GB")})
    ctx = given_rate_cards(
        api,
        ctx,
        cards=[
            {"territory_code": "US", "rate_micros_per_stream": 1000},
            {"territory_code": "GB", "rate_micros_per_stream": 1000},
        ],
    )
    report = mk_report(api, ctx["deal_id"], ctx["partner_headers"])
    at_half = mk_line(
        api,
        report["id"],
        ctx["release_id"],
        ctx["partner_headers"],
        territory_code="US",
        tier=TIER_PREMIUM,
        stream_count=5,
    )
    below_half = mk_line(
        api,
        report["id"],
        ctx["release_id"],
        ctx["partner_headers"],
        territory_code="GB",
        tier=TIER_PREMIUM,
        stream_count=4,
    )

    response = api.submit_report(report["id"], ctx["partner_headers"])
    priced = validate_success(response, 200)

    assert_field_money(priced, "gross_receipts_cents", 1)
    lines = read_report_lines(api, report["id"])
    assert_field_money(find_by_id(lines, at_half["id"]), "resolved_revenue_cents", 1)
    assert_field_money(find_by_id(lines, below_half["id"]), "resolved_revenue_cents", 0)


def test_shipping_one_thousand_of_a_ten_fifty_pressing_sits_exactly_on_the_obligation(api):
    """The retained stock "must be at least five percent of units_shipped rounded
    up to a whole unit, so shipping 1,000 units out of a 1,040-unit pressing
    breaches the obligation (40 retained against a 50-unit floor) while 1,050
    satisfies it exactly": 1050 - 1000 = 50 retained against ceil(1000 * 0.05) =
    50. Cost is 1050 * 250 = 262,500, the 0.1000 partner default reserves 90,000
    of the 900,000 shipped, and net receipts are 900,000 - 262,500 = 637,500.

    Design: Difficulty/boundary_precision_check/inventory_obligation_at_exact_ceiling
    """
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        releases=[{"formats": (FORMAT_VINYL,)}],
    )
    run = mk_run(api, ctx["release_id"], ctx["dist_id"], units_planned=1050)
    do_manufacture(api, run["id"], 1050)

    response = api.ship_run(
        run["id"], f.ship_payload(1000, 900), ctx["partner_headers"]
    )
    shipped = validate_success(response, 200)

    assert_status(shipped, RUN_STATUS_SHIPPED)
    assert shipped["units_shipped"] == 1000
    assert_pct_equals(
        shipped["effective_reserve_pct"], "0.1000", "effective_reserve_pct"
    )
    assert_fields_money(
        shipped,
        manufacturing_cost_cents=262500,
        reserve_initial_cents=90000,
        reserve_held_cents=90000,
        physical_net_receipts_cents=637500,
    )
    assert_reserve_conserved(shipped)
    assert_status(shipped, RESERVE_STATUS_HELD, "reserve_status")


def test_shipping_one_unit_more_breaches_the_inventory_obligation(api):
    """One unit past the boundary the floor jumps a whole unit: 1,001 shipped
    needs ceil(1001 * 0.05) = ceil(50.05) = 51 retained but leaves only 49, and
    "a breach is refused with ERR_INVENTORY_OBLIGATION_BREACH (422)". This is the
    rank-12 fiscal rule, not the shape rule - 1,001 does not exceed the 1,050
    manufactured, so ERR_INVALID_REQUEST must not be the answer - and the run is
    left MANUFACTURED.

    Design: Difficulty/boundary_precision_check/inventory_obligation_at_exact_ceiling
    """
    ctx = given_released_catalog(
        api,
        distributor_kw={"default_returns_reserve_pct": f.pct4("0.1000")},
        releases=[{"formats": (FORMAT_VINYL,)}],
    )
    run = mk_run(api, ctx["release_id"], ctx["dist_id"], units_planned=1050)
    do_manufacture(api, run["id"], 1050)

    response = api.ship_run(
        run["id"], f.ship_payload(1001, 900), ctx["partner_headers"]
    )
    validate_error(response, ERR_INVENTORY_OBLIGATION_BREACH)

    unchanged = read_run(api, run["id"])
    assert_status(unchanged, RUN_STATUS_MANUFACTURED)
    assert_field_money(
        read_deal(api, ctx["deal_id"]), "net_receipts_to_date_cents", 0
    )
