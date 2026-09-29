"""Cross-entity state dependencies, in both directions, around the final statement.

Each write below is legal in every respect on its own row: the official statement
sits in the only status from which post-final is allowed and every one of its
sections is approved; the bond opinion is `PENDING` and signed by exactly the role
it names. The sole obstacle is the state of the *other* entity:

* OfficialStatement depends on Deal -- post-final needs the deal `AWARDED`;
* ClosingDocument depends on OfficialStatement -- a `BOND_OPINION` needs the
  statement `FINAL_POSTED`, while the `ISSUE_PRICE_CERTIFICATE` on the very same
  deal carries no such dependency.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_DEAL_INVALID_STATE, ERR_OS_NOT_FINAL_POSTED
from test_helpers.assertions import assert_timestamps_equal, assert_version_advanced
from test_helpers.constants import CLOCK_EPOCH, plus_days, plus_hours
from test_helpers.types import (
    DealStatus,
    DisclosureClearance,
    DocType,
    ExecutionStatus,
    OfficialStatementStatus,
    ReviewStatus,
)

# The instant the design index posts the final statement and executes the bond
# opinion from: 2026-08-05T14:00:00.000Z on the logical clock.
CLOCK_AT_CLOSING = plus_hours(plus_days(CLOCK_EPOCH, 4), 14)

COUNSEL_SIGNATORY_NAME = "R. Alvarez, Bond Counsel"
UNDERWRITER_SIGNATORY_NAME = "T. Whitfield, Alpha Underwriting"


def _read_statement(ctx):
    """Read the deal's governing official statement as its posting advisor."""
    return validate_success(
        ctx.client.get_official_statement(ctx.statement_id, ctx.advisor_headers)
    )


def _assert_every_section_approved(ctx):
    """PRD section 3.4's raised bar for post-final, satisfied before the trigger."""
    sections, meta = validate_paginated(
        ctx.client.list_statement_sections(ctx.statement_id, ctx.compliance_headers)
    )
    assert meta["total_count"] == len(sections)
    assert sections != []
    assert all(
        section["review_status"] == ReviewStatus.APPROVED for section in sections
    )


def _document(ctx, doc_type):
    """Re-read one closing document of the deal by its `doc_type`."""
    return fx.documents_by_type(ctx.client, ctx.deal_id, ctx.compliance_headers)[doc_type]


def _execute_as_named_signatory(ctx, document, signatory_name):
    """Attempt an execution under headers matching the document's `signatory_role`."""
    return ctx.client.execute_closing_document(
        document["id"],
        f.execute_payload(signatory_name),
        fx.headers_for_signatory_role(ctx, document["signatory_role"]),
    )


def _priced_deal_at_closing_clock(ctx):
    """A PRICED deal with its preliminary statement posted, clock at the closing instant."""
    fx.set_clock(ctx.client, CLOCK_AT_CLOSING)
    ctx.deal = fx.read_deal(ctx.client, ctx.deal_id, ctx.advisor_headers)
    assert ctx.deal["status"] == DealStatus.PRICED
    ctx.statement = _read_statement(ctx)
    assert ctx.statement["status"] == OfficialStatementStatus.PRELIMINARY_POSTED
    assert ctx.statement["posted_final_at"] is None
    _assert_every_section_approved(ctx)
    return ctx


def _awarded_deal_at_closing_clock(ctx):
    """An AWARDED deal whose statement is still only PRELIMINARY_POSTED."""
    fx.set_clock(ctx.client, CLOCK_AT_CLOSING)
    ctx.deal = fx.read_deal(ctx.client, ctx.deal_id, ctx.advisor_headers)
    assert ctx.deal["status"] == DealStatus.AWARDED
    ctx.statement = _read_statement(ctx)
    assert ctx.statement["status"] == OfficialStatementStatus.PRELIMINARY_POSTED
    return ctx


def test_post_final_refused_while_the_deal_is_still_priced(client, priced_negotiated_deal):
    """PRD section 3.4: "It requires the deal's `status` to be exactly `AWARDED`, refusing anything else with `ERR_DEAL_INVALID_STATE`, and it raises the disclosure bar: *every* section on the statement must have `review_status` `APPROVED`, including `GENERAL` sections that never counted toward `mandatory_sections_approved`."

    Design: Difficulty/cross_entity_state_dependency/official_statement_final_post_requires_deal_awarded
    """
    ctx = _priced_deal_at_closing_clock(priced_negotiated_deal)
    assert ctx.deal["disclosure_clearance"] == DisclosureClearance.CLEARED

    response = client.post_final(ctx.statement_id, None, ctx.advisor_headers)
    validate_error(response, ERR_DEAL_INVALID_STATE)

    after = _read_statement(ctx)
    assert after["status"] == OfficialStatementStatus.PRELIMINARY_POSTED
    assert after["posted_final_at"] is None
    assert after["version"] == ctx.statement["version"]


