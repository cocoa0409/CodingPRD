"""Page lifecycle: closure cascades and ownership transfer cascades."""
from test_helpers import (
    ADMIN,
    MODERATOR,
    OPS,
    ApiErrorId,
    claim_page,
    create_campaign_payload,
    create_complaint_payload,
    create_page,
    create_page_claim_payload,
    create_review,
    create_user,
    get_page,
    get_review,
    make_advertiser_headers,
    make_business_owner_headers,
    make_reviewer_headers,
    setup_claimed_page,
    set_clock,
    validate_error,
    validate_success,
)


class TestPageCloseCascade:
    def test_close_suspends_ad_account_and_pauses_campaigns(self, api):
        """PRD §3.2: "Closure cascades: if the page has an attached ad account,
        that account transitions to `SUSPENDED` and all of its `ACTIVE`
        campaigns transition to `PAUSED`".

        Design: Corner/endpoints/page_close_cascades_to_ads_and_claims
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        account = validate_success(
            api.create_ad_account(page["id"], {"daily_budget_cents": 5000},
                                  make_business_owner_headers(owner["id"])),
            expected_status=201,
        )
        campaign = validate_success(
            api.create_campaign(account["id"],
                                create_campaign_payload(bid_cents=100),
                                make_advertiser_headers(owner["id"])),
            expected_status=201,
        )
        validate_success(
            api.activate_campaign(campaign["id"], make_advertiser_headers(owner["id"]))
        )
        closed = validate_success(api.close_business_page(page["id"], ADMIN))
        assert closed["status"] == "CLOSED"
        account_after = validate_success(api.get_ad_account(account["id"], ADMIN))
        assert account_after["status"] == "SUSPENDED"
        campaign_after = validate_success(api.get_campaign(campaign["id"], ADMIN))
        assert campaign_after["status"] == "PAUSED"

    def test_close_expires_open_claims_and_blocks_new_reviews(self, api):
        """PRD §3.2: "any `PageClaim` on the page in `SUBMITTED` or `VERIFIED`
        transitions to `EXPIRED`. Existing reviews on a closed page remain
        queryable, but new review submissions are rejected with
        `ERR_PAGE_NOT_ACTIVE` (HTTP 409)."

        Design: Corner/endpoints/page_close_cascades_to_ads_and_claims
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        transfer_claimant = create_user()
        claim2 = validate_success(
            api.create_page_claim(page["id"], create_page_claim_payload(kind="TRANSFER"),
                                  make_business_owner_headers(transfer_claimant["id"])),
            expected_status=201,
        )
        validate_success(api.close_business_page(page["id"], ADMIN))
        claim2_after = validate_success(api.get_page_claim(claim2["id"], ADMIN))
        assert claim2_after["status"] == "EXPIRED"
        newcomer = create_user()
        r = api.create_review(
            page["id"],
            {"rating": 4, "text": "Reviewing a closed page must be rejected."},
            make_reviewer_headers(newcomer["id"]),
        )
        validate_error(r, ApiErrorId.ERR_PAGE_NOT_ACTIVE.value)


