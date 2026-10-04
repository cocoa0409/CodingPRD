"""Cross-entity state dependencies: a parent's next state depends on a child."""
from test_helpers import (
    api_client,
    validate_error,
    validate_success,
    create_broker_engagement,
    assign_broker_engagement,
    setup_approved_request,
    setup_sites_for_execution_gate,
    vacate_site,
    consolidate_site,
    TEST_USERS,
    ApiErrorId,
)

TM = TEST_USERS["transaction_manager_headers"]
OP = TEST_USERS["occupancy_planner_headers"]
FM = TEST_USERS["facilities_manager_headers"]


class TestMarketingLaunchGate:

    def test_launch_refused_while_engagement_is_pending(self, api):
        """PRD §3.2: "Marketing launch requires the lease to be BROKER_ASSIGNED
        and requires that a BrokerEngagement on the lease already exist in state
        ASSIGNED; without one the request is rejected before any business check
        with ERR_INVALID_STATE".

        Design: Difficulty/cross_entity_state_dependency/launch_marketing_requires_assigned_broker_engagement
        """
        account, lease, request, assignment = setup_approved_request()
        assert lease["pipeline_state"] == "BROKER_ASSIGNED"
        engagement = create_broker_engagement(account, request)
        assert engagement["engagement_state"] == "PENDING"
        res = api.launch_marketing(lease["id"], TM)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_launch_succeeds_once_engagement_is_assigned(self, api):
        """PRD §3.2: "A successful launch moves the lease to IN_MARKET."
        PRD §3.4: "Assignment requires the engagement to be PENDING and licensed,
        and moves it to ASSIGNED."

        Design: Difficulty/cross_entity_state_dependency/launch_marketing_requires_assigned_broker_engagement
        """
        account, lease, request, assignment = setup_approved_request()
        engagement = create_broker_engagement(account, request)
        engagement = assign_broker_engagement(engagement)
        launched = validate_success(api.launch_marketing(lease["id"], TM), 200)
        assert launched["pipeline_state"] == "IN_MARKET"
        engagement_after = validate_success(api.get_broker_engagement(engagement["id"], TM), 200)
        assert engagement_after["engagement_state"] == "ASSIGNED"


class TestExecutionReadinessGate:

    def test_start_execution_refused_while_sites_are_occupied(self, api):
        """PRD §3.6: "Starting execution requires the project to be APPROVED,
        requires every site assigned to the project to be in CONSOLIDATING or
        DISPOSED ... and an unready site set is rejected before business checks
        with ERR_INVALID_STATE."

        Design: Difficulty/cross_entity_state_dependency/start_execution_requires_sites_consolidating
        """
        account, project, vendor, sites, assignment = setup_sites_for_execution_gate(
            reductions=(40_001, 25_002)
        )
        assert project["project_state"] == "APPROVED"
        for site in sites:
            assert site["vacancy_state"] == "OCCUPIED"
        res = api.start_consolidation_execution(project["id"], OP)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)

    def test_start_execution_succeeds_once_sites_consolidate(self, api):
        """PRD §3.6: "Starting execution moves the project to IN_EXECUTION,
        computes savings_finalized_cents through the final variant below, and sets
        every assigned site to DISPOSED."

        Design: Difficulty/cross_entity_state_dependency/start_execution_requires_sites_consolidating
        """
        account, project, vendor, sites, assignment = setup_sites_for_execution_gate(
            reductions=(40_001, 25_002)
        )
        windows = [
            ("2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z"),
            ("2026-12-01T00:00:00Z", "2027-01-01T00:00:00Z"),
        ]
        for site, window in zip(sites, windows):
            vacate_site(site)
            consolidate_site(site, window[0], window[1])
        executed = validate_success(
            api.start_consolidation_execution(project["id"], OP), 200
        )
        assert executed["project_state"] == "IN_EXECUTION"
        for site in sites:
            after = validate_success(api.get_site(site["id"], FM), 200)
            assert after["vacancy_state"] == "DISPOSED"