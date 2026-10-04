"""The screening information-gathering loop: SCREENING <-> MORE_INFO_REQUESTED
is cyclic, and the cycle closes only via submit-supplement."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    advance_intake,
    intake_advance_payload,
    make_client_headers,
    setup_intake_pipeline,
    submit_supplement,
    validate_error,
)

SPECIALIST = TEST_USERS["intake_specialist_headers"]


def _request_in_screening():
    ctx = setup_intake_pipeline(
        jurisdiction_overrides={"state_code": "NM", "name": "New Mexico"},
        intake_overrides={
            "conviction_date": "2020-01-10T00:00:00Z",
            "conviction_summary": "Cycle probe",
            "claim_strength": "MODERATE",
            "evidence_potential": "UNCERTAIN",
            "years_served": 6,
            "health_urgency": "NONE",
        },
    )
    advance_intake(ctx["intake"]["id"], "BEGIN_SCREENING")
    return ctx


def test_more_info_cycle_requires_supplement_not_rebegin(api):
    """PRD section 3.1: "When the file is incomplete, the specialist requests
    more information, moving it from `SCREENING` to `MORE_INFO_REQUESTED`; the
    request returns to `SCREENING` when a supplement is submitted, an action
    open to the assigned specialist or to the owning `Client`".
    PRD section 3.1: "Requesting a transition from a status that does not admit
    it — for example, beginning screening twice — is rejected with
    `ERR_INVALID_STATE`."

    Design: Difficulty/non_linear_state_machine/intake_more_info_cycle_returns_to_screening
    """
    ctx = _request_in_screening()
    request_id = ctx["intake"]["id"]

    data = advance_intake(request_id, "REQUEST_MORE_INFO")
    assert data["status"] == "MORE_INFO_REQUESTED"

    # BEGIN_SCREENING is illegal from MORE_INFO_REQUESTED: the cycle closes
    # via submit-supplement, not a fresh begin.
    resp = api.advance_intake_request(
        request_id, intake_advance_payload("BEGIN_SCREENING"), SPECIALIST
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    # The owning Client may submit the supplement.
    data = submit_supplement(
        request_id,
        "Trial transcript pages 40-52 attached",
        headers=make_client_headers(ctx["client"]["id"]),
    )
    assert data["status"] == "SCREENING"
    assert data["supplement_notes"] == "Trial transcript pages 40-52 attached"


def test_more_info_cycle_is_repeatable_and_overwrites_notes(api):
    """PRD section 3.1: "the request returns to `SCREENING` when a supplement
    is submitted, an action open to the assigned specialist or to the owning
    `Client`, carrying `supplement_notes` which are stored as the request's
    most recent supplement text."

    Design: Difficulty/non_linear_state_machine/intake_more_info_cycle_returns_to_screening
    """
    ctx = _request_in_screening()
    request_id = ctx["intake"]["id"]

    first = advance_intake(request_id, "REQUEST_MORE_INFO")
    assert first["status"] == "MORE_INFO_REQUESTED"
    back = submit_supplement(
        request_id,
        "Trial transcript pages 40-52 attached",
        headers=make_client_headers(ctx["client"]["id"]),
    )
    assert back["status"] == "SCREENING"

    # The loop is repeatable, and the IntakeSpecialist may also submit.
    second = advance_intake(request_id, "REQUEST_MORE_INFO")
    assert second["status"] == "MORE_INFO_REQUESTED"
    back2 = submit_supplement(request_id, "Lab inventory sheet attached")
    assert back2["status"] == "SCREENING"
    assert back2["supplement_notes"] == "Lab inventory sheet attached"
