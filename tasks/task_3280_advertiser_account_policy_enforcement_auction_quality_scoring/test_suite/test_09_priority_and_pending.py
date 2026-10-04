"""Priority-pair validation tests and the verification pending-window exclusion."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_account,
    create_verified_account,
    create_campaign,
    create_and_activate_campaign,
    create_ad_group,
    create_ad,
    submit_identity_verification,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
)


class TestStateBeatsFiscalOnEndedCampaignPut:
    def test_active_campaign_put_with_low_budget_reports_fiscal(self, api):
        """PRD §2.10 item 11: "Fiscal rules — budget minimum, date range, daily
        overdelivery, and overpayment, all (422)."
        PRD §3.3: "Campaigns may also be created or updated only within the fiscal
        rules: the 100-cent floor and the date-range check apply at both create
        and update time."

        Design: Difficulty/priority_pair_validation_conflict/state_error_beats_fiscal_error_on_ended_campaign_put
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Prio Corp", with_billing_profile=False)
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        camp = create_and_activate_campaign(account, name="LONG", daily_budget_cents=1000)
        got = get_success_data(api_client.get_campaign(camp["id"], headers))
        # Only the fiscal rule fails (campaign is ACTIVE, version fresh).
        resp = api_client.update_campaign(
            camp["id"],
            {"daily_budget_cents": 50, "expected_campaign_version": got["version"]},
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_BUDGET_BELOW_MINIMUM)


class TestSafetyBeatsConstraintOnAdCreate:
    def test_uncertified_restricted_ad_reports_safety_not_duplicate(self, api):
        """PRD §2.10: "When a request fails several checks, the error returned is
        the one whose check ranks highest in this fixed priority order — readers
        should treat the list as an ordered cascade, not a menu of independent
        rules:"
        PRD §2.10 item 7: "Restricted-category certification —
        `ERR_RESTRICTED_CATEGORY_UNCERTIFIED` (422)."
        PRD §2.10 item 8: "Uniqueness and conflict rules — the six conflict errors
        of §2.11, all (409)."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_constraint_error_on_ad_create
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Safe Corp", with_billing_profile=False)
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        camp = create_campaign(account, name="CS", daily_budget_cents=1000)
        ag = create_ad_group(camp, account, name="AG")
        create_ad(
            ag, account, headline="SALE NOW", category="GENERAL",
            quality_ectr_score=5, quality_relevance_score=5, quality_lp_score=5,
            final_url="https://s.example/1",
        )
        # Both violations: uncertified GAMBLING (priority 7) + duplicate headline
        # case-insensitive (priority 8). Priority 7 wins.
        resp = api_client.create_ad(
            ag["id"],
            {
                "headline": "sale now", "final_url": "https://s.example/2",
                "category": "GAMBLING", "restricted_category_certified": False,
                "quality_ectr_score": 5, "quality_relevance_score": 5,
                "quality_lp_score": 5,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_RESTRICTED_CATEGORY_UNCERTIFIED)

    def test_duplicate_headline_alone_reports_duplicate(self, api):
        """PRD §2.11: "An ad whose headline matches another ad in the same ad
        group, compared case-insensitively, is rejected with
        `ERR_DUPLICATE_AD_HEADLINE` (409)."

        Design: Difficulty/priority_pair_validation_conflict/safety_error_beats_constraint_error_on_ad_create
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Safe Corp", with_billing_profile=False)
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        camp = create_campaign(account, name="CS", daily_budget_cents=1000)
        ag = create_ad_group(camp, account, name="AG")
        create_ad(
            ag, account, headline="SALE NOW", category="GENERAL",
            quality_ectr_score=5, quality_relevance_score=5, quality_lp_score=5,
            final_url="https://s.example/1",
        )
        # Only the duplicate-headline rule fails (GENERAL category).
        resp = api_client.create_ad(
            ag["id"],
            {
                "headline": "sale now", "final_url": "https://s.example/2",
                "category": "GENERAL",
                "quality_ectr_score": 5, "quality_relevance_score": 5,
                "quality_lp_score": 5,
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_AD_HEADLINE)


class TestVerificationPendingWindow:
    def test_second_submission_while_pending_rejected(self, api):
        """PRD §2.11: "A new identity verification while the account already has a
        verification in `SUBMITTED` — the pending window is occupied — is rejected
        with `ERR_DUPLICATE_VERIFICATION_PENDING` (409)."

        Design: Difficulty/resource_temporal_overlap/verification_pending_window_mutual_exclusion
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Mutex Corp")
        headers = make_advertiser_headers(account["id"])
        submit_identity_verification(account)
        observed = get_success_data(api_client.get_advertiser_account(account["id"], headers))
        # OCC version is fresh, so the pending-window conflict surfaces (409),
        # not a stale-version 412.
        resp = api_client.create_identity_verification(
            account["id"],
            {
                "legal_business_name": "Mutex Corp LLC Amended",
                "registration_number": "RN-14B",
                "document_type": "TAX_CERTIFICATE",
                "disclosure_consent": True,
                "expected_account_version": observed["version"],
            },
            headers,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_VERIFICATION_PENDING)

    def test_submission_after_rejection_allowed(self, api):
        """PRD §3.1: "Rejection moves the verification from `SUBMITTED` to
        `REJECTED`, recording the reviewer's `rejection_reason` — the reason is
        required whenever the outcome is a rejection — while the account remains
        `PENDING_VERIFICATION`. The advertiser may then submit a fresh
        verification, which supersedes the rejected one under the OCC guard
        described above."

        Design: Difficulty/resource_temporal_overlap/verification_pending_window_mutual_exclusion
        """
        set_clock("2026-09-01T00:00:00Z")
        account = create_account("Mutex Corp")
        headers = make_advertiser_headers(account["id"])
        v1 = submit_identity_verification(account)
        api_client.decide_identity_verification(
            v1["id"], {"outcome": "REJECTED", "rejection_reason": "bad doc"},
            TEST_USERS["platform_admin_headers"],
        )
        observed = get_success_data(api_client.get_advertiser_account(account["id"], headers))
        resp = api_client.create_identity_verification(
            account["id"],
            {
                "legal_business_name": "Mutex Corp LLC Amended",
                "registration_number": "RN-14B",
                "document_type": "TAX_CERTIFICATE",
                "disclosure_consent": True,
                "expected_account_version": observed["version"],
            },
            headers,
        )
        v2 = validate_success(resp, expected_status=201)
        assert v2["status"] == "SUBMITTED"
        assert v2["supersedes_id"] == v1["id"]
