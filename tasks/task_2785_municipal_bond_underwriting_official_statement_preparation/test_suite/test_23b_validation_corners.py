"""Validation corners, second half: disclosure gates, the book, and the money rules.

Each test below translates exactly one instance of the CORNER design index's
``validations`` section, and the ``Design:`` line of every docstring names the
instance it came from. Where one instance bundles several independent rules
under a single error id -- the three order-type placement rules of PRD section
3.7, the two-sided compensation-input rule of PRD section 3.8, the
never-waivable document pair of PRD section 3.9 -- the rules are split into one
test each and all of them carry that instance's tag.

The worlds are the conftest fixtures, so the money figures asserted here are the
PRD's own worked figures for the canonical two-tranche 10,000,000 issue rather
than the single-tranche arithmetic the design index happens to narrate.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLOSING_DOCS_INCOMPLETE,
    ERR_COMPENSATION_INPUT_MISSING,
    ERR_DEAL_INVALID_STATE,
    ERR_DISCLOSURE_NOT_CLEARED,
    ERR_ENHANCEMENT_ALREADY_COMMITTED,
    ERR_ENHANCEMENT_INVALID_STATE,
    ERR_LIABILITY_PCT_SUM_INVALID,
    ERR_MANDATORY_SECTION_NOT_APPROVED,
    ERR_ORDER_TYPE_NOT_PERMITTED,
    ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE,
    ERR_PREMIUM_EXCEEDS_PROCEEDS,
    ERR_PRESENTATION_REQUIRED,
    ERR_PRICING_PRECONDITION_UNMET,
    ERR_SIGNATORY_ROLE_INVALID,
    ERR_UNDERTAKING_NOT_ACTIVE,
)
from test_helpers.assertions import (
    assert_money,
    assert_money_identity,
    assert_price,
    assert_timestamps_equal,
    assert_yield_value,
    expected_negotiated_gross_spread,
    to_decimal,
)
from test_helpers.constants import (
    CANONICAL_ARBITRAGE_YIELD_PCT,
    CANONICAL_ISSUE_PRICE_TOTAL_USD,
    CLOCK_EPOCH,
    COMPETITIVE_WINNING_BID_PRICE_PCT,
    ENHANCEMENT_PREMIUM_USD,
    INSURED_DEBT_SERVICE_TRANCHE_1_USD,
    LIABILITY_PCT_TOTAL,
    MIN_DENOMINATION_USD,
    MIN_RECORD_RETENTION_YEARS,
    NEGOTIATED_EXPENSES_PER_BOND_USD,
    NEGOTIATED_GROSS_SPREAD_PER_BOND_USD,
    NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
    NEGOTIATED_MANAGEMENT_FEE_PER_BOND_USD,
    NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
    PREMIUM_BPS_MAX,
    TRANCHE_1_YIELD_PCT,
    plus_days,
    plus_hours,
)
from test_helpers.types import (
    DealStatus,
    DisclosureClearance,
    DocType,
    EnhancementStatus,
    EnhancementType,
    EngagementStatus,
    ExecutionStatus,
    HandoffStatus,
    MemberRole,
    MemberStatus,
    OfficialStatementStatus,
    OrderPeriodStatus,
    OrderStatus,
    OrderType,
    Outlook,
    PeriodType,
    PresentationStatus,
    PriorityPolicy,
    RatingBasis,
    SaleMethod,
    SectionType,
    UndertakingStatus,
)

# ---------------------------------------------------------------------------
# The design index's order-book day: 2026-08-05, four days past the clock epoch.
# A RETAIL_ONLY retail book runs 09:00Z to 12:00Z and a STANDARD_PRIORITY
# institutional book runs 13:00Z to 17:00Z, so the two windows never overlap
# (PRD section 3.7).
# ---------------------------------------------------------------------------
BOOK_DAY = plus_days(CLOCK_EPOCH, 4)
RETAIL_OPENS_AT = plus_hours(BOOK_DAY, 9)
RETAIL_CLOSES_AT = plus_hours(BOOK_DAY, 12)
CLOCK_INSIDE_RETAIL_WINDOW = plus_hours(BOOK_DAY, 10)
BOOK_OPENS_AT = plus_hours(BOOK_DAY, 13)
BOOK_CLOSES_AT = plus_hours(BOOK_DAY, 17)
CLOCK_INSIDE_BOOK_WINDOW = plus_hours(BOOK_DAY, 14)

# One order of 1,000,000 dollars: a whole multiple of the five-thousand-dollar
# minimum denomination, so PRD section 3.7's denomination rule is satisfied and
# the placement rules are the only live constraints.
ORDER_PAR_USD = 200 * MIN_DENOMINATION_USD

# The design index's presentation day: 2026-08-10, nine days past the epoch. The
# first slot is cancelled, the second runs 13:00Z to 15:00Z and is the one the
# clock later promotes to HELD (PRD section 3.5).
PRESENTATION_DAY = plus_days(CLOCK_EPOCH, 9)
CANCELLED_SLOT_STARTS_AT = plus_hours(PRESENTATION_DAY, 9)
CANCELLED_SLOT_ENDS_AT = plus_hours(PRESENTATION_DAY, 11)
BOOKED_SLOT_STARTS_AT = plus_hours(PRESENTATION_DAY, 13)
BOOKED_SLOT_ENDS_AT = plus_hours(PRESENTATION_DAY, 15)
ASSIGNED_RATING = "AA2"

# Syndicate shares: a senior manager at sixty percent leaves exactly forty, so
# an added seat of forty-five breaks the whole and one of forty lands on it
# (PRD section 3.6).
SENIOR_SEAT_PCT = 60.0000
OVERFLOWING_SEAT_PCT = 45.0000
EXACT_REMAINDER_PCT = 40.0000

# A fat-finger takedown: PRD section 3.8 declares no numeric range for
# ``takedown_per_bond_usd``, so 1100.000 is schema-valid and reaches the fiscal
# rule with a component total of 1103.750 per bond.
FAT_FINGER_TAKEDOWN_PER_BOND_USD = 1100.000
FAT_FINGER_COMPONENT_TOTAL_PER_BOND_USD = (
    FAT_FINGER_TAKEDOWN_PER_BOND_USD
    + NEGOTIATED_MANAGEMENT_FEE_PER_BOND_USD
    + NEGOTIATED_EXPENSES_PER_BOND_USD
)

# Five years of record retention: one below PRD section 3.9's floor of six, and
# schema-valid because the endpoint declares no range for the field.
BELOW_FLOOR_RETENTION_YEARS = MIN_RECORD_RETENTION_YEARS - 1

# The six closing documents a competitive award creates (PRD section 3.9).
COMPETITIVE_DOC_TYPES = frozenset(DocType.ALWAYS_CREATED) | {
    DocType.NOTICE_OF_SALE_CERTIFICATE
}


# ---------------------------------------------------------------------------
# Module-local world builders
# ---------------------------------------------------------------------------
def _statement_with_only_the_risk_factor_approved(ctx):
    """All four mandatory categories exist; only the material RISK_FACTOR is APPROVED.

    Three sections merely sit in DRAFT, which is what makes
    ``mandatory_sections_approved`` a test of approvals rather than of rows
    (PRD section 3.4).
    """
    fx.with_active_undertaking(ctx)
    fx.with_drafting_statement(ctx)
    ctx.sections = {
        SectionType.RISK_FACTOR: fx.add_section(
            ctx.client, ctx.statement_id, f.material_risk_section_payload()
        ),
        SectionType.TAX_MATTERS: fx.add_section(
            ctx.client, ctx.statement_id, f.section_payload(SectionType.TAX_MATTERS)
        ),
        SectionType.CONTINUING_DISCLOSURE: fx.add_section(
            ctx.client,
            ctx.statement_id,
            f.continuing_disclosure_risk_section_payload(),
        ),
        SectionType.UNDERWRITING: fx.add_section(
            ctx.client, ctx.statement_id, f.section_payload(SectionType.UNDERWRITING)
        ),
    }
    ctx.section_ids = {key: row["id"] for key, row in ctx.sections.items()}
    fx.approve_section(ctx.client, ctx.section_ids[SectionType.RISK_FACTOR])
    ctx.statement = fx.submit_for_review(ctx.client, ctx.statement_id)
    return ctx


def _read_statement(client, ctx):
    """Read the governing official statement under the deal's advisor."""
    return get_success_data(
        client.get_official_statement(ctx.statement_id, ctx.advisor_headers), 200
    )


