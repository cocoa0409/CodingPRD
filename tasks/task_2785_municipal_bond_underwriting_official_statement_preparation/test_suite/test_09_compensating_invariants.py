"""Two compensating actions, two conserved quantities.

Reopening a closed order period voids a full allotment run -- a filled tier, a
pro-rated tier and a starved tier -- and must leave the **par** identity exactly
satisfied, then let a second close reproduce the identical allotment. Withdrawing
a committed credit enhancement from an already priced deal moves the premium term
into the net-proceeds term and must leave the **money** identity exactly
satisfied at a different split.

Every test here translates one instance of the DIFFICULTY design index; the
``Design:`` line of each docstring names it.
"""

from prd_bench_local_runner.testing import (
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_deal_par_total,
    assert_money,
    assert_money_identity,
    assert_par_identity,
    assert_yield_value,
)
from test_helpers.constants import (
    CANONICAL_ARBITRAGE_YIELD_PCT,
    CANONICAL_ISSUE_PRICE_TOTAL_USD,
    ENHANCEMENT_PREMIUM_USD,
    NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
    NEGOTIATED_NET_PROCEEDS_INSURED_USD,
    NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
    WATERFALL_O1_ALLOTTED_USD,
    WATERFALL_O2_ALLOTTED_USD,
    WATERFALL_O3_ALLOTTED_USD,
    WATERFALL_O4_ALLOTTED_USD,
    WATERFALL_TRANCHE_PRINCIPAL_USD,
)
from test_helpers.types import (
    DealStatus,
    EnhancementStatus,
    OrderPeriodStatus,
    OrderStatus,
    RatingBasis,
)

# The design index's own wording for the two compensating actions.
REOPEN_REASON = "Allotment recorded against the wrong maturity."
WITHDRAWAL_REASON = "Insurer downgraded after pricing."

# PRD section 3.7's worked waterfall, order by order: the filled retail tier, the
# pro-rated institutional tier, and the starved member tier.
EXPECTED_ALLOTMENT = (
    (WATERFALL_O1_ALLOTTED_USD, OrderStatus.ALLOTTED),
    (WATERFALL_O2_ALLOTTED_USD, OrderStatus.PARTIALLY_ALLOTTED),
    (WATERFALL_O3_ALLOTTED_USD, OrderStatus.PARTIALLY_ALLOTTED),
    (WATERFALL_O4_ALLOTTED_USD, OrderStatus.UNFILLED),
)
EXPECTED_ALLOTTED_ORDER_COUNT = 3


# ---------------------------------------------------------------------------
# Reading the order book back (PRD section 3.7)
# ---------------------------------------------------------------------------
def _orders_in_entry_order(ctx):
    """The period's four orders, keyed by the identifiers the fixture recorded.

    Returns a list aligned with ``ctx.order_ids`` -- that is, in the order the
    orders were entered -- so it lines up with ``EXPECTED_ALLOTMENT``.
    """
    rows, _meta = validate_paginated(
        ctx.client.list_period_orders(ctx.period_id, ctx.compliance_headers)
    )
    by_id = {row["id"]: row for row in rows}
    assert set(by_id) == set(ctx.order_ids), (
        "the period should still hold exactly the four entered orders; "
        f"expected {sorted(ctx.order_ids)}, got {sorted(by_id)}"
    )
    return [by_id[order_id] for order_id in ctx.order_ids]


def _assert_worked_allotment(orders, moment):
    """PRD section 3.7's worked figures: 2,005,000 / 1,715,000 / 1,280,000 / 0."""
    for index, (order, (expected_par, expected_status)) in enumerate(
        zip(orders, EXPECTED_ALLOTMENT), start=1
    ):
        label = f"order[O{index}] {moment}"
        assert order["par_allotted_usd"] == expected_par, (
            f"{label}.par_allotted_usd: expected {expected_par}, "
            f"got {order['par_allotted_usd']!r}"
        )
        assert order["status"] == expected_status, (
            f"{label}.status: expected {expected_status}, got {order['status']!r}"
        )


def _assert_book_voided(orders, moment):
    """PRD section 3.7 hop two: every order returns to PENDING with zero par."""
    for index, order in enumerate(orders, start=1):
        label = f"order[O{index}] {moment}"
        assert order["status"] == OrderStatus.PENDING, (
            f"{label}.status: expected {OrderStatus.PENDING}, got {order['status']!r}"
        )
        assert order["par_allotted_usd"] == 0, (
            f"{label}.par_allotted_usd: expected 0, got {order['par_allotted_usd']!r}"
        )


