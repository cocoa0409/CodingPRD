"""Sub-resource reads and conditional workflow actions (PRD §3.5–§3.9)."""
from test_helpers import (
    APPEALS,
    ApiErrorId,
    PANEL,
    api_client,
    assert_brief,
    assert_final_written_decision,
    create_amendment_motion,
    create_amendment_motion_payload,
    decide_appeal,
    file_brief,
    file_petitioner_reply,
    file_po_response,
    file_po_sur_reply,
    get_proceeding,
    get_success_data,
    issue_final_decision,
    outcomes_payload,
    request_hearing,
    resolve_amendment_motion,
    resolve_hearing,
    schedule_hearing,
    set_clock,
    setup_decided_with_appeal,
    setup_decision_phase,
    setup_instituted_proceeding,
    substitute_claim,
    validate_error,
)


def test_briefs_subresource_lists_type_cycle_and_fee():
    """PRD §3.5: "Every accepted brief records its `proceeding_id` from the
    filing path, its `brief_type`, the filer's identity as `author_user_id`,
    the `page_count`, the computed `overage_fee_cents`, and the `cycle` — the
    proceeding's `briefing_cycle` at filing time."

    Design: Corner/endpoints/briefs_subresource_lists_type_cycle_and_fee
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-sara2",
    )
    file_po_response(world, 91)       # 1 overage page -> 316
    file_petitioner_reply(world, 45)  # exactly at the fee-free limit -> 0
    file_po_sur_reply(world, 21)      # 1 overage page -> 316
    briefs = get_success_data(api_client.list_briefs(world["proceeding"]["id"],
                                                     PANEL))
    assert len(briefs) == 3
    for brief in briefs:
        assert_brief(brief)
        assert brief["cycle"] == 0
    fees = {b["brief_type"]: b["overage_fee_cents"] for b in briefs}
    assert fees == {"PO_RESPONSE": 316, "PETITIONER_REPLY": 0,
                    "PO_SUR_REPLY": 316}
    assert {b["brief_type"] for b in briefs} == {
        "PO_RESPONSE", "PETITIONER_REPLY", "PO_SUR_REPLY"
    }
    assert get_proceeding(world["proceeding"]["id"])[
        "total_overage_fee_cents"
    ] == 632


def test_final_decisions_subresource_accumulates_one_record_per_remand_cycle():
    """PRD §3.8: "exactly one decision may issue per cycle" — and the
    decisions endpoint lists "final written decisions of a proceeding (one
    per cycle)" (PRD §4), so after a remand and a second trial round the
    sub-resource holds one immutable record per cycle.

    Design: Corner/endpoints/final_decisions_subresource_accumulates_one_record_per_remand_cycle
    """
    world = setup_decided_with_appeal(
        institute_kw=dict(
            total_claims=2, challenged_claims=(1, 2),
            scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80},
                    {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 70}],
            lead_judge="judge-tara",
        ),
        outcomes=outcomes_payload((1, "UNPATENTABLE"), (2, "NOT_UNPATENTABLE")),
    )
    fwd0_id = world["fwd"]["id"]
    set_clock("2027-08-01T00:00:00Z")
    decide_appeal(world["appeal"]["id"], "VACATED_AND_REMANDED",
                  remand_instructions="REOPEN_RECORD")
    # Cycle 1 reruns the choreography from the remand anchor (2027-08-01).
    file_po_response(world, 55)
    file_petitioner_reply(world, 28)
    hearing = request_hearing(world["proceeding"]["id"],
                              world["petitioner_headers"])
    schedule_hearing(hearing["id"], world["room"]["id"],
                     "2027-08-15T10:00:00Z", "2027-08-15T11:00:00Z")
    resolve_hearing(hearing["id"], "WAIVED", world["petitioner_headers"])
    set_clock("2027-08-20T00:00:00Z")  # within the (unextended) 2027-09-01 due
    fwd1 = issue_final_decision(
        world["proceeding"]["id"],
        outcomes_payload((1, "NOT_UNPATENTABLE"), (2, "NOT_UNPATENTABLE")),
    )
    assert get_proceeding(world["proceeding"]["id"])["phase"] == "DECIDED"
    records = get_success_data(
        api_client.list_final_decisions(world["proceeding"]["id"], APPEALS)
    )
    assert len(records) == 2
    for record in records:
        assert_final_written_decision(record)
    by_id = {r["id"]: r for r in records}
    assert by_id[fwd0_id]["cycle"] == 0
    assert by_id[fwd1["id"]]["cycle"] == 1
    # The cycle-0 record is an immutable original: it still shows claim 1
    # UNPATENTABLE even though the cycle-1 decision superseded it.
    cycle0_outcomes = {o["claim_number"]: o["outcome"]
                       for o in by_id[fwd0_id]["outcomes"]}
    assert cycle0_outcomes == {1: "UNPATENTABLE", 2: "NOT_UNPATENTABLE"}


def test_waived_hearing_moves_proceeding_to_decision_phase():
    """PRD §3.7: "A hearing held or waived moves the proceeding from
    `HEARING_PHASE` to `DECISION_PHASE`."

    Design: Corner/endpoints/waived_hearing_moves_proceeding_to_decision_phase
    """
    world = setup_instituted_proceeding(
        total_claims=2, challenged_claims=(1,),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80}],
        lead_judge="judge-uma",
    )
    world = setup_decision_phase(
        world, hearing_outcome="WAIVED", waive_headers=world["owner_headers"],
        hearing_start="2027-02-10T09:00:00Z", hearing_end="2027-02-10T10:00:00Z",
        file_reply=False,
    )
    hearing = get_success_data(
        api_client.get_oral_hearing(world["hearing"]["id"], PANEL)
    )
    assert hearing["status"] == "WAIVED"
    assert world["proceeding"]["phase"] == "DECISION_PHASE"


def test_denied_amendment_motion_keeps_its_slot_consumed():
    """PRD §3.6: "A denial spends the motion of right: the amendment slot
    stays consumed."

    Design: Corner/endpoints/denied_amendment_motion_keeps_its_slot_consumed
    """
    world = setup_instituted_proceeding(
        total_claims=3, challenged_claims=(1, 2),
        scores=[{"claim_number": 1, "basis": "ANTICIPATION_102", "score": 80},
                {"claim_number": 2, "basis": "OBVIOUSNESS_103", "score": 70}],
        lead_judge="judge-vlad",
    )
    motion = create_amendment_motion(
        world["proceeding"]["id"], world["owner_headers"], (1,)
    )
    denied = resolve_amendment_motion(
        motion["id"], "DENIED", PANEL,
        rationale="Substitute fails to respond to the instituted obviousness "
                  "ground.",
    )
    assert denied["status"] == "DENIED"
    # Unlike withdrawal, denial does NOT return the slot.
    resp = api_client.create_amendment_motion(
        world["proceeding"]["id"],
        create_amendment_motion_payload([substitute_claim(2)]),
        world["owner_headers"],
    )
    validate_error(resp, ApiErrorId.ERR_AMENDMENT_QUOTA_EXCEEDED, 422)
