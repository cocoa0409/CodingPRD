"""Editorial enhancement workflow: headnote drafting, author-personal
submission, segregated review, the DRAFT/IN_REVIEW cycle, document-state
gates, and compliance-driven retraction (PRD §3.3, §3.8)."""
from test_helpers import (
    CLOCK_SEP_05,
    CLOCK_SEP_15,
    ApiErrorId,
    assert_headnote,
    create_document,
    create_headnote,
    create_published_document,
    create_published_headnote,
    decide_headnote,
    get_document,
    get_headnote,
    make_attorney_editor_headers,
    reverse_removal_order,
    seal_document,
    set_clock,
    submit_headnote,
    validate_error,
)

ED_AUTHOR = "ed-author-1"
ED_REVIEWER = "ed-reviewer-1"


def test_reject_returns_headnote_to_draft(api):
    """PRD §3.3: "An approval moves the headnote to `PUBLISHED`; a rejection sends
    it back to `DRAFT`, and the author may revise and resubmit without limit — the
    loop between `DRAFT` and `IN_REVIEW` is unbounded."
    PRD §3.3: "Both branches record `reviewer_editor_id` from the caller's header
    and store the supplied `review_note`, and each transition increments the
    headnote's `version` by one."

    Design: Difficulty/non_linear_state_machine/headnote_reject_resubmit_cycle
    """
    doc = create_published_document(
        title="Cycle v. Loop", raw_citation_string="10 N.Y.3d 1", jurisdiction_code="NY",
        decision_date="2026-05-01",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR)
    submit_headnote(headnote["id"], ED_AUTHOR)
    rejected = decide_headnote(headnote["id"], ED_REVIEWER, "REJECT", review_note="Rework the synopsis")
    assert rejected["status"] == "DRAFT"
    assert rejected["reviewer_editor_id"] == ED_REVIEWER
    assert rejected["review_note"] == "Rework the synopsis"


def test_resubmit_after_reject_then_approve_publishes(api):
    """PRD §3.3: "An approval moves the headnote to `PUBLISHED`; a rejection sends
    it back to `DRAFT`, and the author may revise and resubmit without limit — the
    loop between `DRAFT` and `IN_REVIEW` is unbounded."

    Design: Difficulty/non_linear_state_machine/headnote_reject_resubmit_cycle
    """
    doc = create_published_document(
        title="Cycle v. Loop", raw_citation_string="10 N.Y.3d 1", jurisdiction_code="NY",
        decision_date="2026-05-01",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR)
    submit_headnote(headnote["id"], ED_AUTHOR)
    decide_headnote(headnote["id"], ED_REVIEWER, "REJECT", review_note="Rework the synopsis")

    resubmitted = submit_headnote(headnote["id"], ED_AUTHOR)
    assert resubmitted["status"] == "IN_REVIEW", "the cycle is re-entered after a rejection"

    approved = decide_headnote(headnote["id"], ED_REVIEWER, "APPROVE", review_note="Looks good")
    assert approved["status"] == "PUBLISHED"
    assert approved["review_note"] == "Looks good"
    assert approved["reviewer_editor_id"] == ED_REVIEWER


def test_decide_approve_sets_reviewer_and_note(api):
    """PRD §3.3: "Both branches record `reviewer_editor_id` from the caller's header
    and store the supplied `review_note`, and each transition increments the
    headnote's `version` by one."

    Design: Corner/state_machines/decide_approve_sets_reviewer_and_note
    """
    doc = create_published_document(
        title="Side v. Effect", raw_citation_string="40 N.E.3d 1", jurisdiction_code="IL",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR, topic_code="IP")
    created_version = headnote["version"]
    submit_headnote(headnote["id"], ED_AUTHOR)
    decided = decide_headnote(headnote["id"], "ed-reviewer-9", "APPROVE", review_note="thorough")
    assert_headnote(decided)
    assert decided["status"] == "PUBLISHED"
    assert decided["reviewer_editor_id"] == "ed-reviewer-9"
    assert decided["review_note"] == "thorough"
    assert decided["version"] == created_version + 2, (
        "submit and decide each increment the version by exactly 1"
    )


def test_submit_on_unpublished_document_rejected(api):
    """PRD §3.3: "Submitting also requires the underlying document to be `PUBLISHED`
    and `PUBLIC` — a document still in `RECEIVED` ingestion yields
    `ERR_DOCUMENT_NOT_PUBLISHED` (HTTP 409), and one whose visibility is `SEALED`
    or `REMOVED` yields `ERR_DOCUMENT_SEALED` (HTTP 409), with the not-published
    check firing first per §2.9."

    Design: Difficulty/cross_entity_state_dependency/headnote_submit_gated_by_document_ingestion
    """
    set_clock(CLOCK_SEP_05)
    doc = create_document(
        source_type="AGENCY", jurisdiction_code="US", document_type="REGULATION",
        title="Unpublished Reg", raw_citation_string="82 Fed. Reg. 100", decision_date="2026-04-01",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR, topic_code="TAX")
    resp = api.submit_headnote(headnote["id"], make_attorney_editor_headers(ED_AUTHOR))
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_PUBLISHED, 409)


