"""Appointment-application scoring: priority, tier, required action, pipeline."""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    get_success_data,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    create_appointment_application_payload,
    set_clock,
)

FIELD = TEST_USERS["field_manager_headers"]
EXEC = TEST_USERS["appointing_executive_headers"]


def submit_application(**overrides):
    set_clock()
    return get_success_data(
        api_client.create_application(
            create_appointment_application_payload(**overrides), FIELD
        )
    )


def test_application_value_tier_boundary_at_eighty_is_premium(api):
    """PRD §3.1: "application_value_tier is granted at a single boundary: an
    appointment_priority of at least 80 makes the application PREMIUM; anything
    lower makes it STANDARD. A priority of exactly 80 is PREMIUM."
    PRD §3.1: "appointment_priority is a weighted score: four tenths of
    market_odds_score, plus three tenths of candidate_assessment_score, plus
    three tenths of market_need_score, with the weights summing to exactly one.
    The weighted sum is rounded half up to the nearest whole integer and exposed
    as an integer between 0 and 100."

    Design: Difficulty/combinatorial_formula/application_value_tier_score_boundary_at_eighty
    """
    exact = submit_application(
        market_need_score=80, candidate_assessment_score=80, market_odds_score=80
    )
    scored = validate_success(api.assess_application(exact["id"], FIELD), 200)
    assert scored["appointment_priority"] == 80, "0.4*80 + 0.3*80 + 0.3*80 == 80"
    assert scored["application_value_tier"] == "PREMIUM"

    # One point lower on the odds input still lands on the same weighted sum,
    # so the boundary is inclusive at 80 and not a strict-greater comparison.
    near = submit_application(
        market_need_score=80, candidate_assessment_score=80, market_odds_score=79
    )
    near_scored = validate_success(api.assess_application(near["id"], FIELD), 200)
    assert near_scored["appointment_priority"] == 80, "0.4*79 + 0.3*80 + 0.3*80 == 79.6 → 80"
    assert near_scored["application_value_tier"] == "PREMIUM"


def test_application_value_tier_below_eighty_is_standard(api):
    """PRD §3.1: "application_value_tier is granted at a single boundary: an
    appointment_priority of at least 80 makes the application PREMIUM; anything
    lower makes it STANDARD."
    PRD §3.1: "The weighted sum is rounded half up to the nearest whole integer
    and exposed as an integer between 0 and 100."

    Design: Difficulty/combinatorial_formula/application_value_tier_score_boundary_at_eighty
    """
    standard = submit_application(
        market_need_score=79, candidate_assessment_score=79, market_odds_score=79
    )
    scored = validate_success(api.assess_application(standard["id"], FIELD), 200)
    assert scored["appointment_priority"] == 79, "0.4*79 + 0.3*79 + 0.3*79 == 79.0"
    assert scored["application_value_tier"] == "STANDARD"


def test_application_priority_weighted_literal_whole_point_sum(api):
    """PRD §3.1: "appointment_priority is a weighted score: four tenths of
    market_odds_score, plus three tenths of candidate_assessment_score, plus
    three tenths of market_need_score, with the weights summing to exactly one.
    The weighted sum is rounded half up to the nearest whole integer and exposed
    as an integer between 0 and 100."

    Design: Corner/calculations/appointment_priority_weighted_literal_90
    """
    application = submit_application(
        market_need_score=85, candidate_assessment_score=95, market_odds_score=80,
        creation_channel="DIGITAL",
    )
    scored = validate_success(api.assess_application(application["id"], FIELD), 200)
    # 0.4*80 + 0.3*95 + 0.3*85 == 86.0, and both scores exceed 70.
    assert scored["appointment_priority"] == 86
    assert isinstance(scored["appointment_priority"], int)
    assert scored["required_action"] == "PROCEED"


def test_first_assessment_moves_submitted_to_scored(api):
    """PRD §3.1: "Scoring is a FieldManager action that moves an application from
    SUBMITTED to SCORED. It recomputes three derived values."
    PRD §3.1: "If market_odds_score is below 40, or candidate_assessment_score is
    below 40, the action is REJECT. Otherwise, if both scores are strictly
    greater than 70, the action is PROCEED."

    Design: Difficulty/non_linear_state_machine/appointment_application_assess_self_loop_reassessment
    """
    application = submit_application(
        market_need_score=90, candidate_assessment_score=90, market_odds_score=90,
        creation_channel="DIGITAL",
    )
    assert application["status"] == "SUBMITTED"

    scored = validate_success(api.assess_application(application["id"], FIELD), 200)
    assert scored["status"] == "SCORED"
    assert scored["required_action"] == "PROCEED"


def test_second_assessment_self_loops_and_keeps_derived_values(api):
    """PRD §3.1: "A second assessment of an application that is already SCORED is
    accepted and stays SCORED; re-assessment is idempotent on the derived values."
    PRD §3.1: "Approval moves a SCORED application to APPROVED and is permitted
    only when required_action is PROCEED".

    Design: Difficulty/non_linear_state_machine/appointment_application_assess_self_loop_reassessment
    """
    application = submit_application(
        market_need_score=90, candidate_assessment_score=90, market_odds_score=90,
        creation_channel="DIGITAL",
    )
    first = validate_success(api.assess_application(application["id"], FIELD), 200)
    second = validate_success(api.assess_application(application["id"], FIELD), 200)

    assert second["status"] == "SCORED", "re-assessment stays SCORED, never a new state"
    assert second["appointment_priority"] == first["appointment_priority"] == 90
    assert second["required_action"] == "PROCEED"
    assert second["application_value_tier"] == first["application_value_tier"]

    # The application is genuinely still approvable after the self-loop.
    approved = validate_success(api.approve_application(application["id"], EXEC), 200)
    assert approved["status"] == "APPROVED"


