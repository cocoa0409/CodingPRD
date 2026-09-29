"""Calculation corners: pinned rounding scales, degenerate inputs and input sets.

Seven instances of the CORNER design index, section ``calculations``, are
translated here. Each one attacks a different way an arithmetic rule of PRD.md
can be got wrong without any state machine noticing:

* ``tranche_reoffering_price_rounds_each_variant_to_three_decimals`` -- both
  price variants are rounded half up to three places *independently* and the
  rounded figures are what the yield-to-worst comparison sees.
* ``closing_an_empty_order_book_allots_nothing`` -- the degenerate waterfall
  input: zero candidates must still count as a run.
* ``takedown_credit_counts_only_allotted_orders_per_member`` -- the per-member
  aggregation spans ``ALLOTTED`` and ``PARTIALLY_ALLOTTED`` orders only, so an
  ``UNFILLED`` order contributes 0.00 rather than its requested par.
* ``arbitrage_yield_uses_only_the_deals_own_tranches`` -- the bond-year weighting
  is scoped to one deal, not to the issuer.
* ``permitted_investment_yield_adds_the_one_eighth_allowance`` -- the 0.125
  allowance, the 360-day basis and the two-place rounding of the excess.
* ``disclosure_risk_score_sums_weights_and_clamps_at_one_hundred`` -- every term
  of the weighted sum, and the clamp that turns a raw 140 into 100.
* ``committing_an_enhancement_propagates_the_premium_down_and_up`` -- one commit
  propagates to the listed maturity and to the deal, and stops there.

Scenarios that the shared conftest fixtures do not carry -- a three-maturity
schedule, a single-tranche 5,000,000 issue split 60/40 between two managers --
are built from ``test_helpers.fixtures`` step helpers.
"""

from decimal import Decimal

from prd_bench_local_runner.testing import get_success_data, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    MONEY,
    assert_decimal_places,
    assert_is_number,
    assert_money,
    assert_money_identity,
    assert_par_identity,
    assert_price,
    assert_yield_value,
    expected_arbitrage_yield,
    expected_excess_earnings,
    expected_gross_spread_per_bond,
    expected_insured_debt_service,
    expected_issue_price_total,
    expected_liability_par,
    expected_negotiated_gross_spread,
    expected_net_proceeds,
    expected_permitted_investment_yield,
    expected_premium,
    expected_price_pct,
    expected_risk_score,
    expected_takedown_credit,
    round_half_up,
    to_decimal,
)
from test_helpers.constants import (
    ARBITRAGE_DAY_BASIS,
    CANONICAL_ARBITRAGE_YIELD_PCT,
    CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    DATED_DATE,
    ENHANCEMENT_PREMIUM_BPS,
    ENHANCEMENT_PREMIUM_USD,
    ENTITY_TYPE_SURCHARGE,
    INSURED_DEBT_SERVICE_TRANCHE_1_USD,
    LATE_ANNUAL_FILING_POINTS,
    LATE_EVENT_NOTICE_POINTS,
    MATERIAL_EVENT_POINTS,
    MONEY_DECIMALS,
    NEGOTIATED_COMPONENT_TOTAL_PER_BOND_USD,
    NEGOTIATED_GROSS_SPREAD_PER_BOND_USD,
    NEGOTIATED_TAKEDOWN_PER_BOND_USD,
    PRICE_DECIMALS,
    RISK_SCORE_MAX,
    TRANCHE_1_COUPON_PCT,
    TRANCHE_1_MATURITY_DATE,
    TRANCHE_1_PERIODS,
    TRANCHE_1_PRICE_TO_MATURITY_PCT,
    TRANCHE_1_REOFFERING_PRICE_PCT,
    TRANCHE_1_YIELD_PCT,
    TRANCHE_2_CALL_PERIODS,
    TRANCHE_2_COUPON_PCT,
    TRANCHE_2_FIRST_CALL_DATE,
    TRANCHE_2_PERIODS,
    TRANCHE_2_PRICE_TO_CALL_PCT,
    TRANCHE_2_PRICE_TO_MATURITY_PCT,
    TRANCHE_2_YIELD_PCT,
    WATERFALL_O1_ALLOTTED_USD,
    WATERFALL_O1_REQUESTED_USD,
    WATERFALL_O2_ALLOTTED_USD,
    WATERFALL_O2_REQUESTED_USD,
    WATERFALL_O3_ALLOTTED_USD,
    WATERFALL_O3_REQUESTED_USD,
    WATERFALL_O4_ALLOTTED_USD,
    WATERFALL_O4_REQUESTED_USD,
    WATERFALL_MEMBER_A_TAKEDOWN_USD,
    WATERFALL_MEMBER_B_TAKEDOWN_USD,
    YIELD_DECIMALS,
    plus_semiannual,
)
from test_helpers.test_users import COMPLIANCE_HEADERS
from test_helpers.types import (
    DealStatus,
    EnhancementStatus,
    EntityType,
    MemberRole,
    OrderStatus,
    OrderPeriodStatus,
    RatingBasis,
    SaleMethod,
    TaxStatus,
)

# --- The third maturity of the rounding corner -------------------------------
# A premium call at 102.000 rather than at par: the same 5.000 coupon and 4.000
# yield taken to a twenty-period call, so only the redemption value differs from
# the canonical callable maturity. PRD section 3.2's actuarial price is then
# 109.522 to the call, three decimal places.
TRANCHE_3_CALL_PRICE_PCT = 102.000
TRANCHE_3_PERIODS = 60
TRANCHE_3_PRICE_TO_CALL_PCT = 109.522
THREE_TRANCHE_EXPECTED_PAR_USD = 15000000

# --- The single-maturity negotiated issue of the takedown corner -------------
# One 5,000,000 maturity reoffered at 106.058, split 60/40 between a senior
# manager and a co-manager, so PRD section 3.8's liability sum is exactly
# 100.0000 and the two members' liability par differs.
SENIOR_LIABILITY_PCT = 60.0000
CO_LIABILITY_PCT = 40.0000
SINGLE_TRANCHE_ISSUE_PRICE_TOTAL_USD = 5302900.00
SINGLE_TRANCHE_GROSS_SPREAD_TOTAL_USD = 43750.00
SINGLE_TRANCHE_NET_PROCEEDS_USD = 5259150.00
TAKEDOWN_CREDIT_TOTAL_USD = 25000.00