def test_submit_on_unpublished_document_leaves_draft(api):
    """PRD §3.3: "A headnote not currently in `DRAFT` cannot be submitted
    (`ERR_INVALID_STATE`)."
    PRD §3.3: "Submitting also requires the underlying document to be `PUBLISHED`
    and `PUBLIC` — a document still in `RECEIVED` ingestion yields
    `ERR_DOCUMENT_NOT_PUBLISHED` (HTTP 409), and one whose visibility is `SEALED`
    or `REMOVED` yields `ERR_DOCUMENT_SEALED` (HTTP 409), with the not-published
    check firing first per §2.9."

    Design: Difficulty/cross_entity_state_dependency/headnote_submit_gated_by_document_ingestion
    """
    set_clock(CLOCK_SEP_05)
    doc = create_document(
        source_type="AGENCY", jurisdiction_code="US", document_type="REGULATION",
        title="Unpublished Reg", raw_citation_string="82 Fed. Reg. 100", decision_date="2026-04-01",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR, topic_code="TAX")
    resp = api.submit_headnote(headnote["id"], make_attorney_editor_headers(ED_AUTHOR))
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_NOT_PUBLISHED, 409)
    after = get_headnote(headnote["id"])
    assert after["status"] == "DRAFT", "a rejected submit must not move the headnote"
    assert after["version"] == headnote["version"]


def test_submit_on_sealed_document_rejected(api):
    """PRD §3.3: "Submitting also requires the underlying document to be `PUBLISHED`
    and `PUBLIC` — a document still in `RECEIVED` ingestion yields
    `ERR_DOCUMENT_NOT_PUBLISHED` (HTTP 409), and one whose visibility is `SEALED`
    or `REMOVED` yields `ERR_DOCUMENT_SEALED` (HTTP 409), with the not-published
    check firing first per §2.9."

    Design: Corner/validations/suspended_subscription_blocks_headnote_workflows_via_document_seal
    """
    set_clock(CLOCK_SEP_05)
    doc = create_published_document(
        title="Sealed v. Submit", raw_citation_string="80 P.3d 7", jurisdiction_code="NV",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR, topic_code="FAMILY")
    seal_document(doc["id"], scope="SEAL", effective_from="2026-09-01",
                  effective_until="2026-09-30", reason="seal")
    assert get_document(doc["id"])["visibility_status"] == "SEALED"
    resp = api.submit_headnote(headnote["id"], make_attorney_editor_headers(ED_AUTHOR))
    validate_error(resp, ApiErrorId.ERR_DOCUMENT_SEALED, 409)
    assert get_headnote(headnote["id"])["status"] == "DRAFT"


def test_headnote_submit_by_non_author_forbidden(api):
    """PRD §3.3: "Submission is personal: if the caller's `X-User-ID` differs from
    the headnote's `author_editor_id`, the request is rejected with
    `ERR_NOT_HEADNOTE_AUTHOR` (HTTP 403)."

    Design: Corner/rbac/headnote_submit_by_non_author_forbidden
    """
    doc = create_published_document(
        title="Own v. Author", raw_citation_string="95 P.3d 3", jurisdiction_code="CO",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR, topic_code="TAX")
    resp = api.submit_headnote(headnote["id"], make_attorney_editor_headers(ED_REVIEWER))
    validate_error(resp, ApiErrorId.ERR_NOT_HEADNOTE_AUTHOR, 403)
    assert get_headnote(headnote["id"])["status"] == "DRAFT"


def test_reviewer_is_author_rejected_on_in_review(api):
    """PRD §3.3: "Segregation of duties is absolute: the reviewer's `X-User-ID` must
    differ from `author_editor_id`, and a self-review is rejected with
    `ERR_REVIEWER_IS_AUTHOR` (HTTP 422)."

    Design: Corner/rbac/reviewer_is_author_rejected_on_in_review
    """
    doc = create_published_document(
        title="SoD v. Self", raw_citation_string="96 P.3d 4", jurisdiction_code="OR",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR, topic_code="IP")
    submit_headnote(headnote["id"], ED_AUTHOR)
    resp = api.decide_headnote(
        headnote["id"],
        {"decision": "APPROVE", "review_note": "self"},
        make_attorney_editor_headers(ED_AUTHOR),
    )
    validate_error(resp, ApiErrorId.ERR_REVIEWER_IS_AUTHOR, 422)
    after = get_headnote(headnote["id"])
    assert after["status"] == "IN_REVIEW"
    assert after["reviewer_editor_id"] is None