def _second_seat_payload(firm_id, liability_pct, takedown_share_pct):
    """A CO_MANAGER seat at rank two, whose shares are the only thing under test."""
    return f.syndicate_member_payload(
        firm_id,
        MemberRole.CO_MANAGER,
        liability_pct=liability_pct,
        takedown_share_pct=takedown_share_pct,
        priority_rank=2,
    )


def _deal_with_a_sixty_percent_senior_manager(client, ctx):
    """Seat one ACTIVE SENIOR_MANAGER at 60.0000 of liability and of takedown."""
    ctx.senior_member = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.underwriter_firm_id,
        ctx.advisor_headers,
        MemberRole.SENIOR_MANAGER,
        liability_pct=SENIOR_SEAT_PCT,
        takedown_share_pct=SENIOR_SEAT_PCT,
        priority_rank=1,
    )
    ctx.members = [ctx.senior_member]
    ctx.member_ids = [ctx.senior_member["id"]]
    ctx.candidate_firm = fx.register_underwriter_firm(client)
    return ctx


def _active_share_sums(members):
    """The ACTIVE liability and takedown sums the fiscal bound of 3.6 is read from."""
    active = [m for m in members if m["status"] == MemberStatus.ACTIVE]
    return (
        sum(to_decimal(m["liability_pct"]) for m in active),
        sum(to_decimal(m["takedown_share_pct"]) for m in active),
    )


def _read_members(client, ctx, headers):
    members, meta = validate_paginated(
        client.list_deal_syndicate_members(ctx.deal_id, headers)
    )
    return members, meta


def _two_seat_negotiated_book(client, ctx):
    """A PRICING_NEGOTIATED deal with a senior manager, a selling-group seat and two books.

    The selling-group seat is the one PRD section 3.7 refuses ``MEMBER`` demand
    from, and the RETAIL_ONLY retail book is the one that refuses everything but
    ``RETAIL``.
    """
    _deal_with_a_sixty_percent_senior_manager(client, ctx)
    ctx.selling_group_member = fx.seat_member(
        client,
        ctx.deal_id,
        ctx.candidate_firm["id"],
        ctx.advisor_headers,
        MemberRole.SELLING_GROUP,
        liability_pct=EXACT_REMAINDER_PCT,
        takedown_share_pct=EXACT_REMAINDER_PCT,
        priority_rank=2,
    )
    ctx.members = [ctx.senior_member, ctx.selling_group_member]
    ctx.member_ids = [m["id"] for m in ctx.members]
    fx.submit_structure(client, ctx.deal_id, ctx.advisor_headers)
    ctx.deal = fx.designate_sale_method(
        client, ctx.deal_id, SaleMethod.NEGOTIATED, ctx.advisor_headers
    )
    ctx.retail_period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(
            RETAIL_OPENS_AT,
            RETAIL_CLOSES_AT,
            PeriodType.RETAIL,
            priority_policy=PriorityPolicy.RETAIL_ONLY,
        ),
    )
    ctx.institutional_period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(
            BOOK_OPENS_AT,
            BOOK_CLOSES_AT,
            PeriodType.INSTITUTIONAL,
            priority_policy=PriorityPolicy.STANDARD_PRIORITY,
        ),
    )
    return ctx


def _open_book(client, ctx, period_id, clock_instant):
    """Move the clock inside the window, open the book, and return its fresh read."""
    fx.set_clock(client, clock_instant)
    fx.open_period(client, period_id, ctx.underwriter_headers)
    return fx.read_period(client, period_id, ctx.underwriter_headers)


def _order_payload(ctx, period, order_type, member_id):
    """One well-formed order whose only questionable field is its ``order_type``."""
    return f.order_payload(
        ctx.tranche_ids[0],
        member_id,
        period["version"],
        order_type,
        ORDER_PAR_USD,
        price_or_yield_pct=TRANCHE_1_YIELD_PCT,
    )


def _committed_first_policy(client, ctx):
    """One COMMITTED bond insurance policy over tranche one, plus a PROPOSED second.

    The second proposal is priced at the inclusive upper bound of two hundred
    basis points, so its creation is legal and only its commitment is at issue
    (PRD section 3.3).
    """
    proposal = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.tranche_ids[0]], ctx.advisor_headers
    )
    ctx.first_enhancement = fx.commit_enhancement(
        client, proposal["id"], ctx.issuer_headers
    )
    ctx.second_enhancement = fx.propose_enhancement(
        client,
        ctx.deal_id,
        [ctx.tranche_ids[1]],
        ctx.advisor_headers,
        enhancement_type=EnhancementType.LETTER_OF_CREDIT,
        premium_bps=PREMIUM_BPS_MAX,
    )
    return ctx


def _enhancements_by_id(client, ctx, headers):
    rows, meta = validate_paginated(
        client.list_deal_credit_enhancements(ctx.deal_id, headers)
    )
    return {row["id"]: row for row in rows}, meta


def _read_tranche(client, ctx, index):
    return get_success_data(
        client.get_maturity_tranche(ctx.tranche_ids[index], ctx.advisor_headers), 200
    )


def _priceable_but_unposted(client, ctx):
    """Every pricing precondition met except the preliminary posting itself.

    The statement stops at IN_REVIEW with all four mandatory categories approved
    and one CLOSED period carries a completed allotment run, so PRD section
    3.8's two disclosure preconditions are the only unsatisfied ones.
    """
    fx.with_active_undertaking(ctx)
    fx.with_statement_in_review(ctx)
    fx.with_completed_allotment_run(ctx)
    return ctx


