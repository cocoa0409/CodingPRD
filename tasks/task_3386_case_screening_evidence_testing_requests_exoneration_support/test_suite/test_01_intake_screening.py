"""Intake creation defaults, the ACCEPT screening-criteria gate, segregation
of duties on decide, and terminal lockdown of a decided intake request."""
import pytest

from test_helpers import (
    ApiErrorId,
    SECOND_MANAGING_ATTORNEY_ID,
    TEST_USERS,
    advance_intake,
    create_client,
    create_intake_request,
    create_intake_request_payload,
    create_jurisdiction,
    decide_intake,
    decide_payload,
    get_intake_request,
    intake_advance_payload,
    is_valid_uuid,
    make_managing_attorney_headers,
    setup_accepted_case,
    setup_intake_pipeline,
    validate_created,
    validate_error,
    validate_ok,
)

SPECIALIST = TEST_USERS["intake_specialist_headers"]


def test_intake_create_initializes_screening_fields(api):
    """PRD section 3.1: "A new request lands in `RECEIVED` status."
    PRD section 3.1: "an optional `expedited_review` flag defaulting to false
    that selects which weight profile will govern the frozen waitlist score."
    PRD section 2.6: "a field described as stamped, recorded, or computed by a
    particular event carries null until that event has occurred."

    Design: Corner/entities/intake_create_initializes_screening_fields
    """
    jurisdiction = create_jurisdiction(state_code="VT", name="Vermont")
    client = create_client(full_name="Quentin Abe", inmate_number="VT-11")

    resp = api.create_intake_request(
        create_intake_request_payload(
            client["id"],
            jurisdiction["id"],
            conviction_date="2021-04-01T00:00:00Z",
            conviction_summary="Init-state probe",
            claim_of_actual_innocence=False,
            claim_strength="WEAK",
            evidence_potential="NONE_KNOWN",
            years_served=5,
            health_urgency="NONE",
        ),
        SPECIALIST,
    )
    data = validate_created(resp)
    assert data["status"] == "RECEIVED"
    assert data["expedited_review"] is False
    for field in (
        "screening_score_standard",
        "screening_score_expedited",
        "waitlist_priority_score",
        "recommendation",
        "decision",
        "decided_by_user_id",
        "accepted_case_id",
    ):
        assert data[field] is None, f"{field} must be null on a fresh request"
    assert data["version"] == 1


def test_recommend_accept_requires_screening_criteria(api):
    """PRD section 3.1: "Recommending acceptance is gated on the screening
    criteria: `claim_of_actual_innocence` must be true and `evidence_potential`
    must be `LIKELY_STORED` or `CONFIRMED_STORED`; otherwise the recommendation
    is rejected with `ERR_SCREENING_CRITERIA_NOT_MET` (HTTP 422)."

    Design: Corner/validations/recommend_accept_requires_screening_criteria
    """
    ctx = setup_intake_pipeline(
        jurisdiction_overrides={"state_code": "LA", "name": "Louisiana"},
        intake_overrides={
            "conviction_summary": "Criteria probe",
            "claim_of_actual_innocence": False,
            "claim_strength": "WEAK",
            "evidence_potential": "NONE_KNOWN",
            "years_served": 5,
            "health_urgency": "NONE",
        },
    )
    request_id = ctx["intake"]["id"]
    advance_intake(request_id, "BEGIN_SCREENING")

    resp = api.advance_intake_request(
        request_id, intake_advance_payload("RECOMMEND", "ACCEPT"), SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_SCREENING_CRITERIA_NOT_MET)
    assert get_intake_request(request_id)["status"] == "SCREENING"

    # The gate is ACCEPT-specific: REJECT on the same request proceeds.
    data = validate_ok(
        api.advance_intake_request(
            request_id, intake_advance_payload("RECOMMEND", "REJECT"), SPECIALIST
        )
    )
    assert data["status"] == "DECISION_PENDING"
    assert data["recommendation"] == "REJECT"


def test_decide_self_approval_blocked(api):
    """PRD section 3.2: "the deciding attorney's `X-User-ID` must differ from
    the `recommended_by_user_id` recorded at recommendation time. A
    self-decision is rejected with `ERR_DECISION_SELF_APPROVAL` (HTTP 403)."

    Design: Corner/validations/decide_self_approval_blocked
    """
    ctx = setup_intake_pipeline(
        jurisdiction_overrides={"state_code": "NC", "name": "North Carolina"},
        recommendation="ACCEPT",
        specialist_id="hybrid_1",
    )
    request_id = ctx["intake"]["id"]
    assert ctx["intake"]["recommended_by_user_id"] == "hybrid_1"

    resp = api.decide_intake_request(
        request_id,
        decide_payload("ACCEPTED"),
        make_managing_attorney_headers("hybrid_1"),
    )
    validate_error(resp, ApiErrorId.ERR_DECISION_SELF_APPROVAL)
    # The failed decide leaves the request DECISION_PENDING (no partial mutation).
    assert get_intake_request(request_id)["status"] == "DECISION_PENDING"

    data = decide_intake(
        request_id, "ACCEPTED", decider_id=SECOND_MANAGING_ATTORNEY_ID
    )
    assert data["decision"] == "ACCEPTED"
    assert data["decided_by_user_id"] == SECOND_MANAGING_ATTORNEY_ID
    assert is_valid_uuid(data["accepted_case_id"])


def test_accepted_intake_is_terminal_for_advance(api):
    """PRD section 3.2: "The intake request's `accepted_case_id` is set to the
    new case's id, and `ACCEPTED` is terminal for the request."
    PRD section 3.1: "Requesting a transition from a status that does not admit
    it — for example, beginning screening twice — is rejected with
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/accepted_intake_is_terminal_for_advance
    """
    ctx = setup_accepted_case(
        jurisdiction_overrides={"state_code": "ID", "name": "Idaho"}
    )
    request_id = ctx["intake"]["id"]
    assert ctx["intake"]["status"] == "ACCEPTED"

    resp = api.advance_intake_request(
        request_id, intake_advance_payload("REQUEST_MORE_INFO"), SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_intake_request(request_id)["status"] == "ACCEPTED"