class TestTransferApprovalCascade:
    def _setup_transfer(self, api):
        page, old_owner = setup_claimed_page()
        account = validate_success(
            api.create_ad_account(page["id"], {"daily_budget_cents": 5000},
                                  make_business_owner_headers(old_owner["id"])),
            expected_status=201,
        )
        new_owner = create_user()
        claim2 = validate_success(
            api.create_page_claim(page["id"], create_page_claim_payload(kind="TRANSFER"),
                                  make_business_owner_headers(new_owner["id"])),
            expected_status=201,
        )
        validate_success(
            api.verify_page_claim(claim2["id"],
                                  {"verification_code": claim2["verification_code"]},
                                  make_business_owner_headers(new_owner["id"]))
        )
        return page, old_owner, new_owner, account, claim2

    def test_transfer_reassigns_and_suspends_ad_account(self, api):
        """PRD §3.4: "A `TRANSFER` approval additionally cascades: if the page
        has an attached ad account, the account's `owner_user_id` is reassigned
        to the claimant and its `status` is forced to `SUSPENDED` (the new
        owner must reactivate it explicitly)".

        Design: Corner/endpoints/ad_account_transfer_suspends_on_ownership_change
        """
        set_clock("2026-09-01T00:00:00Z")
        page, old_owner, new_owner, account, claim2 = self._setup_transfer(api)
        current = get_page(page["id"])
        validate_success(
            api.approve_page_claim(
                claim2["id"], {"expected_page_version": current["version"]}, ADMIN
            )
        )
        page_after = get_page(page["id"])
        assert page_after["claimed_by_user_id"] == new_owner["id"]
        account_after = validate_success(api.get_ad_account(account["id"], ADMIN))
        assert account_after["owner_user_id"] == new_owner["id"]
        assert account_after["status"] == "SUSPENDED"

    def test_old_owner_loses_campaign_control_after_transfer(self, api):
        """PRD §3.5: "An `Advertiser` activates a `DRAFT` campaign, provided
        the parent ad account is `ACTIVE`, the caller is the account's owner".

        Design: Corner/endpoints/ad_account_transfer_suspends_on_ownership_change
        """
        set_clock("2026-09-01T00:00:00Z")
        page, old_owner, new_owner, account, claim2 = self._setup_transfer(api)
        campaign = validate_success(
            api.create_campaign(account["id"], create_campaign_payload(bid_cents=100),
                                make_advertiser_headers(old_owner["id"])),
            expected_status=201,
        )
        current = get_page(page["id"])
        validate_success(
            api.approve_page_claim(
                claim2["id"], {"expected_page_version": current["version"]}, ADMIN
            )
        )
        r = api.activate_campaign(
            campaign["id"], make_advertiser_headers(old_owner["id"])
        )
        assert r.status_code in (403, 409), (
            f"Old owner must not be able to activate after transfer; got "
            f"{r.status_code}: {r.text}"
        )


class TestClosedPageOwnerReviewRejection:
    def test_owner_review_on_closed_page_rejected_page_not_active(self, api):
        """PRD §3.2: "Existing reviews on a closed page remain queryable, but
        new review submissions are rejected with `ERR_PAGE_NOT_ACTIVE`
        (HTTP 409)."
        PRD §3.3: "Submission is gated by a strict priority of checks. After
        the generic auth, existence, and payload checks, the page-side rules
        fire in this order: the page must be in `ACTIVE` status and must not
        currently host an `ACTIVE` `ConsumerAlert` whose
        `review_cooldown_until` is later than the current logical time — any
        violation is `ERR_PAGE_NOT_ACTIVE` (HTTP 409). Next, the author's own
        `status` must be `ACTIVE`; otherwise the submission is rejected with
        `ERR_USER_NOT_ACTIVE` (HTTP 409). Finally, the solicitation prohibition
        applies".

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_review_submit
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        validate_success(api.close_business_page(page["id"], ADMIN))
        r = api.create_review(
            page["id"],
            {"rating": 5, "text": "Owner reviewing own closed bar, double violation."},
            make_reviewer_headers(owner["id"]),
        )
        validate_error(r, ApiErrorId.ERR_PAGE_NOT_ACTIVE.value)

    def test_failed_submission_creates_no_review(self, api):
        """PRD §3.2: "Existing reviews on a closed page remain queryable, but
        new review submissions are rejected with `ERR_PAGE_NOT_ACTIVE`
        (HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/state_beats_business_referential_on_review_submit
        """
        set_clock("2026-09-01T00:00:00Z")
        page, owner = setup_claimed_page()
        validate_success(api.close_business_page(page["id"], ADMIN))
        api.create_review(
            page["id"],
            {"rating": 5, "text": "Owner reviewing own closed bar, double violation."},
            make_reviewer_headers(owner["id"]),
        )
        reviews = validate_success(api.list_page_reviews(page["id"], OPS))
        assert reviews == []