# --- The arbitrage corners ---------------------------------------------------
# A second, taxable deal of the same issuer whose single maturity yields the
# statutory maximum, so contaminating the input set is unmistakable.
FOREIGN_DEAL_PAR_USD = 5000000
FOREIGN_TRANCHE_COUPON_PCT = 12.000
FOREIGN_TRANCHE_YIELD_PCT = 12.000
FOREIGN_ARBITRAGE_YIELD_PCT = 12.0000
PROJECTED_INVESTMENT_YIELD_PCT = 4.600
UNSPENT_PROCEEDS_USD = 5000000
INVESTMENT_DAYS = 180
EXCESS_EARNINGS_USD = 9792.50
# PRD section 3.8 divides by three hundred sixty; a 365-day year is the classic
# wrong basis and lands here instead.
ALTERNATIVE_DAY_BASIS = 365
EXCESS_EARNINGS_ON_365_BASIS_USD = 9658.36

# --- The risk-score corners (PRD section 3.1) -------------------------------
STATE_CLEAN_SCORE = 0
CITY_CLEAN_SCORE = 5
AUTHORITY_THREE_NOTICES_SCORE = 39
CLAMPED_AUTHORITY_RAW_SCORE = 140


# ---------------------------------------------------------------------------
# Module-local helpers
# ---------------------------------------------------------------------------
def _raw_risk_score(
    entity_type,
    prior_late_annual_filings=0,
    prior_late_event_notices=0,
    has_prior_material_event=False,
):
    """PRD section 3.1's raw total *before* the clamp, so the clamp is observable.

    ``expected_risk_score`` already applies the clamp, which is exactly the step
    under test here, so the unclamped sum of the four contributions is computed
    from the same weight constants and used only as the figure the stored score
    must *not* carry.
    """
    return (
        prior_late_annual_filings * LATE_ANNUAL_FILING_POINTS
        + prior_late_event_notices * LATE_EVENT_NOTICE_POINTS
        + (MATERIAL_EVENT_POINTS if has_prior_material_event else 0)
        + ENTITY_TYPE_SURCHARGE[entity_type]
    )


def _excess_earnings_on_alternative_basis(
    unspent_proceeds_usd,
    projected_investment_yield_pct,
    permitted_investment_yield_pct,
    investment_days,
    day_basis,
):
    """PRD section 3.8's excess earnings on a day basis other than three hundred
    sixty, computed only so the rejected basis is observable in the assertion."""
    raw = (
        to_decimal(unspent_proceeds_usd)
        * (
            to_decimal(projected_investment_yield_pct)
            - to_decimal(permitted_investment_yield_pct)
        )
        / Decimal(100)
        * Decimal(int(investment_days))
        / Decimal(int(day_basis))
    )
    return round_half_up(raw, MONEY)


def _tranche_by_sequence(tranches, sequence_number):
    """Pick one maturity out of a schedule listed in ascending sequence order."""
    for tranche in tranches:
        if tranche["sequence_number"] == sequence_number:
            return tranche
    raise AssertionError(
        f"no maturity with sequence_number {sequence_number} in {tranches!r}"
    )


def _member_by_role(members, member_role):
    """Pick one syndicate seat out of a list ordered by ``priority_rank``."""
    for member in members:
        if member["member_role"] == member_role:
            return member
    raise AssertionError(f"no syndicate member with role {member_role} in {members!r}")


def _three_maturity_draft_deal(client):
    """A DRAFT deal carrying three maturities that pin every rounding path.

    Maturity one is the non-callable twenty-period premium bond, maturity two the
    forty-period bond callable at par after twenty, and maturity three the same
    coupon and yield callable at 102.000 after twenty. PRD section 3.2 requires
    ``maturity_date`` to increase strictly with ``sequence_number``, so maturity
    three matures sixty periods out; its ``periods_to_call`` is still twenty,
    which is what its ``price_to_call_pct`` is built from.
    """
    ctx = fx.draft_deal(
        client, tranches=False, expected_par_amount_usd=THREE_TRANCHE_EXPECTED_PAR_USD
    )
    ctx.tranche_1 = fx.add_tranche(
        client, ctx.deal_id, ctx.advisor_headers, f.canonical_tranche_1_payload()
    )
    ctx.tranche_2 = fx.add_tranche(
        client, ctx.deal_id, ctx.advisor_headers, f.canonical_tranche_2_payload()
    )
    ctx.tranche_3 = fx.add_tranche(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.tranche_payload(
            3,
            plus_semiannual(DATED_DATE, TRANCHE_3_PERIODS),
            coupon_rate_pct=TRANCHE_2_COUPON_PCT,
            yield_pct=TRANCHE_2_YIELD_PCT,
            is_callable=True,
            first_call_date=TRANCHE_2_FIRST_CALL_DATE,
            call_price_pct=TRANCHE_3_CALL_PRICE_PCT,
        ),
    )
    ctx.tranches = [ctx.tranche_1, ctx.tranche_2, ctx.tranche_3]
    ctx.tranche_ids = [t["id"] for t in ctx.tranches]
    return ctx


