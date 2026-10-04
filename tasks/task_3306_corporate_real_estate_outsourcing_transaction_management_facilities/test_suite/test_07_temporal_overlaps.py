"""Temporal overlap boundaries: premises cooldown and half-open intervals."""
from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    create_account_with_approver,
    create_activated_account,
    create_approved_project,
    create_lease,
    create_active_vendor,
    create_site,
    vacate_site,
    consolidate_site,
    set_clock,
    TEST_USERS,
    ApiErrorId,
    ae_headers,
)

TM = TEST_USERS["transaction_manager_headers"]
FM = TEST_USERS["facilities_manager_headers"]


class TestPremisesCooldown:

    def test_start_31_days_after_prior_end_is_accepted(self, api):
        """PRD §3.2: "Creating a lease on an account and address that a prior
        lease still occupies, or that falls inside the 30-day cooldown after that
        prior lease ends, is rejected with ERR_LEASE_OVERLAP (HTTP 422)."
        PRD §2.10: "a new lease on the same account and property address may not
        start before the prior lease on that address ends, nor within a 30-day
        cooldown after it ends".

        Design: Difficulty/resource_temporal_overlap/premises_cooldown_overlap_on_new_lease
        """
        set_clock("2026-09-15T00:00:00Z")
        account = create_activated_account()
        prior = create_lease(
            account,
            property_address="1 Market St",
            market_code="SFO",
            lease_start_date="2026-02-01T00:00:00Z",
            lease_end_date="2027-02-01T00:00:00Z",
        )
        validate_success(api.expire_lease(prior["id"], ae_headers(account)), 200)
        accepted = validate_success(
            api.create_lease(
                {
                    "account_id": account["id"],
                    "property_address": "1 Market St",
                    "market_code": "SFO",
                    "leased_sqft": 40_000,
                    "base_rent_cents_per_year": 74_000_000,
                    "lease_start_date": "2027-03-04T00:00:00Z",
                    "lease_end_date": "2028-03-04T00:00:00Z",
                },
                TM,
            ),
            201,
        )
        assert accepted["pipeline_state"] == "PIPELINE"

    def test_start_inside_the_cooldown_is_rejected(self, api):
        """PRD §2.10: "a new lease on the same account and property address may
        not start before the prior lease on that address ends, nor within a
        30-day cooldown after it ends; a violation is rejected with
        ERR_LEASE_OVERLAP (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/premises_cooldown_overlap_on_new_lease
        """
        set_clock("2026-09-15T00:00:00Z")
        account = create_activated_account()
        prior = create_lease(
            account,
            property_address="1 Market St",
            market_code="SFO",
            lease_start_date="2026-02-01T00:00:00Z",
            lease_end_date="2027-02-01T00:00:00Z",
        )
        validate_success(api.expire_lease(prior["id"], ae_headers(account)), 200)
        res = api.create_lease(
            {
                "account_id": account["id"],
                "property_address": "1 Market St",
                "market_code": "SFO",
                "leased_sqft": 40_000,
                "base_rent_cents_per_year": 74_000_000,
                "lease_start_date": "2027-03-02T00:00:00Z",
                "lease_end_date": "2028-03-02T00:00:00Z",
            },
            TM,
        )
        validate_error(res, ApiErrorId.ERR_LEASE_OVERLAP)


class TestHalfOpenConsolidationWindows:

    def _approved_project_with_vendor(self):
        """An APPROVED consolidation project plus an active vendor on the account.

        PRD §3.6: moving a site into consolidation "requires the site's
        consolidation_project_id to reference a project whose project_state is
        APPROVED", so each site must carry the approved project reference.
        """
        account, assignment = create_account_with_approver(platform_tier="COMPLETE")
        vendor = create_active_vendor(account)
        project = create_approved_project(
            account,
            assignment,
            planned_sqft_reduction=65_003,
            cost_inflation_factor=1.05,
            per_site_rates=[3.335, 6.665],
            per_site_sqft_reductions=[40_001, 25_002],
        )
        return account, vendor, project

    def test_window_starting_at_committed_end_is_accepted(self, api):
        """PRD §2.10: "Consolidation windows are half-open intervals [start, end)."
        PRD §2.10: "Two committed intervals on the same account may not overlap
        under half-open semantics; an overlapping interval is rejected with
        ERR_SITE_OVERLAP (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/half_open_consolidation_windows_adjacency
        """
        account, vendor, project = self._approved_project_with_vendor()
        first = create_site(
            account, vendor, site_name="Tower 42000", sqft=40_001,
            sqft_reduction=40_001, consolidation_project_id=project["id"],
        )
        vacate_site(first)
        consolidate_site(first, "2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z")
        second = create_site(
            account, vendor, site_name="Tower 28500", sqft=25_002,
            sqft_reduction=25_002, consolidation_project_id=project["id"],
        )
        vacate_site(second)
        adjacent = validate_success(
            api.consolidate_site(
                second["id"],
                {
                    "window_start": "2026-12-01T00:00:00Z",
                    "window_end": "2027-02-01T00:00:00Z",
                },
                FM,
            ),
            200,
        )
        assert adjacent["vacancy_state"] == "CONSOLIDATING"
        disposed = validate_success(api.dispose_site(second["id"], FM), 200)
        assert disposed["vacancy_state"] == "DISPOSED"

    def test_window_starting_one_day_earlier_is_rejected(self, api):
        """PRD §2.10: "Two committed intervals on the same account may not
        overlap under half-open semantics; an overlapping interval is rejected
        with ERR_SITE_OVERLAP (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/half_open_consolidation_windows_adjacency
        """
        account, vendor, project = self._approved_project_with_vendor()
        first = create_site(
            account, vendor, site_name="Tower 42000", sqft=40_001,
            sqft_reduction=40_001, consolidation_project_id=project["id"],
        )
        vacate_site(first)
        consolidate_site(first, "2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z")
        second = create_site(
            account, vendor, site_name="Tower 28500", sqft=25_002,
            sqft_reduction=25_002, consolidation_project_id=project["id"],
        )
        vacate_site(second)
        res = api.consolidate_site(
            second["id"],
            {
                "window_start": "2026-11-30T00:00:00Z",
                "window_end": "2027-02-01T00:00:00Z",
            },
            FM,
        )
        validate_error(res, ApiErrorId.ERR_SITE_OVERLAP)