def test_award_unblocks_the_identical_post_final_call(client, priced_negotiated_deal):
    """PRD section 3.4: "On success, `posted_final_at` is stamped from the logical clock, `Deal.disclosure_clearance` stays `CLEARED`, and the statement's `version` increments."

    Design: Difficulty/cross_entity_state_dependency/official_statement_final_post_requires_deal_awarded
    """
    ctx = _priced_deal_at_closing_clock(priced_negotiated_deal)
    assert ctx.deal["disclosure_clearance"] == DisclosureClearance.CLEARED
    before = ctx.statement

    awarded = fx.award(client, ctx.deal_id, ctx.issuer_headers)
    assert awarded["status"] == DealStatus.AWARDED

    # The award writes nothing to the statement row, yet the same call now passes.
    unchanged = _read_statement(ctx)
    assert unchanged["version"] == before["version"]
    assert unchanged["posted_final_at"] is None

    statement = fx.post_final(client, ctx.statement_id, ctx.advisor_headers)
    assert statement["status"] == OfficialStatementStatus.FINAL_POSTED
    assert_timestamps_equal(
        statement["posted_final_at"], CLOCK_AT_CLOSING, "posted_final_at"
    )
    assert_version_advanced(statement, before, 1, "official statement")

    deal = fx.read_deal(client, ctx.deal_id, ctx.advisor_headers)
    assert deal["disclosure_clearance"] == DisclosureClearance.CLEARED


def test_bond_opinion_execution_refused_before_the_statement_is_final(
    client, awarded_negotiated_deal
):
    """PRD section 3.9: "A `BOND_OPINION` requires the deal's governing official statement to have `status` `FINAL_POSTED`, or the request is refused with `ERR_OS_NOT_FINAL_POSTED`: counsel will not opine until the final disclosure document is on the record."

    Design: Difficulty/cross_entity_state_dependency/bond_opinion_execution_requires_final_official_statement
    """
    ctx = _awarded_deal_at_closing_clock(awarded_negotiated_deal)
    opinion = _document(ctx, DocType.BOND_OPINION)
    assert opinion["execution_status"] == ExecutionStatus.PENDING
    assert opinion["executed_at"] is None

    response = _execute_as_named_signatory(ctx, opinion, COUNSEL_SIGNATORY_NAME)
    validate_error(response, ERR_OS_NOT_FINAL_POSTED)

    after = _document(ctx, DocType.BOND_OPINION)
    assert after["execution_status"] == ExecutionStatus.PENDING
    assert after["executed_at"] is None
    assert after["signatory_name"] is None
    assert after["version"] == opinion["version"]
    assert _read_statement(ctx)["status"] == OfficialStatementStatus.PRELIMINARY_POSTED


def test_issue_price_certificate_executes_against_a_preliminary_statement(
    client, awarded_negotiated_deal
):
    """PRD section 3.9: "Three further gates then apply by `doc_type`."

    Design: Difficulty/cross_entity_state_dependency/bond_opinion_execution_requires_final_official_statement
    """
    ctx = _awarded_deal_at_closing_clock(awarded_negotiated_deal)
    certificate = _document(ctx, DocType.ISSUE_PRICE_CERTIFICATE)
    assert certificate["execution_status"] == ExecutionStatus.PENDING

    # No doc_type gate subscribes this document to the statement's status, so it
    # executes while the governing statement is still only PRELIMINARY_POSTED.
    executed = validate_success(
        _execute_as_named_signatory(ctx, certificate, UNDERWRITER_SIGNATORY_NAME)
    )
    assert executed["execution_status"] == ExecutionStatus.EXECUTED
    assert executed["signatory_name"] == UNDERWRITER_SIGNATORY_NAME
    assert_timestamps_equal(executed["executed_at"], CLOCK_AT_CLOSING, "executed_at")
    assert_version_advanced(executed, certificate, 1, "closing document")

    assert _read_statement(ctx)["status"] == OfficialStatementStatus.PRELIMINARY_POSTED
    assert (
        _document(ctx, DocType.BOND_OPINION)["execution_status"]
        == ExecutionStatus.PENDING
    )


def test_final_posting_unblocks_the_bond_opinion_execution(
    client, awarded_negotiated_deal
):
    """PRD section 3.9: "On success the document becomes the terminal `EXECUTED` with the supplied `signatory_name` stored, `executed_at` set to the current logical clock instant, and its `version` incremented."

    Design: Difficulty/cross_entity_state_dependency/bond_opinion_execution_requires_final_official_statement
    """
    ctx = _awarded_deal_at_closing_clock(awarded_negotiated_deal)
    opinion = _document(ctx, DocType.BOND_OPINION)
    assert opinion["execution_status"] == ExecutionStatus.PENDING

    statement = fx.post_final(client, ctx.statement_id, ctx.advisor_headers)
    assert statement["status"] == OfficialStatementStatus.FINAL_POSTED

    executed = validate_success(
        _execute_as_named_signatory(ctx, opinion, COUNSEL_SIGNATORY_NAME)
    )
    assert executed["execution_status"] == ExecutionStatus.EXECUTED
    assert executed["signatory_name"] == COUNSEL_SIGNATORY_NAME
    assert_timestamps_equal(executed["executed_at"], CLOCK_AT_CLOSING, "executed_at")
    assert_version_advanced(executed, opinion, 1, "closing document")