def _single_maturity_two_manager_deal(client):
    """A negotiated 5,000,000 issue of one maturity, seated 60/40, book allotted.

    The schedule is a single 5,000,000 maturity so the waterfall worked example of
    PRD section 3.7 runs against the whole issue, and the two seats carry
    different ``liability_pct`` so PRD section 3.8's ``liability_par_usd`` is
    distinguishable per member while still summing to exactly 100.0000.
    """
    ctx = fx.participants(client)
    deal = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )
    ctx.deal = deal
    ctx.deal_id = deal["id"]
    ctx.tranches = [
        fx.add_tranche(
            client, ctx.deal_id, ctx.advisor_headers, f.canonical_tranche_1_payload()
        )
    ]
    ctx.tranche_ids = [t["id"] for t in ctx.tranches]

    ctx.co_manager_firm = fx.register_underwriter_firm(client)
    ctx.co_manager_firm_id = ctx.co_manager_firm["id"]
    ctx.senior_member = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
        liability_pct=SENIOR_LIABILITY_PCT,
        takedown_share_pct=SENIOR_LIABILITY_PCT,
        priority_rank=1,
    )
    ctx.co_member = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.co_manager_firm_id,
        ctx.underwriter_headers,
        MemberRole.CO_MANAGER,
        liability_pct=CO_LIABILITY_PCT,
        takedown_share_pct=CO_LIABILITY_PCT,
        priority_rank=2,
    )
    ctx.members = [ctx.senior_member, ctx.co_member]
    ctx.member_ids = [m["id"] for m in ctx.members]

    ctx.deal = fx.submit_structure(client, ctx.deal_id, ctx.advisor_headers)
    ctx.deal = fx.designate_sale_method(
        client, ctx.deal_id, SaleMethod.NEGOTIATED, ctx.advisor_headers
    )
    fx.cleared_disclosure(ctx)
    fx.waterfall_book(ctx)
    return ctx


def _proposed_enhancement_on_the_first_maturity(client):
    """A STRUCTURING two-maturity deal with a PROPOSED 45 basis point policy on T1.

    Only maturity one appears in ``insured_tranche_ids``, so maturity two is the
    control that must stay uninsured through the commitment.
    """
    ctx = fx.structuring_deal(client)
    ctx.insured_tranche_id = ctx.tranche_ids[0]
    ctx.uninsured_tranche_id = ctx.tranche_ids[1]
    ctx.enhancement = fx.propose_enhancement(
        client,
        ctx.deal_id,
        [ctx.insured_tranche_id],
        ctx.advisor_headers,
        premium_bps=ENHANCEMENT_PREMIUM_BPS,
    )
    ctx.enhancement_id = ctx.enhancement["id"]
    return ctx


# ---------------------------------------------------------------------------
# Corner/calculations/tranche_reoffering_price_rounds_each_variant_to_three_decimals
# ---------------------------------------------------------------------------
def test_each_price_variant_is_rounded_to_three_decimals_independently(client):
    """PRD 3.2: "Each variant is rounded independently, and the rounded figures
    are what get compared."

    Design: Corner/calculations/tranche_reoffering_price_rounds_each_variant_to_three_decimals
    """
    ctx = _three_maturity_draft_deal(client)
    schedule = fx.list_tranches(client, ctx.deal_id, ctx.advisor_headers)
    assert len(schedule) == 3, f"expected three maturities, got {len(schedule)}"

    first = _tranche_by_sequence(schedule, 1)
    second = _tranche_by_sequence(schedule, 2)
    third = _tranche_by_sequence(schedule, 3)

    # Maturity one: not callable, so only the to-maturity variant exists at all.
    assert first["periods_to_maturity"] == TRANCHE_1_PERIODS
    assert first["periods_to_call"] is None, (
        f"a non-callable maturity has no periods_to_call: {first['periods_to_call']!r}"
    )
    assert first["price_to_call_pct"] is None, (
        f"a non-callable maturity has no price_to_call_pct: "
        f"{first['price_to_call_pct']!r}"
    )
    assert_price(
        first["price_to_maturity_pct"],
        expected_price_pct(TRANCHE_1_COUPON_PCT, TRANCHE_1_YIELD_PCT, TRANCHE_1_PERIODS),
        "maturity one price_to_maturity_pct",
    )
    assert_price(
        first["price_to_maturity_pct"],
        TRANCHE_1_PRICE_TO_MATURITY_PCT,
        "maturity one price_to_maturity_pct",
    )
    assert_price(
        first["reoffering_price_pct"],
        TRANCHE_1_REOFFERING_PRICE_PCT,
        "maturity one reoffering_price_pct",
    )
    assert_is_number(first["reoffering_price_pct"], "maturity one reoffering_price_pct")
    assert_decimal_places(
        first["reoffering_price_pct"],
        PRICE_DECIMALS,
        "maturity one reoffering_price_pct",
    )
    assert_decimal_places(
        first["price_to_maturity_pct"],
        PRICE_DECIMALS,
        "maturity one price_to_maturity_pct",
    )

    # Maturity two: both variants computed, each rounded to three places on its
    # own, and the call variant is the one the comparison selects.
    assert second["periods_to_maturity"] == TRANCHE_2_PERIODS
    assert second["periods_to_call"] == TRANCHE_2_CALL_PERIODS
    assert_price(
        second["price_to_maturity_pct"],
        expected_price_pct(
            TRANCHE_2_COUPON_PCT, TRANCHE_2_YIELD_PCT, TRANCHE_2_PERIODS
        ),
        "maturity two price_to_maturity_pct",
    )
    assert_price(
        second["price_to_maturity_pct"],
        TRANCHE_2_PRICE_TO_MATURITY_PCT,
        "maturity two price_to_maturity_pct",
    )
    assert_price(
        second["price_to_call_pct"],
        expected_price_pct(
            TRANCHE_2_COUPON_PCT, TRANCHE_2_YIELD_PCT, TRANCHE_2_CALL_PERIODS
        ),
        "maturity two price_to_call_pct",
    )
    assert_price(
        second["price_to_call_pct"],
        TRANCHE_2_PRICE_TO_CALL_PCT,
        "maturity two price_to_call_pct",
    )
    assert_decimal_places(
        second["price_to_maturity_pct"],
        PRICE_DECIMALS,
        "maturity two price_to_maturity_pct",
    )
    assert_decimal_places(
        second["price_to_call_pct"], PRICE_DECIMALS, "maturity two price_to_call_pct"
    )
    # The stored reoffering price is the already-rounded variant itself.
    assert_price(
        second["reoffering_price_pct"],
        second["price_to_call_pct"],
        "maturity two reoffering_price_pct",
    )

    # Maturity three: the same coupon and yield redeemed at 102.000 instead of at
    # par, so only the redemption term of the call variant moves.
    assert third["periods_to_call"] == TRANCHE_2_CALL_PERIODS
    assert_price(
        third["price_to_call_pct"],
        expected_price_pct(
            TRANCHE_2_COUPON_PCT,
            TRANCHE_2_YIELD_PCT,
            TRANCHE_2_CALL_PERIODS,
            redemption_pct=TRANCHE_3_CALL_PRICE_PCT,
        ),
        "maturity three price_to_call_pct",
    )
    assert_price(
        third["price_to_call_pct"],
        TRANCHE_3_PRICE_TO_CALL_PCT,
        "maturity three price_to_call_pct",
    )
    assert_price(
        third["reoffering_price_pct"],
        TRANCHE_3_PRICE_TO_CALL_PCT,
        "maturity three reoffering_price_pct",
    )
    assert_decimal_places(
        third["price_to_call_pct"], PRICE_DECIMALS, "maturity three price_to_call_pct"
    )
    assert_decimal_places(
        third["reoffering_price_pct"],
        PRICE_DECIMALS,
        "maturity three reoffering_price_pct",
    )


