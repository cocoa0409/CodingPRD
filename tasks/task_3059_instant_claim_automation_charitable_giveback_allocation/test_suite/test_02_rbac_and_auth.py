"""RBAC, authentication ordering, and ownership enforcement tests."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_application,
    create_claim_payload,
    create_escalated_claim,
    create_policyholder,
    get_policy,
    get_success_data,
    pay_premium,
    set_clock,
    setup_bound_policy,
    validate_error,
    validate_success,
    make_policyholder_headers,
    approve_escalated_claim,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UNDERWRITER = TEST_USERS["underwriting_admin_headers"]
FINANCE = TEST_USERS["finance_ops_headers"]


class TestAuthentication:
    def test_missing_role_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request whose X-User-Role header is missing or names no declared role is rejected with ERR_UNAUTHENTICATED (HTTP 401)."

        Design: Corner/validations/missing_role_header_returns_unauthenticated
        """
        set_clock()
        headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
        resp = api.list_causes(headers)
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_authorize_before_existence_role_check_beats_not_found(self, api):
        """PRD §2.8: "Authentication, authorization, and existence checks, in that order, precede every business validation on every endpoint"

        Design: Corner/validations/authorize_before_existence_role_check_beats_not_found
        """
        set_clock()
        resp = api.approve_rate_filing(
            "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2", FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)


class TestSegregationOfDutiesRbac:
    def test_policyholder_cannot_approve_own_application(self, api):
        """PRD §4: the approve-application row lists only "UnderwritingAdmin" under Authorized Role(s).
        PRD §2.1: "A request whose role is declared but not permitted for the target endpoint — or whose acting policyholder attempts to touch a resource owned by someone else — is rejected with ERR_FORBIDDEN (HTTP 403)."

        Design: Corner/rbac/policyholder_cannot_approve_own_application
        """
        from test_helpers import (
            create_cause_and_cohort,
            setup_state_fee,
            create_quote,
        )
        set_clock()
        cause, cohort = create_cause_and_cohort(2026)
        setup_state_fee(state_code="TX")
        ph = create_policyholder(state_code="TX")
        quote = create_quote(ph["id"], 500000, 100000)
        app = create_application(ph["id"], quote["id"])
        resp = api.approve_application(app["id"], make_policyholder_headers(ph["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        app_after = validate_success(api.get_application(app["id"], UNDERWRITER))
        assert app_after["status"] == "UNDER_REVIEW"

    def test_underwriting_admin_cannot_adjudicate_claim(self, api):
        """PRD §2.1: "an UnderwritingAdmin manages rate filings, fee configurations, and application decisions but never touches claims adjudication or giveback".

        Design: Corner/rbac/underwriting_admin_cannot_adjudicate_claim
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        ph = ctx["policyholder"]
        claim = create_escalated_claim(ph["id"], ctx["policy"]["id"], 50000)
        resp = api.approve_claim(
            claim["id"],
            {"payout_cents": 50000, "expected_claim_version": claim["version"]},
            UNDERWRITER,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        claim_after = validate_success(api.get_claim(claim["id"], TEST_USERS["adjuster_1_headers"]))
        assert claim_after["status"] == "ESCALATED"

    def test_policyholder_cannot_read_others_claim(self, api):
        """PRD §2.1: "When X-User-Role is Policyholder, X-User-ID is the id of the acting Policyholder entity; ownership checks on any resource that references a Policyholder — quotes, applications, policies, claims filed on those policies, appeals — compare the resource's foreign-key field to X-User-ID, and a mismatch yields ERR_FORBIDDEN."

        Design: Corner/rbac/policyholder_cannot_read_others_claim
        """
        ctx = setup_bound_policy(state_code="TX", premium_cents=100000)
        pay_premium(ctx["policy"]["id"], 100000)
        ph_a = ctx["policyholder"]
        claim = create_escalated_claim(ph_a["id"], ctx["policy"]["id"], 50000)
        ph_b = create_policyholder(state_code="TX", email="b@x.com")
        resp = api.get_claim(claim["id"], make_policyholder_headers(ph_b["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