def test_proceed_application_mints_agent_through_the_pipeline(api):
    """PRD §3.2: "A FieldManager appoints from an APPROVED application, which
    consumes the application — moving it to CONSUMED — and mints a new Agent in
    state APPOINTED, which is the CANDIDATE to APPOINTED transition."
    PRD §3.2: "The new agent carries full_name, state_code, and market_need_score
    from the application, starts with is_new_agent true".
    PRD §3.1: "Otherwise, if both scores are strictly greater than 70, the action
    is PROCEED."

    Design: Corner/calculations/appointment_priority_weighted_literal_90
    """
    set_clock()
    application = submit_application(
        market_need_score=90, candidate_assessment_score=90, market_odds_score=90
    )
    scored = validate_success(api.assess_application(application["id"], FIELD), 200)
    assert scored["required_action"] == "PROCEED"
    validate_success(api.approve_application(application["id"], EXEC), 200)

    agent = validate_success(api.appoint_application(application["id"], FIELD), 201)
    assert agent["status"] == "APPOINTED"
    assert agent["is_new_agent"] is True
    assert agent["license_status"] == "NOT_LICENSED"

    consumed = validate_success(api.get_application(application["id"], FIELD), 200)
    assert consumed["status"] == "CONSUMED"
    assert consumed["agent_id"] == agent["id"]


def test_digital_channel_application_completes_the_pipeline(api):
    """PRD §3.1: "creation_channel is either DIGITAL or FIELD, is fixed at
    creation, and is immutable thereafter."
    PRD §3.2: "An agent record's lifecycle begins in CANDIDATE, the un-minted
    state it holds before any application has produced it."

    Design: Corner/calculations/appointment_priority_weighted_literal_90
    """
    application = submit_application(
        market_need_score=80, candidate_assessment_score=80, market_odds_score=80,
        creation_channel="DIGITAL",
    )
    assert application["creation_channel"] == "DIGITAL"
    scored = validate_success(api.assess_application(application["id"], FIELD), 200)
    assert scored["status"] == "SCORED"
    validate_success(api.approve_application(application["id"], EXEC), 200)
    agent = validate_success(api.appoint_application(application["id"], FIELD), 201)
    assert agent["status"] == "APPOINTED"


@pytest.mark.parametrize(
    "need,assessment,odds,expected_action",
    [
        (90, 90, 90, "PROCEED"),
        (80, 80, 80, "PROCEED"),
    ],
)
def test_high_band_requires_strictly_greater_than_seventy(api, need, assessment, odds, expected_action):
    """PRD §3.1: "Otherwise, if both scores are strictly greater than 70, the
    action is PROCEED. Otherwise, if either score lies between 60 and 70
    inclusive, the action is MARKET_ANALYSIS_REQUIRED."
    PRD §3.1: "Note the asymmetry the boundaries create: the high band is open,
    so a score of exactly 70 is not sufficient for PROCEED and falls into the
    middle band, whereas the middle band is closed at both ends."

    Design: Difficulty/priority_pair_validation_conflict/assess_dual_failure_license_before_market_need
    """
    application = submit_application(
        market_need_score=need, candidate_assessment_score=assessment, market_odds_score=odds
    )
    scored = validate_success(api.assess_application(application["id"], FIELD), 200)
    assert scored["required_action"] == expected_action


def test_boundary_score_of_seventy_is_not_sufficient_for_proceed(api):
    """PRD §3.1: "Otherwise, if either score lies between 60 and 70 inclusive, the
    action is MARKET_ANALYSIS_REQUIRED."
    PRD §3.1: "Note the asymmetry the boundaries create: the high band is open,
    so a score of exactly 70 is not sufficient for PROCEED and falls into the
    middle band, whereas the middle band is closed at both ends."

    Design: Difficulty/priority_pair_validation_conflict/assess_dual_failure_license_before_market_need
    """
    application = submit_application(
        market_need_score=90, candidate_assessment_score=90, market_odds_score=70
    )
    scored = validate_success(api.assess_application(application["id"], FIELD), 200)
    assert scored["required_action"] == "MARKET_ANALYSIS_REQUIRED"

def test_market_need_at_the_floor_blocks_the_assessment(api):
    """PRD §3.1: "One territorial rule can stop an application at assessment time.
    An application whose market_need_score is at most 40 for a territory of the
    support subtype does not fit that territory, and the assessment is refused
    with ERR_MARKET_NEED_EXISTS (HTTP 409)."

    Design: Corner/errors/err_market_need_exists_triggered
    """
    application = submit_application(
        market_need_score=40, candidate_assessment_score=90, market_odds_score=90
    )
    res = api.assess_application(application["id"], FIELD)
    validate_error(res, ApiErrorId.ERR_MARKET_NEED_EXISTS, expected_status=409)
