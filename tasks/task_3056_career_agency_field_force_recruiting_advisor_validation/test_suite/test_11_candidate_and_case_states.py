"""Candidate and joint-case state machines: rejection, terminal lockdown,
screening preconditions and the void/reopen cycle."""
from test_helpers import (
    ApiErrorId,
    api_client,
    candidate_to_offer_extended,
    get_success_data,
    make_financial_rep_headers,
    new_candidate,
    new_office,
    any_headers,
    dd_headers,
    md_headers,
    ro_headers,
    set_clock,
    setup_joint_case,
    validate_error,
    validate_success,
)


def test_rejecting_an_offer_extended_candidate_invalidates_the_assessment():
    """PRD §3.2: "when the candidate is rejected, every one of its assessments
    currently in `SCHEDULED` or `SCORED` is set to `INVALIDATED` by the system,
    and the candidate's `ASSESSED` station is never re-entered."

    Design: Corner/state_machines/candidate_reject_from_offer_extended_is_allowed_and_invalidates_assessment
    """
    set_clock()
    office = new_office()
    candidate, assessment = candidate_to_offer_extended(office["id"], name="Kara Reject")

    rejected = validate_success(api_client.reject_candidate(candidate["id"], dd_headers))
    assert rejected["stage"] == "REJECTED"

    scored = get_success_data(api_client.get_assessment(assessment["id"], any_headers))
    assert scored["status"] == "INVALIDATED"


def test_a_rejected_candidate_cannot_be_advanced_again():
    """PRD §3.2: "A `DistrictDirector` may also reject a candidate from any
    stage that is not already terminal" ... "the terminal pipeline stages are
    `CONTRACTED`, `REJECTED`, and `OFFER_DECLINED`."
    PRD §2.10: "a resource that sits in a terminal state and admits no further
    transition is refused with `ERR_ALREADY_TERMINAL`."

    Design: Corner/state_machines/candidate_reject_from_offer_extended_is_allowed_and_invalidates_assessment
    """
    set_clock()
    office = new_office()
    candidate, _ = candidate_to_offer_extended(office["id"], name="Kara Terminal")

    validate_success(api_client.reject_candidate(candidate["id"], dd_headers))

    refused = api_client.reject_candidate(candidate["id"], dd_headers)
    validate_error(refused, ApiErrorId.ERR_ALREADY_TERMINAL.value)

    invalid_stage = api_client.extend_offer(candidate["id"], dd_headers)
    validate_error(invalid_stage, ApiErrorId.ERR_INVALID_STATE.value)


def test_an_offer_declined_candidate_locks_down_everything_but_reengagement():
    """PRD §3.2: "A declined or rejected candidate is not necessarily lost. A
    `RecruitingOfficer` may re-engage a candidate whose stage is
    `OFFER_DECLINED` or `REJECTED`."

    Design: Corner/state_machines/terminal_candidate_admits_no_further_stage_change_except_reengagement
    """
    set_clock()
    office = new_office()
    candidate, assessment = candidate_to_offer_extended(office["id"], name="Liam Terminal")
    candidate = validate_success(api_client.decline_offer(candidate["id"], ro_headers))
    assert candidate["stage"] == "OFFER_DECLINED"

    refused = api_client.advance_to_interview(candidate["id"], ro_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value)

    reengaged = validate_success(api_client.reengage_candidate(candidate["id"], ro_headers))
    assert reengaged["stage"] == "REENGAGED"
    assert reengaged["reengagement_count"] == 1

    superseded = get_success_data(api_client.get_assessment(assessment["id"], any_headers))
    assert superseded["status"] == "SUPERSEDED"