def _fully_priceable_negotiated(client, ctx):
    """A PRICING_NEGOTIATED deal on which only the compensation inputs remain."""
    fx.cleared_disclosure(ctx)
    fx.with_completed_allotment_run(ctx)
    return ctx


def _negotiated_payload_without_expenses():
    """The negotiated set minus ``expenses_per_bond_usd``: an omission, not a typo."""
    payload = f.negotiated_pricing_payload()
    payload.pop("expenses_per_bond_usd")
    return payload


def _closable_competitive_deal(client, ctx, compliance_headers):
    """An AWARDED competitive deal whose two higher-priority close gates are met.

    PRD section 3.9 orders the close gates so that a FINAL_POSTED statement and a
    READY handoff must be satisfied before the document sweep is observable.
    """
    fx.with_final_statement(ctx)
    fx.complete_handoff(client, ctx.deal_id)
    ctx.documents = fx.documents_by_type(client, ctx.deal_id, compliance_headers)
    return ctx


# ---------------------------------------------------------------------------
# Posting the preliminary official statement (PRD section 3.4)
# ---------------------------------------------------------------------------
def test_preliminary_posting_requires_all_four_mandatory_categories(
    client, competitive_deal
):
    """PRD section 3.4: "First, `mandatory_sections_approved` must be true, or the request is refused with `ERR_MANDATORY_SECTION_NOT_APPROVED`."

    Design: Corner/validations/preliminary_posting_requires_the_four_mandatory_section_types
    """
    ctx = _statement_with_only_the_risk_factor_approved(competitive_deal)
    assert ctx.deal["status"] == DealStatus.PRICING_COMPETITIVE
    assert ctx.statement["status"] == OfficialStatementStatus.IN_REVIEW
    assert ctx.statement["mandatory_sections_approved"] is False

    # All four categories are present as rows; three are merely unapproved.
    assert set(ctx.section_ids) == set(SectionType.MANDATORY)

    response = client.post_preliminary(ctx.statement_id, None, ctx.advisor_headers)
    validate_error(response, ERR_MANDATORY_SECTION_NOT_APPROVED)

    refused = _read_statement(client, ctx)
    assert refused["status"] == OfficialStatementStatus.IN_REVIEW
    assert refused["mandatory_sections_approved"] is False
    assert refused["posted_preliminary_at"] is None
    blocked_deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert blocked_deal["disclosure_clearance"] != DisclosureClearance.CLEARED

    for section_type in (
        SectionType.TAX_MATTERS,
        SectionType.CONTINUING_DISCLOSURE,
        SectionType.UNDERWRITING,
    ):
        fx.approve_section(client, ctx.section_ids[section_type])

    posted = fx.post_preliminary(client, ctx.statement_id, ctx.advisor_headers)
    assert posted["status"] == OfficialStatementStatus.PRELIMINARY_POSTED
    assert posted["mandatory_sections_approved"] is True
    cleared_deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert cleared_deal["disclosure_clearance"] == DisclosureClearance.CLEARED


def test_preliminary_posting_requires_an_active_undertaking(client, competitive_deal):
    """PRD section 3.4: "Second, the deal must carry a continuing disclosure undertaking whose `status` is `ACTIVE`, or it is refused with `ERR_UNDERTAKING_NOT_ACTIVE`."

    Design: Corner/validations/preliminary_posting_requires_an_active_undertaking
    """
    ctx = competitive_deal
    undertaking = fx.draft_undertaking(client, ctx.deal_id, ctx.advisor_headers)
    assert undertaking["status"] == UndertakingStatus.DRAFT

    fx.with_statement_in_review(ctx)
    assert ctx.statement["status"] == OfficialStatementStatus.IN_REVIEW
    assert ctx.statement["mandatory_sections_approved"] is True

    # The undertaking row exists, so only its status can be the defect, and the
    # earlier gate at the same tier is already satisfied.
    response = client.post_preliminary(ctx.statement_id, None, ctx.advisor_headers)
    error = validate_error(response, ERR_UNDERTAKING_NOT_ACTIVE)
    assert error["error_id"] != ERR_MANDATORY_SECTION_NOT_APPROVED

    refused = _read_statement(client, ctx)
    assert refused["status"] == OfficialStatementStatus.IN_REVIEW
    assert refused["mandatory_sections_approved"] is True
    assert refused["posted_preliminary_at"] is None

    activated = fx.activate_undertaking(client, undertaking["id"], ctx.issuer_headers)
    assert activated["status"] == UndertakingStatus.ACTIVE

    posted = fx.post_preliminary(client, ctx.statement_id, ctx.advisor_headers)
    assert posted["status"] == OfficialStatementStatus.PRELIMINARY_POSTED
    assert_timestamps_equal(
        posted["posted_preliminary_at"], CLOCK_EPOCH, "posted_preliminary_at"
    )


# ---------------------------------------------------------------------------
# Rating assignment (PRD section 3.5)
# ---------------------------------------------------------------------------
def test_rating_assignment_requires_a_presentation_that_was_held(
    client, draft_deal, analyst
):
    """PRD section 3.5: "An analyst who tries to rate an issue on which no presentation has actually taken place is refused with `ERR_PRESENTATION_REQUIRED`."

    Design: Corner/validations/rating_assignment_requires_a_presentation_that_was_actually_held
    """
    ctx = fx.acknowledged_engagement(draft_deal)
    assert ctx.engagement["status"] == EngagementStatus.UNDER_REVIEW

    cancelled = fx.schedule_presentation(
        client,
        ctx.engagement_id,
        ctx.advisor_headers,
        CANCELLED_SLOT_STARTS_AT,
        CANCELLED_SLOT_ENDS_AT,
    )
    fx.cancel_presentation(
        client, cancelled["id"], ctx.advisor_headers, "Agency rescheduled the session."
    )
    booked = fx.schedule_presentation(
        client,
        ctx.engagement_id,
        ctx.advisor_headers,
        BOOKED_SLOT_STARTS_AT,
        BOOKED_SLOT_ENDS_AT,
    )
    assert booked["status"] == PresentationStatus.SCHEDULED

    response = client.assign_rating(
        ctx.engagement_id, f.assign_rating_payload(ASSIGNED_RATING, Outlook.STABLE), analyst
    )
    validate_error(response, ERR_PRESENTATION_REQUIRED)

    still_booked = get_success_data(
        client.get_presentation(booked["id"], ctx.advisor_headers), 200
    )
    assert still_booked["status"] == PresentationStatus.SCHEDULED
    unrated = get_success_data(
        client.get_rating_engagement(ctx.engagement_id, ctx.advisor_headers), 200
    )
    assert unrated["status"] == EngagementStatus.UNDER_REVIEW
    assert unrated["assigned_rating"] is None

    # The clock crossing ``ends_at`` promotes the booked slot and leaves the
    # cancelled one alone: a CANCELLED slot never satisfies the rule.
    fx.set_clock(client, BOOKED_SLOT_ENDS_AT)
    promoted = get_success_data(
        client.get_presentation(booked["id"], ctx.advisor_headers), 200
    )
    assert promoted["status"] == PresentationStatus.HELD
    untouched = get_success_data(
        client.get_presentation(cancelled["id"], ctx.advisor_headers), 200
    )
    assert untouched["status"] == PresentationStatus.CANCELLED

    rated = get_success_data(
        client.assign_rating(
            ctx.engagement_id,
            f.assign_rating_payload(ASSIGNED_RATING, Outlook.STABLE),
            analyst,
        ),
        200,
    )
    assert rated["status"] == EngagementStatus.RATED
    assert rated["assigned_rating"] == ASSIGNED_RATING
    assert rated["outlook"] == Outlook.STABLE


