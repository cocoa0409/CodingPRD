"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints; the server is restarted (empty database) before each test.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import DEFAULT_CLOCK
from .factories import (
    create_candidate_payload,
    create_application_payload,
    create_interview_payload,
    create_assessment_payload,
    create_restaurant_payload,
    create_experience_payload,
    create_operator_payload,
    create_week_payload,
    create_scorecard_payload,
    create_relocation_request_payload,
    create_exit_payload,
)
from .test_users import TEST_USERS, make_candidate_headers, make_operator_headers

ADMIN = TEST_USERS["system_admin_headers"]
FC = TEST_USERS["field_consultant_headers"]
SC = TEST_USERS["selection_committee_headers"]
FIN = TEST_USERS["finance_admin_headers"]

# A market plan long enough that the rubric plan component plus a maxed
# projection component lands the rubric score at or above the pass bar.
PASSING_PLAN_TEXT = "p" * 400


def set_clock(to_iso8601=DEFAULT_CLOCK):
    """Drive the logical clock to the supplied instant."""
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, ADMIN)
    return get_success_data(resp)


def setup_restaurant_available(**overrides):
    """Register a restaurant and move it to AVAILABLE. Returns the restaurant."""
    resp = api_client.create_restaurant(create_restaurant_payload(**overrides), ADMIN)
    restaurant = get_success_data(resp)
    resp = api_client.make_restaurant_available(restaurant["id"], ADMIN)
    return get_success_data(resp)


def setup_candidate(**overrides):
    """Register a candidate. Returns the candidate."""
    resp = api_client.create_candidate(create_candidate_payload(**overrides), ADMIN)
    return get_success_data(resp)


def submit_application(candidate, **overrides):
    """Submit an application as the candidate. Returns the application."""
    headers = make_candidate_headers(candidate["id"])
    resp = api_client.create_application(candidate["id"], create_application_payload(**overrides), headers)
    return get_success_data(resp)


def advance_to_interviews(application_id):
    """SUBMITTED -> SCREENING -> INTERVIEWS."""
    get_success_data(api_client.advance_application(application_id, FC))
    return get_success_data(api_client.advance_application(application_id, FC))


def pass_interviews(application_id, scores=(80, 90)):
    """Schedule and score rounds so the interview gate is satisfied."""
    round_ids = []
    for i, score in enumerate(scores):
        resp = api_client.create_interview(
            application_id,
            create_interview_payload(scheduled_for=f"2026-09-0{i + 2}T00:00:00Z"),
            FC,
        )
        round_id = get_success_data(resp)["id"]
        get_success_data(api_client.score_interview(application_id, round_id, {"score": score}, FC))
        round_ids.append(round_id)
    return round_ids


def pass_assessment(application_id, candidate_id):
    """Create, submit, and evaluate a passing business assessment."""
    cand_headers = make_candidate_headers(candidate_id)
    get_success_data(api_client.create_assessment(
        application_id,
        create_assessment_payload(market_plan_text=PASSING_PLAN_TEXT),
        cand_headers,
    ))
    get_success_data(api_client.submit_assessment(application_id, cand_headers))
    return get_success_data(api_client.evaluate_assessment(application_id, FC))


def complete_experience(application_id, host_restaurant_id,
                        starts_on="2026-09-07T00:00:00Z", ends_on="2026-09-12T00:00:00Z"):
    """Schedule the experience block, open it via the clock, sign off every
    required shift, and complete it. Returns the experience."""
    resp = api_client.create_experience(
        application_id,
        create_experience_payload(host_restaurant_id, starts_on=starts_on, ends_on=ends_on),
        FC,
    )
    experience = get_success_data(resp)
    set_clock(starts_on)
    for _ in range(experience["required_shift_count"]):
        get_success_data(api_client.signoff_experience(application_id, experience["id"], FC))
    return get_success_data(api_client.complete_experience(application_id, experience["id"], FC))


def drive_application_to_approved(candidate, restaurant):
    """Run a candidate's application through the full selection pipeline to
    APPROVED. Returns (application, candidate_refetched)."""
    application = submit_application(candidate)
    app_id = application["id"]
    advance_to_interviews(app_id)
    pass_interviews(app_id)
    get_success_data(api_client.advance_application(app_id, FC))
    pass_assessment(app_id, candidate["id"])
    get_success_data(api_client.advance_application(app_id, FC))
    complete_experience(app_id, restaurant["id"])
    advanced = get_success_data(api_client.advance_application(app_id, FC))
    decided = get_success_data(api_client.committee_decision(
        app_id,
        {"decision": "APPROVE", "expected_application_version": advanced["version"]},
        SC,
    ))
    candidate_now = get_success_data(api_client.get_candidate(candidate["id"], ADMIN))
    return decided, candidate_now


