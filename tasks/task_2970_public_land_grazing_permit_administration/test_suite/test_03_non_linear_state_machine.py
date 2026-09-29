"""The appeal remand cycle: a bounded loop rather than a linear progression."""
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import ApiErrorId, api_client, make_adjudicator_headers, make_officer_headers
from test_helpers import factories as f
from test_helpers.fixtures import (
    create_allotment,
    create_permittee,
    decide_appeal,
    docketed_appeal,
    finalized_assessment,
    get_appeal,
    get_decision,
    signed_decision,
)
from test_helpers.test_users import JUDGE_1, OFFICER_1


def _remand_basin_setup():
    """An allotment and a permittee, a FINAL STOCKING_ADJUSTMENT decision signed by
    u_officer_1 over an assessment authored by u_spec_1, and an appeal docketed by
    u_judge_1 so the case sits in UNDER_REVIEW."""
    allotment = create_allotment(total_permitted_aums=1200, acres=30000)
    permittee = create_permittee()
    assessment = finalized_assessment(allotment["id"], assessment_year=2026)
    decision = signed_decision(
        allotment["id"], signer_user_id=OFFICER_1, decision_type="STOCKING_ADJUSTMENT",
        assessment_id=assessment["id"], adjustment_pct=0.20, nepa_level="EA")
    assert decision["decision_status"] == "FINAL"
    appeal = docketed_appeal(decision["id"], permittee["id"], stay_requested=False,
                             adjudicator_user_id=JUDGE_1)
    return {"allotment": allotment, "permittee": permittee, "assessment": assessment,
            "decision": decision, "appeal": appeal}


def _re_sign(decision_id):
    """The deciding officer signs the remanded decision again, closing the loop."""
    return validate_success(api_client.finalize_decision(
        decision_id, f.finalize_payload(), make_officer_headers(OFFICER_1)))


def test_remand_pushes_the_decision_down_and_re_signature_returns_the_appeal_to_review():
    """One REMAND moves the case to REMANDED with remand_count 1 and drops the decision
    FINAL -> PROPOSED with its deciding officer and rationale nulled; the docket endpoint
    refuses to revive the case, and only the officer's re-signature returns it to
    UNDER_REVIEW with remand_count preserved.

    PRD 3.9: "`REMAND` moves the case to `REMANDED`, increments `remand_count` by 1, and
    pushes the appealed decision back down the chain, `FINAL → PROPOSED`, with
    `deciding_officer_id` and `rationale` both nulled — so the decision must be signed again,
    by an officer who still may not be its author, and the re-signature is what returns this
    same appeal to `UNDER_REVIEW` with its `remand_count` preserved."
    PRD 3.9: "Docketing a case that is not in `appeal_status` `FILED` is
    `ERR_APPEAL_STATE_INVALID`, and in particular a `REMANDED` case is never returned to
    review through this endpoint — it returns only when the deciding officer re-signs the
    remanded decision."

    Design: Difficulty/non_linear_state_machine/appeal_remand_cycle_bounded_at_two
    """
    setup = _remand_basin_setup()
    appeal_id = setup["appeal"]["id"]
    decision_id = setup["decision"]["id"]

    remanded = decide_appeal(appeal_id, "REMAND", adjudicator_user_id=JUDGE_1)
    assert remanded["appeal_status"] == "REMANDED"
    assert remanded["remand_count"] == 1

    pushed_down = get_decision(decision_id)
    assert pushed_down["decision_status"] == "PROPOSED"
    assert pushed_down["deciding_officer_id"] is None
    assert pushed_down["rationale"] is None
    assert pushed_down["nepa_status"] == "COMPLETE", "the remand does not undo the review"

    validate_error(
        api_client.docket_appeal(appeal_id, make_adjudicator_headers(JUDGE_1)),
        ApiErrorId.ERR_APPEAL_STATE_INVALID, 409)

    re_signed = _re_sign(decision_id)
    assert re_signed["decision_status"] == "FINAL"
    assert re_signed["deciding_officer_id"] == OFFICER_1

    reopened = get_appeal(appeal_id)
    assert reopened["appeal_status"] == "UNDER_REVIEW"
    assert reopened["remand_count"] == 1, "the count survives the loop"
    assert reopened["adjudicator_id"] == JUDGE_1


