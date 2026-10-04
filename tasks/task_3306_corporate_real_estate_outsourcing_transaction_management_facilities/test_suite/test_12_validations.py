"""Validation corner claims: fiscal, referential and temporal guards."""

from test_helpers import (
    api_client,
    get_success_data,
    validate_error,
    validate_success,
    create_activated_account,
    create_account_with_approver,
    create_active_vendor,
    create_vendor,
    create_broker_engagement,
    create_commission_record,
    create_consolidation_project,
    create_data_license,
    create_fee_accrual,
    create_granted_data_license,
    create_site,
    create_approved_project,
    apply_credits_to_accrual,
    grant_data_license,
    submit_consolidation_project,
    vacate_site,
    consolidate_site,
    set_clock,
    setup_approved_request,
    TEST_USERS,
    ApiErrorId,
    ae_headers,
)

TM = TEST_USERS["transaction_manager_headers"]
FM = TEST_USERS["facilities_manager_headers"]
OP = TEST_USERS["occupancy_planner_headers"]
DS = TEST_USERS["data_steward_headers"]


class TestFeeAccrualLock:

    def test_second_credit_application_on_credited_accrual_is_locked(self, api):
        """PRD §3.4: "It requires the target accrual to be OPEN — an accrual that
        is not open is rejected with ERR_FEE_ACCRUAL_LOCKED (HTTP 409)".

        Design: Corner/validations/second_credit_application_on_credited_accrual_is_locked
        """
        account = create_activated_account()
        create_commission_record(
            account, base_rent_cents=30_000_000, commission_pct=0.15,
            accrual_date="2026-07-01T00:00:00Z",
        )
        accrual = create_fee_accrual(account, period="2026-Q3", base_fee_cents=3_000_000)
        credited = apply_credits_to_accrual(accrual)
        assert credited["credit_application_state"] == "CREDITED"
        res = api.apply_lease_execution(accrual["id"], TM)
        validate_error(res, ApiErrorId.ERR_FEE_ACCRUAL_LOCKED)
        current = validate_success(api.get_fee_accrual(accrual["id"], ae_headers(account)), 200)
        assert current["credit_application_state"] == "CREDITED"


class TestDataLicenceConsent:

    def test_line_item_licence_on_exclusive_data_needs_consent(self, api):
        """PRD §3.9: "The requirement is true exactly when the account's current
        client_data_rights is CLIENT_OWNED_EXCLUSIVE and the licence's data_scope
        is LINE_ITEM."
        PRD §3.9: "a licence that would be granted while consent is required is
        rejected with ERR_CONSENT_REQUIRED (HTTP 422) until explicit consent is
        recorded through the licence's client_consent_confirmed flag."

        Design: Corner/validations/line_item_licence_on_exclusive_data_needs_consent
        """
        account = create_activated_account(platform_tier="ENTERPRISE")
        license = create_data_license(
            account, licensee_name="Helix Analytics",
            platform_tier_at_issue="ENTERPRISE", data_scope="LINE_ITEM",
        )
        assert license["requires_written_client_consent"] is True
        res = api.grant_data_license(license["id"], {}, DS)
        validate_error(res, ApiErrorId.ERR_CONSENT_REQUIRED)
        current = validate_success(api.get_data_license(license["id"], DS), 200)
        assert current["license_state"] == "REQUESTED"

    def test_shared_rights_tier_grants_line_item_without_consent(self, api):
        """PRD §2.11: "client_data_rights maps BASIC to BROKER_OWNED, COMPLETE to
        CLIENT_OWNED_SHARED and ENTERPRISE to CLIENT_OWNED_EXCLUSIVE."
        PRD §3.9: "A grant moves the licence to GRANTED and recomputes
        requires_written_client_consent against the account's current tier."

        Design: Corner/validations/shared_rights_tier_grants_line_item_without_consent
        """
        account = create_activated_account(platform_tier="COMPLETE")
        license = create_data_license(
            account, licensee_name="Helix Analytics",
            platform_tier_at_issue="COMPLETE", data_scope="LINE_ITEM",
        )
        assert license["requires_written_client_consent"] is False
        granted = grant_data_license(license)
        assert granted["license_state"] == "GRANTED"