# ---------------------------------------------------------------------------
# Corner/calculations/closing_an_empty_order_book_allots_nothing
# ---------------------------------------------------------------------------
def test_closing_an_empty_order_book_still_counts_a_run(client):
    """PRD 3.7: "Closing a period that holds no `PENDING` orders at all is
    entirely legal: `allotment_run_count` still becomes one,
    `allotted_order_count` is zero, and every tranche keeps `par_unsold_usd` equal
    to its `principal_amount_usd`."

    Design: Corner/calculations/closing_an_empty_order_book_allots_nothing
    """
    ctx = fx.competitive_pricing_deal(client)
    period = fx.schedule_order_period(
        client, ctx.deal_id, ctx.advisor_headers, f.default_order_period_payload()
    )
    period_id = period["id"]
    fx.open_period(client, period_id, ctx.underwriter_headers)

    response = client.close_order_period(period_id, None, ctx.underwriter_headers)
    closed = validate_success(response, 200)

    assert closed["status"] == OrderPeriodStatus.CLOSED
    assert closed["allotment_run_count"] == 1, (
        "an empty book still records one allotment run, got "
        f"{closed['allotment_run_count']!r}"
    )
    assert closed["allotted_order_count"] == 0
    assert closed["orders_received_count"] == 0

    schedule = fx.list_tranches(client, ctx.deal_id, ctx.advisor_headers)
    assert len(schedule) == 2, f"expected two maturities, got {len(schedule)}"
    for tranche in schedule:
        label = f"maturity {tranche['sequence_number']}"
        assert_money(tranche["par_allotted_usd"], 0, f"{label} par_allotted_usd")
        assert_money(
            tranche["par_unsold_usd"],
            CANONICAL_TRANCHE_PRINCIPAL_USD,
            f"{label} par_unsold_usd",
        )
        assert_par_identity(tranche, label)

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert_money(deal["par_allotted_total_usd"], 0, "par_allotted_total_usd")


