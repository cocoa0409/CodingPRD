"""Cross-cutting complexity layers and the consistency model.

Every test in this module translates exactly one instance of the CORNER design
index (``SCAFFOLD_CORNER_DESIGN.yaml``), drawn from its last two sections:

* ``cross-cutting complexity layers`` -- the two optimistic-concurrency guards of
  PRD section 2.7 (``expected_deal_version`` on official-statement creation and
  ``expected_order_period_version`` on order entry), and the pair of branch flags
  that ``designate-sale-method`` writes.
* ``consistency model`` -- PRD section 2.2's promise that a writing response
  already carries every computed field, and PRD section 2.9's promise that a
  cascade is visible to a read issued immediately afterwards with the logical
  clock left untouched.

No test in this module advances the logical clock after a trigger, because the
claim under test in the consistency-model section is precisely that no advance is
needed. Setup is delegated to ``test_helpers.fixtures``, and every URL, enum
literal, error id and pinned figure comes from ``test_helpers``.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers import make_advisor_headers, make_issuer_official_headers
from test_helpers.api_errors import (
    ERR_ORDER_TYPE_NOT_PERMITTED,
    ERR_STALE_DEAL_VERSION,
    ERR_STALE_ORDER_PERIOD_VERSION,
)
from test_helpers.assertions import (
    assert_common_fields,
    assert_money,
    assert_money_identity,
    assert_pagination,
    assert_price,
    assert_timestamps_equal,
    assert_yield_value,
    expected_risk_score,
    ids_of,
)
from test_helpers.constants import (
    CANONICAL_ARBITRAGE_YIELD_PCT,
    CANONICAL_ISSUE_PRICE_TOTAL_USD,
    CANONICAL_TRANCHE_PRINCIPAL_USD,
    CLOCK_EPOCH,
    ENHANCEMENT_PREMIUM_USD,
    NEGOTIATED_GROSS_SPREAD_PER_BOND_USD,
    NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
    NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
    TRANCHE_1_PERIODS,
    TRANCHE_1_PRICE_TO_MATURITY_PCT,
    TRANCHE_1_REOFFERING_PRICE_PCT,
    plus_days,
    plus_hours,
)
from test_helpers.types import (
    DealStatus,
    EnhancementStatus,
    EntityType,
    GrossSpreadBasis,
    MemberRole,
    OfficialStatementStatus,
    OrderStatus,
    OrderType,
    PeriodType,
    RatingBasis,
    SaleMethod,
)

# The order-entry instance runs its book on 2026-08-05T14:00, four days and
# fourteen hours after the logical clock's start instant of PRD section 2.4.
ORDER_CLOCK = plus_hours(plus_days(CLOCK_EPOCH, 4), 14)
ORDER_PERIOD_CLOSES_AT = plus_hours(ORDER_CLOCK, 8)

FIRST_ORDER_PAR_USD = 2000000
SECOND_ORDER_PAR_USD = 1000000
ORDER_PRICE_PCT = 4.250

WITHDRAWAL_REASON = "Provider downgraded before pricing."


# ---------------------------------------------------------------------------
# Module-local read helpers
# ---------------------------------------------------------------------------
def _read_deal(ctx, deal_id=None):
    return get_success_data(
        ctx.client.get_deal(deal_id or ctx.deal_id, ctx.compliance_headers), 200
    )


def _read_statement(ctx, statement_id):
    return get_success_data(
        ctx.client.get_official_statement(statement_id, ctx.compliance_headers), 200
    )


def _read_tranche(ctx, tranche_id):
    return get_success_data(
        ctx.client.get_maturity_tranche(tranche_id, ctx.compliance_headers), 200
    )


def _list_statements(ctx):
    return validate_paginated(
        ctx.client.list_deal_official_statements(ctx.deal_id, ctx.compliance_headers)
    )


def _list_orders(ctx, period_id):
    return validate_paginated(
        ctx.client.list_period_orders(period_id, ctx.underwriter_headers)
    )


# ---------------------------------------------------------------------------
# Corner/cross-cutting complexity layers
# / stale_deal_version_is_rejected_on_official_statement_create
# ---------------------------------------------------------------------------
def test_second_official_statement_create_reusing_the_same_deal_token_is_refused(
    draft_deal,
):
    """PRD 2.7: "Starting a new official statement on a deal requires
    `expected_deal_version` as a mandatory body field carrying the `version` the
    client last observed on that `Deal`. If it does not equal the deal's current
    `version`, the request is rejected with `ERR_STALE_DEAL_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_deal_version_is_rejected_on_official_statement_create
    """
    ctx = draft_deal
    deal_v0 = _read_deal(ctx)["version"]

    first = validate_success(
        ctx.client.create_official_statement(
            ctx.deal_id, f.official_statement_payload(deal_v0), ctx.counsel_headers
        ),
        201,
    )
    assert_common_fields(first, "official_statement")
    assert first["status"] == OfficialStatementStatus.DRAFTING, (
        f"a new statement starts in DRAFTING, got {first['status']!r}"
    )
    assert first["draft_round"] == 1, (
        f"a new statement starts at draft_round 1, got {first['draft_round']!r}"
    )

    # The first create incremented Deal.version, so the same token is now stale.
    stale = ctx.client.create_official_statement(
        ctx.deal_id, f.official_statement_payload(deal_v0), ctx.counsel_headers
    )
    validate_error(stale, ERR_STALE_DEAL_VERSION)

    # The refusal must have superseded nothing: exactly one statement survives and
    # it is still the DRAFTING first one.
    rows, meta = _list_statements(ctx)
    assert_pagination(meta, total_count=1)
    assert ids_of(rows) == [first["id"]], (
        f"the refused create must not have written a row: {ids_of(rows)}"
    )
    assert _read_statement(ctx, first["id"])["status"] == (
        OfficialStatementStatus.DRAFTING
    ), "the 412 must leave the first statement in DRAFTING"


def test_retrying_the_create_with_the_refreshed_deal_token_supersedes_the_first(
    draft_deal,
):
    """PRD 3.4: "Creation also supersedes the predecessor: any earlier statement on
    the same deal whose `status` is `DRAFTING`, `IN_REVIEW`, or
    `REVISION_REQUESTED` is moved to the terminal `SUPERSEDED` state with its own
    `version` incremented."

    Design: Corner/cross-cutting complexity layers/stale_deal_version_is_rejected_on_official_statement_create
    """
    ctx = draft_deal
    deal_v0 = _read_deal(ctx)["version"]

    first = validate_success(
        ctx.client.create_official_statement(
            ctx.deal_id, f.official_statement_payload(deal_v0), ctx.counsel_headers
        ),
        201,
    )
    validate_error(
        ctx.client.create_official_statement(
            ctx.deal_id, f.official_statement_payload(deal_v0), ctx.counsel_headers
        ),
        ERR_STALE_DEAL_VERSION,
    )

    deal_v1 = _read_deal(ctx)["version"]
    assert deal_v1 > deal_v0, (
        f"the accepted create must have advanced Deal.version past {deal_v0}, "
        f"got {deal_v1}"
    )

    second = validate_success(
        ctx.client.create_official_statement(
            ctx.deal_id, f.official_statement_payload(deal_v1), ctx.counsel_headers
        ),
        201,
    )
    assert second["status"] == OfficialStatementStatus.DRAFTING, (
        f"the retried create starts in DRAFTING, got {second['status']!r}"
    )
    assert _read_statement(ctx, first["id"])["status"] == (
        OfficialStatementStatus.SUPERSEDED
    ), "the accepted retry supersedes the predecessor it did see"

    rows, meta = _list_statements(ctx)
    assert_pagination(meta, total_count=2)


# ---------------------------------------------------------------------------
# Corner/cross-cutting complexity layers
# / stale_order_period_version_is_rejected_on_order_entry
# ---------------------------------------------------------------------------
def _open_institutional_book(client):
    """A negotiated deal whose INSTITUTIONAL order period is OPEN on the clock.

    PRD section 3.7 opens a book only while the deal sits on a pricing branch and
    the logical clock lies inside the window, so the clock is moved to the
    window's own opening instant before the book is opened -- and never again, so
    every ``submitted_at`` the test reads is that same instant.
    """
    ctx = fx.negotiated_pricing_deal(client)
    fx.set_clock(client, ORDER_CLOCK)
    period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(
            ORDER_CLOCK, ORDER_PERIOD_CLOSES_AT, PeriodType.INSTITUTIONAL
        ),
    )
    ctx.period_id = period["id"]
    ctx.period = fx.open_period(client, ctx.period_id, ctx.underwriter_headers)
    return ctx


def _order_payload(ctx, token, order_type=OrderType.INSTITUTIONAL_PRIORITY,
                   par_requested_usd=FIRST_ORDER_PAR_USD):
    return f.order_payload(
        ctx.tranche_ids[0],
        ctx.senior_member["id"],
        token,
        order_type,
        par_requested_usd,
        price_or_yield_pct=ORDER_PRICE_PCT,
    )


def test_second_order_reusing_the_first_orders_period_token_is_refused(client):
    """PRD 2.7: "Entering an order into an order period requires
    `expected_order_period_version` as a mandatory body field carrying the
    `version` the client last observed on that `OrderPeriod`. If it does not equal
    the period's current `version`, the request is rejected with
    `ERR_STALE_ORDER_PERIOD_VERSION` (HTTP 412)."

    Design: Corner/cross-cutting complexity layers/stale_order_period_version_is_rejected_on_order_entry
    """
    ctx = _open_institutional_book(client)
    op_v0 = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)["version"]

    first = validate_success(
        client.create_order(
            ctx.period_id, _order_payload(ctx, op_v0), ctx.underwriter_headers
        ),
        201,
    )
    assert_common_fields(first, "order")
    assert first["status"] == OrderStatus.PENDING, (
        f"a new order starts PENDING, got {first['status']!r}"
    )
    assert_money(first["par_allotted_usd"], 0, "order.par_allotted_usd")
    assert_timestamps_equal(first["submitted_at"], ORDER_CLOCK, "order.submitted_at")

    # Every business field below is valid; only the token is stale.
    stale = client.create_order(
        ctx.period_id,
        _order_payload(ctx, op_v0, par_requested_usd=SECOND_ORDER_PAR_USD),
        ctx.underwriter_headers,
    )
    validate_error(stale, ERR_STALE_ORDER_PERIOD_VERSION)

    rows, meta = _list_orders(ctx, ctx.period_id)
    assert_pagination(meta, total_count=1)
    assert ids_of(rows) == [first["id"]], (
        f"the refused order must not have joined the book: {ids_of(rows)}"
    )
    period = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)
    assert period["orders_received_count"] == 1, (
        "orders_received_count must stay at 1 across the refusal, got "
        f"{period['orders_received_count']!r}"
    )


def test_stale_period_token_outranks_the_forbidden_order_type_rule(client):
    """PRD 2.5: "When two conditions in a single request are both unsatisfied, the
    response always carries the error of the lower-numbered tier; a caller cannot
    observe the later failure until the earlier one is fixed."

    Design: Corner/cross-cutting complexity layers/stale_order_period_version_is_rejected_on_order_entry
    """
    ctx = _open_institutional_book(client)
    op_v0 = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)["version"]

    validate_success(
        client.create_order(
            ctx.period_id, _order_payload(ctx, op_v0), ctx.underwriter_headers
        ),
        201,
    )

    # A RETAIL order may only enter a RETAIL period (tier 15), and the token is
    # also stale (tier 10). Only the tier-10 refusal may be observed.
    both_wrong = client.create_order(
        ctx.period_id,
        _order_payload(
            ctx, op_v0, OrderType.RETAIL, par_requested_usd=SECOND_ORDER_PAR_USD
        ),
        ctx.underwriter_headers,
    )
    error = validate_error(both_wrong, ERR_STALE_ORDER_PERIOD_VERSION)
    assert error["error_id"] != ERR_ORDER_TYPE_NOT_PERMITTED, (
        "tier 10 optimistic concurrency precedes the tier 15 order-type rule"
    )

    op_v1 = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)["version"]
    assert op_v1 > op_v0, (
        f"the accepted order must have advanced OrderPeriod.version past {op_v0}, "
        f"got {op_v1}"
    )

    second = validate_success(
        client.create_order(
            ctx.period_id,
            _order_payload(ctx, op_v1, par_requested_usd=SECOND_ORDER_PAR_USD),
            ctx.underwriter_headers,
        ),
        201,
    )
    assert second["status"] == OrderStatus.PENDING, (
        f"the retried order starts PENDING, got {second['status']!r}"
    )
    period = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)
    assert period["orders_received_count"] == 2, (
        "the refreshed token admits the order, so orders_received_count is 2, got "
        f"{period['orders_received_count']!r}"
    )
    assert period["version"] > op_v1, (
        f"the second accepted order advances the period's version past {op_v1}, "
        f"got {period['version']!r}"
    )


# ---------------------------------------------------------------------------
# Corner/cross-cutting complexity layers
# / sale_method_designation_toggles_the_document_requirement_flags
# ---------------------------------------------------------------------------
def _structuring_deal_on(ctx):
    """Add one more STRUCTURING deal to ``ctx``'s issuer and return its identifier."""
    fx.structuring_deal(ctx.client, ctx)
    return ctx.deal_id


def _designate(ctx, deal_id, sale_method):
    return validate_success(
        ctx.client.designate_sale_method(
            deal_id, f.sale_method_payload(sale_method), ctx.advisor_headers
        ),
        200,
    )


def _assert_flags(deal, notice_of_sale, g17_letter, label="deal"):
    assert deal["requires_notice_of_sale"] is notice_of_sale, (
        f"{label}.requires_notice_of_sale: expected {notice_of_sale}, got "
        f"{deal['requires_notice_of_sale']!r}"
    )
    assert deal["requires_g17_letter"] is g17_letter, (
        f"{label}.requires_g17_letter: expected {g17_letter}, got "
        f"{deal['requires_g17_letter']!r}"
    )


def test_competitive_designation_raises_only_the_notice_of_sale_flag(participants):
    """PRD 3.6: "On success, `sale_method` and `gross_spread_basis` are both set to
    `COMPETITIVE`, `requires_notice_of_sale` is set to true, `requires_g17_letter`
    remains false, and the deal's `version` increments."

    Design: Corner/cross-cutting complexity layers/sale_method_designation_toggles_the_document_requirement_flags
    """
    ctx = participants
    deal_id = _structuring_deal_on(ctx)

    before = _read_deal(ctx, deal_id)
    _assert_flags(before, False, False, "deal before designation")
    assert before["sale_method"] == SaleMethod.UNDETERMINED, (
        f"an undesignated deal reads UNDETERMINED, got {before['sale_method']!r}"
    )

    after = _designate(ctx, deal_id, SaleMethod.COMPETITIVE)
    _assert_flags(after, True, False, "competitive deal")
    assert after["sale_method"] == SaleMethod.COMPETITIVE
    assert after["gross_spread_basis"] == GrossSpreadBasis.COMPETITIVE, (
        f"gross_spread_basis: expected COMPETITIVE, got {after['gross_spread_basis']!r}"
    )
    assert after["status"] == DealStatus.PRICING_COMPETITIVE, (
        f"status: expected PRICING_COMPETITIVE, got {after['status']!r}"
    )
    assert after["version"] > before["version"], (
        f"designation increments the deal's version past {before['version']}, "
        f"got {after['version']!r}"
    )
    _assert_flags(_read_deal(ctx, deal_id), True, False, "competitive deal on re-read")


def test_negotiated_designation_raises_only_the_g17_letter_flag(participants):
    """PRD 3.6: "On success, `sale_method` and `gross_spread_basis` are both set to
    `NEGOTIATED`, `requires_g17_letter` is set to true, `requires_notice_of_sale`
    remains false, and the deal's `version` increments."

    Design: Corner/cross-cutting complexity layers/sale_method_designation_toggles_the_document_requirement_flags
    """
    ctx = participants
    deal_id = _structuring_deal_on(ctx)
    fx.seat_member(
        ctx.client,
        deal_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
    )

    before = _read_deal(ctx, deal_id)
    _assert_flags(before, False, False, "deal before designation")

    after = _designate(ctx, deal_id, SaleMethod.NEGOTIATED)
    _assert_flags(after, False, True, "negotiated deal")
    assert after["sale_method"] == SaleMethod.NEGOTIATED
    assert after["gross_spread_basis"] == GrossSpreadBasis.NEGOTIATED, (
        f"gross_spread_basis: expected NEGOTIATED, got {after['gross_spread_basis']!r}"
    )
    assert after["status"] == DealStatus.PRICING_NEGOTIATED, (
        f"status: expected PRICING_NEGOTIATED, got {after['status']!r}"
    )
    assert after["version"] > before["version"], (
        f"designation increments the deal's version past {before['version']}, "
        f"got {after['version']!r}"
    )
    _assert_flags(_read_deal(ctx, deal_id), False, True, "negotiated deal on re-read")


def test_the_two_branches_disagree_on_both_flags_while_an_undesignated_deal_keeps_them_false(
    participants,
):
    """PRD 3.2: "Both branch flags, `requires_g17_letter` and
    `requires_notice_of_sale`, start false."

    Design: Corner/cross-cutting complexity layers/sale_method_designation_toggles_the_document_requirement_flags
    """
    ctx = participants
    competitive_id = _structuring_deal_on(ctx)
    negotiated_id = _structuring_deal_on(ctx)
    fx.seat_member(
        ctx.client,
        negotiated_id,
        ctx.underwriter_firm_id,
        ctx.underwriter_headers,
        MemberRole.SENIOR_MANAGER,
    )
    undesignated_id = _structuring_deal_on(ctx)

    for deal_id in (competitive_id, negotiated_id, undesignated_id):
        _assert_flags(_read_deal(ctx, deal_id), False, False, f"deal {deal_id}")

    competitive = _designate(ctx, competitive_id, SaleMethod.COMPETITIVE)
    negotiated = _designate(ctx, negotiated_id, SaleMethod.NEGOTIATED)

    # Neither flag is a constant: the two designated deals disagree on both.
    assert (
        competitive["requires_notice_of_sale"] != negotiated["requires_notice_of_sale"]
    ), "the branches must disagree on requires_notice_of_sale"
    assert competitive["requires_g17_letter"] != negotiated["requires_g17_letter"], (
        "the branches must disagree on requires_g17_letter"
    )

    # Absence of the fork means absence of both features.
    never_designated = _read_deal(ctx, undesignated_id)
    _assert_flags(never_designated, False, False, "never-designated deal")
    assert never_designated["sale_method"] == SaleMethod.UNDETERMINED, (
        f"a never-designated deal stays UNDETERMINED, got "
        f"{never_designated['sale_method']!r}"
    )
    assert never_designated["status"] == DealStatus.STRUCTURING, (
        f"a never-designated deal stays in STRUCTURING, got "
        f"{never_designated['status']!r}"
    )


# ---------------------------------------------------------------------------
# Corner/consistency model / computed_fields_are_visible_in_the_writing_response
# ---------------------------------------------------------------------------
TRANCHE_COMPUTED_FIELDS = (
    "periods_to_maturity",
    "price_to_maturity_pct",
    "price_to_call_pct",
    "reoffering_price_pct",
    "is_priced_to_call",
)

DEAL_MONEY_FIELDS = (
    "issue_price_total_usd",
    "gross_spread_total_usd",
    "gross_spread_per_bond_usd",
    "credit_enhancement_premium_usd",
    "net_proceeds_to_issuer_usd",
    "arbitrage_yield_pct",
)


def _assert_same_fields(write_body, read_body, fields, label="row"):
    """A writing response and a later read must agree field for field."""
    for field in fields:
        assert write_body[field] == read_body[field], (
            f"{label}.{field}: the create/transition response said "
            f"{write_body[field]!r} but the follow-up read said {read_body[field]!r}"
        )


def test_the_create_response_already_carries_the_issuer_score_and_the_tranche_prices(
    client, compliance
):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency model/computed_fields_are_visible_in_the_writing_response
    """
    # Layer one: the issuer's weighted score, in the POST /issuers response itself.
    issuer_payload = f.issuer_payload(
        entity_type=EntityType.AUTHORITY,
        prior_late_annual_filings=0,
        prior_late_event_notices=3,
        has_prior_material_event=False,
    )
    created_issuer = validate_success(client.create_issuer(issuer_payload, compliance), 201)
    assert_common_fields(created_issuer, "issuer")
    expected_score = expected_risk_score(
        EntityType.AUTHORITY,
        prior_late_annual_filings=0,
        prior_late_event_notices=3,
        has_prior_material_event=False,
    )
    assert created_issuer["disclosure_risk_score"] == expected_score, (
        "the create response must already carry the scored risk, expected "
        f"{expected_score}, got {created_issuer['disclosure_risk_score']!r}"
    )
    read_issuer = get_success_data(
        client.get_issuer(created_issuer["id"], compliance), 200
    )
    _assert_same_fields(
        created_issuer, read_issuer, ("disclosure_risk_score",), "issuer"
    )

    # Layer two: the maturity's price variants, in the POST /maturity-tranches
    # response itself.
    advisor_firm = fx.register_advisor_firm(client)
    advisor_headers = make_advisor_headers(advisor_firm["id"])
    deal = fx.create_deal(
        client,
        created_issuer["id"],
        advisor_firm["id"],
        make_issuer_official_headers(created_issuer["id"]),
        expected_par_amount_usd=CANONICAL_TRANCHE_PRINCIPAL_USD,
    )
    created_tranche = validate_success(
        client.create_maturity_tranche(
            deal["id"], f.canonical_tranche_1_payload(), advisor_headers
        ),
        201,
    )
    assert_common_fields(created_tranche, "maturity_tranche")
    assert created_tranche["periods_to_maturity"] == TRANCHE_1_PERIODS, (
        f"periods_to_maturity: expected {TRANCHE_1_PERIODS}, got "
        f"{created_tranche['periods_to_maturity']!r}"
    )
    assert_price(
        created_tranche["price_to_maturity_pct"],
        TRANCHE_1_PRICE_TO_MATURITY_PCT,
        "tranche.price_to_maturity_pct",
    )
    assert created_tranche["price_to_call_pct"] is None, (
        "a non-callable maturity has no call price, got "
        f"{created_tranche['price_to_call_pct']!r}"
    )
    assert_price(
        created_tranche["reoffering_price_pct"],
        TRANCHE_1_REOFFERING_PRICE_PCT,
        "tranche.reoffering_price_pct",
    )
    assert created_tranche["is_priced_to_call"] is False, (
        "a non-callable maturity is never priced to the call, got "
        f"{created_tranche['is_priced_to_call']!r}"
    )

    read_tranche = get_success_data(
        client.get_maturity_tranche(created_tranche["id"], compliance), 200
    )
    _assert_same_fields(
        created_tranche, read_tranche, TRANCHE_COMPUTED_FIELDS, "maturity_tranche"
    )


def test_the_pricing_response_already_carries_the_whole_money_set(
    priced_negotiated_deal,
):
    """PRD 2.2: "Unless otherwise noted, operations that create or modify a resource
    will return the created or updated resource object in the data field."

    Design: Corner/consistency model/computed_fields_are_visible_in_the_writing_response
    """
    ctx = priced_negotiated_deal
    priced = ctx.deal  # the body of the POST /price call itself

    assert priced["status"] == DealStatus.PRICED, (
        f"the pricing response reports PRICED, got {priced['status']!r}"
    )
    assert_money(
        priced["issue_price_total_usd"],
        CANONICAL_ISSUE_PRICE_TOTAL_USD,
        "deal.issue_price_total_usd",
    )
    assert_money(
        priced["gross_spread_total_usd"],
        NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
        "deal.gross_spread_total_usd",
    )
    assert_price(
        priced["gross_spread_per_bond_usd"],
        NEGOTIATED_GROSS_SPREAD_PER_BOND_USD,
        "deal.gross_spread_per_bond_usd",
    )
    assert_money(
        priced["credit_enhancement_premium_usd"], 0, "deal.credit_enhancement_premium_usd"
    )
    assert_money(
        priced["net_proceeds_to_issuer_usd"],
        NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
        "deal.net_proceeds_to_issuer_usd",
    )
    assert_yield_value(
        priced["arbitrage_yield_pct"],
        CANONICAL_ARBITRAGE_YIELD_PCT,
        "deal.arbitrage_yield_pct",
    )
    assert_money_identity(priced, "pricing response")

    # Nothing was back-filled asynchronously: the follow-up read agrees exactly.
    read_back = _read_deal(ctx)
    _assert_same_fields(priced, read_back, DEAL_MONEY_FIELDS, "deal")
    assert_money_identity(read_back, "deal on re-read")


# ---------------------------------------------------------------------------
# Corner/consistency model / cascade_effects_are_visible_without_advancing_the_clock
# ---------------------------------------------------------------------------
def test_the_withdrawal_cascade_is_visible_to_the_very_next_read(structuring_deal):
    """PRD 2.9: "Where a transition's effects are described as hops, each hop is
    caused by the hop before it, and every hop is applied inside the same request
    that triggered the first one."

    Design: Corner/consistency model/cascade_effects_are_visible_without_advancing_the_clock
    """
    ctx = structuring_deal
    insured_tranche_id = ctx.tranche_ids[0]

    proposal = fx.propose_enhancement(
        ctx.client, ctx.deal_id, [insured_tranche_id], ctx.advisor_headers
    )
    enhancement = fx.commit_enhancement(ctx.client, proposal["id"], ctx.issuer_headers)
    assert enhancement["status"] == EnhancementStatus.COMMITTED

    # The commit cascade is itself already visible, with the clock still at the epoch.
    before = _read_tranche(ctx, insured_tranche_id)
    assert before["is_insured"] is True, (
        "the commit cascade must have reached the named maturity before any clock move"
    )
    assert before["rating_basis"] == RatingBasis.ENHANCED
    deal_before = _read_deal(ctx)
    assert_money(
        deal_before["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "deal.credit_enhancement_premium_usd after the commit",
    )

    # The trigger. From here to the end of the test the logical clock is untouched:
    # no set_clock call, no retry loop, no re-post.
    withdrawn = validate_success(
        ctx.client.withdraw_credit_enhancement(
            proposal["id"], f.withdraw_payload(WITHDRAWAL_REASON), ctx.issuer_headers
        ),
        200,
    )
    assert withdrawn["status"] == EnhancementStatus.WITHDRAWN
    assert withdrawn["enhanced_rating"] is None
    assert withdrawn["withdrawal_reason"] == WITHDRAWAL_REASON

    # Hop two, read immediately afterwards.
    after = _read_tranche(ctx, insured_tranche_id)
    assert after["is_insured"] is False, (
        "the withdrawal cascade must be settled by the next read, with no clock advance"
    )
    assert after["rating_basis"] == RatingBasis.UNDERLYING

    # Hop three, in the same uninterrupted sequence.
    deal_after = _read_deal(ctx)
    assert_money(
        deal_after["credit_enhancement_premium_usd"],
        0,
        "deal.credit_enhancement_premium_usd after the withdrawal",
    )
    # This deal is STRUCTURING, never PRICED, so the conditional proceeds
    # recomputation of hop three has no figure to settle on.
    assert deal_after["status"] == DealStatus.STRUCTURING
    assert deal_after["net_proceeds_to_issuer_usd"] is None
    assert deal_after["issue_price_total_usd"] is None
