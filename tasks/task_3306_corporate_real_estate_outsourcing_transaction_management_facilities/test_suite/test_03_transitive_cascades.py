"""Transitive cascades: one trigger walks a multi-hop chain."""

from test_helpers import (
    api_client,
    get_success_data,
    validate_success,
    create_activated_account,
    setup_project_with_three_sites,
    setup_termination_cascade_account,
    TEST_USERS,
    ae_headers,
)

TM = TEST_USERS["transaction_manager_headers"]
# PRD §4: vendor / site / licence reads authorise FacilitiesManager and
# GovernanceManager (and AccountExecutive), not TransactionManager.
FM = TEST_USERS["facilities_manager_headers"]


class TestTerminationCascade:

    def test_close_terminates_vendor_and_closes_account(self, api):
        """PRD §3.8: "The first hop is the account's own closure to
        CLOSED_TERMINATED, which transitions every FacilitiesVendor on the
        account whose vendor_state is ACTIVE to TERMINATED."

        Design: Difficulty/transitive_cascade/account_close_cascades_vendor_then_site_then_data_license
        """
        account, vendor, site, license = setup_termination_cascade_account(
            account_name="Cascade Terminating"
        )
        closed = validate_success(
            api.close_account(account["id"], ae_headers(account)), 200
        )
        assert closed["lifecycle_state"] == "CLOSED_TERMINATED"
        vendor_after = validate_success(api.get_vendor(vendor["id"], FM), 200)
        assert vendor_after["vendor_state"] == "TERMINATED"

    def test_vendor_hop_disposes_site_and_revokes_line_item_licence(self, api):
        """PRD §3.8: "The second hop is that vendor termination, which sets every
        FacilitySite on the account whose vendor_id is that vendor — and which is
        still OCCUPIED — to DISPOSED."
        PRD §3.8: "The third hop is a site reaching DISPOSED, which transitions
        every DataLicense on the account whose data_scope is LINE_ITEM to
        REVOKED."

        Design: Difficulty/transitive_cascade/account_close_cascades_vendor_then_site_then_data_license
        """
        account, vendor, site, license = setup_termination_cascade_account(
            data_scope="LINE_ITEM", grant_consent=True,
            account_name="Cascade Licence Hop",
        )
        validate_success(api.close_account(account["id"], ae_headers(account)), 200)
        site_after = validate_success(api.get_site(site["id"], FM), 200)
        assert site_after["vacancy_state"] == "DISPOSED"
        license_after = validate_success(
            api.get_data_license(
                license["id"], TEST_USERS["data_steward_headers"]
            ),
            200,
        )
        assert license_after["license_state"] == "REVOKED"


class TestConsolidationExecutionCascade:

    def test_start_execution_disposes_every_assigned_site(self, api):
        """PRD §3.6: "Starting execution moves the project to IN_EXECUTION,
        computes savings_finalized_cents through the final variant below, and
        sets every assigned site to DISPOSED."

        Design: Difficulty/transitive_cascade/consolidation_execution_disposes_sites_and_finalizes_savings
        """
        account, project, vendor, sites, assignment = setup_project_with_three_sites(
            consolidate=True
        )
        executed = validate_success(
            api.start_consolidation_execution(project["id"], TEST_USERS[
                "occupancy_planner_headers"
            ]),
            200,
        )
        assert executed["project_state"] == "IN_EXECUTION"
        for site in sites:
            after = validate_success(
                api.get_site(site["id"], TEST_USERS["facilities_manager_headers"]), 200
            )
            assert after["vacancy_state"] == "DISPOSED"

    def test_final_savings_sums_raw_products_before_rounding(self, api):
        """PRD §3.6: "In the final variant, the raw per-site products are summed
        first without intermediate rounding, the sum is rounded half-up to 2
        decimal places once, and only then is it multiplied by the effective
        inflation factor and rounded half-up to 2 decimal places."
        PRD §3.6: "The two orders diverge by exactly one cent when per-site
        products land on a half-cent, which is why the order is pinned rather
        than left to the implementer."

        Design: Difficulty/transitive_cascade/consolidation_execution_disposes_sites_and_finalizes_savings
        """
        account, project, vendor, sites, assignment = setup_project_with_three_sites(
            consolidate=True
        )
        executed = validate_success(
            api.start_consolidation_execution(project["id"], TEST_USERS[
                "occupancy_planner_headers"
            ]),
            200,
        )
        # Raw products sum to 360,128.68 before rounding; the provisional leg
        # rounds each product first and sums to 360,128.69.
        assert executed["savings_finalized_cents"] == 378_135.11
        assert executed["savings_finalized_cents"] != executed["savings_estimate_cents"]