def _read_schedule(ctx):
    """Both maturities of the deal, in ``sequence_number`` order."""
    return [
        validate_success(
            ctx.client.get_maturity_tranche(tranche_id, ctx.compliance_headers), 200
        )
        for tranche_id in ctx.tranche_ids
    ]


def _assert_par_conserved(ctx, moment, first_allotted, first_unsold):
    """The par identity on both maturities plus the deal's rolled-up total.

    ``first_allotted`` and ``first_unsold`` pin the maturity the book was written
    against; the second maturity carries no orders at any moment, so it stands at
    zero allotted against its full principal throughout.
    """
    tranches = _read_schedule(ctx)
    deal = validate_success(
        ctx.client.get_deal(ctx.deal_id, ctx.compliance_headers), 200
    )
    for index, tranche in enumerate(tranches, start=1):
        assert_par_identity(tranche, f"tranche[{index}] {moment}")
    assert tranches[0]["par_allotted_usd"] == first_allotted, (
        f"tranche[1] {moment}.par_allotted_usd: expected {first_allotted}, "
        f"got {tranches[0]['par_allotted_usd']!r}"
    )
    assert tranches[0]["par_unsold_usd"] == first_unsold, (
        f"tranche[1] {moment}.par_unsold_usd: expected {first_unsold}, "
        f"got {tranches[0]['par_unsold_usd']!r}"
    )
    assert tranches[1]["par_allotted_usd"] == 0, (
        f"tranche[2] {moment}.par_allotted_usd: expected 0, "
        f"got {tranches[1]['par_allotted_usd']!r}"
    )
    assert tranches[1]["par_unsold_usd"] == WATERFALL_TRANCHE_PRINCIPAL_USD, (
        f"tranche[2] {moment}.par_unsold_usd: expected "
        f"{WATERFALL_TRANCHE_PRINCIPAL_USD}, got {tranches[1]['par_unsold_usd']!r}"
    )
    assert_deal_par_total(deal, tranches, f"deal {moment}")
    return tranches, deal


def _member_credits(ctx):
    """Every active seat's ``takedown_credit_usd``, keyed by member identifier."""
    rows, _meta = validate_paginated(
        ctx.client.list_deal_syndicate_members(ctx.deal_id, ctx.compliance_headers)
    )
    return {row["id"]: row["takedown_credit_usd"] for row in rows}


def _reopen(ctx):
    """The compensating action itself, taken by a ``ComplianceOfficer``."""
    return validate_success(
        ctx.client.reopen_order_period(
            ctx.period_id, f.reopen_payload(REOPEN_REASON), ctx.compliance_headers
        ),
        200,
    )


def _close(ctx):
    """Run the allotment again by closing the reopened book."""
    return validate_success(
        ctx.client.close_order_period(ctx.period_id, None, ctx.underwriter_headers),
        200,
    )


# ---------------------------------------------------------------------------
# A priced deal carrying a committed enhancement (PRD sections 3.3, 3.8)
# ---------------------------------------------------------------------------
def _priced_insured_negotiated_deal(client):
    """A PRICED negotiated deal whose first maturity is insured at forty-five bps.

    No shared fixture combines a committed enhancement with pricing, so the two
    are composed here from ``test_helpers.fixtures`` steps: the enhancement is
    committed while the deal sits in ``PRICING_NEGOTIATED``, which PRD section 3.3
    permits, and pricing then computes the premium into the money identity.
    """
    ctx = fx.negotiated_pricing_deal(client)
    proposal = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.tranche_ids[0]], ctx.advisor_headers
    )
    ctx.enhancement_id = proposal["id"]
    ctx.enhancement = fx.commit_enhancement(
        client, ctx.enhancement_id, ctx.issuer_headers
    )
    fx.cleared_disclosure(ctx)
    fx.with_completed_allotment_run(ctx)
    ctx.deal = fx.price_negotiated(client, ctx.deal_id, ctx.underwriter_headers)
    return ctx


