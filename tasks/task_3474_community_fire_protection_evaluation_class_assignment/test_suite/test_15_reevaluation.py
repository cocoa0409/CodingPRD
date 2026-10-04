"""Reevaluation requests: the community grading loop and filing gates."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    activate_classification,
    advance_cycle_to,
    approve_reevaluation_request,
    begin_field_reverification,
    create_score_sheet,
    evidence_item,
    file_reevaluation_request,
    finalize_score_sheet,
    get_community,
    get_success_data,
    make_community_official_headers,
    open_documentation_review,
    patch_request_evidence,
    publish_classification,
    reevaluation_request_payload,
    return_request_for_docs,
    set_clock,
    setup_classified_community,
    transition_cycle,
    validate_error,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]


def _classified_then_clock_forward(api, name):
    """CLASSIFIED community (effective 2026-09-01) with the clock at
    2027-09-02 — twelve months plus a day past the effective date."""
    ctx = setup_classified_community(api, name=name, effective_from="2026-09-01")
    set_clock(api, "2027-09-02T00:00:00Z")
    return ctx


def _drive_reevaluation_loop(api, ctx):
    """File -> review -> approve -> rescore the spawned cycle -> activate."""
    community_id = ctx["community"]["id"]
    request = file_reevaluation_request(api, community_id, justification="New tanker and training program completed")
    open_documentation_review(api, request["id"])
    begin_field_reverification(api, request["id"])
    approved = approve_reevaluation_request(api, request["id"], community_id, field_analyst_id="analyst-2")
    assert approved["status"] == "APPROVED"
    after_approval = get_community(api, community_id)
    assert after_approval["status"] == "UNDER_REEVALUATION"
    spawned = get_success_data(
        api.list_evaluation_cycles(COORD, params={"community_id": community_id, "status": "SCHEDULED"})
    )
    assert len(spawned) == 1, "approval spawns exactly one new evaluation cycle"
    cycle2 = spawned[0]
    advance_cycle_to(api, cycle2["id"], "SCORING")
    sheet2 = create_score_sheet(api, cycle2["id"], analyst_id="analyst-2")
    finalize_score_sheet(api, sheet2["id"], analyst_id="analyst-2")
    transition_cycle(api, cycle2["id"], "CLASSIFICATION_REVIEW")
    cl2 = publish_classification(api, cycle2["id"], sheet2["id"])
    activate_classification(api, cl2["id"], effective_from="2027-09-02")
    return approved, cl2


def test_reevaluation_loop_returns_community_to_classified(api):
    """PRD §3.9: "Approval moves the community to `UNDER_REEVALUATION`" and
    §3.7's activation cascade moves it back: the community traverses
    REEVALUATION_REQUESTED then UNDER_REEVALUATION and rests CLASSIFIED
    again once the replacement classification activates.

    Design: Difficulty/non_linear_state_machine/community_reevaluation_loop_classified_to_classified
    """
    ctx = _classified_then_clock_forward(api, "Loopville")
    community_id = ctx["community"]["id"]
    request, cl2 = _drive_reevaluation_loop(api, ctx)
    assert request["status"] == "APPROVED"
    community = get_community(api, community_id)
    assert community["status"] == "CLASSIFIED"
    assert get_success_data(api.get_classification(cl2["id"], COORD))["status"] == "EFFECTIVE"


def test_reevaluation_loop_supersedes_prior_classification(api):
    """PRD §3.7: "the community's prior `EFFECTIVE` classification, if any,
    becomes `SUPERSEDED` with its `effective_until` set to the new
    `effective_from`" and "`next_evaluation_due_date` set to `effective_from`
    plus sixty calendar months (five years)" — 2027-09-02 plus sixty months
    is 2032-09-02.

    Design: Difficulty/non_linear_state_machine/community_reevaluation_loop_classified_to_classified
    """
    ctx = _classified_then_clock_forward(api, "Loopville")
    community_id = ctx["community"]["id"]
    _drive_reevaluation_loop(api, ctx)
    cl1 = get_success_data(api.get_classification(ctx["classification"]["id"], COORD))
    assert cl1["status"] == "SUPERSEDED"
    assert cl1["effective_until"] == "2027-09-02"
    community = get_community(api, community_id)
    assert community["current_class_number"] == 10
    assert community["next_evaluation_due_date"] == "2032-09-02"


def test_request_return_for_docs_revert_loop(api):
    """PRD §3.9: "An `EvaluationCoordinator` moves `SUBMITTED` to
    `DOCUMENTATION_REVIEW`, and may return it to `SUBMITTED` for more
    documentation — after which the official replaces the request's
    `evidence_items` while it is `SUBMITTED`, the only state in which
    evidence may be patched."

    Design: Corner/state_machines/request_return_for_docs_revert_loop
    """
    ctx = _classified_then_clock_forward(api, "Loop Request")
    community_id = ctx["community"]["id"]
    request = file_reevaluation_request(
        api, community_id, justification="tanker purchased",
        evidence_items=[evidence_item("INVOICE", "s3://docs/i1.pdf")],
    )
    open_documentation_review(api, request["id"])
    returned = return_request_for_docs(api, request["id"], note="need flow test records")
    assert returned["status"] == "SUBMITTED"
    patched = patch_request_evidence(
        api, request["id"], community_id,
        [evidence_item("INVOICE", "s3://docs/i1.pdf"), evidence_item("FLOW_TEST_RECORD", "s3://docs/f1.pdf")],
    )
    assert len(patched["evidence_items"]) == 2
    reopened = open_documentation_review(api, request["id"])
    assert reopened["status"] == "DOCUMENTATION_REVIEW", "the revert loop is repeatable"
    resp = api.patch_reevaluation_request(
        request["id"], {"evidence_items": [evidence_item("LATE", "s3://docs/x.pdf")]},
        make_community_official_headers(community_id),
    )
    validate_error(resp, ApiErrorId.ERR_REQUEST_INVALID_STATE)


def test_reevaluation_too_early_at_default_clock(api):
    """PRD §3.9: "the logical clock date must have reached twelve calendar
    months past the current effective classification's `effective_from`
    (earlier filings are `ERR_REEVALUATION_TOO_EARLY`, HTTP 422)" and
    PRD §2.4: "Before the clock has ever been set, it reads exactly
    2026-09-01T00:00:00Z."

    Design: Corner/validations/reevaluation_too_early_at_default_clock
    """
    ctx = setup_classified_community(api, name="TooEarly", effective_from="2026-09-01")
    community_id = ctx["community"]["id"]
    resp = api.create_reevaluation_request(
        reevaluation_request_payload(community_id, justification="improvements done"),
        make_community_official_headers(community_id),
    )
    validate_error(resp, ApiErrorId.ERR_REEVALUATION_TOO_EARLY)


def test_request_create_empty_evidence_returns_invalid_request(api):
    """PRD §3.9: "`evidence_items` — documentation entries each pairing a
    document type with a reference URI — of which at least one item is
    required (an empty list is `ERR_INVALID_REQUEST`)."

    Design: Corner/validations/request_create_empty_evidence_returns_invalid_request
    """
    ctx = _classified_then_clock_forward(api, "NoDocs")
    community_id = ctx["community"]["id"]
    resp = api.create_reevaluation_request(
        reevaluation_request_payload(community_id, justification="no docs attached", evidence_items=[]),
        make_community_official_headers(community_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