# ---------------------------------------------------------------------------
# Corner/calculations/takedown_credit_counts_only_allotted_orders_per_member
# ---------------------------------------------------------------------------
def test_takedown_credit_counts_only_allotted_orders_per_member(client):
    """PRD 3.8: "Orders that are `PENDING`, `UNFILLED`, or `CANCELLED` contribute
    zero."

    Design: Corner/calculations/takedown_credit_counts_only_allotted_orders_per_member
    """
    ctx = _single_maturity_two_manager_deal(client)

    response = client.price_deal(
        ctx.deal_id, f.negotiated_pricing_payload(), ctx.underwriter_headers
    )
    deal = validate_success(response, 200)
    assert deal["status"] == DealStatus.PRICED

    # The four-order book allots exactly as PRD section 3.7's worked case does.
    order_1 = get_success_data(client.get_order(ctx.order_ids[0], ctx.underwriter_headers), 200)
    order_2 = get_success_data(client.get_order(ctx.order_ids[1], ctx.underwriter_headers), 200)
    order_3 = get_success_data(client.get_order(ctx.order_ids[2], ctx.underwriter_headers), 200)
    order_4 = get_success_data(client.get_order(ctx.order_ids[3], ctx.underwriter_headers), 200)

    assert_money(order_1["par_allotted_usd"], WATERFALL_O1_ALLOTTED_USD, "O1 par_allotted_usd")
    assert order_1["status"] == OrderStatus.ALLOTTED
    assert_money(order_2["par_allotted_usd"], WATERFALL_O2_ALLOTTED_USD, "O2 par_allotted_usd")
    assert order_2["status"] == OrderStatus.PARTIALLY_ALLOTTED
    assert_money(order_3["par_allotted_usd"], WATERFALL_O3_ALLOTTED_USD, "O3 par_allotted_usd")
    assert order_3["status"] == OrderStatus.PARTIALLY_ALLOTTED
    assert_money(order_4["par_allotted_usd"], WATERFALL_O4_ALLOTTED_USD, "O4 par_allotted_usd")
    assert order_4["status"] == OrderStatus.UNFILLED

    members = validate_success(
        client.list_deal_syndicate_members(ctx.deal_id, ctx.underwriter_headers), 200
    )
    senior = _member_by_role(members, MemberRole.SENIOR_MANAGER)
    co_manager = _member_by_role(members, MemberRole.CO_MANAGER)

    senior_credit = expected_takedown_credit(
        [WATERFALL_O1_ALLOTTED_USD, WATERFALL_O2_ALLOTTED_USD],
        NEGOTIATED_TAKEDOWN_PER_BOND_USD,
    )
    # The co-manager's second order is UNFILLED, so only one order contributes.
    co_credit = expected_takedown_credit(
        [WATERFALL_O3_ALLOTTED_USD], NEGOTIATED_TAKEDOWN_PER_BOND_USD
    )
    assert_money(
        senior["takedown_credit_usd"], senior_credit, "senior takedown_credit_usd"
    )
    assert_money(
        senior["takedown_credit_usd"],
        WATERFALL_MEMBER_A_TAKEDOWN_USD,
        "senior takedown_credit_usd",
    )
    assert_money(
        co_manager["takedown_credit_usd"], co_credit, "co-manager takedown_credit_usd"
    )
    assert_money(
        co_manager["takedown_credit_usd"],
        WATERFALL_MEMBER_B_TAKEDOWN_USD,
        "co-manager takedown_credit_usd",
    )

    # Crediting requested rather than allotted par is the discriminating error.
    senior_on_requested = expected_takedown_credit(
        [WATERFALL_O1_REQUESTED_USD, WATERFALL_O2_REQUESTED_USD],
        NEGOTIATED_TAKEDOWN_PER_BOND_USD,
    )
    co_on_requested = expected_takedown_credit(
        [WATERFALL_O3_REQUESTED_USD, WATERFALL_O4_REQUESTED_USD],
        NEGOTIATED_TAKEDOWN_PER_BOND_USD,
    )
    assert to_decimal(senior["takedown_credit_usd"]) != senior_on_requested, (
        "the senior manager was credited requested par "
        f"{senior_on_requested} rather than allotted par"
    )
    assert to_decimal(co_manager["takedown_credit_usd"]) != co_on_requested, (
        "the co-manager was credited requested par "
        f"{co_on_requested} rather than allotted par"
    )

    # The two credits exhaust the takedown on the 5,000 bonds actually sold.
    credit_total = to_decimal(senior["takedown_credit_usd"]) + to_decimal(
        co_manager["takedown_credit_usd"]
    )
    assert_money(credit_total, TAKEDOWN_CREDIT_TOTAL_USD, "takedown credit total")

    # Liability par follows liability_pct, not the allotments.
    assert_money(
        senior["liability_par_usd"],
        expected_liability_par(SENIOR_LIABILITY_PCT, CANONICAL_TRANCHE_PRINCIPAL_USD),
        "senior liability_par_usd",
    )
    assert_money(
        co_manager["liability_par_usd"],
        expected_liability_par(CO_LIABILITY_PCT, CANONICAL_TRANCHE_PRINCIPAL_USD),
        "co-manager liability_par_usd",
    )

    # The single-maturity issue's money figures, and the identity over them.
    assert_money(
        deal["issue_price_total_usd"],
        expected_issue_price_total(ctx.tranches),
        "issue_price_total_usd",
    )
    assert_money(
        deal["issue_price_total_usd"],
        SINGLE_TRANCHE_ISSUE_PRICE_TOTAL_USD,
        "issue_price_total_usd",
    )
    assert_money(
        deal["gross_spread_total_usd"],
        expected_negotiated_gross_spread(
            ctx.tranches, NEGOTIATED_COMPONENT_TOTAL_PER_BOND_USD
        ),
        "gross_spread_total_usd",
    )
    assert_money(
        deal["gross_spread_total_usd"],
        SINGLE_TRANCHE_GROSS_SPREAD_TOTAL_USD,
        "gross_spread_total_usd",
    )
    assert_price(
        deal["gross_spread_per_bond_usd"],
        expected_gross_spread_per_bond(
            SINGLE_TRANCHE_GROSS_SPREAD_TOTAL_USD, CANONICAL_TRANCHE_PRINCIPAL_USD
        ),
        "gross_spread_per_bond_usd",
    )
    assert_price(
        deal["gross_spread_per_bond_usd"],
        NEGOTIATED_GROSS_SPREAD_PER_BOND_USD,
        "gross_spread_per_bond_usd",
    )
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        expected_net_proceeds(
            SINGLE_TRANCHE_ISSUE_PRICE_TOTAL_USD, SINGLE_TRANCHE_GROSS_SPREAD_TOTAL_USD, 0
        ),
        "net_proceeds_to_issuer_usd",
    )
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        SINGLE_TRANCHE_NET_PROCEEDS_USD,
        "net_proceeds_to_issuer_usd",
    )
    assert_money_identity(deal)


# ---------------------------------------------------------------------------
# Corner/calculations/arbitrage_yield_uses_only_the_deals_own_tranches
# ---------------------------------------------------------------------------
def test_arbitrage_yield_weights_only_the_deals_own_tranches(client):
    """PRD 3.8: "`Deal.arbitrage_yield_pct` is the bond-year-weighted average of
    the tranches' `yield_pct` — the sum over tranches of `yield_pct` multiplied by
    that tranche's bond years, divided by the total bond years — rounded to four
    decimal places."

    Design: Corner/calculations/arbitrage_yield_uses_only_the_deals_own_tranches
    """
    # Deal A: the canonical schedule, bond years 50,000 and 100,000.
    ctx = fx.draft_deal(client)

    # Deal B: the same issuer, one taxable maturity at the far end of the yield
    # curve, so pooling the two input sets is unmistakable in the result.
    deal_b = fx.create_deal(
        client,
        ctx.issuer_id,
        ctx.advisor_firm_id,
        ctx.issuer_headers,
        tax_status=TaxStatus.TAXABLE,
        expected_par_amount_usd=FOREIGN_DEAL_PAR_USD,
    )
    tranche_b = fx.add_tranche(
        client,
        deal_b["id"],
        ctx.advisor_headers,
        f.tranche_payload(
            1,
            TRANCHE_1_MATURITY_DATE,
            principal_amount_usd=FOREIGN_DEAL_PAR_USD,
            coupon_rate_pct=FOREIGN_TRANCHE_COUPON_PCT,
            yield_pct=FOREIGN_TRANCHE_YIELD_PCT,
        ),
    )

    analysis_a = validate_success(
        client.yield_restriction_analysis(
            ctx.deal_id, f.yield_restriction_payload(), ctx.compliance_headers
        ),
        200,
    )
    assert_yield_value(
        analysis_a["arbitrage_yield_pct"],
        expected_arbitrage_yield(ctx.tranches),
        "deal A arbitrage_yield_pct",
    )
    assert_yield_value(
        analysis_a["arbitrage_yield_pct"],
        CANONICAL_ARBITRAGE_YIELD_PCT,
        "deal A arbitrage_yield_pct",
    )
    assert_yield_value(
        analysis_a["permitted_investment_yield_pct"],
        CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
        "deal A permitted_investment_yield_pct",
    )

    # Weighting across the issuer's deals rather than the one deal lands here.
    pooled = expected_arbitrage_yield(list(ctx.tranches) + [tranche_b])
    assert to_decimal(analysis_a["arbitrage_yield_pct"]) != pooled, (
        "deal A's arbitrage yield pooled deal B's maturity: "
        f"expected {CANONICAL_ARBITRAGE_YIELD_PCT}, got the cross-deal {pooled}"
    )

    # The two input sets are disjoint: deal B sees only its own maturity.
    analysis_b = validate_success(
        client.yield_restriction_analysis(
            deal_b["id"], f.yield_restriction_payload(), ctx.compliance_headers
        ),
        200,
    )
    assert_yield_value(
        analysis_b["arbitrage_yield_pct"],
        expected_arbitrage_yield([tranche_b]),
        "deal B arbitrage_yield_pct",
    )
    assert_yield_value(
        analysis_b["arbitrage_yield_pct"],
        FOREIGN_ARBITRAGE_YIELD_PCT,
        "deal B arbitrage_yield_pct",
    )