# ---------------------------------------------------------------------------
# The par identity across a reopen (PRD section 3.7)
# ---------------------------------------------------------------------------
def test_first_allotment_run_fills_the_book_and_conserves_par(client, allotted_deal):
    """PRD 3.7: "Beyond the per-order writes, closing adds one to the period's
    `allotment_run_count`, recomputes `allotted_order_count` as the count of
    orders on the period whose `status` is `ALLOTTED` or `PARTIALLY_ALLOTTED`
    after this run, recomputes every touched tranche's `par_allotted_usd` and its
    `par_unsold_usd` as `principal_amount_usd` less `par_allotted_usd`, sets
    `Deal.par_allotted_total_usd` to the sum of `par_allotted_usd` across the
    deal's tranches, and increments both the period's and the deal's `version`."

    Design: Difficulty/compensating_invariant/order_period_reopen_conserves_tranche_par
    """
    ctx = allotted_deal

    _assert_worked_allotment(_orders_in_entry_order(ctx), "after the first close")
    _, deal = _assert_par_conserved(
        ctx, "after the first close", WATERFALL_TRANCHE_PRINCIPAL_USD, 0
    )
    assert deal["par_allotted_total_usd"] == WATERFALL_TRANCHE_PRINCIPAL_USD, (
        "deal after the first close.par_allotted_total_usd: expected "
        f"{WATERFALL_TRANCHE_PRINCIPAL_USD}, got {deal['par_allotted_total_usd']!r}"
    )

    period = validate_success(
        client.get_order_period(ctx.period_id, ctx.compliance_headers), 200
    )
    assert period["status"] == OrderPeriodStatus.CLOSED, (
        f"period.status: expected {OrderPeriodStatus.CLOSED}, "
        f"got {period['status']!r}"
    )
    assert period["allotment_run_count"] == 1, (
        f"period.allotment_run_count: expected 1, "
        f"got {period['allotment_run_count']!r}"
    )
    assert period["allotted_order_count"] == EXPECTED_ALLOTTED_ORDER_COUNT, (
        f"period.allotted_order_count: expected {EXPECTED_ALLOTTED_ORDER_COUNT}, "
        f"got {period['allotted_order_count']!r}"
    )


def test_reopen_voids_the_run_and_conserves_par(client, allotted_deal):
    """PRD 3.7: "The par identity is the acceptance test for this cascade: for
    every tranche, `par_allotted_usd` plus `par_unsold_usd` equals
    `principal_amount_usd` exactly, both before the reopen and after it, with no
    drift of a single dollar."

    Design: Difficulty/compensating_invariant/order_period_reopen_conserves_tranche_par
    """
    ctx = allotted_deal
    # The identity holds before the compensating action as well as after it.
    _assert_par_conserved(
        ctx, "before the reopen", WATERFALL_TRANCHE_PRINCIPAL_USD, 0
    )

    reopened = _reopen(ctx)
    assert reopened["status"] == OrderPeriodStatus.OPEN, (
        f"period after the reopen.status: expected {OrderPeriodStatus.OPEN}, "
        f"got {reopened['status']!r}"
    )
    assert reopened["reopen_reason"] == REOPEN_REASON, (
        "period after the reopen.reopen_reason: expected "
        f"{REOPEN_REASON!r}, got {reopened['reopen_reason']!r}"
    )
    # Hop four does not touch the cumulative run counter.
    assert reopened["allotment_run_count"] == 1, (
        "period after the reopen.allotment_run_count: expected 1, "
        f"got {reopened['allotment_run_count']!r}"
    )

    _assert_book_voided(_orders_in_entry_order(ctx), "after the reopen")
    _, deal = _assert_par_conserved(
        ctx, "after the reopen", 0, WATERFALL_TRANCHE_PRINCIPAL_USD
    )
    assert deal["par_allotted_total_usd"] == 0, (
        "deal after the reopen.par_allotted_total_usd: expected 0, "
        f"got {deal['par_allotted_total_usd']!r}"
    )


def test_second_close_reproduces_the_allotment_exactly(client, allotted_deal):
    """PRD 2.9: "The **par identity** states that for every maturity tranche,
    `par_allotted_usd` plus `par_unsold_usd` equals `principal_amount_usd`, and
    that `Deal.par_allotted_total_usd` equals the sum of `par_allotted_usd` across
    the deal's tranches. Running an allotment, reopening a closed order period,
    cancelling an order, and cancelling the deal all disturb these terms; each
    must restore the identity exactly, with zero drift."

    Design: Difficulty/compensating_invariant/order_period_reopen_conserves_tranche_par
    """
    ctx = allotted_deal
    _reopen(ctx)

    period = _close(ctx)
    assert period["status"] == OrderPeriodStatus.CLOSED, (
        f"period after the second close.status: expected "
        f"{OrderPeriodStatus.CLOSED}, got {period['status']!r}"
    )
    # The counter is cumulative, so a second run reads two rather than one.
    assert period["allotment_run_count"] == 2, (
        "period after the second close.allotment_run_count: expected 2, "
        f"got {period['allotment_run_count']!r}"
    )
    assert period["allotted_order_count"] == EXPECTED_ALLOTTED_ORDER_COUNT, (
        "period after the second close.allotted_order_count: expected "
        f"{EXPECTED_ALLOTTED_ORDER_COUNT}, got {period['allotted_order_count']!r}"
    )

    # The reversal was exact, not merely balanced: the same four figures return.
    _assert_worked_allotment(_orders_in_entry_order(ctx), "after the second close")
    _assert_par_conserved(
        ctx, "after the second close", WATERFALL_TRANCHE_PRINCIPAL_USD, 0
    )


