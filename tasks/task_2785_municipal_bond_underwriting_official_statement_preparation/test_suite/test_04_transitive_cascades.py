"""Transitive cascades: the two multi-hop chains PRD sections 3.3 and 3.4 describe.

Every test in this module translates exactly one instance of the DIFFICULTY
design index (``SCAFFOLD_DIFFICULTY_DESIGN.yaml``, rule ``transitive_cascade``):

* ``revision_request_five_hop_cascade`` -- one ``request-revision`` call travels
  statement -> sections -> ``mandatory_sections_approved`` ->
  ``Deal.disclosure_clearance`` -> rating presentations and engagements, five
  hops away from the entity the request named.
* ``enhancement_withdrawal_four_hop_cascade`` -- one ``withdraw`` call travels
  enhancement -> insured maturities -> deal premium -> the disclosure sections
  that referenced the enhancement, four hops away.

Because PRD section 2.4 makes cascades immediately consistent and hop-ordered,
each test fires the trigger once and then reads one hop's landing state; no test
observes a partially applied chain. Setup is delegated to
``test_helpers.fixtures`` and every URL, enum literal and pinned figure comes
from ``test_helpers``.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_money
from test_helpers.constants import (
    CLOCK_EPOCH,
    ENHANCEMENT_PREMIUM_USD,
    INSURED_DEBT_SERVICE_TRANCHE_1_USD,
    plus_days,
    plus_hours,
)
from test_helpers.types import (
    CascadeReason,
    DealStatus,
    DisclosureClearance,
    EnhancementStatus,
    EngagementStatus,
    OfficialStatementStatus,
    PresentationStatus,
    RatingBasis,
    ReviewStatus,
    SectionType,
)

REVISION_REASON = "Pension liability disclosure is inadequate."
WITHDRAWAL_REASON = "Insurer pulled the commitment before pricing."


# ---------------------------------------------------------------------------
# Shared read helpers
# ---------------------------------------------------------------------------
def _read_statement(ctx):
    return get_success_data(
        ctx.client.get_official_statement(ctx.statement_id, ctx.compliance_headers), 200
    )


def _read_section(ctx, section_id):
    return get_success_data(
        ctx.client.get_os_section(section_id, ctx.compliance_headers), 200
    )


def _read_engagement(ctx):
    return get_success_data(
        ctx.client.get_rating_engagement(ctx.engagement_id, ctx.compliance_headers), 200
    )


def _read_presentations(ctx):
    rows, _meta = validate_paginated(
        ctx.client.list_engagement_presentations(
            ctx.engagement_id, ctx.compliance_headers
        )
    )
    return rows


def _read_tranche(ctx, tranche_id):
    return get_success_data(
        ctx.client.get_maturity_tranche(tranche_id, ctx.compliance_headers), 200
    )


# ---------------------------------------------------------------------------
# transitive_cascade / revision_request_five_hop_cascade -- shared setup
# ---------------------------------------------------------------------------
def _five_hop_world(client):
    """A cleared deal carrying a SCHEDULED presentation and an UNDER_REVIEW engagement.

    The statement sits in IN_REVIEW with all four mandatory categories approved,
    so PRD section 2.4 puts ``Deal.disclosure_clearance`` at ``CLEARED`` before
    the trigger -- the only starting point from which every one of the five hops
    is observable.
    """
    ctx = fx.draft_deal(client)
    fx.acknowledged_engagement(ctx)
    starts_at = plus_hours(plus_days(CLOCK_EPOCH, 9), 14)
    ctx.presentation = fx.schedule_presentation(
        client, ctx.engagement_id, ctx.advisor_headers, starts_at, plus_hours(starts_at, 2)
    )
    ctx.presentation_id = ctx.presentation["id"]
    fx.with_statement_in_review(ctx)

    # The pre-trigger state the design instance pins.
    before_statement = _read_statement(ctx)
    assert before_statement["status"] == OfficialStatementStatus.IN_REVIEW
    assert before_statement["mandatory_sections_approved"] is True
    before_deal = fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)
    assert before_deal["disclosure_clearance"] == DisclosureClearance.CLEARED
    before_engagement = _read_engagement(ctx)
    assert before_engagement["status"] == EngagementStatus.UNDER_REVIEW
    assert before_engagement["info_request_count"] == 0
    assert ctx.presentation["status"] == PresentationStatus.SCHEDULED

    ctx.revision_response = client.request_revision(
        ctx.statement_id, f.revision_payload(REVISION_REASON), ctx.advisor_headers
    )
    return ctx


# ---------------------------------------------------------------------------
# transitive_cascade / revision_request_five_hop_cascade
# ---------------------------------------------------------------------------
def test_hop_one_moves_the_statement_to_revision_requested(client):
    """PRD 3.4: "Hop one sets the statement's `status` to `REVISION_REQUESTED`,
    adds one to `draft_round`, and stores `revision_reason`."

    Design: Difficulty/transitive_cascade/revision_request_five_hop_cascade
    """
    ctx = _five_hop_world(client)

    statement = validate_success(ctx.revision_response, 200)
    assert statement["status"] == OfficialStatementStatus.REVISION_REQUESTED
    assert statement["draft_round"] == 2
    assert statement["revision_reason"] == REVISION_REASON


def test_hop_two_unapproves_the_risk_factor_section(client):
    """PRD 3.4: "Hop two, caused by hop one, moves every section on that statement
    whose `section_type` is `RISK_FACTOR` and whose `review_status` is `APPROVED`
    to `NEEDS_REVISION`, clearing each one's `approved_by_user_id` back to null."

    Design: Difficulty/transitive_cascade/revision_request_five_hop_cascade
    """
    ctx = _five_hop_world(client)
    validate_success(ctx.revision_response, 200)

    section = _read_section(ctx, ctx.section_ids[SectionType.RISK_FACTOR])
    assert section["review_status"] == ReviewStatus.NEEDS_REVISION
    assert section["approved_by_user_id"] is None


def test_hop_two_leaves_the_other_three_mandatory_sections_approved(client):
    """PRD 3.4: "Hop two, caused by hop one, moves every section on that statement
    whose `section_type` is `RISK_FACTOR` and whose `review_status` is `APPROVED`
    to `NEEDS_REVISION`, clearing each one's `approved_by_user_id` back to null."

    Design: Difficulty/transitive_cascade/revision_request_five_hop_cascade
    """
    ctx = _five_hop_world(client)
    validate_success(ctx.revision_response, 200)

    for section_type in (
        SectionType.TAX_MATTERS,
        SectionType.CONTINUING_DISCLOSURE,
        SectionType.UNDERWRITING,
    ):
        section = _read_section(ctx, ctx.section_ids[section_type])
        assert section["review_status"] == ReviewStatus.APPROVED, (
            f"{section_type} is outside the RISK_FACTOR scope of hop two but reads "
            f"{section['review_status']!r}"
        )
        assert section["approved_by_user_id"] is not None


def test_hop_three_drops_mandatory_sections_approved_to_false(client):
    """PRD 3.4: "Hop three, caused by hop two, recomputes
    `mandatory_sections_approved`, which necessarily becomes false because no
    approved `RISK_FACTOR` section survives."

    Design: Difficulty/transitive_cascade/revision_request_five_hop_cascade
    """
    ctx = _five_hop_world(client)
    validate_success(ctx.revision_response, 200)

    assert _read_statement(ctx)["mandatory_sections_approved"] is False


def test_hop_four_blocks_the_deal_disclosure_clearance(client):
    """PRD 3.4: "Hop four, caused by hop three, recomputes
    `Deal.disclosure_clearance`, which becomes `BLOCKED` because the governing
    statement now has `mandatory_sections_approved` false and `status`
    `REVISION_REQUESTED`."

    Design: Difficulty/transitive_cascade/revision_request_five_hop_cascade
    """
    ctx = _five_hop_world(client)
    validate_success(ctx.revision_response, 200)

    deal = fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)
    assert deal["disclosure_clearance"] == DisclosureClearance.BLOCKED


def test_hop_five_cancels_the_scheduled_rating_presentation(client):
    """PRD 3.5: "The third route is a cascade: the disclosure-block cascade and the
    enhancement-withdrawal cascade both cancel `SCHEDULED` presentations with
    `cancellation_reason` recorded as `DISCLOSURE_BLOCKED`, and deal cancellation
    cancels them with `cancellation_reason` recorded as `DEAL_CANCELLED`."

    Design: Difficulty/transitive_cascade/revision_request_five_hop_cascade
    """
    ctx = _five_hop_world(client)
    validate_success(ctx.revision_response, 200)

    presentations = _read_presentations(ctx)
    assert [row["id"] for row in presentations] == [ctx.presentation_id]
    assert presentations[0]["status"] == PresentationStatus.CANCELLED
    assert presentations[0]["cancellation_reason"] == CascadeReason.DISCLOSURE_BLOCKED


def test_hop_five_pushes_the_under_review_engagement_to_info_requested(client):
    """PRD 3.4: "Hop five, caused by hop four, reaches into the credit review: every
    rating presentation with `status` `SCHEDULED` belonging to any rating engagement
    of that deal is moved to `CANCELLED` with `cancellation_reason` set to
    `DISCLOSURE_BLOCKED`, and every rating engagement of that deal whose `status` is
    `UNDER_REVIEW` is moved to `INFO_REQUESTED` with one added to its
    `info_request_count` and its `latest_information_request` set to
    `DISCLOSURE_BLOCKED_PENDING_OS_REVISION`."

    Design: Difficulty/transitive_cascade/revision_request_five_hop_cascade
    """
    ctx = _five_hop_world(client)
    validate_success(ctx.revision_response, 200)

    engagement = _read_engagement(ctx)
    assert engagement["status"] == EngagementStatus.INFO_REQUESTED
    assert engagement["info_request_count"] == 1
    assert (
        engagement["latest_information_request"]
        == CascadeReason.DISCLOSURE_BLOCKED_PENDING_OS_REVISION
    )


# ---------------------------------------------------------------------------
# transitive_cascade / enhancement_withdrawal_four_hop_cascade -- shared setup
# ---------------------------------------------------------------------------
def _statement_referencing_the_enhancement(ctx):
    """Approve all four mandatory categories, subscribing only UNDERWRITING.

    PRD section 3.4 makes the section's ``references_credit_enhancement`` flag the
    subscription to the reopening cascade, so the UNDERWRITING section sets it and
    the other three leave it at its default of false.
    """
    fx.with_drafting_statement(ctx)
    sections = {
        SectionType.RISK_FACTOR: fx.add_section(
            ctx.client, ctx.statement_id, f.material_risk_section_payload()
        ),
        SectionType.TAX_MATTERS: fx.add_section(
            ctx.client, ctx.statement_id, f.section_payload(SectionType.TAX_MATTERS)
        ),
        SectionType.CONTINUING_DISCLOSURE: fx.add_section(
            ctx.client, ctx.statement_id, f.continuing_disclosure_risk_section_payload()
        ),
        SectionType.UNDERWRITING: fx.add_section(
            ctx.client,
            ctx.statement_id,
            f.section_payload(
                SectionType.UNDERWRITING, references_credit_enhancement=True
            ),
        ),
    }
    ctx.section_ids = {
        section_type: section["id"] for section_type, section in sections.items()
    }
    for section_id in ctx.section_ids.values():
        fx.approve_section(ctx.client, section_id)
    ctx.statement = fx.submit_for_review(ctx.client, ctx.statement_id)
    return ctx


def _withdrawal_world(client):
    """A PRICING_NEGOTIATED deal whose first maturity is insured by a COMMITTED policy."""
    ctx = fx.negotiated_pricing_deal(client)
    ctx.insured_tranche_id = ctx.tranche_ids[0]
    ctx.uninsured_tranche_id = ctx.tranche_ids[1]
    proposal = fx.propose_enhancement(
        client, ctx.deal_id, [ctx.insured_tranche_id], ctx.advisor_headers
    )
    ctx.enhancement_id = proposal["id"]
    ctx.enhancement = fx.commit_enhancement(client, ctx.enhancement_id, ctx.issuer_headers)
    _statement_referencing_the_enhancement(ctx)

    # The pre-trigger state the design instance pins.
    assert ctx.enhancement["status"] == EnhancementStatus.COMMITTED
    assert_money(
        ctx.enhancement["insured_debt_service_usd"],
        INSURED_DEBT_SERVICE_TRANCHE_1_USD,
        "enhancement.insured_debt_service_usd before withdrawal",
    )
    assert_money(
        ctx.enhancement["premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "enhancement.premium_usd before withdrawal",
    )
    before_tranche = _read_tranche(ctx, ctx.insured_tranche_id)
    assert before_tranche["is_insured"] is True
    assert before_tranche["rating_basis"] == RatingBasis.ENHANCED
    before_deal = fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)
    assert before_deal["status"] == DealStatus.PRICING_NEGOTIATED
    assert_money(
        before_deal["credit_enhancement_premium_usd"],
        ENHANCEMENT_PREMIUM_USD,
        "deal.credit_enhancement_premium_usd before withdrawal",
    )
    assert _read_statement(ctx)["mandatory_sections_approved"] is True

    ctx.withdraw_response = client.withdraw_credit_enhancement(
        ctx.enhancement_id, f.withdraw_payload(WITHDRAWAL_REASON), ctx.issuer_headers
    )
    return ctx


# ---------------------------------------------------------------------------
# transitive_cascade / enhancement_withdrawal_four_hop_cascade
# ---------------------------------------------------------------------------
def test_withdrawal_hop_one_terminates_the_commitment(client):
    """PRD 3.3: "In the first hop the enhancement's `status` becomes `WITHDRAWN`, its
    `enhanced_rating` is cleared to null, and `withdrawal_reason` is stored."

    Design: Difficulty/transitive_cascade/enhancement_withdrawal_four_hop_cascade
    """
    ctx = _withdrawal_world(client)

    enhancement = validate_success(ctx.withdraw_response, 200)
    assert enhancement["status"] == EnhancementStatus.WITHDRAWN
    assert enhancement["enhanced_rating"] is None
    assert enhancement["withdrawal_reason"] == WITHDRAWAL_REASON


def test_withdrawal_hop_two_returns_the_insured_maturity_to_underlying(client):
    """PRD 3.3: "In the second hop, caused by the first, every maturity named in
    `insured_tranche_ids` whose `is_insured` is true has that flag set back to false
    and its `rating_basis` returned to `UNDERLYING`."

    Design: Difficulty/transitive_cascade/enhancement_withdrawal_four_hop_cascade
    """
    ctx = _withdrawal_world(client)
    validate_success(ctx.withdraw_response, 200)

    insured = _read_tranche(ctx, ctx.insured_tranche_id)
    assert insured["is_insured"] is False
    assert insured["rating_basis"] == RatingBasis.UNDERLYING

    # The second maturity was never named, so it was never insured to begin with.
    untouched = _read_tranche(ctx, ctx.uninsured_tranche_id)
    assert untouched["is_insured"] is False
    assert untouched["rating_basis"] == RatingBasis.UNDERLYING


def test_withdrawal_hop_three_zeroes_the_deal_premium_without_repricing(client):
    """PRD 3.3: "In the third hop, caused by the second, the deal now has no insured
    maturity, so `Deal.credit_enhancement_premium_usd` becomes 0.00 and — when the
    deal's `status` is already `PRICED` — `net_proceeds_to_issuer_usd` is recomputed
    as `issue_price_total_usd` less `gross_spread_total_usd` less a zero premium,
    rounded half up to two decimal places."

    Design: Difficulty/transitive_cascade/enhancement_withdrawal_four_hop_cascade
    """
    ctx = _withdrawal_world(client)
    validate_success(ctx.withdraw_response, 200)

    deal = fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)
    assert_money(
        deal["credit_enhancement_premium_usd"],
        0.00,
        "deal.credit_enhancement_premium_usd after withdrawal",
    )
    # This deal was never priced, so the conditional half of the hop does not fire.
    assert deal["status"] == DealStatus.PRICING_NEGOTIATED
    assert deal["net_proceeds_to_issuer_usd"] is None


def test_withdrawal_hop_four_reopens_only_the_subscribed_section(client):
    """PRD 3.3: "In the fourth hop, caused by the third, the disclosed proceeds figure
    has changed, so every section of the deal's governing official statement whose
    `references_credit_enhancement` is true and whose `review_status` is `APPROVED`
    is moved to `NEEDS_REVISION`, that statement's `mandatory_sections_approved` is
    recomputed, and `Deal.disclosure_clearance` is recomputed — becoming `BLOCKED`
    when the governing statement's `status` is `REVISION_REQUESTED` or `WITHDRAWN`
    and `PENDING` otherwise."

    Design: Difficulty/transitive_cascade/enhancement_withdrawal_four_hop_cascade
    """
    ctx = _withdrawal_world(client)
    validate_success(ctx.withdraw_response, 200)

    underwriting = _read_section(ctx, ctx.section_ids[SectionType.UNDERWRITING])
    assert underwriting["review_status"] == ReviewStatus.NEEDS_REVISION
    assert underwriting["approved_by_user_id"] is None

    for section_type in (
        SectionType.RISK_FACTOR,
        SectionType.TAX_MATTERS,
        SectionType.CONTINUING_DISCLOSURE,
    ):
        section = _read_section(ctx, ctx.section_ids[section_type])
        assert section["review_status"] == ReviewStatus.APPROVED, (
            f"{section_type} does not reference the enhancement but reads "
            f"{section['review_status']!r}"
        )
        assert section["approved_by_user_id"] is not None


def test_withdrawal_hop_four_lands_the_clearance_on_pending(client):
    """PRD 3.3: "In the fourth hop, caused by the third, the disclosed proceeds figure
    has changed, so every section of the deal's governing official statement whose
    `references_credit_enhancement` is true and whose `review_status` is `APPROVED`
    is moved to `NEEDS_REVISION`, that statement's `mandatory_sections_approved` is
    recomputed, and `Deal.disclosure_clearance` is recomputed — becoming `BLOCKED`
    when the governing statement's `status` is `REVISION_REQUESTED` or `WITHDRAWN`
    and `PENDING` otherwise."

    Design: Difficulty/transitive_cascade/enhancement_withdrawal_four_hop_cascade
    """
    ctx = _withdrawal_world(client)
    validate_success(ctx.withdraw_response, 200)

    statement = _read_statement(ctx)
    assert statement["status"] == OfficialStatementStatus.IN_REVIEW
    assert statement["mandatory_sections_approved"] is False

    deal = fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)
    assert deal["disclosure_clearance"] == DisclosureClearance.PENDING
