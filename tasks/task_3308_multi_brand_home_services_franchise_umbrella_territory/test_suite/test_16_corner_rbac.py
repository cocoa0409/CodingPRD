"""RBAC corner claims: role exclusivity, header validation and scope isolation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    accept_referral,
    activate_agreement,
    award_territory,
    create_agreement,
    create_brand,
    create_franchisee,
    create_referral,
    create_territory,
    get_territory,
    make_franchisee_operator_headers,
    offer_agreement,
    offer_territory,
    set_clock,
    setup_two_brand_pair,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["franchise_admin_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]


class TestClockIsFranchiseAdminOnly:
    def test_a_compliance_auditor_cannot_drive_the_logical_clock(self, api):
        """PRD §2.1: "This role holds no exclusive write operation."
        PRD §2.1: "A request whose role is not among the roles authorized for
        that endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

        Design: Corner/rbac/compliance_auditor_cannot_drive_the_logical_clock
        """
        set_clock("2026-09-01T00:00:00Z")

        resp = api.set_clock("2026-09-15T00:00:00Z", AUDITOR)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

        # The authorized operator is unaffected by the refused call.
        resp = api.set_clock("2026-09-15T00:00:00Z", ADMIN)
        validate_success(resp, 200)


class TestTerritoryReclaimIsFranchiseAdminOnly:
    def test_the_holding_franchisee_cannot_reclaim_its_own_territory(self, api):
        """PRD §2.1: "A request whose role is not among the roles authorized for
        that endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."
        PRD §4: reclaim is exclusive to `FranchiseAdmin`.

        Design: Corner/rbac/franchisee_operator_cannot_reclaim_a_territory
        """
        set_clock("2026-09-01T00:00:00Z")
        brand = create_brand(
            brand_code="MSP", display_name="Mosaic Plumbing", trade="PLUMBING",
            royalty_rate=0.06, national_ad_fund_rate=0.01,
            min_certification_level="APPRENTICE", audit_cycle_months=12,
            cross_brand_fee_table={},
        )
        franchisee = create_franchisee()
        territory = create_territory(brand["id"], franchisee_id=franchisee["id"])
        agreement = create_agreement(franchisee["id"], brand["id"], territory["id"])
        offer_agreement(agreement["id"])
        offer_territory(territory["id"], franchisee["id"])
        award_territory(territory["id"])
        activate_agreement(agreement["id"])
        api.suspend_agreement(agreement["id"], ADMIN, reason="Standing down")

        resp = api.reclaim_territory(
            territory["id"], make_franchisee_operator_headers(franchisee["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED, 403)

        refused = get_territory(territory["id"])
        assert refused["status"] == "PENDING_REALLOCATION", (
            f"the refusal must leave the territory unchanged, got {refused['status']}"
        )
        assert refused["franchisee_id"] == franchisee["id"]


class TestMissingAuthHeaders:
    def test_an_undeclared_role_is_rejected_before_every_other_gate(self, api):
        """PRD §2.1: "A request whose headers are absent, or whose
        `X-User-Role` does not name one of the three declared roles, is rejected
        with `ERR_UNAUTHENTICATED` (HTTP 401)."
        PRD §2.2: "The `meta` object for error responses contains only
        `api_request_id` and `api_request_timestamp`."

        Design: Corner/rbac/missing_role_header_returns_unauthenticated
        """
        set_clock("2026-09-01T00:00:00Z")
        resp = api.list_brands(
            {"X-User-ID": "op-unknown-1", "X-User-Role": "RegionalSupervisor",
             "Content-Type": "application/json"},
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, 401)

        body = resp.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"]
        assert body["data"]["message"]
        assert body["meta"]["api_request_id"]
        assert body["meta"]["api_request_timestamp"]


class TestReferralListScopeIsolation:
    def test_the_listing_is_scoped_to_the_acting_franchisees_own_book(self, api):
        """PRD §2.1: "When `X-User-Role` is `FranchiseeOperator`, `X-User-ID` is
        the `id` of the acting `Franchisee`; ownership checks on any resource
        that references a `Franchisee` compare the resource's foreign-key field
        to `X-User-ID`, and an operator who is not the owning, performing,
        receiving or participating party of the resource is refused."

        Design: Corner/rbac/franchisee_operator_cannot_read_another_franchisees_referrals
        """
        ctx = setup_two_brand_pair()
        stranger = create_franchisee(
            legal_name="Copperline Services LLC", principal_name="Neve Adeyemi",
            entity_type="LLC", shared_services_enrolled=False,
        )
        referral = create_referral(
            ctx["agt_a1"]["id"], ctx["agt_a2"]["id"], ctx["fr_ms"]["id"],
        )
        accept_referral(referral["id"], ctx["fr_il"]["id"])

        rows, meta = validate_paginated(
            api.list_referrals(make_franchisee_operator_headers(stranger["id"]))
        )
        assert meta["total_count"] == 0, (
            f"a franchisee party to nothing sees no referrals, got {meta['total_count']}"
        )

        rows, meta = validate_paginated(
            api.list_referrals(make_franchisee_operator_headers(ctx["fr_ms"]["id"]))
        )
        assert meta["total_count"] == 1

        rows, meta = validate_paginated(api.list_referrals(AUDITOR))
        assert meta["total_count"] == 1, (
            f"the compliance auditor sees the franchisor-wide book, got "
            f"{meta['total_count']}"
        )