class TestSiteAreaGuards:

    def test_site_over_remaining_area_is_refused(self, api):
        """PRD §3.1: "A FacilitySite cannot be created with an sqft greater than
        the account's remaining leasable area — that is, portfolio_sqft minus the
        sum of the sqft of the sites already on the account — and a request that
        would exceed it is rejected with ERR_SITE_EXCEEDS_PORTFOLIO."

        Design: Corner/validations/budget_style_validation_violation_returns_site_exceeds_portfolio
        """
        account = create_activated_account(portfolio_sqft=400_000)
        vendor = create_active_vendor(account)
        res = api.create_site(
            {
                "account_id": account["id"],
                "vendor_id": vendor["id"],
                "site_name": "Tower Too Big",
                "sqft": 500_000,
            },
            FM,
        )
        validate_error(res, ApiErrorId.ERR_SITE_EXCEEDS_PORTFOLIO)

    def test_site_beyond_whole_portfolio_is_refused(self, api):
        """PRD §2.10: "A new site may not claim more than the account's remaining
        leasable area, which is the account's portfolio_sqft minus the sum of the
        square footage already committed by existing sites on that account; a
        request that exceeds it is rejected with ERR_SITE_EXCEEDS_PORTFOLIO
        (HTTP 422)."

        Design: Corner/validations/lease_create_sqft_over_portfolio_plus_area_is_refused
        """
        account = create_activated_account(portfolio_sqft=400_000)
        vendor = create_active_vendor(account)
        create_site(account, vendor, site_name="Tower 100000", sqft=100_000)
        res = api.create_site(
            {
                "account_id": account["id"],
                "vendor_id": vendor["id"],
                "site_name": "Tower Over",
                "sqft": 500_000,
            },
            FM,
        )
        validate_error(res, ApiErrorId.ERR_SITE_EXCEEDS_PORTFOLIO)


class TestVendorKpiTrack:

    def test_national_program_never_raises_kpi_track(self, api):
        """PRD §3.5: "The base is LEVEL_A when the delivery model is SELF_PERFORM
        and LEVEL_B when it is SUBCONTRACTED. That base is raised to LEVEL_C only
        when both of two conditions hold at once: the sourcing programme is
        DIVERSITY, and the vendor serves at least one site on the account whose
        vacancy_state is OCCUPIED."
        PRD §3.5: "A vendor awarded under NATIONAL never rises above its base
        level."

        Design: Corner/validations/national_program_never_raises_kpi_track
        """
        account = create_activated_account()
        national = create_vendor(
            account, vendor_name="National Services", service_line="HVAC",
            delivery_model="SUBCONTRACTED", sourcing_program="NATIONAL",
            service_rate_cents_per_sqft=2.10,
        )
        diverse = create_vendor(
            account, vendor_name="Ace Janitorial", service_line="JANITORIAL",
            delivery_model="SELF_PERFORM", sourcing_program="DIVERSITY",
        )
        assert national["vendor_state"] == "SOURCING"
        create_site(account, national, site_name="Tower 30000", sqft=30_000)
        create_site(account, diverse, site_name="Tower 20000", sqft=20_000)
        national_after = validate_success(api.activate_vendor(national["id"], FM), 200)
        diverse_after = validate_success(api.activate_vendor(diverse["id"], FM), 200)
        assert national_after["kpi_track"] == "LEVEL_B"
        assert diverse_after["kpi_track"] == "LEVEL_C"