def test_the_yield_restriction_analysis_stores_nothing(client):
    """PRD 3.8: "It stores nothing whatsoever."

    Design: Corner/calculations/arbitrage_yield_uses_only_the_deals_own_tranches
    """
    ctx = fx.draft_deal(client)
    before = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert before["arbitrage_yield_pct"] is None

    analysis = validate_success(
        client.yield_restriction_analysis(
            ctx.deal_id, f.yield_restriction_payload(), ctx.compliance_headers
        ),
        200,
    )
    assert_yield_value(
        analysis["arbitrage_yield_pct"],
        CANONICAL_ARBITRAGE_YIELD_PCT,
        "arbitrage_yield_pct",
    )

    # The projection computed the yield but must not have persisted it, and the
    # read-only call must not have moved the deal at all.
    after = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert after["arbitrage_yield_pct"] is None, (
        "the read-only projection persisted arbitrage_yield_pct "
        f"{after['arbitrage_yield_pct']!r} on the deal"
    )
    assert after["version"] == before["version"], (
        "the read-only projection incremented the deal's version from "
        f"{before['version']} to {after['version']}"
    )
    assert after["status"] == before["status"] == DealStatus.DRAFT


# ---------------------------------------------------------------------------
# Corner/calculations/permitted_investment_yield_adds_the_one_eighth_allowance
# ---------------------------------------------------------------------------
def test_the_permitted_yield_adds_the_one_eighth_of_one_percent_allowance(client):
    """PRD 3.8: "The permitted yield is `arbitrage_yield_pct` plus the one-eighth
    of one percent allowance — that is, plus 0.125 — rounded to four decimal
    places."

    Design: Corner/calculations/permitted_investment_yield_adds_the_one_eighth_allowance
    """
    ctx = fx.draft_deal(client)

    analysis = validate_success(
        client.yield_restriction_analysis(
            ctx.deal_id, f.yield_restriction_payload(), ctx.compliance_headers
        ),
        200,
    )

    assert_yield_value(
        analysis["arbitrage_yield_pct"],
        CANONICAL_ARBITRAGE_YIELD_PCT,
        "arbitrage_yield_pct",
    )
    assert_decimal_places(
        analysis["arbitrage_yield_pct"], YIELD_DECIMALS, "arbitrage_yield_pct"
    )

    permitted = expected_permitted_investment_yield(analysis["arbitrage_yield_pct"])
    assert_yield_value(
        analysis["permitted_investment_yield_pct"],
        permitted,
        "permitted_investment_yield_pct",
    )
    assert_yield_value(
        analysis["permitted_investment_yield_pct"],
        CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
        "permitted_investment_yield_pct",
    )
    assert_decimal_places(
        analysis["permitted_investment_yield_pct"],
        YIELD_DECIMALS,
        "permitted_investment_yield_pct",
    )
    # The allowance is added, not folded into the arbitrage yield itself.
    assert to_decimal(analysis["permitted_investment_yield_pct"]) - to_decimal(
        analysis["arbitrage_yield_pct"]
    ) == Decimal("0.125")

    # The projected yield is echoed back exactly as supplied.
    assert_yield_value(
        analysis["projected_investment_yield_pct"],
        PROJECTED_INVESTMENT_YIELD_PCT,
        "projected_investment_yield_pct",
    )
    # 4.600 is strictly greater than 4.2083, so the restriction applies.
    assert analysis["yield_restriction_applies"] is True


def test_excess_earnings_use_the_three_hundred_sixty_day_basis(client):
    """PRD 3.8: "When the restriction applies, `excess_earnings_usd` is
    `unspent_proceeds_usd` multiplied by the difference between the projected and
    permitted yields, divided by one hundred, multiplied by `investment_days`,
    divided by three hundred sixty, rounded to two decimal places; when it does not
    apply, `excess_earnings_usd` is 0.00."

    Design: Corner/calculations/permitted_investment_yield_adds_the_one_eighth_allowance
    """
    ctx = fx.draft_deal(client)

    analysis = validate_success(
        client.yield_restriction_analysis(
            ctx.deal_id, f.yield_restriction_payload(), ctx.compliance_headers
        ),
        200,
    )
    assert analysis["yield_restriction_applies"] is True

    assert_money(
        analysis["excess_earnings_usd"],
        expected_excess_earnings(
            UNSPENT_PROCEEDS_USD,
            PROJECTED_INVESTMENT_YIELD_PCT,
            CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
            INVESTMENT_DAYS,
        ),
        "excess_earnings_usd",
    )
    assert_money(analysis["excess_earnings_usd"], EXCESS_EARNINGS_USD, "excess_earnings_usd")
    assert_decimal_places(analysis["excess_earnings_usd"], MONEY_DECIMALS, "excess_earnings_usd")
    assert_is_number(analysis["excess_earnings_usd"], "excess_earnings_usd")

    # A 365-day year is the classic wrong basis and lands 134.14 lower.
    on_365 = _excess_earnings_on_alternative_basis(
        UNSPENT_PROCEEDS_USD,
        PROJECTED_INVESTMENT_YIELD_PCT,
        CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT,
        INVESTMENT_DAYS,
        ALTERNATIVE_DAY_BASIS,
    )
    assert on_365 == round_half_up(EXCESS_EARNINGS_ON_365_BASIS_USD, MONEY)
    assert to_decimal(analysis["excess_earnings_usd"]) != on_365, (
        f"excess_earnings_usd used a {ALTERNATIVE_DAY_BASIS}-day basis rather than "
        f"{ARBITRAGE_DAY_BASIS}: got {on_365}"
    )

    # Measuring the excess against the bare arbitrage yield, i.e. forgetting the
    # 0.125 allowance, overstates it instead.
    without_allowance = expected_excess_earnings(
        UNSPENT_PROCEEDS_USD,
        PROJECTED_INVESTMENT_YIELD_PCT,
        CANONICAL_ARBITRAGE_YIELD_PCT,
        INVESTMENT_DAYS,
    )
    assert to_decimal(analysis["excess_earnings_usd"]) != without_allowance, (
        "excess_earnings_usd was measured against the bare arbitrage yield, "
        f"dropping the one-eighth allowance: got {without_allowance}"
    )