# ---------------------------------------------------------------------------
# The syndicate's fiscal bound (PRD section 3.6)
# ---------------------------------------------------------------------------
def test_liability_pct_sum_may_not_exceed_the_whole_syndicate(
    client, draft_deal, compliance
):
    """PRD section 3.6: "Finally the fiscal bound: the sum of `liability_pct` over the deal's `ACTIVE` members may never exceed 100.0000 once the new seat is counted, and the identical bound applies to the sum of `takedown_share_pct`; a breach of either reports `ERR_LIABILITY_PCT_SUM_INVALID`."

    Design: Corner/validations/liability_shares_may_not_exceed_the_whole_syndicate
    """
    ctx = _deal_with_a_sixty_percent_senior_manager(client, draft_deal)

    # Each field is individually inside (0, 100]; only the collective sum of
    # 105.0000 breaks the whole.
    response = client.create_syndicate_member(
        ctx.deal_id,
        _second_seat_payload(
            ctx.candidate_firm["id"], OVERFLOWING_SEAT_PCT, EXACT_REMAINDER_PCT
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_LIABILITY_PCT_SUM_INVALID)

    members, meta = _read_members(client, ctx, compliance)
    assert meta["total_count"] == 1
    assert to_decimal(members[0]["liability_pct"]) == to_decimal(SENIOR_SEAT_PCT)

    # The same seat at exactly the remaining forty lands the sum on 100.0000.
    accepted = get_success_data(
        client.create_syndicate_member(
            ctx.deal_id,
            _second_seat_payload(
                ctx.candidate_firm["id"], EXACT_REMAINDER_PCT, EXACT_REMAINDER_PCT
            ),
            ctx.advisor_headers,
        ),
        201,
    )
    assert to_decimal(accepted["liability_pct"]) == to_decimal(EXACT_REMAINDER_PCT)
    assert accepted["status"] == MemberStatus.ACTIVE

    members, meta = _read_members(client, ctx, compliance)
    assert meta["total_count"] == 2
    liability_sum, takedown_sum = _active_share_sums(members)
    assert liability_sum == to_decimal(LIABILITY_PCT_TOTAL)
    assert takedown_sum == to_decimal(LIABILITY_PCT_TOTAL)


def test_takedown_share_pct_sum_may_not_exceed_the_whole_syndicate(
    client, draft_deal, compliance
):
    """PRD section 3.6: "Finally the fiscal bound: the sum of `liability_pct` over the deal's `ACTIVE` members may never exceed 100.0000 once the new seat is counted, and the identical bound applies to the sum of `takedown_share_pct`; a breach of either reports `ERR_LIABILITY_PCT_SUM_INVALID`."

    Design: Corner/validations/liability_shares_may_not_exceed_the_whole_syndicate
    """
    ctx = _deal_with_a_sixty_percent_senior_manager(client, draft_deal)

    # Liability would land on exactly 100.0000; only takedown overflows, and the
    # bound applies to it independently.
    response = client.create_syndicate_member(
        ctx.deal_id,
        _second_seat_payload(
            ctx.candidate_firm["id"], EXACT_REMAINDER_PCT, OVERFLOWING_SEAT_PCT
        ),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_LIABILITY_PCT_SUM_INVALID)

    members, meta = _read_members(client, ctx, compliance)
    assert meta["total_count"] == 1
    assert to_decimal(members[0]["takedown_share_pct"]) == to_decimal(SENIOR_SEAT_PCT)
    liability_sum, takedown_sum = _active_share_sums(members)
    assert liability_sum == to_decimal(SENIOR_SEAT_PCT)
    assert takedown_sum == to_decimal(SENIOR_SEAT_PCT)


# ---------------------------------------------------------------------------
# Order-type placement (PRD section 3.7)
# ---------------------------------------------------------------------------
def test_retail_only_period_refuses_an_institutional_order(client, draft_deal):
    """PRD section 3.7: "Three order-type placement rules apply, all reported as `ERR_ORDER_TYPE_NOT_PERMITTED`: an order of `order_type` `RETAIL` may only be placed into a period whose `period_type` is `RETAIL`; when the period's `priority_policy` is `RETAIL_ONLY`, only `order_type` `RETAIL` is accepted at all; and an order of `order_type` `MEMBER` or `STOCK` requires the referenced syndicate member to have `member_role` `SENIOR_MANAGER` or `CO_MANAGER`, because those classes are the syndicate's own demand."

    Design: Corner/validations/order_type_must_be_permitted_by_the_period_and_the_seat
    """
    ctx = _two_seat_negotiated_book(client, draft_deal)
    period = _open_book(
        client, ctx, ctx.retail_period["id"], CLOCK_INSIDE_RETAIL_WINDOW
    )
    assert period["period_type"] == PeriodType.RETAIL
    assert period["priority_policy"] == PriorityPolicy.RETAIL_ONLY
    assert period["status"] == OrderPeriodStatus.OPEN

    response = client.create_order(
        period["id"],
        _order_payload(
            ctx, period, OrderType.INSTITUTIONAL_PRIORITY, ctx.senior_member["id"]
        ),
        ctx.underwriter_headers,
    )
    validate_error(response, ERR_ORDER_TYPE_NOT_PERMITTED)

    after_refusal = fx.read_period(client, period["id"], ctx.underwriter_headers)
    assert after_refusal["orders_received_count"] == 0

    # Retail demand into the same narrowed book is exactly what it accepts.
    accepted = fx.place_order(
        client,
        period["id"],
        ctx.tranche_ids[0],
        ctx.senior_member["id"],
        ctx.underwriter_headers,
        OrderType.RETAIL,
        ORDER_PAR_USD,
        price_or_yield_pct=TRANCHE_1_YIELD_PCT,
    )
    assert accepted["order_type"] == OrderType.RETAIL
    assert accepted["status"] == OrderStatus.PENDING


def test_institutional_period_refuses_a_retail_order(client, draft_deal):
    """PRD section 3.7: "Three order-type placement rules apply, all reported as `ERR_ORDER_TYPE_NOT_PERMITTED`: an order of `order_type` `RETAIL` may only be placed into a period whose `period_type` is `RETAIL`; when the period's `priority_policy` is `RETAIL_ONLY`, only `order_type` `RETAIL` is accepted at all; and an order of `order_type` `MEMBER` or `STOCK` requires the referenced syndicate member to have `member_role` `SENIOR_MANAGER` or `CO_MANAGER`, because those classes are the syndicate's own demand."

    Design: Corner/validations/order_type_must_be_permitted_by_the_period_and_the_seat
    """
    ctx = _two_seat_negotiated_book(client, draft_deal)
    period = _open_book(
        client, ctx, ctx.institutional_period["id"], CLOCK_INSIDE_BOOK_WINDOW
    )
    assert period["period_type"] == PeriodType.INSTITUTIONAL
    assert period["priority_policy"] == PriorityPolicy.STANDARD_PRIORITY

    # STANDARD_PRIORITY does not narrow the book, but retail demand still has
    # only one home: a period whose ``period_type`` is RETAIL.
    response = client.create_order(
        period["id"],
        _order_payload(ctx, period, OrderType.RETAIL, ctx.senior_member["id"]),
        ctx.underwriter_headers,
    )
    validate_error(response, ERR_ORDER_TYPE_NOT_PERMITTED)

    after_refusal = fx.read_period(client, period["id"], ctx.underwriter_headers)
    assert after_refusal["orders_received_count"] == 0
    orders, meta = validate_paginated(
        client.list_period_orders(period["id"], ctx.underwriter_headers)
    )
    assert orders == []
    assert meta["total_count"] == 0


def test_member_order_requires_a_syndicate_demand_eligible_seat(client, draft_deal):
    """PRD section 3.7: "Three order-type placement rules apply, all reported as `ERR_ORDER_TYPE_NOT_PERMITTED`: an order of `order_type` `RETAIL` may only be placed into a period whose `period_type` is `RETAIL`; when the period's `priority_policy` is `RETAIL_ONLY`, only `order_type` `RETAIL` is accepted at all; and an order of `order_type` `MEMBER` or `STOCK` requires the referenced syndicate member to have `member_role` `SENIOR_MANAGER` or `CO_MANAGER`, because those classes are the syndicate's own demand."

    Design: Corner/validations/order_type_must_be_permitted_by_the_period_and_the_seat
    """
    ctx = _two_seat_negotiated_book(client, draft_deal)
    assert (
        ctx.selling_group_member["member_role"]
        not in MemberRole.SYNDICATE_DEMAND_ELIGIBLE
    )
    period = _open_book(
        client, ctx, ctx.institutional_period["id"], CLOCK_INSIDE_BOOK_WINDOW
    )

    # The book accepts MEMBER demand; this seat is not entitled to enter it.
    response = client.create_order(
        period["id"],
        _order_payload(
            ctx, period, OrderType.MEMBER, ctx.selling_group_member["id"]
        ),
        ctx.underwriter_headers,
    )
    validate_error(response, ERR_ORDER_TYPE_NOT_PERMITTED)

    after_refusal = fx.read_period(client, period["id"], ctx.underwriter_headers)
    assert after_refusal["orders_received_count"] == 0

    # The identical order against the SENIOR_MANAGER seat is the syndicate's own
    # demand and is accepted.
    accepted = fx.place_order(
        client,
        period["id"],
        ctx.tranche_ids[0],
        ctx.senior_member["id"],
        ctx.underwriter_headers,
        OrderType.MEMBER,
        ORDER_PAR_USD,
        price_or_yield_pct=TRANCHE_1_YIELD_PCT,
    )
    assert accepted["order_type"] == OrderType.MEMBER
    assert accepted["status"] == OrderStatus.PENDING


# ---------------------------------------------------------------------------
# Credit enhancement (PRD section 3.3)
# ---------------------------------------------------------------------------
def test_a_second_enhancement_commitment_is_refused(
    client, structuring_deal, compliance
):
    """PRD section 3.3: "At most one enhancement per deal may hold `COMMITTED` at a time, so a second commitment while one is live is refused with `ERR_ENHANCEMENT_ALREADY_COMMITTED`."

    Design: Corner/validations/only_one_enhancement_may_be_committed_per_deal
    """
    ctx = _committed_first_policy(client, structuring_deal)
    assert ctx.first_enhancement["status"] == EnhancementStatus.COMMITTED
    assert ctx.second_enhancement["status"] == EnhancementStatus.PROPOSED
    # Two hundred basis points exactly is inside the range, so the proposal was
    # legally created and only the commitment is at issue.
    assert to_decimal(ctx.second_enhancement["premium_bps"]) == to_decimal(
        PREMIUM_BPS_MAX
    )

    response = client.commit_credit_enhancement(
        ctx.second_enhancement["id"], None, ctx.issuer_headers
    )
    validate_error(response, ERR_ENHANCEMENT_ALREADY_COMMITTED)

    rows, meta = _enhancements_by_id(client, ctx, compliance)
    assert meta["total_count"] == 2
    assert rows[ctx.first_enhancement["id"]]["status"] == EnhancementStatus.COMMITTED
    assert rows[ctx.second_enhancement["id"]]["status"] == EnhancementStatus.PROPOSED
    assert rows[ctx.second_enhancement["id"]]["premium_usd"] is None

    uninsured = _read_tranche(client, ctx, 1)
    assert uninsured["is_insured"] is False
    assert uninsured["rating_basis"] == RatingBasis.UNDERLYING

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert_money(
        deal["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "credit_enhancement_premium_usd",
    )


def test_a_duplicated_insured_tranche_id_is_refused(
    client, structuring_deal, compliance
):
    """PRD section 3.3: "That list must hold between one and forty distinct maturity identifiers, and every identifier in it must belong to the same deal as the enhancement; a duplicated identifier, an empty list, or a `premium_bps` outside the range of one through two hundred reports `ERR_ENHANCEMENT_ALREADY_COMMITTED`, while an identifier belonging to another deal reports `ERR_CROSS_DEAL_REFERENCE` at the earlier integrity tier."

    Design: Corner/validations/only_one_enhancement_may_be_committed_per_deal
    """
    ctx = _committed_first_policy(client, structuring_deal)

    # The list is not distinct, which the fiscal rule owns rather than the
    # request schema: the refusal must not collapse into a shape error.
    response = client.create_credit_enhancement(
        ctx.deal_id,
        f.enhancement_payload([ctx.tranche_ids[1], ctx.tranche_ids[1]]),
        ctx.advisor_headers,
    )
    validate_error(response, ERR_ENHANCEMENT_ALREADY_COMMITTED)

    rows, meta = _enhancements_by_id(client, ctx, compliance)
    assert meta["total_count"] == 2
    assert set(rows) == {ctx.first_enhancement["id"], ctx.second_enhancement["id"]}


def test_enhancement_commit_is_refused_while_the_deal_is_still_draft(
    client, draft_deal, compliance
):
    """PRD section 3.3: "The deal must be in `STRUCTURING`, `PRICING_COMPETITIVE`, or `PRICING_NEGOTIATED`, and any other deal status is refused with `ERR_DEAL_INVALID_STATE`."

    Design: Corner/validations/enhancement_commit_depends_on_the_deals_own_state
    """
    ctx = draft_deal
    assert ctx.deal["status"] == DealStatus.DRAFT
    proposal = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.tranche_ids[0]], ctx.advisor_headers
    )
    assert proposal["status"] == EnhancementStatus.PROPOSED

    # The enhancement itself is a perfectly valid PROPOSED row, so the refusal
    # must name the parent deal rather than the enhancement.
    response = client.commit_credit_enhancement(
        proposal["id"], None, ctx.issuer_headers
    )
    error = validate_error(response, ERR_DEAL_INVALID_STATE)
    assert error["error_id"] != ERR_ENHANCEMENT_INVALID_STATE

    rows, meta = _enhancements_by_id(client, ctx, compliance)
    assert meta["total_count"] == 1
    assert rows[proposal["id"]]["status"] == EnhancementStatus.PROPOSED
    assert rows[proposal["id"]]["premium_usd"] is None
    assert rows[proposal["id"]]["insured_debt_service_usd"] is None
    assert _read_tranche(client, ctx, 0)["is_insured"] is False

    structured = fx.submit_structure(client, ctx.deal_id, ctx.advisor_headers)
    assert structured["status"] == DealStatus.STRUCTURING

    committed = fx.commit_enhancement(client, proposal["id"], ctx.issuer_headers)
    assert committed["status"] == EnhancementStatus.COMMITTED
    assert_money(
        committed["insured_debt_service_usd"],
        INSURED_DEBT_SERVICE_TRANCHE_1_USD,
        "insured_debt_service_usd",
    )
    assert_money(committed["premium_usd"], ENHANCEMENT_PREMIUM_USD, "premium_usd")

    insured = _read_tranche(client, ctx, 0)
    assert insured["is_insured"] is True
    assert insured["rating_basis"] == RatingBasis.ENHANCED

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert_money(
        deal["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "credit_enhancement_premium_usd",
    )


# ---------------------------------------------------------------------------
# Pricing: the disclosure and order-book preconditions (PRD section 3.8)
# ---------------------------------------------------------------------------
def test_pricing_requires_a_posted_preliminary_statement(client, negotiated_deal):
    """PRD section 3.8: "Two disclosure preconditions also apply to both branches and both report `ERR_DISCLOSURE_NOT_CLEARED`: the deal's governing official statement must have `status` `PRELIMINARY_POSTED`, and `Deal.disclosure_clearance` must read `CLEARED`."

    Design: Corner/validations/pricing_requires_a_posted_official_statement
    """
    ctx = _priceable_but_unposted(client, negotiated_deal)
    assert ctx.statement["status"] == OfficialStatementStatus.IN_REVIEW
    assert ctx.statement["mandatory_sections_approved"] is True
    assert ctx.period["status"] == OrderPeriodStatus.CLOSED
    assert ctx.period["allotment_run_count"] >= 1

    response = client.price_deal(
        ctx.deal_id, f.negotiated_pricing_payload(), ctx.underwriter_headers
    )
    validate_error(response, ERR_DISCLOSURE_NOT_CLEARED)

    unpriced = fx.read_deal(client, ctx.deal_id, ctx.underwriter_headers)
    assert unpriced["status"] == DealStatus.PRICING_NEGOTIATED
    assert unpriced["issue_price_total_usd"] is None
    assert unpriced["gross_spread_total_usd"] is None

    posted = fx.post_preliminary(client, ctx.statement_id, ctx.advisor_headers)
    assert posted["status"] == OfficialStatementStatus.PRELIMINARY_POSTED

    priced = fx.price_negotiated(client, ctx.deal_id, ctx.underwriter_headers)
    assert priced["status"] == DealStatus.PRICED
    assert_money(
        priced["issue_price_total_usd"],
        CANONICAL_ISSUE_PRICE_TOTAL_USD,
        "issue_price_total_usd",
    )
    assert_money(
        priced["gross_spread_total_usd"],
        NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
        "gross_spread_total_usd",
    )
    assert_money(
        priced["net_proceeds_to_issuer_usd"],
        NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
        "net_proceeds_to_issuer_usd",
    )
    assert_money_identity(priced)

    settled = fx.read_period(client, ctx.period_id, ctx.underwriter_headers)
    assert settled["status"] == OrderPeriodStatus.SETTLED


def test_order_book_gate_outranks_the_compensation_gate(client, negotiated_deal):
    """PRD section 3.8: "The relative order in which these are observed follows the ladder of section 2.5: the deal-state check precedes the acting firm's suspension check, which precedes the order-book and disclosure checks, which precede the compensation, liability-sum, and net-proceeds checks."

    Design: Corner/validations/order_book_completeness_is_checked_before_the_compensation_inputs
    """
    ctx = fx.cleared_disclosure(negotiated_deal)
    assert ctx.deal["disclosure_clearance"] == DisclosureClearance.CLEARED
    periods, meta = validate_paginated(
        client.list_deal_order_periods(ctx.deal_id, ctx.underwriter_headers)
    )
    assert periods == []
    assert meta["total_count"] == 0

    # Two defects in one request: no order period at all, and the COMPETITIVE
    # input on a NEGOTIATED deal. The order-book check sits at the earlier tier.
    response = client.price_deal(
        ctx.deal_id, f.competitive_pricing_payload(), ctx.underwriter_headers
    )
    error = validate_error(response, ERR_PRICING_PRECONDITION_UNMET)
    assert error["error_id"] != ERR_COMPENSATION_INPUT_MISSING

    unpriced = fx.read_deal(client, ctx.deal_id, ctx.underwriter_headers)
    assert unpriced["status"] == DealStatus.PRICING_NEGOTIATED
    assert unpriced["gross_spread_total_usd"] is None


def test_a_merely_open_period_does_not_satisfy_the_order_book_gate(
    client, negotiated_deal
):
    """PRD section 3.8: "Two order-book preconditions apply to both branches and both report `ERR_PRICING_PRECONDITION_UNMET`: no order period of the deal may currently be `OPEN`, and at least one order period of the deal must be `CLOSED` with `allotment_run_count` of one or more."

    Design: Corner/validations/order_book_completeness_is_checked_before_the_compensation_inputs
    """
    ctx = fx.cleared_disclosure(negotiated_deal)
    period = fx.schedule_order_period(
        client,
        ctx.deal_id,
        ctx.advisor_headers,
        f.order_period_payload(
            BOOK_OPENS_AT,
            BOOK_CLOSES_AT,
            PeriodType.INSTITUTIONAL,
            priority_policy=PriorityPolicy.STANDARD_PRIORITY,
        ),
    )
    opened = _open_book(client, ctx, period["id"], CLOCK_INSIDE_BOOK_WINDOW)
    assert opened["status"] == OrderPeriodStatus.OPEN
    assert opened["allotment_run_count"] == 0

    # The compensation inputs are now the correct NEGOTIATED set, so the book is
    # the only remaining defect: an OPEN period is not a distributed one.
    response = client.price_deal(
        ctx.deal_id, f.negotiated_pricing_payload(), ctx.underwriter_headers
    )
    validate_error(response, ERR_PRICING_PRECONDITION_UNMET)

    unpriced = fx.read_deal(client, ctx.deal_id, ctx.underwriter_headers)
    assert unpriced["status"] == DealStatus.PRICING_NEGOTIATED
    assert unpriced["gross_spread_total_usd"] is None


# ---------------------------------------------------------------------------
# Pricing: the compensation inputs and the net-proceeds floor (PRD section 3.8)
# ---------------------------------------------------------------------------
def test_negotiated_pricing_refuses_the_competitive_input(client, negotiated_deal):
    """PRD section 3.8: "The compensation inputs are branch-exclusive, and supplying the wrong set is refused with `ERR_COMPENSATION_INPUT_MISSING`."

    Design: Corner/validations/compensation_inputs_must_match_the_sale_method
    """
    ctx = _fully_priceable_negotiated(client, negotiated_deal)

    response = client.price_deal(
        ctx.deal_id, f.competitive_pricing_payload(), ctx.underwriter_headers
    )
    validate_error(response, ERR_COMPENSATION_INPUT_MISSING)

    unpriced = fx.read_deal(client, ctx.deal_id, ctx.underwriter_headers)
    assert unpriced["status"] == DealStatus.PRICING_NEGOTIATED
    assert unpriced["gross_spread_total_usd"] is None


def test_negotiated_pricing_requires_all_three_per_bond_components(
    client, negotiated_deal
):
    """PRD section 3.8: "Pricing a `NEGOTIATED` deal requires `takedown_per_bond_usd`, `management_fee_per_bond_usd`, and `expenses_per_bond_usd` all to be present and forbids `winning_bid_price_pct`."

    Design: Corner/validations/compensation_inputs_must_match_the_sale_method
    """
    ctx = _fully_priceable_negotiated(client, negotiated_deal)
    omission = _negotiated_payload_without_expenses()
    assert "expenses_per_bond_usd" not in omission

    response = client.price_deal(ctx.deal_id, omission, ctx.underwriter_headers)
    validate_error(response, ERR_COMPENSATION_INPUT_MISSING)

    unpriced = fx.read_deal(client, ctx.deal_id, ctx.underwriter_headers)
    assert unpriced["status"] == DealStatus.PRICING_NEGOTIATED
    assert unpriced["gross_spread_total_usd"] is None


def test_negotiated_pricing_forbids_a_supplied_winning_bid(client, negotiated_deal):
    """PRD section 3.8: "Presence of a forbidden input is as much a violation as absence of a required one, so a competitive pricing that helpfully includes a takedown is rejected rather than ignored."

    Design: Corner/validations/compensation_inputs_must_match_the_sale_method
    """
    ctx = _fully_priceable_negotiated(client, negotiated_deal)

    # All three required components are present; the intrusion alone is fatal.
    response = client.price_deal(
        ctx.deal_id,
        f.negotiated_pricing_payload(
            winning_bid_price_pct=COMPETITIVE_WINNING_BID_PRICE_PCT
        ),
        ctx.underwriter_headers,
    )
    validate_error(response, ERR_COMPENSATION_INPUT_MISSING)

    unpriced = fx.read_deal(client, ctx.deal_id, ctx.underwriter_headers)
    assert unpriced["status"] == DealStatus.PRICING_NEGOTIATED

    # Dropping the intrusion is the only change the request needs.
    priced = fx.price_negotiated(client, ctx.deal_id, ctx.underwriter_headers)
    assert priced["status"] == DealStatus.PRICED
    assert_money(
        priced["gross_spread_total_usd"],
        NEGOTIATED_GROSS_SPREAD_TOTAL_USD,
        "gross_spread_total_usd",
    )
    assert_price(
        priced["gross_spread_per_bond_usd"],
        NEGOTIATED_GROSS_SPREAD_PER_BOND_USD,
        "gross_spread_per_bond_usd",
    )
    assert_yield_value(
        priced["arbitrage_yield_pct"],
        CANONICAL_ARBITRAGE_YIELD_PCT,
        "arbitrage_yield_pct",
    )


def test_gross_spread_may_not_exhaust_the_issue_proceeds(client, negotiated_deal):
    """PRD section 3.8: "`Deal.net_proceeds_to_issuer_usd` must come out strictly greater than zero, or the whole pricing is refused with `ERR_PREMIUM_EXCEEDS_PROCEEDS`."

    Design: Corner/validations/gross_spread_may_not_exhaust_the_issue_proceeds
    """
    ctx = _fully_priceable_negotiated(client, negotiated_deal)

    # The fat-finger takedown is schema-valid and drives the spread past the
    # whole issue price, so net proceeds would come out negative.
    fat_finger_spread = expected_negotiated_gross_spread(
        ctx.tranches, FAT_FINGER_COMPONENT_TOTAL_PER_BOND_USD
    )
    assert fat_finger_spread > to_decimal(CANONICAL_ISSUE_PRICE_TOTAL_USD)

    response = client.price_deal(
        ctx.deal_id,
        f.negotiated_pricing_payload(
            takedown_per_bond_usd=FAT_FINGER_TAKEDOWN_PER_BOND_USD
        ),
        ctx.underwriter_headers,
    )
    validate_error(response, ERR_PREMIUM_EXCEEDS_PROCEEDS)

    unpriced = fx.read_deal(client, ctx.deal_id, ctx.underwriter_headers)
    assert unpriced["status"] == DealStatus.PRICING_NEGOTIATED
    assert unpriced["issue_price_total_usd"] is None
    assert unpriced["gross_spread_total_usd"] is None
    assert unpriced["net_proceeds_to_issuer_usd"] is None

    # Nothing from the refused attempt leaked into the ledger.
    priced = fx.price_negotiated(client, ctx.deal_id, ctx.underwriter_headers)
    assert priced["status"] == DealStatus.PRICED
    assert_money(
        priced["net_proceeds_to_issuer_usd"],
        NEGOTIATED_NET_PROCEEDS_UNINSURED_USD,
        "net_proceeds_to_issuer_usd",
    )
    assert_money_identity(priced)


# ---------------------------------------------------------------------------
# Closing documents, closing and the handoff (PRD section 3.9)
# ---------------------------------------------------------------------------
def test_bond_opinion_may_not_be_waived(client, awarded_competitive_deal, compliance):
    """PRD section 3.9: "Two document types can never be waived: a `BOND_OPINION` and a `TAX_CERTIFICATE` are the never-waivable pair of section 2.8, and an attempt to waive either is refused with `ERR_SIGNATORY_ROLE_INVALID`."

    Design: Corner/validations/bond_opinion_and_tax_certificate_may_never_be_waived
    """
    ctx = awarded_competitive_deal
    opinion = ctx.documents[DocType.BOND_OPINION]
    assert opinion["execution_status"] == ExecutionStatus.PENDING

    # The caller is the ComplianceOfficer the endpoint requires, so this is a
    # refusal on the document's ``doc_type`` and not an access-control refusal.
    response = client.waive_closing_document(
        opinion["id"],
        f.waiver_payload("Counsel unavailable at closing."),
        compliance,
    )
    validate_error(response, ERR_SIGNATORY_ROLE_INVALID)

    after = get_success_data(client.get_closing_document(opinion["id"], compliance), 200)
    assert after["execution_status"] == ExecutionStatus.PENDING
    assert after["waiver_reason"] is None


def test_tax_certificate_may_not_be_waived(client, awarded_competitive_deal, compliance):
    """PRD section 3.9: "Two document types can never be waived: a `BOND_OPINION` and a `TAX_CERTIFICATE` are the never-waivable pair of section 2.8, and an attempt to waive either is refused with `ERR_SIGNATORY_ROLE_INVALID`."

    Design: Corner/validations/bond_opinion_and_tax_certificate_may_never_be_waived
    """
    ctx = awarded_competitive_deal
    certificate = ctx.documents[DocType.TAX_CERTIFICATE]
    assert certificate["execution_status"] == ExecutionStatus.PENDING
    assert certificate["doc_type"] in DocType.NEVER_WAIVABLE

    response = client.waive_closing_document(
        certificate["id"],
        f.waiver_payload("Tax counsel unavailable."),
        compliance,
    )
    validate_error(response, ERR_SIGNATORY_ROLE_INVALID)

    after = get_success_data(
        client.get_closing_document(certificate["id"], compliance), 200
    )
    assert after["execution_status"] == ExecutionStatus.PENDING
    assert after["waiver_reason"] is None


def test_receipt_refuses_a_mismatched_signatory_yet_admits_a_waiver(
    client, awarded_competitive_deal, compliance
):
    """PRD section 3.9: "The acting role must equal the document's `signatory_role` exactly, or the request is refused with `ERR_SIGNATORY_ROLE_INVALID` — a `MunicipalAdvisor` may not sign a bond opinion however senior."

    Design: Corner/validations/bond_opinion_and_tax_certificate_may_never_be_waived
    """
    ctx = awarded_competitive_deal
    receipt = ctx.documents[DocType.UNDERWRITER_RECEIPT]
    assert receipt["execution_status"] == ExecutionStatus.PENDING
    assert receipt["doc_type"] not in DocType.NEVER_WAIVABLE

    response = client.execute_closing_document(
        receipt["id"], f.execute_payload("Dana Reyes"), ctx.advisor_headers
    )
    validate_error(response, ERR_SIGNATORY_ROLE_INVALID)

    unsigned = get_success_data(
        client.get_closing_document(receipt["id"], compliance), 200
    )
    assert unsigned["execution_status"] == ExecutionStatus.PENDING
    assert unsigned["signatory_name"] is None

    # The very same ComplianceOfficer whose waiver the never-waivable pair
    # refuses discharges this one, so the ban is per ``doc_type``.
    waived = fx.waive_document(
        client, receipt["id"], "Receipt delivered outside the platform.", compliance
    )
    assert waived["execution_status"] == ExecutionStatus.WAIVED


def test_closing_requires_every_required_document_executed_or_waived(
    client, awarded_competitive_deal, compliance
):
    """PRD section 3.9: "Every closing document of the deal whose `is_required` is true must have `execution_status` `EXECUTED` or `WAIVED`, or the request is refused with `ERR_CLOSING_DOCS_INCOMPLETE`."

    Design: Corner/validations/closing_requires_every_required_document_executed_or_waived
    """
    ctx = _closable_competitive_deal(client, awarded_competitive_deal, compliance)
    assert set(ctx.documents) == set(COMPETITIVE_DOC_TYPES)
    assert all(
        doc["execution_status"] == ExecutionStatus.PENDING
        for doc in ctx.documents.values()
    )
    assert ctx.statement["status"] == OfficialStatementStatus.FINAL_POSTED

    validate_error(
        client.close_deal(ctx.deal_id, None, compliance), ERR_CLOSING_DOCS_INCOMPLETE
    )

    for doc_type in DocType.ALWAYS_CREATED:
        document = ctx.documents[doc_type]
        fx.execute_document(
            client,
            document["id"],
            fx.headers_for_signatory_role(ctx, document["signatory_role"]),
        )

    # Five of six are EXECUTED and only the sale-method-specific document is
    # outstanding, which is still not every required document.
    notice = ctx.documents[DocType.NOTICE_OF_SALE_CERTIFICATE]
    assert notice["is_required"] is True
    validate_error(
        client.close_deal(ctx.deal_id, None, compliance), ERR_CLOSING_DOCS_INCOMPLETE
    )
    still_awarded = fx.read_deal(client, ctx.deal_id, compliance)
    assert still_awarded["status"] == DealStatus.AWARDED

    fx.execute_document(
        client, notice["id"], fx.headers_for_signatory_role(ctx, notice["signatory_role"])
    )

    closed = fx.close_deal(client, ctx.deal_id, compliance)
    assert closed["status"] == DealStatus.CLOSED
    outstanding = fx.list_closing_documents(
        client, ctx.deal_id, compliance, execution_status=ExecutionStatus.PENDING
    )
    assert outstanding == []


def test_post_issuance_handoff_requires_six_years_of_record_retention(
    client, priced_competitive_deal, compliance
):
    """PRD section 3.9: "Four conditions must all hold, and any failure is reported as `ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE`: the deal's `status` must be `PRICED` or `AWARDED`, `Deal.arbitrage_yield_pct` must be non-null, the deal must have a continuing-disclosure undertaking with `status` `ACTIVE`, and `record_retention_years` must be at least six."

    Design: Corner/validations/post_issuance_handoff_requires_six_years_of_record_retention
    """
    ctx = priced_competitive_deal
    before = fx.read_deal(client, ctx.deal_id, compliance)
    assert before["status"] == DealStatus.PRICED
    assert_yield_value(
        before["arbitrage_yield_pct"],
        CANONICAL_ARBITRAGE_YIELD_PCT,
        "arbitrage_yield_pct",
    )
    assert before["post_issuance_handoff_status"] == HandoffStatus.NOT_STARTED

    # Five years is schema-valid: only the record-retention floor refuses it.
    response = client.post_issuance_handoff(
        ctx.deal_id, f.handoff_payload(BELOW_FLOOR_RETENTION_YEARS), compliance
    )
    validate_error(response, ERR_POST_ISSUANCE_HANDOFF_INCOMPLETE)

    refused = fx.read_deal(client, ctx.deal_id, compliance)
    assert refused["post_issuance_handoff_status"] == HandoffStatus.NOT_STARTED
    assert refused["record_retention_years"] is None

    ready = fx.complete_handoff(
        client, ctx.deal_id, MIN_RECORD_RETENTION_YEARS, compliance
    )
    assert ready["post_issuance_handoff_status"] == HandoffStatus.READY
    assert ready["record_retention_years"] == MIN_RECORD_RETENTION_YEARS
