"""Combinatorial money formulas: pinned rounding order and pinned evaluation order.

Two instances of the difficulty design index are translated here:

* ``gross_spread_round_per_tranche_then_sum`` -- a schedule split 2,505,000 /
  7,495,000 whose per-bond components sum to exactly 8.333, so rounding each
  tranche's spread to cents before summing and summing bond counts before
  rounding once differ by a single observable cent.
* ``premium_and_net_proceeds_evaluation_order_pinned`` -- the enhancement premium
  looks as though it should be charged on the proceeds it reduces, but PRD.md
  pins it to insured debt service and pins net proceeds to one single pass, so
  nothing is ever grossed up and re-fed.

Both scenarios are built from ``test_helpers.fixtures`` step helpers because
neither schedule is the canonical one that the shared conftest fixtures carry.
"""

from decimal import Decimal

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    MONEY,
    assert_money,
    assert_money_identity,
    assert_price,
    expected_gross_spread_per_bond,
    expected_insured_debt_service,
    expected_issue_price_total,
    expected_negotiated_gross_spread,
    expected_net_proceeds,
    expected_premium,
    round_half_up,
    to_decimal,
)
from test_helpers.constants import (
    BOND_PAR_USD,
    CANONICAL_EXPECTED_PAR_USD,
    CANONICAL_ISSUE_PRICE_TOTAL_USD,
    ENHANCEMENT_PREMIUM_BPS,
    ENHANCEMENT_PREMIUM_USD,
    INSURED_DEBT_SERVICE_TRANCHE_1_USD,
    NEGOTIATED_EXPENSES_PER_BOND_USD,
    NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
    NEGOTIATED_NET_PROCEEDS_INSURED_USD,
    NEGOTIATED_TAKEDOWN_PER_BOND_USD,
    TRANCHE_1_REOFFERING_PRICE_PCT,
    TRANCHE_2_REOFFERING_PRICE_PCT,
)
from test_helpers.types import DealStatus, EnhancementStatus, MemberRole, RatingBasis, SaleMethod

# The split schedule of the design index: the two halves still foot to the
# 10,000,000 authorisation that ``deal_payload`` requests.
SPLIT_TRANCHE_1_PRINCIPAL_USD = 2505000
SPLIT_TRANCHE_2_PRINCIPAL_USD = 7495000

# A management fee carrying three decimals is what separates the two aggregation
# orders: 5.000 + 2.083 + 1.250 is exactly 8.333 per bond.
SPLIT_MANAGEMENT_FEE_PER_BOND_USD = 2.083


def _component_total_per_bond(takedown, management_fee, expenses):
    """PRD section 3.8's negotiated per-bond component total, at Decimal scale.

    The three inputs are summed as decimals rather than as floats so the exact
    8.333 the schedule depends on survives the addition.
    """
    return to_decimal(takedown) + to_decimal(management_fee) + to_decimal(expenses)


def _spread_summed_before_rounding(tranches, component_total_per_bond):
    """The rejected aggregation order, computed only so the cent gap is observable.

    PRD section 3.8 calls summing bond counts across tranches and rounding once at
    the end "a different and wrong answer", so this figure is precisely what the
    priced deal must *not* carry.
    """
    bond_count = sum(
        to_decimal(tranche["principal_amount_usd"]) / Decimal(BOND_PAR_USD)
        for tranche in tranches
    )
    return round_half_up(bond_count * to_decimal(component_total_per_bond), MONEY)


def _priced_deal_with_split_schedule(client):
    """Drive a negotiated deal carrying the 2,505,000 / 7,495,000 split to PRICED."""
    ctx = fx.participants(client)
    deal = fx.create_deal(client, ctx.issuer_id, ctx.advisor_firm_id, ctx.issuer_headers)
    ctx.deal = deal
    ctx.deal_id = deal["id"]
    fx.add_tranche(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.canonical_tranche_1_payload(
            principal_amount_usd=SPLIT_TRANCHE_1_PRINCIPAL_USD
        ),
    )
    fx.add_tranche(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.canonical_tranche_2_payload(
            principal_amount_usd=SPLIT_TRANCHE_2_PRINCIPAL_USD
        ),
    )
    ctx.senior_member = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
    )
    ctx.members = [ctx.senior_member]
    ctx.member_ids = [ctx.senior_member["id"]]
    ctx.deal = fx.submit_structure(client, ctx.deal_id, ctx.advisor_headers)
    ctx.deal = fx.designate_sale_method(
        client, ctx.deal_id, SaleMethod.NEGOTIATED, ctx.advisor_headers
    )
    fx.cleared_disclosure(ctx)
    fx.with_completed_allotment_run(ctx)
    ctx.deal = fx.price_negotiated(
        client,
        ctx.deal_id,
        ctx.underwriter_headers,
        management_fee_per_bond_usd=SPLIT_MANAGEMENT_FEE_PER_BOND_USD,
    )
    ctx.tranches = fx.list_tranches(client, ctx.deal_id, ctx.advisor_headers)
    ctx.tranche_ids = [t["id"] for t in ctx.tranches]
    ctx.component_total_per_bond = _component_total_per_bond(
        NEGOTIATED_TAKEDOWN_PER_BOND_USD,
        SPLIT_MANAGEMENT_FEE_PER_BOND_USD,
        NEGOTIATED_EXPENSES_PER_BOND_USD,
    )
    return ctx