class TestProjectReductionInvariant:

    def test_reduction_mismatch_blocks_start_execution(self, api):
        """PRD §3.6: "requires the sum of the assigned sites' sqft_reduction to
        equal approved_sqft_reduction; a shortfall on that sum is rejected with
        ERR_SQFT_MISMATCH (HTTP 422)".

        Design: Corner/validations/budget_load_planning_violation_returns_sqft_mismatch
        """
        account, assignment = create_account_with_approver()
        vendor = create_active_vendor(account)
        project = create_approved_project(
            account, assignment,
            planned_sqft_reduction=50_000,
            per_site_rates=[3.335, 6.665],
            per_site_sqft_reductions=[40_001, 25_002],
        )
        sites = []
        for sqft in (40_001, 25_002):
            sites.append(
                create_site(
                    account, vendor, site_name=f"Tower {sqft}", sqft=sqft,
                    sqft_reduction=sqft, consolidation_project_id=project["id"],
                )
            )
        windows = [
            ("2026-10-01T00:00:00Z", "2026-12-01T00:00:00Z"),
            ("2026-12-01T00:00:00Z", "2027-02-01T00:00:00Z"),
        ]
        for site, window in zip(sites, windows):
            vacate_site(site)
            consolidate_site(site, window[0], window[1])
        res = api.start_consolidation_execution(project["id"], OP)
        validate_error(res, ApiErrorId.ERR_SQFT_MISMATCH)


class TestCommissionAndBrokerGuards:

    def test_commission_exceeding_gross_fee_is_refused(self, api):
        """PRD §3.4: "A record whose base_rent_cents exceeds the account's gross
        fee base is rejected as uncreditable with ERR_COMMISSION_EXCEEDS_FEE
        (HTTP 422)."

        Design: Corner/validations/commission_exceeding_gross_fee_is_refused
        """
        account = create_activated_account(platform_tier="ENTERPRISE", portfolio_sqft=400_000)
        res = api.create_commission_record(
            {
                "account_id": account["id"],
                "commission_source": "THIRD_PARTY",
                "base_rent_cents": 90_000_000,
                "commission_pct": 0.15,
                "accrual_date": "2026-07-01T00:00:00Z",
            },
            TEST_USERS["account_executive_headers"],
        )
        validate_error(res, ApiErrorId.ERR_COMMISSION_EXCEEDS_FEE)
        current = get_success_data(api.get_account(account["id"], ae_headers(account)))
        assert current["fee_ledger_credit_cents"] == 0

    def test_unlicensed_broker_assign_returns_not_licensed(self, api):
        """PRD §3.4: "At assignment, the broker's licensed_in_market flag must be
        true for the market it will trade in, and an unlicensed placement is
        rejected with ERR_BROKER_NOT_LICENSED (HTTP 422)."

        Design: Corner/validations/unlicensed_broker_assign_returns_not_licensed
        """
        account, lease, request, assignment = setup_approved_request()
        engagement = create_broker_engagement(
            account, request, broker_name="Sam Rookie",
            licensed_in_market=False, broker_class="STANDARD",
        )
        assert engagement["engagement_state"] == "PENDING"
        res = api.assign_broker_engagement(engagement["id"], TM)
        validate_error(res, ApiErrorId.ERR_BROKER_NOT_LICENSED)
        current = validate_success(api.get_broker_engagement(engagement["id"], TM), 200)
        assert current["engagement_state"] == "PENDING"

    def test_engagement_market_mismatch_is_refused(self, api):
        """PRD §3.4: "the engagement's market_code must match the market_code of
        the lease on its transaction request, and a mismatch is rejected with
        ERR_MARKET_MISMATCH (HTTP 422)."

        Design: Corner/validations/engagement_market_mismatch_is_refused
        """
        account, lease, request, assignment = setup_approved_request()
        res = api.create_broker_engagement(
            {
                "account_id": account["id"],
                "transaction_request_id": request["id"],
                "market_code": "CHI",
                "broker_name": "Pat Senior",
                "licensed_in_market": True,
                "broker_class": "SENIOR",
            },
            TM,
        )
        validate_error(res, ApiErrorId.ERR_MARKET_MISMATCH)


class TestClockGuard:

    def test_clock_rewind_is_refused(self, api):
        """PRD §3.9: "The clock only moves forward: a target instant that is not
        strictly after the clock's current value is rejected with
        ERR_CLOCK_ALREADY_ADVANCED (HTTP 409)."

        Design: Corner/validations/clock_rewind_is_refused
        """
        set_clock("2026-09-15T00:00:00Z")
        res = api.set_clock(
            "2026-09-15T00:00:00Z", TEST_USERS["account_executive_headers"]
        )
        validate_error(res, ApiErrorId.ERR_CLOCK_ALREADY_ADVANCED)
