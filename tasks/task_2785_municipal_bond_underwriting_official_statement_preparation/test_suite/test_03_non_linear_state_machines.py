"""Non-linear state machines: the bounded revision cycle and the sale-method fork.

Every test in this module translates exactly one instance of the DIFFICULTY
design index (``SCAFFOLD_DIFFICULTY_DESIGN.yaml``, rule
``non_linear_state_machine``):

* ``official_statement_revision_cycle_bounded`` -- a true cycle,
  ``DRAFTING`` -> ``IN_REVIEW`` -> ``REVISION_REQUESTED`` -> ``DRAFTING``,
  traversed three times with ``draft_round`` as its loop counter and refused on
  the fourth pass while the statement stays in ``IN_REVIEW``.
* ``deal_fork_join_divergent_closing_document_sets`` -- the branching fork taken
  at ``designate-sale-method``, whose two arms rejoin at ``PRICED`` and then at
  ``AWARDED`` yet remain distinguishable because award composes a different
  sixth closing document on each arm.

Setup is delegated to ``test_helpers.fixtures`` and every URL, enum literal,
error id and bound comes from ``test_helpers``; nothing is re-derived here.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_REVISION_LIMIT_EXCEEDED
from test_helpers.assertions import assert_pagination
from test_helpers.constants import REVISION_ROUND_CAP
from test_helpers.types import (
    DealStatus,
    DocType,
    ExecutionStatus,
    OfficialStatementStatus,
    ReviewStatus,
)

# The three reasons the design index drives the loop with, then the refused one.
FIRST_REASON = "Expand the pension liability discussion."
SECOND_REASON = "Add the tax increment financing risk."
THIRD_REASON = "Restate the debt service coverage table."
FOURTH_REASON = "Fourth pass rejected."


# ---------------------------------------------------------------------------
# Module-local setup for the revision cycle
# ---------------------------------------------------------------------------
def _statement_in_review_with_one_material_risk_section(client):
    """A DRAFT deal whose statement sits in IN_REVIEW at ``draft_round`` 1.

    The statement carries exactly one section: an approved material
    ``RISK_FACTOR``, which is the only population hop two of the revision
    cascade touches.
    """
    ctx = fx.draft_deal(client)
    fx.with_drafting_statement(ctx)
    section = fx.add_section(
        client, ctx.statement_id, f.material_risk_section_payload()
    )
    ctx.risk_section_id = section["id"]
    fx.approve_section(client, ctx.risk_section_id)
    ctx.statement = fx.submit_for_review(client, ctx.statement_id)
    return ctx


def _request_revision(ctx, reason):
    """Fire the trigger under test as the deal's own municipal advisor."""
    return ctx.client.request_revision(
        ctx.statement_id, f.revision_payload(reason), ctx.advisor_headers
    )


def _reenter_review(ctx):
    """Close the loop: REVISION_REQUESTED -> DRAFTING -> IN_REVIEW."""
    fx.resume_drafting(ctx.client, ctx.statement_id)
    return fx.submit_for_review(ctx.client, ctx.statement_id)


def _read_statement(ctx):
    return get_success_data(
        ctx.client.get_official_statement(ctx.statement_id, ctx.compliance_headers), 200
    )


def _read_section(ctx, section_id):
    return get_success_data(
        ctx.client.get_os_section(section_id, ctx.compliance_headers), 200
    )


def _drive_to_the_round_cap(client):
    """Traverse the loop three times, leaving IN_REVIEW at ``draft_round`` four."""
    ctx = _statement_in_review_with_one_material_risk_section(client)
    for reason in (FIRST_REASON, SECOND_REASON, THIRD_REASON):
        validate_success(_request_revision(ctx, reason), 200)
        ctx.statement = _reenter_review(ctx)
    return ctx


def _closing_documents(ctx):
    """Award's only discovery channel: list the deal's closing documents."""
    return validate_paginated(
        ctx.client.list_deal_closing_documents(ctx.deal_id, ctx.compliance_headers)
    )


# ---------------------------------------------------------------------------
# non_linear_state_machine / official_statement_revision_cycle_bounded
# ---------------------------------------------------------------------------
def test_three_revision_requests_advance_draft_round_around_the_loop(client):
    """PRD 3.4: "Hop one sets the statement's `status` to `REVISION_REQUESTED`,
    adds one to `draft_round`, and stores `revision_reason`."

    Design: Difficulty/non_linear_state_machine/official_statement_revision_cycle_bounded
    """
    ctx = _statement_in_review_with_one_material_risk_section(client)
    assert ctx.statement["draft_round"] == 1
    assert ctx.statement["status"] == OfficialStatementStatus.IN_REVIEW

    for expected_round, reason in (
        (2, FIRST_REASON),
        (3, SECOND_REASON),
        (4, THIRD_REASON),
    ):
        statement = validate_success(_request_revision(ctx, reason), 200)
        assert statement["status"] == OfficialStatementStatus.REVISION_REQUESTED
        assert statement["draft_round"] == expected_round, (
            f"draft_round after the revision request that should reach "
            f"{expected_round}: got {statement['draft_round']!r}"
        )
        assert statement["revision_reason"] == reason
        # Close the loop so the next pass starts from IN_REVIEW again.
        if expected_round < REVISION_ROUND_CAP:
            resumed = _reenter_review(ctx)
            assert resumed["status"] == OfficialStatementStatus.IN_REVIEW
            assert resumed["draft_round"] == expected_round