def test_third_remand_is_refused_once_the_count_has_reached_two():
    """After two full REMAND / re-signature traversals the loop is closed: the third remand
    attempt is refused with ERR_APPEAL_REMAND_LIMIT_EXCEEDED, the case stays UNDER_REVIEW
    with remand_count 2, and the decision stays FINAL.

    PRD 3.9: "That loop is bounded: a remand is refused with
    `ERR_APPEAL_REMAND_LIMIT_EXCEEDED` once `remand_count` has reached 2, leaving the
    adjudicator to affirm, reverse or dismiss."
    PRD 3.9: "The case must be in `appeal_status` `UNDER_REVIEW`, else
    `ERR_APPEAL_STATE_INVALID`, and the acting `X-User-ID` must equal `adjudicator_id` — the
    adjudicator who docketed the case is the only one who may decide it, and anyone else is
    `ERR_UNAUTHORIZED`."

    Design: Difficulty/non_linear_state_machine/appeal_remand_cycle_bounded_at_two
    """
    setup = _remand_basin_setup()
    appeal_id = setup["appeal"]["id"]
    decision_id = setup["decision"]["id"]

    first = decide_appeal(appeal_id, "REMAND", adjudicator_user_id=JUDGE_1)
    assert first["remand_count"] == 1
    _re_sign(decision_id)

    second = decide_appeal(appeal_id, "REMAND", adjudicator_user_id=JUDGE_1)
    assert second["remand_count"] == 2
    _re_sign(decision_id)
    assert get_appeal(appeal_id)["appeal_status"] == "UNDER_REVIEW"

    validate_error(
        api_client.decide_appeal(appeal_id, f.appeal_decision_payload("REMAND"),
                                 make_adjudicator_headers(JUDGE_1)),
        ApiErrorId.ERR_APPEAL_REMAND_LIMIT_EXCEEDED, 409)

    unchanged = get_appeal(appeal_id)
    assert unchanged["remand_count"] == 2
    assert unchanged["appeal_status"] == "UNDER_REVIEW"
    assert unchanged["adjudicator_id"] == JUDGE_1

    decision = get_decision(decision_id)
    assert decision["decision_status"] == "FINAL"
    assert decision["deciding_officer_id"] == OFFICER_1


def test_a_bounded_appeal_may_still_be_affirmed_after_two_remands():
    """The bound leaves the other three outcomes open, so the same case that cannot be
    remanded a third time can still be AFFIRMED, which is terminal and clears the stay flag.

    PRD 3.9: "`AFFIRM` moves the case to `appeal_status` `AFFIRMED`, sets `stay_granted` to
    false, and — if the appealed decision is `STAYED` — releases it into effect, running its
    full cascade at that moment."
    PRD 3.9: "`AFFIRMED`, `REVERSED` and `DISMISSED` are terminal."

    Design: Difficulty/non_linear_state_machine/appeal_remand_cycle_bounded_at_two
    """
    setup = _remand_basin_setup()
    appeal_id = setup["appeal"]["id"]
    decision_id = setup["decision"]["id"]

    decide_appeal(appeal_id, "REMAND", adjudicator_user_id=JUDGE_1)
    _re_sign(decision_id)
    decide_appeal(appeal_id, "REMAND", adjudicator_user_id=JUDGE_1)
    _re_sign(decision_id)

    affirmed = decide_appeal(appeal_id, "AFFIRM", adjudicator_user_id=JUDGE_1)
    assert affirmed["appeal_status"] == "AFFIRMED"
    assert affirmed["stay_granted"] is False
    assert affirmed["remand_count"] == 2

    validate_error(
        api_client.decide_appeal(appeal_id, f.appeal_decision_payload("AFFIRM"),
                                 make_adjudicator_headers(JUDGE_1)),
        ApiErrorId.ERR_APPEAL_STATE_INVALID, 409)
    assert get_decision(decision_id)["decision_status"] == "FINAL", (
        "a decision that was never stayed is not released into effect by the affirmance")
