"""Envelope shape and RBAC denial tests (corner: endpoints, rbac sections)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account_payload,
    create_campaign_payload,
    create_account,
    create_verified_account,
    create_campaign,
    create_ad_group,
    create_ad,
    submit_ad_review,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
    is_iso8601_timestamp,
)


class TestSuccessEnvelope:
    def test_success_envelope_shape_on_object_response(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes)
        follow this standard envelope format in their JSON body:" with
        `meta.api_request_id`, `meta.api_request_timestamp`, `response_type`, and
        `data`.
        PRD §2.2: "The `response_type` is either "object" for a single resource
        or "array" for a list of resources."

        Design: Corner/endpoints/success_envelope_shape_on_object_response
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Env Corp", with_billing_profile=False)
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        camp = create_campaign(
            account, name="EN", daily_budget_cents=1000,
            start_date="2026-09-01", end_date="2026-09-30",
        )
        resp = api.activate_campaign(camp["id"], headers)
        assert resp.status_code == 200
        body = resp.json()
        assert "meta" in body and "response_type" in body and "data" in body
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["data"]["status"] == "ACTIVE"


class TestRbacDenials:
    def test_missing_auth_headers_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role not
        among the declared roles, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401) — this authentication check runs before every other validation
        on every authenticated endpoint."

        Design: Corner/rbac/missing_auth_headers_returns_unauthenticated
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Auth Corp")
        resp = api.get_advertiser_account(account["id"], headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_advertiser_cannot_decide_policy_review(self, api):
        """PRD §2.1: "A request whose role is not permitted for the addressed
        endpoint, or whose identity fails the ownership rule below, is rejected
        with `ERR_FORBIDDEN` (HTTP 403); the authorization check runs immediately
        after authentication and before any path resolution."
        PRD §3.4: "A `PolicyReviewer` decides a review in `NEEDS_HUMAN`, supplying
        an `outcome` of `HUMAN_APPROVED` or `HUMAN_VIOLATION` with an optional
        `reviewer_note` recorded on the review."

        Design: Corner/rbac/advertiser_cannot_decide_policy_review
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("RB Corp", with_billing_profile=False)
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        camp = create_campaign(account, name="RB", daily_budget_cents=1000)
        ag = create_ad_group(camp, account, name="AG")
        ad = create_ad(
            ag, account, headline="Wine", category="ALCOHOL",
            restricted_category_certified=True,
            quality_ectr_score=5, quality_relevance_score=5, quality_lp_score=5,
            final_url="https://rb.example/w",
        )
        review = submit_ad_review(ad["id"], account)
        resp = api.decide_policy_review(review["id"], {"outcome": "HUMAN_APPROVED"}, headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_billing_admin_cannot_create_campaigns(self, api):
        """PRD §2.1: "A request whose role is not permitted for the addressed
        endpoint, or whose identity fails the ownership rule below, is rejected
        with `ERR_FORBIDDEN` (HTTP 403); the authorization check runs immediately
        after authentication and before any path resolution."

        Design: Corner/rbac/billing_admin_cannot_create_campaigns
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("BA Corp")
        resp = api.create_campaign(
            create_campaign_payload(account["id"], name="XX", daily_budget_cents=100,
                                    start_date="2026-09-01", end_date="2026-09-30"),
            TEST_USERS["billing_admin_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

    def test_advertiser_cannot_touch_other_accounts_resources(self, api):
        """PRD §2.1: "When `X-User-Role` is `Advertiser`, `X-User-ID` is the `id`
        of the acting `AdvertiserAccount`; ownership checks on any resource that
        references an `AdvertiserAccount` compare the resource's account
        foreign-key field (its `account_id`, resolved through the parent chain
        when the resource is nested) to `X-User-ID`, and a mismatch is
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/advertiser_cannot_touch_other_accounts_resources
        """
        set_clock("2026-09-01T00:00:00Z")
        account_a = create_account("A Corp")
        account_b = create_account("B Corp")
        resp = api.get_advertiser_account(
            account_a["id"], make_advertiser_headers(account_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