# ---------------------------------------------------------------------------
# Corner/calculations/disclosure_risk_score_sums_weights_and_clamps_at_one_hundred
# ---------------------------------------------------------------------------
def test_the_risk_score_sums_the_four_weighted_contributions(client):
    """PRD 3.1: "Finally the issuer's governmental character contributes a
    surcharge determined by `entity_type`: a `STATE` adds nothing, a `CITY` or a
    `COUNTY` adds five, a `SCHOOL_DISTRICT` adds ten, and an `AUTHORITY` adds
    fifteen."

    Design: Corner/calculations/disclosure_risk_score_sums_weights_and_clamps_at_one_hundred
    """
    # A STATE with a clean record: the surcharge table has a genuine zero row.
    state = validate_success(
        client.create_issuer(
            f.issuer_payload(entity_type=EntityType.STATE), COMPLIANCE_HEADERS
        ),
        201,
    )
    assert state["disclosure_risk_score"] == expected_risk_score(EntityType.STATE)
    assert state["disclosure_risk_score"] == STATE_CLEAN_SCORE
    assert isinstance(state["disclosure_risk_score"], int) and not isinstance(
        state["disclosure_risk_score"], bool
    ), "disclosure_risk_score must be an integer, never a float"

    # A CITY with a clean record: the surcharge alone.
    city = validate_success(
        client.create_issuer(
            f.issuer_payload(entity_type=EntityType.CITY), COMPLIANCE_HEADERS
        ),
        201,
    )
    assert city["disclosure_risk_score"] == expected_risk_score(EntityType.CITY)
    assert city["disclosure_risk_score"] == CITY_CLEAN_SCORE
    assert isinstance(city["disclosure_risk_score"], int) and not isinstance(
        city["disclosure_risk_score"], bool
    ), "disclosure_risk_score must be an integer, never a float"

    # An AUTHORITY with three late event notices: 15 + 24, which exercises the
    # eight-point notice weight three times.
    authority = validate_success(
        client.create_issuer(
            f.issuer_payload(
                entity_type=EntityType.AUTHORITY,
                prior_late_annual_filings=0,
                prior_late_event_notices=3,
                has_prior_material_event=False,
            ),
            COMPLIANCE_HEADERS,
        ),
        201,
    )
    assert authority["disclosure_risk_score"] == expected_risk_score(
        EntityType.AUTHORITY, prior_late_event_notices=3
    )
    assert authority["disclosure_risk_score"] == AUTHORITY_THREE_NOTICES_SCORE
    assert isinstance(authority["disclosure_risk_score"], int) and not isinstance(
        authority["disclosure_risk_score"], bool
    ), "disclosure_risk_score must be an integer, never a float"

    # Charging late notices at the twelve-point annual-filing weight lands on 51.
    on_annual_weight = (
        ENTITY_TYPE_SURCHARGE[EntityType.AUTHORITY] + 3 * LATE_ANNUAL_FILING_POINTS
    )
    assert authority["disclosure_risk_score"] != on_annual_weight, (
        "late event notices were scored at the twelve-point annual-filing weight: "
        f"got {on_annual_weight} instead of {AUTHORITY_THREE_NOTICES_SCORE}"
    )

    # The stored scores survive a read.
    for issuer in (state, city, authority):
        reread = validate_success(client.get_issuer(issuer["id"], COMPLIANCE_HEADERS), 200)
        assert reread["disclosure_risk_score"] == issuer["disclosure_risk_score"]


def test_the_risk_score_clamps_a_raw_total_above_one_hundred(client):
    """PRD 3.1: "Those four contributions are added together, and the resulting raw
    total is then clamped into the permitted range: anything below zero becomes zero
    and anything above one hundred becomes one hundred."

    Design: Corner/calculations/disclosure_risk_score_sums_weights_and_clamps_at_one_hundred
    """
    # 5 * 12 + 5 * 8 + 25 + 15 = 140 raw, well above the ceiling.
    issuer = validate_success(
        client.create_issuer(
            f.issuer_payload(
                entity_type=EntityType.AUTHORITY,
                prior_late_annual_filings=5,
                prior_late_event_notices=5,
                has_prior_material_event=True,
            ),
            COMPLIANCE_HEADERS,
        ),
        201,
    )

    raw = _raw_risk_score(
        EntityType.AUTHORITY,
        prior_late_annual_filings=5,
        prior_late_event_notices=5,
        has_prior_material_event=True,
    )
    assert raw == CLAMPED_AUTHORITY_RAW_SCORE

    assert issuer["disclosure_risk_score"] == expected_risk_score(
        EntityType.AUTHORITY,
        prior_late_annual_filings=5,
        prior_late_event_notices=5,
        has_prior_material_event=True,
    )
    assert issuer["disclosure_risk_score"] == RISK_SCORE_MAX
    assert issuer["disclosure_risk_score"] != raw, (
        f"the raw total {raw} was stored unclamped instead of {RISK_SCORE_MAX}"
    )
    assert isinstance(issuer["disclosure_risk_score"], int) and not isinstance(
        issuer["disclosure_risk_score"], bool
    ), "disclosure_risk_score must be an integer, never a float"

    reread = validate_success(client.get_issuer(issuer["id"], COMPLIANCE_HEADERS), 200)
    assert reread["disclosure_risk_score"] == RISK_SCORE_MAX