def test_takedown_credits_stay_zero_across_the_reopen(client, allotted_deal):
    """PRD 3.8: "Orders that are `PENDING`, `UNFILLED`, or `CANCELLED` contribute
    zero."

    Design: Difficulty/compensating_invariant/order_period_reopen_conserves_tranche_par
    """
    ctx = allotted_deal
    seated = {member["id"] for member in ctx.members}
    expected = {member_id: 0.00 for member_id in seated}

    def _assert_credits(moment):
        credits = _member_credits(ctx)
        assert set(credits) == seated, (
            f"the syndicate {moment} should hold exactly the two seated members; "
            f"expected {sorted(seated)}, got {sorted(credits)}"
        )
        for member_id, credit in credits.items():
            assert_money(
                credit, expected[member_id], f"member[{member_id}] {moment}"
            )

    # Closing the book does not write takedown credits, so they stand at the
    # zero every seat is created with.
    _assert_credits("after the first close")
    _reopen(ctx)
    # Hop four recomputes them, and every order is PENDING again.
    _assert_credits("after the reopen")
    _close(ctx)
    _assert_credits("after the second close")


# ---------------------------------------------------------------------------
# The money identity across an enhancement withdrawal (PRD sections 2.9, 3.3)
# ---------------------------------------------------------------------------
def test_priced_insured_deal_decomposes_its_proceeds_exactly(client):
    """PRD 2.9: "The **money identity** states that a priced deal's aggregate
    reoffering proceeds decompose exactly: `issue_price_total_usd` equals
    `net_proceeds_to_issuer_usd` plus `gross_spread_total_usd` plus
    `credit_enhancement_premium_usd`."

    Design: Difficulty/compensating_invariant/enhancement_withdraw_conserves_issue_price_identity
    """
    ctx = _priced_insured_negotiated_deal(client)
    deal = validate_success(client.get_deal(ctx.deal_id, ctx.compliance_headers), 200)

    assert_money(
        deal["issue_price_total_usd"],
        CANONICAL_ISSUE_PRICE_TOTAL_USD,
        "deal before the withdrawal.issue_price_total_usd",
    )
    assert_money(
        deal["gross_spread_total_usd"],
        NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
        "deal before the withdrawal.gross_spread_total_usd",
    )
    assert_money(
        deal["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "deal before the withdrawal.credit_enhancement_premium_usd",
    )
    assert_money(
        deal["net_proceeds_to_issuer_usd"],
        NEGOTIATED_NET_PROCEEDS_INSURED_USD,
        "deal before the withdrawal.net_proceeds_to_issuer_usd",
    )
    # 10,590,450.00 + 87,500.00 + 33,750.00 == 10,711,700.00, exactly.
    assert_money_identity(deal, "deal before the withdrawal")


def test_withdrawal_moves_the_premium_into_net_proceeds_without_drift(client):
    """PRD 3.3: "Where a deal was priced with a premium of 33,750.00 against
    proceeds of 10,711,700.00 and a spread of 87,500.00, withdrawal restores net
    proceeds of 10,624,200.00 — the money identity holds before and after with no
    drift."

    Design: Difficulty/compensating_invariant/enhancement_withdraw_conserves_issue_price_identity
    """
    ctx = _priced_insured_negotiated_deal(client)
    before = validate_success(
        client.get_deal(ctx.deal_id, ctx.compliance_headers), 200
    )
    assert_money_identity(before, "deal before the withdrawal")

    withdrawn = validate_success(
        client.withdraw_credit_enhancement(
            ctx.enhancement_id, f.withdraw_payload(WITHDRAWAL_REASON), ctx.issuer_headers
        ),
        200,
    )
    assert withdrawn["status"] == EnhancementStatus.WITHDRAWN, (
        f"enhancement.status: expected {EnhancementStatus.WITHDRAWN}, "
        f"got {withdrawn['status']!r}"
    )

    after = validate_success(client.get_deal(ctx.deal_id, ctx.compliance_headers), 200)
    assert_money(
        after["credit_enhancement_premium_usd"],
        0.00,
        "deal after the withdrawal.credit_enhancement_premium_usd",
    )
    assert_money(
        after["net_proceeds_to_issuer_usd"],
        NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
        "deal after the withdrawal.net_proceeds_to_issuer_usd",
    )
    # The two untouched terms are byte-for-byte what they were before the hop.
    assert after["issue_price_total_usd"] == before["issue_price_total_usd"], (
        "deal after the withdrawal.issue_price_total_usd: expected the unchanged "
        f"{before['issue_price_total_usd']!r}, got {after['issue_price_total_usd']!r}"
    )
    assert after["gross_spread_total_usd"] == before["gross_spread_total_usd"], (
        "deal after the withdrawal.gross_spread_total_usd: expected the unchanged "
        f"{before['gross_spread_total_usd']!r}, got {after['gross_spread_total_usd']!r}"
    )
    # 10,624,200.00 + 87,500.00 + 0.00 == 10,711,700.00: the same total at a
    # different split.
    assert_money_identity(after, "deal after the withdrawal")

    # Withdrawal is not a repricing: neither the arbitrage yield nor the deal's
    # own state moves.
    assert_yield_value(
        after["arbitrage_yield_pct"],
        CANONICAL_ARBITRAGE_YIELD_PCT,
        "deal after the withdrawal.arbitrage_yield_pct",
    )
    assert after["status"] == DealStatus.PRICED, (
        f"deal after the withdrawal.status: expected {DealStatus.PRICED}, "
        f"got {after['status']!r}"
    )


def test_withdrawal_returns_the_insured_maturity_to_its_underlying_rating(client):
    """PRD 3.3: "In the second hop, caused by the first, every maturity named in
    `insured_tranche_ids` whose `is_insured` is true has that flag set back to
    false and its `rating_basis` returned to `UNDERLYING`."

    Design: Difficulty/compensating_invariant/enhancement_withdraw_conserves_issue_price_identity
    """
    ctx = _priced_insured_negotiated_deal(client)
    insured_id = ctx.tranche_ids[0]
    insured_before = validate_success(
        client.get_maturity_tranche(insured_id, ctx.compliance_headers), 200
    )
    assert insured_before["is_insured"] is True, (
        "tranche[1] before the withdrawal.is_insured: expected true, "
        f"got {insured_before['is_insured']!r}"
    )

    validate_success(
        client.withdraw_credit_enhancement(
            ctx.enhancement_id, f.withdraw_payload(WITHDRAWAL_REASON), ctx.issuer_headers
        ),
        200,
    )

    insured_after = validate_success(
        client.get_maturity_tranche(insured_id, ctx.compliance_headers), 200
    )
    assert insured_after["is_insured"] is False, (
        "tranche[1] after the withdrawal.is_insured: expected false, "
        f"got {insured_after['is_insured']!r}"
    )
    assert insured_after["rating_basis"] == RatingBasis.UNDERLYING, (
        f"tranche[1] after the withdrawal.rating_basis: expected "
        f"{RatingBasis.UNDERLYING}, got {insured_after['rating_basis']!r}"
    )

    rows, _meta = validate_paginated(
        client.list_deal_credit_enhancements(ctx.deal_id, ctx.compliance_headers)
    )
    enhancements = {row["id"]: row for row in rows}
    assert ctx.enhancement_id in enhancements, (
        "the withdrawn enhancement should still be listed under its deal; "
        f"expected {ctx.enhancement_id!r} among {sorted(enhancements)}"
    )
    listed = enhancements[ctx.enhancement_id]
    assert listed["status"] == EnhancementStatus.WITHDRAWN, (
        f"enhancement.status: expected {EnhancementStatus.WITHDRAWN}, "
        f"got {listed['status']!r}"
    )
    assert listed["withdrawal_reason"] == WITHDRAWAL_REASON, (
        f"enhancement.withdrawal_reason: expected {WITHDRAWAL_REASON!r}, "
        f"got {listed['withdrawal_reason']!r}"
    )
    assert listed["enhanced_rating"] is None, (
        "enhancement.enhanced_rating: expected null after the withdrawal, "
        f"got {listed['enhanced_rating']!r}"
    )
