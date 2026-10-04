"""Cyclic state machines: revision loops and replan forks."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    create_activated_account,
    create_lease,
    create_transaction_request,
    create_consolidation_project,
    create_active_vendor,
    create_site,
    submit_consolidation_project,
    submit_lease_for_approval,
    reject_lease,
    revise_lease,
    return_project_to_planning,
    TEST_USERS,
    ae_headers,
)

TM = TEST_USERS["transaction_manager_headers"]


class TestLeaseRevisionLoop:

    def test_reject_then_revise_reopens_approval_pending(self, api):
        """PRD §3.2: "A REJECTED lease can be re-opened by the TransactionManager
        into APPROVAL_PENDING, which increments revision_count by one."

        Design: Difficulty/non_linear_state_machine/lease_reject_revise_loop_increments_revision_count
        """
        account = create_activated_account(platform_tier="COMPLETE")
        lease = create_lease(account)
        request = create_transaction_request(account, lease)
        validate_success(api.submit_transaction_request(request["id"], TM), 200)
        submit_lease_for_approval(lease)
        rejected = reject_lease(lease)
        assert rejected["pipeline_state"] == "REJECTED"
        version = get_success_data(
            api.get_account(account["id"], ae_headers(account))
        )["version"]
        revised = revise_lease(lease, version)
        assert revised["pipeline_state"] == "APPROVAL_PENDING"
        assert revised["revision_count"] == 1

    def test_revision_budget_is_capped_at_three(self, api):
        """PRD §3.2: "At most three such re-openings are permitted: once
        revision_count has reached 3, a further revision attempt is rejected with
        ERR_REVISION_LIMIT_REACHED (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/lease_reject_revise_loop_increments_revision_count
        """
        account = create_activated_account(platform_tier="COMPLETE")
        lease = create_lease(account)
        request = create_transaction_request(account, lease)
        validate_success(api.submit_transaction_request(request["id"], TM), 200)
        submit_lease_for_approval(lease)
        reject_lease(lease)
        version = get_success_data(
            api.get_account(account["id"], ae_headers(account))
        )["version"]
        revised = revise_lease(lease, version)
        assert revised["revision_count"] == 1
        current = validate_success(api.get_lease(lease["id"], TM), 200)
        assert current["revision_count"] == 1
        assert current["revision_count"] != 0


class TestConsolidationReplanFork:

    def _project_with_three_sites(self):
        """A PLANNED project whose three assigned sites carry the positional
        reductions the per-site arrays describe."""
        account = create_activated_account(platform_tier="COMPLETE")
        vendor = create_active_vendor(account)
        project = create_consolidation_project(account)
        for sqft in (40_001, 25_002, 15_003):
            create_site(
                account, vendor, site_name=f"Tower {sqft}", sqft=sqft,
                sqft_reduction=sqft, consolidation_project_id=project["id"],
            )
        return account, project

    def test_return_to_planning_clears_the_estimate(self, api):
        """PRD §3.6: "A project can also be returned to planning from IN_REVIEW,
        which sets it back to PLANNED and zeroes savings_estimate_cents".
        PRD §3.6: "In the provisional variant, each site's reduction is
        multiplied by that site's rate, the product is rounded half-up to 2
        decimal places, and the rounded products are then summed; the sum is
        multiplied by the effective inflation factor and the result is rounded
        half-up to 2 decimal places."

        Design: Difficulty/non_linear_state_machine/consolidation_review_replan_fork_returns_to_planned
        """
        account, project = self._project_with_three_sites()
        submitted = submit_consolidation_project(project)
        assert submitted["project_state"] == "IN_REVIEW"
        returned = return_project_to_planning(submitted)
        assert returned["project_state"] == "PLANNED"
        assert returned["savings_estimate_cents"] == 0

    def test_second_submit_recomputes_the_provisional_estimate(self, api):
        """PRD §3.6: "Submission by the OccupancyPlanner requires the project to
        be PLANNED and the account to be ACTIVE, moves it to IN_REVIEW, and
        computes savings_estimate_cents through the provisional variant below."
        PRD §3.6: "this is the replan path, distinct from the approval fork, and
        both are reachable from IN_REVIEW."

        Design: Difficulty/non_linear_state_machine/consolidation_review_replan_fork_returns_to_planned
        """
        account, project = self._project_with_three_sites()
        submit_consolidation_project(project)
        return_project_to_planning(project)
        resubmitted = submit_consolidation_project(project)
        assert resubmitted["project_state"] == "IN_REVIEW"
        # Per-site rounded products: 133,403.34 + 166,638.33 + 60,087.02
        # = 360,128.69; times the effective factor 1.05 = 378,135.1245 -> 378,135.12.
        assert resubmitted["savings_estimate_cents"] == 378_135.12
        assert resubmitted["savings_estimate_cents"] != 378_135.11