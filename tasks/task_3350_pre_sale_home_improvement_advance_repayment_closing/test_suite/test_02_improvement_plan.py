"""Improvement scope development and plan approval."""
from test_helpers import (
    TEST_USERS,
    api_client,
    add_approved_project,
    add_project,
    approve_eligibility,
    approve_plan,
    approve_project,
    create_case,
    create_eligible_case,
    create_project_payload,
    get_case,
    get_case_version,
    get_project,
    make_agent,
    make_listing_agent_headers,
    propose_project,
    reset_clock,
    setup_case_with_approved_project,
    validate_error,
    validate_success,
)
from test_helpers import ApiErrorId as ERR


class TestProjectFields:
    def test_project_get_returns_stored_fields_unchanged(self, api):
        """PRD §3.3: "On approval the project's `approved_cost_cents` is locked to
        its `estimated_cost_cents`, the locked amount is added to the case's
        `advance_total_cents`, and the case's `version` is incremented by 1."

        Design: Corner/entities/improvement_project_get_returns_stored_fields_unchanged
        """
        ctx = setup_case_with_approved_project(with_vendor=False)
        case_id = ctx["case"]["id"]
        project_id = ctx["project"]["id"]
        resp = api_client.get_project(case_id, project_id, TEST_USERS["any_headers"])
        project = validate_success(resp)
        assert project["title"] == "Kitchen"
        assert project["estimated_cost_cents"] == 5_000_000
        assert project["approved_cost_cents"] == 5_000_000
        assert project["status"] == "APPROVED"

    def test_project_create_with_client_supplied_status_is_born_draft(self, api):
        """PRD §3.3: "the project is born in `DRAFT` and belongs to the case
        through its `concierge_case_id`."

        Design: Corner/entities/improvement_project_create_extra_field_status_is_ignored_input
        """
        reset_clock()
        agent = make_agent()
        case = create_eligible_case(agent)
        resp = api_client.create_project(
            case["id"],
            create_project_payload(status="APPROVED"),
            make_listing_agent_headers(agent["id"]),
        )
        project = validate_success(resp, expected_status=201)
        assert project["status"] == "DRAFT"


class TestProjectStateGuards:
    def test_propose_requires_case_in_scope_planning(self, api):
        """PRD §3.3: "proposing is only valid while the case itself is in
        `SCOPE_PLANNING`, and is otherwise rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Corner/state_machines/project_propose_from_draft_requires_case_scope_planning
        """
        reset_clock()
        agent = make_agent()
        # Case stays in ELIGIBILITY_REVIEW (never eligibility-approved).
        case = create_case(agent)
        project = add_project(case["id"], agent)
        resp = api_client.propose_project(
            case["id"], project["id"], make_listing_agent_headers(agent["id"])
        )
        validate_error(resp, ERR.ERR_INVALID_STATE)

    def test_double_approve_project_returns_invalid_state_on_second_attempt(self, api):
        """PRD §2.8: "State appropriateness comes fourth: a resource in the wrong
        state for the requested operation yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/idempotency_double_approve_project_returns_error_on_second_attempt
        """
        reset_clock()
        agent = make_agent()
        case = create_eligible_case(agent)
        project = add_project(case["id"], agent)
        propose_project(case["id"], project["id"], agent)
        approve_project(case["id"], project["id"])
        resp = api_client.approve_project(
            case["id"], project["id"], TEST_USERS["homeowner_headers"]
        )
        validate_error(resp, ERR.ERR_INVALID_STATE)

    def test_cancelled_case_rejects_further_transitions(self, api):
        """PRD §3.7: "`CLOSED_SOLD`, `CLOSED_UNSOLD`, and `CANCELLED` are the
        terminal states of a case."
        PRD §2.8: "State appropriateness comes fourth: a resource in the wrong
        state for the requested operation yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Corner/state_machines/terminal_state_lockdown_cancelled_case_rejects_further_transitions
        """
        reset_clock()
        agent = make_agent()
        case = create_case(agent)
        api_client.reject_eligibility(case["id"], TEST_USERS["program_underwriter_headers"])
        assert get_case(case["id"])["status"] == "CANCELLED"
        resp = api_client.approve_eligibility(
            case["id"], TEST_USERS["program_underwriter_headers"]
        )
        validate_error(resp, ERR.ERR_INVALID_STATE)


