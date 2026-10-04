"""Trial-phase domain constraint corners: page caps, new-evidence limits,
amendment quotas, outcome-set coverage, and the scheduling interval
(PRD §3.5–§3.8).
"""
from test_helpers import (
    ApiErrorId,
    PANEL,
    api_client,
    create_amendment_motion,
    create_amendment_motion_payload,
    create_brief_payload,
    create_declaration_payload,
    create_hearing_room,
    file_brief,
    file_petitioner_reply,
    file_po_response,
    get_proceeding,
    request_hearing,
    resolve_amendment_motion,
    schedule_payload,
    setup_decision_phase,
    setup_instituted_proceeding,
    substitute_claim,
    validate_error,
)


def test_po_response_over_hard_cap_rejected():
    """PRD §3.5: "Hard caps bind absolutely: a `PO_RESPONSE` above 110 pages,
    a `PETITIONER_REPLY` above 65 pages, or a `PO_SUR_REPLY` above 40 pages
    is rejected with `ERR_PAGE_LIMIT_EXCEEDED`".

    Design: Corner/validations/po_response_over_hard_cap_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 70}],
        lead_judge="judge-beth",
    )
    resp = api_client.create_brief(
        world["proceeding"]["id"],
        create_brief_payload("PO_RESPONSE", 111),
        world["owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_PAGE_LIMIT_EXCEEDED, 422)
    proceeding = get_proceeding(world["proceeding"]["id"])
    assert proceeding["phase"] == "INSTITUTED"
    assert proceeding["total_overage_fee_cents"] == 0


def test_new_evidence_declaration_on_petitioner_reply_rejected():
    """PRD §3.5: "a declaration whose `contains_new_evidence` is true
    attached to a `PETITIONER_REPLY` brief is rejected with
    `ERR_NEW_EVIDENCE_IN_REPLY`; declarations attached to patent-owner briefs
    may introduce new evidence freely."

    Design: Corner/validations/new_evidence_declaration_on_petitioner_reply_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 72}],
        lead_judge="judge-cory",
    )
    po = file_po_response(world, 60)
    reply = file_petitioner_reply(world, 30)
    resp = api_client.create_expert_declaration(
        reply["id"],
        create_declaration_payload(declarant_name="Dr. Rao", page_count=15,
                                   contains_new_evidence=True),
        world["petitioner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_NEW_EVIDENCE_IN_REPLY, 422)
    # The identical declaration on the PO_RESPONSE is accepted.
    ok = api_client.create_expert_declaration(
        po["id"],
        create_declaration_payload(declarant_name="Dr. Rao", page_count=15,
                                   contains_new_evidence=True),
        world["owner_headers"],
    )
    assert ok.status_code == 201


def test_substitute_claim_outside_instituted_set_rejected():
    """PRD §3.6: "every original must lie among the proceeding's
    `instituted_claims` (`ERR_SUBSTITUTE_CLAIM_MISMATCH`)".

    Design: Corner/validations/substitute_claim_outside_instituted_set_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=5, challenged_claims=(1, 2, 3),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 75}],
        lead_judge="judge-drew",
    )
    # Claim 4 exists on the patent but is outside the instituted set [1,2,3].
    resp = api_client.create_amendment_motion(
        world["proceeding"]["id"],
        create_amendment_motion_payload([substitute_claim(4)]),
        world["owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_SUBSTITUTE_CLAIM_MISMATCH, 422)
    assert get_proceeding(world["proceeding"]["id"])[
        "amendment_slots_available"
    ] == 1


def test_amendment_volume_beyond_instituted_claim_count_rejected():
    """PRD §3.6: "the number of substitutes may not exceed the number of
    instituted claims (`ERR_AMENDMENT_VOLUME_EXCEEDED`)".

    Design: Corner/validations/amendment_volume_beyond_instituted_claim_count_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=4, challenged_claims=(1, 2),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 75}],
        lead_judge="judge-eliot",
    )
    subs = [substitute_claim(1), substitute_claim(2),
            {"original_claim_number": 2,
             "substitute_text": "2. (second substitute) ..."}]
    resp = api_client.create_amendment_motion(
        world["proceeding"]["id"],
        create_amendment_motion_payload(subs),
        world["owner_headers"],
    )
    # 3 substitutes against 2 instituted claims.
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_VOLUME_EXCEEDED, 422)


def test_decision_outcome_set_missing_an_instituted_claim_rejected():
    """PRD §3.8: "The set must cover every instituted claim exactly once — no
    claim outside the instituted set, no duplicates — and every claim
    carrying a granted substitute must be marked `AMENDED_SUBSTITUTED`; any
    deviation is `ERR_OUTCOME_SET_INVALID`."

    Design: Corner/validations/decision_outcome_set_missing_an_instituted_claim_rejected
    """
    world = setup_decision_phase(
        setup_instituted_proceeding(
            total_claims=3, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 70}],
            lead_judge="judge-nell",
        ),
        hearing_outcome="HELD",
    )
    # Claim 2 is left uncovered.
    resp = api_client.create_final_decision(
        world["proceeding"]["id"],
        {"outcomes": [{"claim_number": 1, "outcome": "UNPATENTABLE"}]},
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_OUTCOME_SET_INVALID, 422)
    assert get_proceeding(world["proceeding"]["id"])["phase"] == "DECISION_PHASE"


def test_outcome_unpatentable_on_granted_substitute_claim_rejected():
    """PRD §3.8: "every claim carrying a granted substitute must be marked
    `AMENDED_SUBSTITUTED`; any deviation is `ERR_OUTCOME_SET_INVALID`."

    Design: Corner/validations/outcome_unpatentable_on_granted_substitute_claim_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=3, challenged_claims=(1, 2),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80},
                {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 70}],
        lead_judge="judge-opal",
    )
    motion = create_amendment_motion(
        world["proceeding"]["id"], world["owner_headers"], (1,)
    )
    resolve_amendment_motion(
        motion["id"], "GRANTED", PANEL,
        rationale="Substitute narrows claim 1 and is responsive under "
                  "PHILLIPS.",
    )
    world = setup_decision_phase(world, hearing_outcome="HELD")
    # Claim 1 has a GRANTED substitute: UNPATENTABLE contradicts the record.
    resp = api_client.create_final_decision(
        world["proceeding"]["id"],
        {"outcomes": [{"claim_number": 1, "outcome": "UNPATENTABLE"},
                      {"claim_number": 2, "outcome": "NOT_UNPATENTABLE"}]},
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_OUTCOME_SET_INVALID, 422)


def test_hearing_interval_with_end_not_after_start_rejected():
    """PRD §3.7: "`end_at` must be strictly after `start_at`
    (`ERR_INVALID_INTERVAL`)".

    Design: Corner/validations/hearing_interval_with_end_not_after_start_rejected
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-pete",
    )
    file_po_response(world, 50)
    room = create_hearing_room(name="Room RAL")
    hearing = request_hearing(world["proceeding"]["id"],
                              world["petitioner_headers"])
    resp = api_client.schedule_oral_hearing(
        hearing["id"],
        schedule_payload(room["id"], "2027-02-01T09:00:00Z",
                         "2027-02-01T09:00:00Z"),
        PANEL,
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_INTERVAL, 422)
