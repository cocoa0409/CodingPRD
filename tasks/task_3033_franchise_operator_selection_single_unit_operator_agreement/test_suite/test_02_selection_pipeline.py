"""Selection pipeline gates: screening, interviews, assessment, stage mismatch,
terminal lockdown, OCC on committee decision, and RBAC denials."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_error_is_one_of,
    get_success_data,
    ApiErrorId, TEST_USERS,
    setup_candidate, submit_application, advance_to_interviews, pass_interviews,
    pass_assessment, complete_experience, setup_restaurant_available,
    setup_selected_candidate, set_clock, make_candidate_headers,
    create_interview_payload,
)

ADMIN = TEST_USERS["system_admin_headers"]
FC = TEST_USERS["field_consultant_headers"]
SC = TEST_USERS["selection_committee_headers"]
FIN = TEST_USERS["finance_admin_headers"]


def test_advance_from_submitted_below_screening_score_rejected(api):
    """PRD §3.2: "An application in `SUBMITTED` may be advanced to `SCREENING`
    by a `FieldConsultant` only when its `screening_score` is at least 60; a
    score below that bar is refused with `ERR_SCREENING_BELOW_THRESHOLD`."

    Design: Corner/state_machines/application_advance_from_submitted_below_screening_score_rejected
    """
    set_clock()
    candidate = setup_candidate(legal_name="Bo", email="bo@example.com",
                                home_market_code="GA", relocation_willing=False,
                                liquid_capital_cents=0)
    application = submit_application(candidate, target_market_code="FL")
    resp = api.advance_application(application["id"], FC)
    validate_error(resp, ApiErrorId.ERR_SCREENING_BELOW_THRESHOLD)
    current = get_success_data(api.get_application(application["id"], ADMIN))
    assert current["stage"] == "SUBMITTED"
    # capital 0 -> 0, market mismatch without relocation -> 0, name "Bo" -> 2
    assert current["screening_score"] == 2


def test_interview_score_out_of_range_rejected(api):
    """PRD §3.3: "Scoring a round — performed by a `FieldConsultant` supplying a
    `score` between 0 and 100 inclusive — moves the round's `status` to
    `SUBMITTED`; a score outside that range is refused with
    `ERR_SCORE_OUT_OF_RANGE`."

    Design: Corner/state_machines/interview_score_out_of_range_rejected
    """
    set_clock()
    candidate = setup_candidate(legal_name="Quinn Applicant", email="quinn@example.com")
    application = submit_application(candidate)
    advance_to_interviews(application["id"])
    resp = api.create_interview(application["id"], create_interview_payload(), FC)
    round_id = get_success_data(resp)["id"]
    resp = api.score_interview(application["id"], round_id, {"score": 101}, FC)
    validate_error(resp, ApiErrorId.ERR_SCORE_OUT_OF_RANGE)
    current = get_success_data(api.get_interview(round_id, FC))
    assert current["status"] == "SCHEDULED"


def test_interview_advance_requires_min_rounds_and_average(api):
    """PRD §3.3: "Advancing from `INTERVIEWS` to `BUSINESS_ASSESSMENT` requires
    three things, all enforced together: at least two interview rounds exist for
    the application, every one of the application's rounds is in `SUBMITTED`
    status, and the `interview_average` is at least 70. Any shortfall is refused
    with `ERR_INTERVIEW_GATE`."

    Design: Corner/state_machines/interview_advance_requires_min_rounds_and_average
    """
    set_clock()
    candidate = setup_candidate(legal_name="Seth Applicant", email="seth@example.com")
    application = submit_application(candidate)
    advance_to_interviews(application["id"])
    resp = api.create_interview(application["id"], create_interview_payload(), FC)
    round_id = get_success_data(resp)["id"]
    validate_success(api.score_interview(application["id"], round_id, {"score": 95}, FC))
    resp = api.advance_application(application["id"], FC)
    validate_error(resp, ApiErrorId.ERR_INTERVIEW_GATE)
    current = get_success_data(api.get_application(application["id"], ADMIN))
    assert current["stage"] == "INTERVIEWS"


def _application_past_interviews_with_round(api):
    """Drive an application to BUSINESS_ASSESSMENT (past INTERVIEWS) and return
    (application, round_id) with the round left behind in SUBMITTED status.

    PRD §3.3 permits scheduling rounds only while the application's `stage` is
    `INTERVIEWS`, and advancing out of `INTERVIEWS` requires every round to be
    `SUBMITTED` — so the only PRD-faithful way to hold a round on an
    application outside `INTERVIEWS` is to drive the application forward."""
    candidate = setup_candidate(legal_name="Hank Applicant", email="hank@example.com")
    application = submit_application(candidate)
    advance_to_interviews(application["id"])
    round_ids = pass_interviews(application["id"], scores=(80, 90))
    advanced = get_success_data(api.advance_application(application["id"], FC))
    assert advanced["stage"] == "BUSINESS_ASSESSMENT"
    return advanced, round_ids[0]


def test_interview_score_rejected_when_application_not_in_interviews(api):
    """PRD §3.3: "Scoring is only meaningful while the application's `stage` is
    actually `INTERVIEWS`; an attempt to score a round for an application in any
    other stage is refused with `ERR_STAGE_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_fiscal_on_interview_score
    """
    set_clock()
    application, round_id = _application_past_interviews_with_round(api)
    resp = api.score_interview(application["id"], round_id, {"score": 80}, FC)
    # PRD §2.8 places the target-state rule (`ERR_INVALID_STATE`, fourth) ahead
    # of the business interview-stage rule (`ERR_STAGE_MISMATCH`), and this
    # setup — the only PRD-faithful way to hold a round on an application
    # outside `INTERVIEWS` — trips both, so the PRD admits either surfacing.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_STAGE_MISMATCH, ApiErrorId.ERR_INVALID_STATE])


def test_interview_round_unchanged_after_stage_mismatch(api):
    """PRD §3.3: "an attempt to score a round for an application in any other
    stage is refused with `ERR_STAGE_MISMATCH`."
    PRD §3.3: "Scoring a round — performed by a `FieldConsultant` supplying a
    `score` between 0 and 100 inclusive — moves the round's `status` to
    `SUBMITTED`" — the refused attempt must not move it.

    Design: Difficulty/priority_pair_validation_conflict/business_referential_beats_fiscal_on_interview_score
    """
    set_clock()
    application, round_id = _application_past_interviews_with_round(api)
    validate_error_is_one_of(
        api.score_interview(application["id"], round_id, {"score": 50}, FC),
        [ApiErrorId.ERR_STAGE_MISMATCH, ApiErrorId.ERR_INVALID_STATE])
    current = get_success_data(api.get_interview(round_id, FC))
    assert current["status"] == "SUBMITTED"
    assert current["score"] == 80


def test_terminal_state_lockdown_on_approved_application(api):
    """PRD §3.4: "A decision of `APPROVE` moves the application to the terminal
    `APPROVED` stage"
    PRD §2.8: "fourth, whether the target resource's current state permits the
    requested transition (`ERR_INVALID_STATE`)"

    Design: Corner/state_machines/terminal_state_lockdown_on_approved_application
    """
    set_clock()
    candidate, application, _ = setup_selected_candidate()
    assert application["stage"] == "APPROVED"
    resp = api.advance_application(application["id"], FC)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = get_success_data(api.get_application(application["id"], ADMIN))
    assert current["stage"] == "APPROVED"


def _drive_to_committee_review(api):
    """Candidate + application driven into COMMITTEE_REVIEW. Returns
    (candidate, application-at-committee-review)."""
    restaurant = setup_restaurant_available()
    candidate = setup_candidate()
    application = submit_application(candidate)
    app_id = application["id"]
    advance_to_interviews(app_id)
    pass_interviews(app_id)
    get_success_data(api.advance_application(app_id, FC))
    pass_assessment(app_id, candidate["id"])
    get_success_data(api.advance_application(app_id, FC))
    complete_experience(app_id, restaurant["id"])
    at_review = get_success_data(api.advance_application(app_id, FC))
    return candidate, at_review


def test_committee_decision_requires_occ_version(api):
    """PRD §2.9: "Recording a committee decision on an application requires the
    request to carry `expected_application_version`, holding the `version` of
    the application as the committee member last read it. If the application's
    current `version` no longer matches — because another writer advanced it in
    the interim — the request is rejected with `ERR_STALE_VERSION` (HTTP 412),
    and no decision is recorded."

    Design: Corner/endpoints/committee_decision_requires_occ_version
    """
    set_clock()
    _, at_review = _drive_to_committee_review(api)
    resp = api.committee_decision(
        at_review["id"],
        {"decision": "APPROVE", "expected_application_version": at_review["version"] - 1},
        SC,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
    current = get_success_data(api.get_application(at_review["id"], ADMIN))
    assert current["stage"] == "COMMITTEE_REVIEW"
    assert current["committee_decision"] == "NONE"


def test_candidate_cannot_advance_own_application(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "Advance the application one pipeline stage | FieldConsultant"

    Design: Corner/roles/candidate_cannot_advance_own_application
    """
    set_clock()
    candidate = setup_candidate(legal_name="Zoe Applicant", email="zoe@example.com")
    application = submit_application(candidate)
    resp = api.advance_application(application["id"], make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    current = get_success_data(api.get_application(application["id"], ADMIN))
    assert current["stage"] == "SUBMITTED"


def test_finance_admin_cannot_drive_selection_pipeline(api):
    """PRD §2.1: "A request whose role is not permitted for the target endpoint
    is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: "Record the committee decision | SelectionCommittee"

    Design: Corner/roles/finance_admin_cannot_drive_selection_pipeline
    """
    set_clock()
    _, at_review = _drive_to_committee_review(api)
    resp = api.committee_decision(
        at_review["id"],
        {"decision": "APPROVE", "expected_application_version": at_review["version"]},
        FIN,
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
    current = get_success_data(api.get_application(at_review["id"], ADMIN))
    assert current["stage"] == "COMMITTEE_REVIEW"