class TestPlanApproval:
    def test_plan_approve_without_approved_projects_returns_no_approved_projects(self, api):
        """PRD §3.3: "At least one project must be in `APPROVED` status —
        otherwise the request is rejected with `ERR_NO_APPROVED_PROJECTS`
        (HTTP 409)."

        Design: Corner/validations/plan_approve_without_approved_projects_returns_no_approved_projects
        """
        reset_clock()
        agent = make_agent()
        case = create_eligible_case(agent)
        add_project(case["id"], agent)  # DRAFT only, never proposed/approved
        version = get_case_version(case["id"])
        resp = api_client.approve_plan(
            case["id"],
            {"expected_case_version": version},
            TEST_USERS["homeowner_headers"],
        )
        validate_error(resp, ERR.ERR_NO_APPROVED_PROJECTS)

    def test_plan_approve_with_stale_version_returns_stale_version(self, api):
        """PRD §2.7: "If the value does not match the case's current `version` —
        because another writer has advanced the case since the client last read
        it, for example by approving a project, approving a change order, or
        approving a different disbursement, each of which bumps the case version
        through the advance-total cascade — the request is rejected with
        `ERR_STALE_VERSION` (HTTP 412), preventing the client from writing against
        a case state it has not observed."

        Design: Corner/errors/err_stale_version_on_plan_approve_with_old_version
        """
        ctx = setup_case_with_approved_project(with_vendor=False)
        case_id = ctx["case"]["id"]
        stale = get_case_version(case_id) - 1
        resp = api_client.approve_plan(
            case_id, {"expected_case_version": stale}, TEST_USERS["homeowner_headers"]
        )
        validate_error(resp, ERR.ERR_STALE_VERSION)

    def test_listing_price_target_aggregates_approved_project_lifts(self, api):
        """PRD §3.3: "On success the case's `listing_price_target_cents` is
        recomputed as the `estimated_property_value_cents` plus the sum of the
        `expected_sale_price_lift_cents` of every `APPROVED` project, and the
        case's `version` is incremented by 1."

        Design: Corner/calculations/listing_price_target_aggregates_approved_project_lifts
        """
        reset_clock()
        agent = make_agent()
        case = create_eligible_case(agent)
        case_id = case["id"]
        add_approved_project(
            case_id, agent, title="Kitchen",
            expected_sale_price_lift_cents=5_000_000, estimated_cost_cents=5_000_000,
        )
        add_approved_project(
            case_id, agent, title="Bath",
            expected_sale_price_lift_cents=3_000_000, estimated_cost_cents=3_000_000,
        )
        add_project(  # DRAFT — its lift must be excluded
            case_id, agent, title="Paint",
            expected_sale_price_lift_cents=1_000_000, estimated_cost_cents=1_000_000,
        )
        approve_plan(case_id)
        fetched = get_case(case_id)
        assert fetched["status"] == "PLAN_APPROVED"
        assert fetched["listing_price_target_cents"] == 88_000_000

    def test_case_reflects_project_approval_immediately(self, api):
        """PRD §3.3: "On approval the project's `approved_cost_cents` is locked to
        its `estimated_cost_cents`, the locked amount is added to the case's
        `advance_total_cents`, and the case's `version` is incremented by 1."

        Design: Corner/consistency_model/immediate_consistency_case_reflects_project_approval_in_same_request
        """
        reset_clock()
        agent = make_agent()
        case = create_eligible_case(agent)
        project = add_project(case["id"], agent)
        propose_project(case["id"], project["id"], agent)
        approve_project(case["id"], project["id"])
        fetched = get_case(case["id"])
        assert fetched["advance_total_cents"] == 5_000_000


class TestProjectApprovalRequiresScopePlanning:
    """Once the plan is approved the case has left SCOPE_PLANNING, so project
    propose/approve on that case must fail as out-of-state operations."""

    def _setup_plan_approved_with_pending_project(self, propose_first):
        """Case PLAN_APPROVED; project A APPROVED; project B created while the
        case was still in SCOPE_PLANNING and left behind (PROPOSED when
        propose_first, otherwise DRAFT)."""
        reset_clock()
        agent = make_agent()
        case = create_eligible_case(agent)
        case_id = case["id"]
        add_approved_project(case_id, agent, title="Kitchen")
        project_b = add_project(case_id, agent, title="Bath")
        if propose_first:
            propose_project(case_id, project_b["id"], agent)  # still SCOPE_PLANNING
        approve_plan(case_id)
        assert get_case(case_id)["status"] == "PLAN_APPROVED"
        return agent, case_id, project_b

    def test_project_approve_after_plan_approval_returns_invalid_state(self, api):
        """PRD §3.3: "Project approval from `PROPOSED` to `APPROVED` requires the
        case to be in `SCOPE_PLANNING`"
        PRD §2.8: "State appropriateness comes fourth: a resource in the wrong
        state for the requested operation yields `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/project_approval_requires_case_scope_planning
        """
        agent, case_id, project_b = self._setup_plan_approved_with_pending_project(
            propose_first=True
        )
        resp = api_client.approve_project(
            case_id, project_b["id"], TEST_USERS["homeowner_headers"]
        )
        validate_error(resp, ERR.ERR_INVALID_STATE)

    def test_project_propose_after_plan_approval_returns_invalid_state(self, api):
        """PRD §3.3: "proposing is only valid while the case itself is in
        `SCOPE_PLANNING`, and is otherwise rejected with `ERR_INVALID_STATE`
        (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/project_approval_requires_case_scope_planning
        """
        agent, case_id, project_b = self._setup_plan_approved_with_pending_project(
            propose_first=False
        )
        resp = api_client.propose_project(
            case_id, project_b["id"], make_listing_agent_headers(agent["id"])
        )
        validate_error(resp, ERR.ERR_INVALID_STATE)