# ---------------------------------------------------------------------------
# Corner/calculations/committing_an_enhancement_propagates_the_premium_down_and_up
# ---------------------------------------------------------------------------
def test_committing_the_policy_insures_only_the_named_maturity(client):
    """PRD 3.3: "Every maturity whose identifier appears in `insured_tranche_ids`
    has its `is_insured` set to true and its `rating_basis` moved from `UNDERLYING`
    to `ENHANCED`, which is what tells the marketing documents that those maturities
    carry the insurer's rating rather than the issuer's own."

    Design: Corner/calculations/committing_an_enhancement_propagates_the_premium_down_and_up
    """
    ctx = _proposed_enhancement_on_the_first_maturity(client)
    insured_before = validate_success(
        client.get_maturity_tranche(ctx.insured_tranche_id, ctx.advisor_headers), 200
    )
    uninsured_before = validate_success(
        client.get_maturity_tranche(ctx.uninsured_tranche_id, ctx.advisor_headers), 200
    )
    assert insured_before["is_insured"] is False
    assert insured_before["rating_basis"] == RatingBasis.UNDERLYING

    enhancement = validate_success(
        client.commit_credit_enhancement(ctx.enhancement_id, None, ctx.issuer_headers), 200
    )
    assert enhancement["status"] == EnhancementStatus.COMMITTED

    # Debt service is rounded per insured maturity and then summed: 5,000,000 of
    # principal plus twenty semiannual coupons of 125,000.
    assert_money(
        enhancement["insured_debt_service_usd"],
        expected_insured_debt_service([insured_before]),
        "insured_debt_service_usd",
    )
    assert_money(
        enhancement["insured_debt_service_usd"],
        INSURED_DEBT_SERVICE_TRANCHE_1_USD,
        "insured_debt_service_usd",
    )
    assert_money(
        enhancement["premium_usd"],
        expected_premium(INSURED_DEBT_SERVICE_TRANCHE_1_USD, ENHANCEMENT_PREMIUM_BPS),
        "premium_usd",
    )
    assert_money(enhancement["premium_usd"], ENHANCEMENT_PREMIUM_USD, "premium_usd")

    # The uninsured maturity's own debt service is not in the policy's base.
    both_maturities = expected_insured_debt_service([insured_before, uninsured_before])
    assert to_decimal(enhancement["insured_debt_service_usd"]) != both_maturities, (
        "insured_debt_service_usd covered the whole schedule rather than the named "
        f"maturity: got {both_maturities}"
    )

    schedule = fx.list_tranches(client, ctx.deal_id, ctx.advisor_headers)
    insured = _tranche_by_sequence(schedule, 1)
    uninsured = _tranche_by_sequence(schedule, 2)
    assert insured["id"] == ctx.insured_tranche_id
    assert insured["is_insured"] is True
    assert insured["rating_basis"] == RatingBasis.ENHANCED
    # The control maturity belongs to the same deal and must not move.
    assert uninsured["id"] == ctx.uninsured_tranche_id
    assert uninsured["is_insured"] is False
    assert uninsured["rating_basis"] == RatingBasis.UNDERLYING
    assert uninsured["version"] == uninsured_before["version"]

    # The propagation reaches a fixed point: a second read shows no movement.
    insured_again = validate_success(
        client.get_maturity_tranche(ctx.insured_tranche_id, ctx.advisor_headers), 200
    )
    uninsured_again = validate_success(
        client.get_maturity_tranche(ctx.uninsured_tranche_id, ctx.advisor_headers), 200
    )
    assert insured_again["is_insured"] is True
    assert insured_again["rating_basis"] == RatingBasis.ENHANCED
    assert insured_again["version"] == insured["version"]
    assert uninsured_again["is_insured"] is False
    assert uninsured_again["rating_basis"] == RatingBasis.UNDERLYING
    assert uninsured_again["version"] == uninsured["version"]


def test_committing_the_policy_propagates_the_premium_up_to_the_deal(client):
    """PRD 3.3: "Finally `Deal.credit_enhancement_premium_usd` is set to that
    `premium_usd`, and if the deal has already been priced its
    `net_proceeds_to_issuer_usd` is recomputed so the money identity continues to
    hold."

    Design: Corner/calculations/committing_an_enhancement_propagates_the_premium_down_and_up
    """
    ctx = _proposed_enhancement_on_the_first_maturity(client)
    before = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert_money(
        before["credit_enhancement_premium_usd"], 0, "credit_enhancement_premium_usd"
    )

    enhancement = validate_success(
        client.commit_credit_enhancement(ctx.enhancement_id, None, ctx.issuer_headers), 200
    )
    assert enhancement["status"] == EnhancementStatus.COMMITTED

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert_money(
        deal["credit_enhancement_premium_usd"],
        enhancement["premium_usd"],
        "credit_enhancement_premium_usd",
    )
    assert_money(
        deal["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "credit_enhancement_premium_usd",
    )

    # The deal is only STRUCTURING, so the priced money fields stay null rather
    # than being computed early off the premium alone.
    assert deal["status"] == DealStatus.STRUCTURING
    assert deal["net_proceeds_to_issuer_usd"] is None, (
        "net_proceeds_to_issuer_usd was computed on an unpriced deal: "
        f"{deal['net_proceeds_to_issuer_usd']!r}"
    )
    assert deal["issue_price_total_usd"] is None, (
        "issue_price_total_usd was computed on an unpriced deal: "
        f"{deal['issue_price_total_usd']!r}"
    )

    # The propagation reaches a fixed point: a second read shows no movement.
    again = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert_money(
        again["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "credit_enhancement_premium_usd",
    )
    assert again["net_proceeds_to_issuer_usd"] is None
    assert again["issue_price_total_usd"] is None
    assert again["version"] == deal["version"]
