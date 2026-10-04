"""Role segregation and the authentication rung (PRD §2.1, §2.4)."""
from test_helpers import (
    TEST_USERS,
    api_client,
    build_user_headers,
    commit_allocation,
    create_active_product,
    create_approved_partner,
    create_season,
    declare_capacity,
    get_profile,
    register_claim,
    set_clock,
    validate_error,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
SERVICE = TEST_USERS["customer_service_headers"]
MARKETING = TEST_USERS["marketing_headers"]
COORD = TEST_USERS["coordinator_headers"]


class TestSeasonCreationIsAuditorOnly:
    """Corner/rbac — season creation is exclusive to the audit role."""

    def test_another_declared_role_is_forbidden(self, api):
        """PRD §2.1: "A request that is properly authenticated but asks for an operation its role may not perform is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/a_non_auditor_cannot_create_an_impact_season
        """
        set_clock("2026-09-01T00:00:00Z")
        body = {
            "season_code": "2026-Q4",
            "starts_at": "2026-12-01T00:00:00Z",
            "ends_at": "2027-03-31T00:00:00Z",
            "freezes_at": "2027-02-15T00:00:00Z",
        }
        validate_error(
            api_client.create_impact_season(body, PLANNER),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )
        seasons = validate_success(api_client.list_impact_seasons(PLANNER), 200)
        assert len(seasons) == 0

        validate_success(
            api_client.create_impact_season(body, TEST_USERS["auditor_headers"]), 201
        )


class TestClaimSubstantiationIsMarketingOnly:
    """Corner/rbac — substantiation is exclusive to the marketing role."""

    def test_the_planner_cannot_move_a_claim(self, api):
        """PRD §2.1: "A request that is properly authenticated but asks for an operation its role may not perform is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
        PRD §2.4: "The presence and validity of `X-User-Role` and `X-User-ID` is checked first (`ERR_MISSING_AUTH_CONTEXT`), so an unauthenticated request that names a product which does not exist reports the authentication failure rather than `ERR_PRODUCT_NOT_FOUND`."

        Design: Corner/rbac/a_planner_cannot_substantiate_a_claim
        """
        set_clock("2026-09-01T00:00:00Z")
        create_season()
        product = create_active_product()
        partner = create_approved_partner()
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)

        validate_error(
            api_client.substantiate_claim(claim["id"], {}, PLANNER),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )
        assert validate_success(
            api_client.get_marketing_claim(claim["id"], MARKETING), 200
        )["status"] == "DRAFT"


class TestCommitIsPlannerOnly:
    """Corner/rbac — commitment is exclusive to the allocation planner."""

    def test_customer_service_cannot_touch_partner_capacity(self, api):
        """PRD §2.1: "A request that is properly authenticated but asks for an operation its role may not perform is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/a_customer_service_agent_cannot_commit_an_allocation
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        profile = declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)

        body = {
            "giving_partner_id": partner["id"],
            "claim_id": claim["id"],
            "donation_product_id": product["id"],
            "allocated_units": 10,
            "priority_tier": "HIGH",
            "liquidity_cap": 10,
            "expected_partner_version": validate_success(
                api_client.get_giving_partner(partner["id"], PLANNER), 200
            )["version"],
        }
        validate_error(
            api_client.commit_allocation_plan(season["id"], body, SERVICE),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )
        assert get_profile(profile["id"])["committed_units"] == 0

        validate_success(
            api_client.commit_allocation_plan(
                season["id"],
                dict(body, expected_partner_version=validate_success(
                    api_client.get_giving_partner(partner["id"], PLANNER), 200
                )["version"]),
                PLANNER,
            ),
            200,
        )


class TestAuditFinalizationIsAuditorOnly:
    """Corner/rbac — finalization is exclusive to the audit role."""

    def test_the_coordinator_cannot_grade_partners(self, api):
        """PRD §2.1: "A request that is properly authenticated but asks for an operation its role may not perform is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/a_partner_coordinator_cannot_finalize_an_audit
        """
        from test_helpers import confirm_receipt, make_auditor_headers, ship_allocation

        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=100)
        allocation = commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=100, priority_tier="CRITICAL",
        )
        distribution = ship_allocation(allocation["id"], 100, "TRK-RB-1", "UPS")
        confirm_receipt(distribution["id"], 100, "RCV-RB-1")

        set_clock("2026-12-02T00:00:00Z")
        audit = validate_success(
            api_client.create_impact_audit(
                {
                    "impact_season_id": season["id"],
                    "claim_id": claim["id"],
                    "audit_kind": "ANNUAL_IMPACT",
                },
                TEST_USERS["auditor_headers"],
            ),
            201,
        )
        started = validate_success(
            api_client.start_audit(
                audit["id"], {}, make_auditor_headers("aud-alpha")
            ),
            200,
        )

        validate_error(
            api_client.finalize_audit(
                audit["id"],
                {
                    "transaction_test_sample_size": 20,
                    "transaction_test_exceptions": 0,
                    "claimed_donation_units": 100,
                    "expected_audit_version": started["version"],
                },
                COORD,
            ),
            "ERR_FORBIDDEN_ROLE",
            expected_status=403,
        )
        assert validate_success(
            api_client.get_impact_audit(audit["id"], TEST_USERS["auditor_headers"]), 200
        )["status"] == "IN_PROGRESS"


class TestUnauthenticatedListing:
    """Corner/rbac — every business endpoint sits behind the authentication rung."""

    def test_a_listing_call_with_no_role_header_is_refused(self, api):
        """PRD §2.4: "A request missing either header, or naming a role that the system does not recognize, is rejected before any path or body inspection with `ERR_MISSING_AUTH_CONTEXT` (HTTP 401)."
        PRD §2.1: "The presence and validity of `X-User-Role` and `X-User-ID` is checked first (`ERR_MISSING_AUTH_CONTEXT`), so an unauthenticated request that names a product which does not exist reports the authentication failure rather than `ERR_PRODUCT_NOT_FOUND`."

        Design: Corner/rbac/an_unauthenticated_call_to_list_allocations_is_refused
        """
        set_clock("2026-09-01T00:00:00Z")
        season = create_season()
        product = create_active_product()
        partner = create_approved_partner()
        declare_capacity(partner["id"], max_allocatable_units=100000)
        claim = register_claim(product["id"], partner["id"], stated_donation_units=1000)
        commit_allocation(
            season["id"], partner["id"], claim["id"], product["id"],
            allocated_units=10, priority_tier="HIGH",
        )

        validate_error(
            api_client.list_allocations(build_user_headers("anon", "Anonymous")),
            "ERR_MISSING_AUTH_CONTEXT",
            expected_status=401,
        )
        rows = validate_success(api_client.list_allocations(PLANNER), 200)
        assert len(rows) == 1