def test_decide_on_draft_reports_invalid_state_not_safety(api):
    """PRD §2.9: "With every identifier resolved, current-state legality is
    evaluated: the generic transition check (`ERR_INVALID_STATE`) first, then the
    editorial document gates (`ERR_DOCUMENT_NOT_PUBLISHED` before
    `ERR_DOCUMENT_SEALED`), then `ERR_SUBSCRIPTION_NOT_ACTIVE`,
    `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_INVOICE_PERIOD_CLOSED`,
    `ERR_SEAT_ALREADY_HELD`, and `ERR_NO_SEAT_HELD`, in that order. Business-safety
    gates come next — segregation of duties (`ERR_REVIEWER_IS_AUTHOR`), bulk-rate
    limits (`ERR_BULK_RATE_EXCEEDED`), and scope enforcement
    (`ERR_USAGE_OUT_OF_SCOPE`)"

    Design: Difficulty/priority_pair_validation_conflict/decide_state_precedes_safety
    """
    set_clock(CLOCK_SEP_05)
    doc = create_published_document(
        title="Prio v. Pair", raw_citation_string="800 S.W.3d 1", jurisdiction_code="TX",
        decision_date="2026-03-01",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR, topic_code="CORPORATE")
    # The author attempts decide on a DRAFT headnote: both the from-state gate
    # (must be IN_REVIEW) and segregation of duties are violated; state wins.
    resp = api.decide_headnote(
        headnote["id"],
        {"decision": "APPROVE", "review_note": "self approve"},
        make_attorney_editor_headers(ED_AUTHOR),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)


def test_decide_on_draft_leaves_no_side_effects(api):
    """PRD §2.9: "With every identifier resolved, current-state legality is
    evaluated: the generic transition check (`ERR_INVALID_STATE`) first, then the
    editorial document gates (`ERR_DOCUMENT_NOT_PUBLISHED` before
    `ERR_DOCUMENT_SEALED`), then `ERR_SUBSCRIPTION_NOT_ACTIVE`,
    `ERR_AGREEMENT_NOT_ACTIVE`, `ERR_INVOICE_PERIOD_CLOSED`,
    `ERR_SEAT_ALREADY_HELD`, and `ERR_NO_SEAT_HELD`, in that order. Business-safety
    gates come next — segregation of duties (`ERR_REVIEWER_IS_AUTHOR`), bulk-rate
    limits (`ERR_BULK_RATE_EXCEEDED`), and scope enforcement
    (`ERR_USAGE_OUT_OF_SCOPE`)"

    Design: Difficulty/priority_pair_validation_conflict/decide_state_precedes_safety
    """
    set_clock(CLOCK_SEP_05)
    doc = create_published_document(
        title="Prio v. Pair", raw_citation_string="800 S.W.3d 1", jurisdiction_code="TX",
        decision_date="2026-03-01",
    )
    headnote = create_headnote(doc["id"], ED_AUTHOR, topic_code="CORPORATE")
    resp = api.decide_headnote(
        headnote["id"],
        {"decision": "APPROVE", "review_note": "self approve"},
        make_attorney_editor_headers(ED_AUTHOR),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, 409)
    after = get_headnote(headnote["id"])
    assert after["status"] == "DRAFT"
    assert after["reviewer_editor_id"] is None
    assert after["version"] == headnote["version"]


def test_headnote_retraction_survives_order_reversal(api):
    """PRD §3.8: "Headnotes are the explicit exception: retraction is not
    compensated, and retracted headnotes remain `RETRACTED` after reversal."
    PRD §3.3: "When a compliance cascade seals or removes the underlying document
    (§3.8), every `PUBLISHED` headnote on that document flips to `RETRACTED`."

    Design: Corner/state_machines/headnote_retraction_survives_order_reversal
    """
    set_clock(CLOCK_SEP_05)
    doc = create_published_document(
        title="Asym v. Retract", raw_citation_string="50 N.E.3d 9", jurisdiction_code="OH",
    )
    headnote = create_published_headnote(doc["id"], ED_AUTHOR, ED_REVIEWER)
    assert headnote["status"] == "PUBLISHED"
    set_clock(CLOCK_SEP_15)
    order = seal_document(doc["id"], scope="SEAL", reason="seal then lift")
    assert get_headnote(headnote["id"])["status"] == "RETRACTED"

    reverse_removal_order(order["id"])
    assert get_document(doc["id"])["visibility_status"] == "PUBLIC"
    assert get_headnote(headnote["id"])["status"] == "RETRACTED", (
        "retraction is terminal: reversal does not restore headnotes"
    )