def setup_selected_candidate(restaurant=None, **candidate_overrides):
    """Candidate driven to SELECTED via the full pipeline. If no restaurant is
    given, an AVAILABLE one is created to host the experience. Returns
    (candidate, application, restaurant)."""
    if restaurant is None:
        restaurant = setup_restaurant_available()
    candidate = setup_candidate(**candidate_overrides)
    application, candidate = drive_application_to_approved(candidate, restaurant)
    return candidate, application, restaurant


def setup_operator_onboarding(restaurant=None, **candidate_overrides):
    """SELECTED candidate -> operator created (ONBOARDING) with DRAFT agreement.
    Returns dict with candidate, application, restaurant, operator, agreement."""
    if restaurant is None:
        restaurant = setup_restaurant_available()
    candidate, application, restaurant = setup_selected_candidate(restaurant, **candidate_overrides)
    resp = api_client.create_operator(
        create_operator_payload(candidate["id"], restaurant["id"]), SC
    )
    operator = get_success_data(resp)
    agreement = get_success_data(api_client.get_operator_agreement(operator["id"], SC))[0]
    return {
        "candidate": candidate,
        "application": application,
        "restaurant": restaurant,
        "operator": operator,
        "agreement": agreement,
    }


def setup_active_operator(restaurant=None, **candidate_overrides):
    """Operator fully onboarded and ACTIVE with an EXECUTED agreement.
    Returns dict with candidate, application, restaurant, operator, agreement."""
    ctx = setup_operator_onboarding(restaurant, **candidate_overrides)
    operator = ctx["operator"]
    op_headers = make_operator_headers(operator["id"])
    get_success_data(api_client.attest_operator(
        operator["id"], {"residency_verified": True, "full_time_attested": True}, op_headers
    ))
    ctx["agreement"] = get_success_data(api_client.execute_agreement(operator["id"], SC))
    ctx["operator"] = get_success_data(api_client.activate_operator(operator["id"], FC))
    ctx["restaurant"] = get_success_data(api_client.get_restaurant(ctx["restaurant"]["id"], ADMIN))
    return ctx


def setup_closed_week(restaurant_id, week_start_on="2026-09-14T00:00:00Z",
                      actual_revenue_cents=10_000_000, clock_after="2026-09-21T00:00:00Z"):
    """Plan a week, advance the clock so it opens and its six operating days
    elapse, then close it with the supplied actuals. Returns the closed week."""
    resp = api_client.create_week(restaurant_id, create_week_payload(week_start_on=week_start_on), FC)
    week = get_success_data(resp)
    set_clock(clock_after)
    # The clock advance opens the week (PLANNED -> OPEN), which mutates the
    # resource and bumps its version; re-read before closing so the OCC
    # expected_week_version matches.
    week = get_success_data(api_client.get_week(week["id"], FC))
    resp = api_client.close_week(
        restaurant_id,
        week["id"],
        {"actual_revenue_cents": actual_revenue_cents, "expected_week_version": week["version"]},
        FC,
    )
    return get_success_data(resp)


def get_operator_statement(operator_id):
    """Fetch the single statement of an operator via the operator statements list."""
    data = get_success_data(api_client.list_statements_of_operator(operator_id, FIN))
    assert isinstance(data, list) and len(data) == 1, f"expected exactly one statement, got {data}"
    return data[0]


def setup_active_operator_with_statement(actual_revenue_cents=10_000_000, **candidate_overrides):
    """ACTIVE operator plus one CLOSED week and its issued PROVISIONAL statement.
    Returns the operator context enriched with week and statement."""
    ctx = setup_active_operator(**candidate_overrides)
    week = setup_closed_week(ctx["restaurant"]["id"], actual_revenue_cents=actual_revenue_cents)
    statement = get_operator_statement(ctx["operator"]["id"])
    ctx["week"] = week
    ctx["statement"] = statement
    return ctx


def setup_open_exit(ctx, **exit_overrides):
    """Open an exit case for an ACTIVE operator. Returns the exit case."""
    op_headers = make_operator_headers(ctx["operator"]["id"])
    resp = api_client.create_exit(ctx["operator"]["id"], create_exit_payload(**exit_overrides), op_headers)
    return get_success_data(resp)


def create_draft_scorecard(operator_id, **overrides):
    """Draft a scorecard for an operator. Returns the scorecard."""
    resp = api_client.create_scorecard(operator_id, create_scorecard_payload(**overrides), FC)
    return get_success_data(resp)
