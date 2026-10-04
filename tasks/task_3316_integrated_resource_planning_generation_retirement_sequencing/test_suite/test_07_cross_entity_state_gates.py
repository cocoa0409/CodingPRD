"""Cross-entity state gates: plan status gates commitments and testimony (PRD §3.9, §3.10)."""
from test_helpers import (
    ApiErrorId,
    create_draft_plan_with_basics,
    create_testimony_payload,
    create_plan,
    drive_plan_to_under_review,
    open_plan_for_comment,
    register_candidate,
    register_intervenor,
    set_clock,
    setup_plan_under_review,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01
from test_helpers.fixtures import PLANNER
from test_helpers.test_users import make_intervener_headers


def test_commitment_against_under_review_plan_rejected(api):
    """PRD §3.9: "Issuing a commitment against a plan requires the plan to be in
    `APPROVED` or `APPROVED_WITH_CONDITIONS`; against any other status the issue is
    rejected with `ERR_PLAN_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/commitment_requires_plan_approved
    """
    plan, _portfolio = setup_plan_under_review(plan_name="IRP Gate")
    candidate = register_candidate(candidate_name="K-GATE")

    resp = api.create_commitment(
        plan["id"],
        {"candidate_id": candidate["id"], "committed_mw": 50,
         "solicitation_type": "RFP"},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED)


def test_commitment_against_draft_plan_rejected(api):
    """PRD §3.9: "Issuing a commitment against a plan requires the plan to be in
    `APPROVED` or `APPROVED_WITH_CONDITIONS`; against any other status the issue is
    rejected with `ERR_PLAN_NOT_APPROVED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/commitment_requires_plan_approved
    """
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP Gate0")
    candidate = register_candidate(candidate_name="K-GATE0")

    resp = api.create_commitment(
        plan["id"],
        {"candidate_id": candidate["id"], "committed_mw": 50,
         "solicitation_type": "RFP"},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_APPROVED)

    # No commitment row was created.
    listed = api.list_commitments(plan["id"], PLANNER)
    assert listed.status_code == 200
    assert listed.json()["data"] == []


def test_testimony_against_open_for_comment_plan_rejected(api):
    """PRD §3.10: "Testimony is filed while a plan is `UNDER_REVIEW`, by the intervenor
    acting as itself: the caller's `X-User-ID` must equal the payload's `intervenor_id`,
    and a mismatch — or an intervenor whose `standing_approved` is false — is rejected
    with `ERR_INTERVENOR_NO_STANDING` (HTTP 422); a plan in the wrong status yields
    `ERR_PLAN_NOT_UNDER_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/testimony_requires_plan_under_review
    """
    intervenor = register_intervenor(legal_name="Industrial Energy Consumers")
    set_clock(CLOCK_AUG_01)
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP Gate2")
    open_plan_for_comment(plan["id"])

    resp = api.create_testimony(
        plan["id"],
        create_testimony_payload(intervenor["id"], topic="Premature",
                                 body="Filed before review opened."),
        make_intervener_headers(intervenor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_UNDER_REVIEW)


def test_testimony_against_draft_plan_rejected(api):
    """PRD §3.10: "Testimony is filed while a plan is `UNDER_REVIEW`, by the intervenor
    acting as itself: the caller's `X-User-ID` must equal the payload's `intervenor_id`,
    and a mismatch — or an intervenor whose `standing_approved` is false — is rejected
    with `ERR_INTERVENOR_NO_STANDING` (HTTP 422); a plan in the wrong status yields
    `ERR_PLAN_NOT_UNDER_REVIEW`."

    Design: Difficulty/cross_entity_state_dependency/testimony_requires_plan_under_review
    """
    intervenor = register_intervenor(legal_name="Draft Plan Intervenor")
    plan, _portfolio = create_draft_plan_with_basics(plan_name="IRP Gate3")

    resp = api.create_testimony(
        plan["id"],
        create_testimony_payload(intervenor["id"]),
        make_intervener_headers(intervenor["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_UNDER_REVIEW)
    assert resp.status_code == 409