def test_a_campus_candidate_cannot_be_screened_without_a_campus_name():
    """PRD §3.1: "For a `CAMPUS` candidate the campus `campus_name` must be
    present: screening a campus candidate whose `campus_name` is null is refused
    with `ERR_CAMPUS_NAME_REQUIRED`, and that refusal happens before the
    transition is attempted."

    Design: Corner/state_machines/campus_candidate_cannot_be_screened_without_campus_name
    """
    set_clock()
    office = new_office()
    campus = new_candidate(office["id"], name="Mia Campus", channel="CAMPUS")
    referral = new_candidate(office["id"], name="Ned Referral", channel="REFERRAL")

    refused = api_client.screen_candidate(campus["id"], ro_headers)
    validate_error(refused, ApiErrorId.ERR_CAMPUS_NAME_REQUIRED.value)

    unchanged = get_success_data(api_client.get_candidate(campus["id"], any_headers))
    assert unchanged["stage"] == "SOURCED"
    assert unchanged["campus_name"] is None

    screened = validate_success(api_client.screen_candidate(referral["id"], ro_headers))
    assert screened["stage"] == "SCREENED"
    assert screened["campus_name"] is None


def test_scoring_requires_exactly_the_four_competency_keys():
    """PRD §3.2: "A map missing a key, or carrying a fifth key, is refused with
    `ERR_ASSESSMENT_INCOMPLETE_SCORES`, and a `raw_score` outside 0 to 100 is a
    malformed field."

    Design: Corner/state_machines/assessment_scoring_requires_all_four_competency_keys
    """
    set_clock()
    office = new_office()
    candidate = new_candidate(office["id"], name="Peta Keys")
    candidate = validate_success(api_client.screen_candidate(candidate["id"], ro_headers))
    assessment = validate_success(api_client.schedule_assessment(
        candidate["id"], {"assessment_version": "V2", "scheduled_date": "2026-09-02T00:00:00Z"},
        ro_headers))

    refused = api_client.score_assessment(
        assessment["id"],
        {"raw_score": 70, "competency_scores": {
            "MARKET_KNOWLEDGE": 7, "RELATIONSHIP": 7, "RESILIENCE": 7}}, ro_headers)
    validate_error(refused, ApiErrorId.ERR_ASSESSMENT_INCOMPLETE_SCORES.value)

    unscored = get_success_data(api_client.get_assessment(assessment["id"], any_headers))
    assert unscored["status"] == "SCHEDULED"
    assert unscored["weighted_score"] is None

    assert get_success_data(api_client.get_candidate(candidate["id"], any_headers))[
        "stage"] == "ASSESSMENT_PENDING"


def test_a_voided_joint_case_can_be_reopened_and_resubmitted():
    """PRD §3.6: "A voided case is not dead, however: a `FinancialRep` may
    reopen it, and reopening requires the case to be `VOIDED` and its policy to
    be `ISSUED` or `ACTIVE`; reopening sets the case to `OPEN`, clears
    `submitted_at` to null, and leaves credit allocation free to move again on a
    later submission."

    Design: Corner/state_machines/joint_work_case_submit_and_reopen_cycle
    """
    set_clock()
    office = new_office()
    ctx = setup_joint_case(office["id"], split_pct_lead=0.5, annual_premium_cents=510000,
                           open_case=True)
    case_id = ctx["case"]["id"]
    lead_id = ctx["lead"]["advisor"]["id"]
    rep_ctx = make_financial_rep_headers(lead_id)

    voided = validate_success(api_client.void_joint_work_case(case_id, rep_ctx))
    assert voided["status"] == "VOIDED"
    assert voided["submitted_at"] is None

    reopened = validate_success(api_client.reopen_joint_work_case(case_id, rep_ctx))
    assert reopened["status"] == "OPEN"

    # close is declared only from SUBMITTED
    refused = api_client.close_joint_work_case(case_id, md_headers)
    validate_error(refused, ApiErrorId.ERR_INVALID_STATE.value)

    submitted = validate_success(api_client.submit_joint_work_case(case_id, rep_ctx))
    assert submitted["status"] == "SUBMITTED"