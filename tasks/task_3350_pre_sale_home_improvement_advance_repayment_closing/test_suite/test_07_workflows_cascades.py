"""End-to-end cascade workflows: case cancellation fans out to children."""
from test_helpers import (
    api_client,
    add_approved_project,
    add_project,
    create_eligible_case,
    get_case,
    get_engagement,
    get_project,
    make_agent,
    reset_clock,
    setup_engagement_scheduled,
    TEST_USERS,
    validate_success,
)

HOMEOWNER = TEST_USERS["homeowner_headers"]


class TestCaseCancelCascade:
    def test_cancel_cascades_to_approved_project_and_scheduled_engagement(self, api):
        """PRD §3.7: "A homeowner may cancel the case outright from
        `SCOPE_PLANNING` or from `LISTED`."
        PRD §3.7: "On cancellation every project not already in a terminal state
        is moved to `CANCELLED`, and every engagement not already in a terminal
        state is moved to `CANCELLED`."

        Design: Difficulty/transitive_cascade/case_cancel_cascade_projects_engagements
        """
        ctx = setup_engagement_scheduled()
        case_id = ctx["case"]["id"]
        project_id = ctx["project"]["id"]
        engagement_id = ctx["engagement"]["id"]
        resp = api_client.cancel_case(case_id, HOMEOWNER)
        cancelled = validate_success(resp)
        assert cancelled["status"] == "CANCELLED"
        assert get_project(case_id, project_id)["status"] == "CANCELLED"
        assert get_engagement(engagement_id)["status"] == "CANCELLED"

    def test_cancel_cascades_to_every_non_terminal_project(self, api):
        """PRD §3.7: "On cancellation every project not already in a terminal
        state is moved to `CANCELLED`, and every engagement not already in a
        terminal state is moved to `CANCELLED`."

        Design: Difficulty/transitive_cascade/case_cancel_cascade_projects_engagements
        """
        reset_clock()
        agent = make_agent()
        case = create_eligible_case(agent)
        case_id = case["id"]
        project_a = add_approved_project(case_id, agent, title="Kitchen")
        project_b = add_project(case_id, agent, title="Bath")  # stays DRAFT
        resp = api_client.cancel_case(case_id, HOMEOWNER)
        validate_success(resp)
        assert get_project(case_id, project_a["id"])["status"] == "CANCELLED"
        assert get_project(case_id, project_b["id"])["status"] == "CANCELLED"
        assert get_case(case_id)["status"] == "CANCELLED"

    def test_case_cancel_cascades_to_children(self, api):
        """PRD §3.7: "A homeowner may cancel the case outright from
        `SCOPE_PLANNING` or from `LISTED`."
        PRD §3.7: "On cancellation every project not already in a terminal state
        is moved to `CANCELLED`, and every engagement not already in a terminal
        state is moved to `CANCELLED`."

        Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_case_cancel_cascades_to_children
        """
        ctx = setup_engagement_scheduled()
        case_id = ctx["case"]["id"]
        api_client.cancel_case(case_id, HOMEOWNER)
        assert get_case(case_id)["status"] == "CANCELLED"
        assert get_project(case_id, ctx["project"]["id"])["status"] == "CANCELLED"
        assert get_engagement(ctx["engagement"]["id"])["status"] == "CANCELLED"