def test_a_fourth_revision_request_is_refused_at_the_round_cap(client):
    """PRD 3.4: "It is permitted only while `draft_round` is strictly less than
    four; a fourth request when `draft_round` has already reached four is refused
    with `ERR_REVISION_LIMIT_EXCEEDED`, which is the hard cap on drafting rounds."

    Design: Difficulty/non_linear_state_machine/official_statement_revision_cycle_bounded
    """
    ctx = _drive_to_the_round_cap(client)
    assert ctx.statement["draft_round"] == REVISION_ROUND_CAP
    assert ctx.statement["status"] == OfficialStatementStatus.IN_REVIEW

    validate_error(_request_revision(ctx, FOURTH_REASON), ERR_REVISION_LIMIT_EXCEEDED)

    # A refusal performs no hop, so the statement is exactly where the loop left it.
    statement = _read_statement(ctx)
    assert statement["status"] == OfficialStatementStatus.IN_REVIEW
    assert statement["draft_round"] == REVISION_ROUND_CAP


def test_the_bounded_loop_leaves_the_risk_factor_section_needing_revision(client):
    """PRD 3.4: "Hop two, caused by hop one, moves every section on that statement
    whose `section_type` is `RISK_FACTOR` and whose `review_status` is `APPROVED`
    to `NEEDS_REVISION`, clearing each one's `approved_by_user_id` back to null."

    Design: Difficulty/non_linear_state_machine/official_statement_revision_cycle_bounded
    """
    ctx = _drive_to_the_round_cap(client)

    section = _read_section(ctx, ctx.risk_section_id)
    assert section["review_status"] == ReviewStatus.NEEDS_REVISION
    assert section["approved_by_user_id"] is None


# ---------------------------------------------------------------------------
# non_linear_state_machine / deal_fork_join_divergent_closing_document_sets
# ---------------------------------------------------------------------------
def test_the_negotiated_arm_carries_its_branch_flags_forward_to_award(
    client, awarded_negotiated_deal
):
    """PRD 3.6: "On success, `sale_method` and `gross_spread_basis` are both set to
    `NEGOTIATED`, `requires_g17_letter` is set to true, `requires_notice_of_sale`
    remains false, and the deal's `version` increments."

    Design: Difficulty/non_linear_state_machine/deal_fork_join_divergent_closing_document_sets
    """
    ctx = awarded_negotiated_deal

    deal = fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)
    assert deal["requires_g17_letter"] is True
    assert deal["requires_notice_of_sale"] is False


def test_the_competitive_arm_carries_its_branch_flags_forward_to_award(
    client, awarded_competitive_deal
):
    """PRD 3.6: "On success, `sale_method` and `gross_spread_basis` are both set to
    `COMPETITIVE`, `requires_notice_of_sale` is set to true, `requires_g17_letter`
    remains false, and the deal's `version` increments."

    Design: Difficulty/non_linear_state_machine/deal_fork_join_divergent_closing_document_sets
    """
    ctx = awarded_competitive_deal

    deal = fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)
    assert deal["requires_notice_of_sale"] is True
    assert deal["requires_g17_letter"] is False


def test_both_arms_of_the_fork_rejoin_in_awarded(
    client, awarded_negotiated_deal, awarded_competitive_deal
):
    """PRD 3.9: "Award is taken by an `IssuerOfficial` and moves the deal from
    `PRICED` to `AWARDED`."

    Design: Difficulty/non_linear_state_machine/deal_fork_join_divergent_closing_document_sets
    """
    negotiated = fx.read_deal(
        client, awarded_negotiated_deal.deal_id, awarded_negotiated_deal.compliance_headers
    )
    competitive = fx.read_deal(
        client, awarded_competitive_deal.deal_id, awarded_competitive_deal.compliance_headers
    )

    assert negotiated["status"] == DealStatus.AWARDED
    assert competitive["status"] == DealStatus.AWARDED


def test_the_negotiated_arm_adds_the_g17_disclosure_letter_as_its_sixth_document(
    client, awarded_negotiated_deal
):
    """PRD 3.9: "When `Deal.requires_g17_letter` is true — which is to say on a
    negotiated deal — award additionally creates a `G17_DISCLOSURE_LETTER` with
    `signatory_role` `Underwriter` and `is_required` true."

    Design: Difficulty/non_linear_state_machine/deal_fork_join_divergent_closing_document_sets
    """
    ctx = awarded_negotiated_deal
    assert fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)[
        "requires_g17_letter"
    ] is True

    documents, meta = _closing_documents(ctx)
    assert_pagination(meta, total_count=6)
    assert {document["doc_type"] for document in documents} == set(
        DocType.ALWAYS_CREATED
    ) | {DocType.G17_DISCLOSURE_LETTER}
    for document in documents:
        assert document["execution_status"] == ExecutionStatus.PENDING
        assert document["is_required"] is True


def test_the_competitive_arm_adds_the_notice_of_sale_certificate_as_its_sixth_document(
    client, awarded_competitive_deal
):
    """PRD 3.9: "When `Deal.requires_notice_of_sale` is true — which is to say on a
    competitive deal — award additionally creates a `NOTICE_OF_SALE_CERTIFICATE`
    with `signatory_role` `MunicipalAdvisor` and `is_required` true."

    Design: Difficulty/non_linear_state_machine/deal_fork_join_divergent_closing_document_sets
    """
    ctx = awarded_competitive_deal
    assert fx.read_deal(client, ctx.deal_id, ctx.compliance_headers)[
        "requires_notice_of_sale"
    ] is True

    documents, meta = _closing_documents(ctx)
    assert_pagination(meta, total_count=6)
    assert {document["doc_type"] for document in documents} == set(
        DocType.ALWAYS_CREATED
    ) | {DocType.NOTICE_OF_SALE_CERTIFICATE}
    for document in documents:
        assert document["execution_status"] == ExecutionStatus.PENDING
        assert document["is_required"] is True
