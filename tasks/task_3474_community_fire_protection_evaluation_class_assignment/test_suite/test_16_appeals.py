"""Appeals: the dispute-rescore loop, evidence reverts, and duplicate filings."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    adjudicate_revised,
    appeal_payload,
    begin_data_verification,
    create_score_sheet,
    evidence_item,
    file_appeal,
    finalize_score_sheet,
    get_cycle,
    get_success_data,
    make_community_official_headers,
    return_appeal_for_evidence,
    setup_published_classification,
    transition_cycle,
    validate_error,
    withdraw_appeal,
)

COORD = TEST_USERS["evaluation_coordinator_headers"]


def _disputia(api):
    """PUBLISHED classification, an appeal in DATA_VERIFICATION, and the
    DISPUTED cycle reworked back to CLASSIFICATION_REVIEW with a FINAL
    replacement sheet."""
    ctx = setup_published_classification(api, name="Disputia")
    community_id = ctx["community"]["id"]
    cycle_id = ctx["cycle"]["id"]
    appeal = file_appeal(
        api, ctx["classification"]["id"], community_id, grounds="DATA_ERROR",
        evidence_items=[evidence_item("FLOW_TEST_AMENDMENT", "s3://docs/a1.pdf")],
    )
    assert get_cycle(api, cycle_id)["status"] == "DISPUTED", "filing disputes the cycle"
    begin_data_verification(api, appeal["id"])
    transition_cycle(api, cycle_id, "FIELD_VERIFICATION")
    transition_cycle(api, cycle_id, "SCORING")
    sheet2 = create_score_sheet(api, cycle_id)
    finalize_score_sheet(api, sheet2["id"])
    transition_cycle(api, cycle_id, "CLASSIFICATION_REVIEW")
    return ctx, appeal, sheet2


def test_dispute_rescore_loop_cycle_and_appeal_states(api):
    """PRD §3.9: "While an appeal on the cycle's classification sits in
    `DATA_VERIFICATION`, the coordinator may return the `DISPUTED` cycle to
    `FIELD_VERIFICATION` for rework" and on adjudication "the cycle returns
    to `PUBLISHED`."

    Design: Difficulty/non_linear_state_machine/cycle_dispute_rescore_loop
    """
    ctx, appeal, sheet2 = _disputia(api)
    adjudicated = adjudicate_revised(api, appeal["id"], sheet2["id"], registrar_id="registrar-2")
    assert adjudicated["status"] == "ADJUDICATED_REVISED"
    assert adjudicated["adjudicated_by"] == "registrar-2", "segregated from publisher registrar-1"
    assert get_cycle(api, ctx["cycle"]["id"])["status"] == "PUBLISHED"


def test_dispute_rescore_loop_vacates_and_replaces_classification(api):
    """PRD §3.9: "the appealed classification becomes `VACATED`, the appealed
    classification's former score sheet moves from `FINAL` to `SUPERSEDED`,
    a replacement classification is created in `PUBLISHED` from the new
    sheet with the adjudicating registrar as its `published_by`".

    Design: Difficulty/non_linear_state_machine/cycle_dispute_rescore_loop
    """
    ctx, appeal, sheet2 = _disputia(api)
    adjudicate_revised(api, appeal["id"], sheet2["id"], registrar_id="registrar-2")
    cl1 = get_success_data(api.get_classification(ctx["classification"]["id"], COORD))
    assert cl1["status"] == "VACATED"
    sheet1 = get_success_data(api.get_score_sheet(ctx["sheet"]["id"], COORD))
    assert sheet1["status"] == "SUPERSEDED"
    replacements = get_success_data(
        api.list_classifications(COORD, params={"score_sheet_id": sheet2["id"]})
    )
    assert len(replacements) == 1
    assert replacements[0]["status"] == "PUBLISHED"
    assert replacements[0]["published_by"] == "registrar-2"


def test_appeal_return_for_evidence_revert_loop(api):
    """PRD §3.9: "A `FieldAnalyst` moves a filed appeal to `DATA_VERIFICATION`
    and may return it to `FILED` for more evidence." and "The filing official
    may withdraw a `FILED` appeal, which likewise returns a `DISPUTED` cycle
    to `PUBLISHED`."

    Design: Corner/state_machines/appeal_return_for_evidence_revert_loop
    """
    ctx = setup_published_classification(api, name="Appeal Loop")
    community_id = ctx["community"]["id"]
    appeal = file_appeal(
        api, ctx["classification"]["id"], community_id, grounds="NEW_EVIDENCE",
        evidence_items=[evidence_item("PHOTO", "s3://docs/p.pdf")],
    )
    begin_data_verification(api, appeal["id"])
    returned = return_appeal_for_evidence(api, appeal["id"])
    assert returned["status"] == "FILED", "the evidence revert loop closes"
    withdrawn = withdraw_appeal(api, appeal["id"], community_id)
    assert withdrawn["status"] == "WITHDRAWN"
    assert get_cycle(api, ctx["cycle"]["id"])["status"] == "PUBLISHED"


def test_duplicate_active_appeal_returns_conflict_and_disputes_cycle(api):
    """PRD §3.9: "no other non-terminal appeal may exist on the same
    classification (else `ERR_DUPLICATE_ACTIVE_APPEAL`, HTTP 409)" and "when
    it targets a cycle's `PUBLISHED` classification, the filing moves that
    cycle from `PUBLISHED` to `DISPUTED` and increments the cycle's
    `version`."

    Design: Corner/validations/duplicate_active_appeal_returns_conflict_and_disputes_cycle
    """
    ctx = setup_published_classification(api, name="DupAppeal")
    community_id = ctx["community"]["id"]
    file_appeal(
        api, ctx["classification"]["id"], community_id, grounds="DATA_ERROR",
        evidence_items=[evidence_item("E1", "s3://e1.pdf")],
    )
    assert get_cycle(api, ctx["cycle"]["id"])["status"] == "DISPUTED"
    resp = api.create_appeal(
        appeal_payload(
            ctx["classification"]["id"], community_id, grounds="PROCEDURAL_ERROR",
            evidence_items=[evidence_item("E2", "s3://e2.pdf")],
        ),
        make_community_official_headers(community_id),
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_ACTIVE_APPEAL)