def _priced_deal_insuring_the_first_maturity(client):
    """Commit a 45 basis point policy over maturity one, then price the deal.

    PRD section 3.3 admits commitment while the deal sits on either pricing
    branch, so the policy is live before the pricing write runs.
    """
    ctx = fx.negotiated_pricing_deal(client)
    ctx.insured_tranche_id = ctx.tranche_ids[0]
    enhancement = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.insured_tranche_id], ctx.advisor_headers
    )
    ctx.enhancement = fx.commit_enhancement(
        client, enhancement["id"], ctx.issuer_headers
    )
    ctx.enhancement_id = ctx.enhancement["id"]
    fx.cleared_disclosure(ctx)
    fx.with_completed_allotment_run(ctx)
    ctx.deal = fx.price_negotiated(client, ctx.deal_id, ctx.underwriter_headers)
    ctx.tranches = fx.list_tranches(client, ctx.deal_id, ctx.advisor_headers)
    ctx.tranche_ids = [t["id"] for t in ctx.tranches]
    return ctx


def test_gross_spread_rounds_each_tranche_before_summing(client):
    """PRD 3.8: "Here too the rounding order is pinned — summing bond counts
    across tranches and rounding once at the end is a different and wrong answer
    whenever a per-bond component carries more than two significant decimals."

    Design: Difficulty/combinatorial_formula/gross_spread_round_per_tranche_then_sum
    """
    ctx = _priced_deal_with_split_schedule(client)
    deal = ctx.deal

    per_tranche_then_sum = expected_negotiated_gross_spread(
        ctx.tranches, ctx.component_total_per_bond
    )
    summed_then_rounded = _spread_summed_before_rounding(
        ctx.tranches, ctx.component_total_per_bond
    )
    # The schedule is only discriminating if the two orders really do differ.
    assert per_tranche_then_sum != summed_then_rounded, (
        "the split schedule must separate the two aggregation orders, "
        f"both came out at {per_tranche_then_sum}"
    )

    assert_money(
        deal["gross_spread_total_usd"], per_tranche_then_sum, "gross_spread_total_usd"
    )
    assert to_decimal(deal["gross_spread_total_usd"]) != summed_then_rounded, (
        "gross_spread_total_usd carries the rejected sum-then-round figure "
        f"{summed_then_rounded}"
    )

    # The per-bond figure is derived from the already-rounded total (PRD 3.8).
    assert_price(
        deal["gross_spread_per_bond_usd"],
        expected_gross_spread_per_bond(per_tranche_then_sum, CANONICAL_EXPECTED_PAR_USD),
        "gross_spread_per_bond_usd",
    )
    assert deal["status"] == DealStatus.PRICED


def test_issue_price_total_rounds_each_tranche_before_summing(client):
    """PRD 3.8: "The rounding order is pinned: round each tranche and then sum,
    never sum and then round."

    Design: Difficulty/combinatorial_formula/gross_spread_round_per_tranche_then_sum
    """
    ctx = _priced_deal_with_split_schedule(client)
    deal = ctx.deal
    first, second = ctx.tranches

    # The split changes only the principals, so the reoffering scale is unchanged.
    assert_money(
        first["principal_amount_usd"],
        SPLIT_TRANCHE_1_PRINCIPAL_USD,
        "tranche 1 principal_amount_usd",
    )
    assert_money(
        second["principal_amount_usd"],
        SPLIT_TRANCHE_2_PRINCIPAL_USD,
        "tranche 2 principal_amount_usd",
    )
    assert_price(
        first["reoffering_price_pct"],
        TRANCHE_1_REOFFERING_PRICE_PCT,
        "tranche 1 reoffering_price_pct",
    )
    assert_price(
        second["reoffering_price_pct"],
        TRANCHE_2_REOFFERING_PRICE_PCT,
        "tranche 2 reoffering_price_pct",
    )

    issue_price = expected_issue_price_total(ctx.tranches)
    assert_money(deal["issue_price_total_usd"], issue_price, "issue_price_total_usd")

    # No enhancement was ever proposed, so the premium counter is still at zero
    # (PRD section 3.2) and net proceeds absorb the whole remainder.
    assert_money(
        deal["credit_enhancement_premium_usd"], 0, "credit_enhancement_premium_usd"
    )
    gross_spread = expected_negotiated_gross_spread(
        ctx.tranches, ctx.component_total_per_bond
    )
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        expected_net_proceeds(issue_price, gross_spread, 0),
        "net_proceeds_to_issuer_usd",
    )
    assert_money_identity(deal)


def test_committing_the_policy_moves_the_insured_maturity_to_the_enhanced_basis(client):
    """PRD 3.3: "Every maturity whose identifier appears in `insured_tranche_ids`
    has its `is_insured` set to true and its `rating_basis` moved from
    `UNDERLYING` to `ENHANCED`, which is what tells the marketing documents that
    those maturities carry the insurer's rating rather than the issuer's own."

    Design: Difficulty/combinatorial_formula/premium_and_net_proceeds_evaluation_order_pinned
    """
    ctx = _priced_deal_insuring_the_first_maturity(client)
    insured, uninsured = ctx.tranches

    assert ctx.enhancement["status"] == EnhancementStatus.COMMITTED
    assert insured["id"] == ctx.insured_tranche_id

    assert insured["is_insured"] is True
    assert insured["rating_basis"] == RatingBasis.ENHANCED

    # The maturity outside `insured_tranche_ids` is untouched (PRD section 3.2).
    assert uninsured["is_insured"] is False
    assert uninsured["rating_basis"] == RatingBasis.UNDERLYING


def test_premium_is_charged_against_insured_debt_service(client):
    """PRD 3.3: "The enhancement's `premium_usd` is `insured_debt_service_usd`
    multiplied by `premium_bps` and divided by ten thousand, because a basis point
    is one ten-thousandth, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/premium_and_net_proceeds_evaluation_order_pinned
    """
    ctx = _priced_deal_insuring_the_first_maturity(client)
    enhancement = ctx.enhancement
    insured = [t for t in ctx.tranches if t["id"] == ctx.insured_tranche_id]

    # Aggregate debt service of the insured set only: 5,000,000 of principal plus
    # twenty semiannual coupons at 5.000 (PRD section 3.3).
    assert_money(
        enhancement["insured_debt_service_usd"],
        expected_insured_debt_service(insured),
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

    # The deal carries the same figure it was charged (PRD section 3.3).
    assert_money(
        ctx.deal["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "credit_enhancement_premium_usd",
    )


def test_net_proceeds_are_evaluated_once_and_never_re_fed(client):
    """PRD 3.8: "Third the **premium and net proceeds**, computed exactly as set
    out in section 3.3 and single-pass by construction: the premium is charged
    against insured debt service, never against proceeds, and net proceeds are
    never grossed up and re-fed into the premium."

    Design: Difficulty/combinatorial_formula/premium_and_net_proceeds_evaluation_order_pinned
    """
    ctx = _priced_deal_insuring_the_first_maturity(client)
    deal = ctx.deal

    assert_money(
        deal["issue_price_total_usd"],
        CANONICAL_ISSUE_PRICE_TOTAL_USD,
        "issue_price_total_usd",
    )
    assert_money(
        deal["gross_spread_total_usd"],
        NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
        "gross_spread_total_usd",
    )
    assert_money(
        deal["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "credit_enhancement_premium_usd",
    )

    # One single pass: proceeds less spread less the debt-service premium.
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        expected_net_proceeds(
            CANONICAL_ISSUE_PRICE_TOTAL_USD,
            NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
            ENHANCEMENT_PREMIUM_USD,
        ),
        "net_proceeds_to_issuer_usd",
    )
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        NEGOTIATED_NET_PROCEEDS_INSURED_USD,
        "net_proceeds_to_issuer_usd",
    )
    assert_money_identity(deal)
