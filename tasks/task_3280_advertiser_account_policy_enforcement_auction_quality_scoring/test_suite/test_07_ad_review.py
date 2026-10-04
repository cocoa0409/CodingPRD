"""Ad policy-review state machine tests: cycles, cascades, cross-entity gates."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_verified_account,
    create_and_activate_campaign,
    create_campaign,
    create_ad_group,
    create_ad,
    create_eligible_general_ad,
    create_keyword,
    submit_ad_review,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
)


class TestAdReviewCycle:
    def test_ad_review_disapprove_edit_approve_cycle(self, api):
        """PRD §3.4: "Submitting an ad for review moves it from `DRAFT` to
        `UNDER_REVIEW`, increments `review_round` by 1, and creates a policy
        review whose `ad_id` binds it to the ad, whose `round` equals the new
        `review_round`, and whose `automated_verdict` is derived from the
        category: `CLEAN` for a `GENERAL` ad, `FLAGGED_RESTRICTED` for any
        restricted category."
        PRD §3.4: "A violation finalizes the review as `HUMAN_VIOLATION` and moves
        the ad to `DISAPPROVED`, firing the two-link cascade: the campaign's
        `eligible_ad_count` is recomputed, and if the count has fallen to zero
        while the campaign is `ACTIVE`, the campaign pauses itself with
        `pause_origin` `NO_ELIGIBLE_ADS`."
        PRD §3.4: "A change to `headline` or `final_url` on an ad in `ELIGIBLE` or
        `DISAPPROVED` returns it to `DRAFT`, requiring a fresh review cycle."

        Design: Difficulty/non_linear_state_machine/ad_review_disapprove_edit_approve_cycle
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Cycle Corp")
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        campaign = create_and_activate_campaign(account, name="CC", daily_budget_cents=1000)
        ag = create_ad_group(campaign, account, name="AG")
        ad = create_ad(
            ag, account, headline="Wine Sale", category="ALCOHOL",
            restricted_category_certified=True,
            quality_ectr_score=5, quality_relevance_score=5, quality_lp_score=5,
            final_url="https://c.example/wine",
        )
        rev1 = submit_ad_review(ad["id"], account)
        assert rev1["outcome"] == "NEEDS_HUMAN"
        # HUMAN_VIOLATION -> DISAPPROVED
        api.decide_policy_review(
            rev1["id"],
            {"outcome": "HUMAN_VIOLATION", "reviewer_note": "implies discount abuse"},
            TEST_USERS["policy_reviewer_headers"],
        )
        got = get_success_data(api.get_ad(ad["id"], headers))
        assert got["status"] == "DISAPPROVED"
        # Edit headline -> DRAFT
        api.update_ad(ad["id"], {"headline": "Fine Wine Selection"}, headers)
        got2 = get_success_data(api.get_ad(ad["id"], headers))
        assert got2["status"] == "DRAFT"
        # Resubmit -> new round, NEEDS_HUMAN again
        rev2 = submit_ad_review(ad["id"], account)
        assert rev2["round"] == 2
        assert rev2["outcome"] == "NEEDS_HUMAN"
        # HUMAN_APPROVED -> ELIGIBLE; snapshot freezes at this approval.
        api.decide_policy_review(
            rev2["id"],
            {"outcome": "HUMAN_APPROVED", "reviewer_note": "compliant copy"},
            TEST_USERS["policy_reviewer_headers"],
        )
        got3 = get_success_data(api.get_ad(ad["id"], headers))
        assert got3["status"] == "ELIGIBLE"
        assert got3["review_round"] == 2
        assert got3["quality_score_snapshot_centi"] == 500  # 50*5 + 30*5 + 20*5

    def test_ad_review_round_increments_per_submission(self, api):
        """PRD §3.4: "Submitting an ad for review moves it from `DRAFT` to
        `UNDER_REVIEW`, increments `review_round` by 1, and creates a policy
        review whose `ad_id` binds it to the ad, whose `round` equals the new
        `review_round`, and whose `automated_verdict` is derived from the
        category: `CLEAN` for a `GENERAL` ad, `FLAGGED_RESTRICTED` for any
        restricted category."

        Design: Difficulty/non_linear_state_machine/ad_review_disapprove_edit_approve_cycle
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Cycle Corp")
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        campaign = create_and_activate_campaign(account, name="CC", daily_budget_cents=1000)
        ag = create_ad_group(campaign, account, name="AG")
        ad = create_ad(
            ag, account, headline="Wine Sale", category="ALCOHOL",
            restricted_category_certified=True,
            quality_ectr_score=5, quality_relevance_score=5, quality_lp_score=5,
        )
        rev1 = submit_ad_review(ad["id"], account)
        assert rev1["round"] == 1
        assert rev1["automated_verdict"] == "FLAGGED_RESTRICTED"
        api.decide_policy_review(
            rev1["id"], {"outcome": "HUMAN_VIOLATION"}, TEST_USERS["policy_reviewer_headers"]
        )
        api.update_ad(ad["id"], {"headline": "Fine Wine"}, headers)
        rev2 = submit_ad_review(ad["id"], account)
        assert rev2["round"] == 2
        assert rev2["ad_id"] == ad["id"]


class TestPolicyViolationCascade:
    def test_policy_violation_cascade_review_to_ad_to_campaign(self, api):
        """PRD §3.4: "A violation finalizes the review as `HUMAN_VIOLATION` and
        moves the ad to `DISAPPROVED`, firing the two-link cascade: the campaign's
        `eligible_ad_count` is recomputed, and if the count has fallen to zero
        while the campaign is `ACTIVE`, the campaign pauses itself with
        `pause_origin` `NO_ELIGIBLE_ADS`."

        Design: Difficulty/transitive_cascade/policy_violation_cascade_review_to_ad_to_campaign
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Cascade Corp")
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        campaign = create_and_activate_campaign(account, name="CX", daily_budget_cents=1000)
        ag = create_ad_group(campaign, account, name="AG")
        ad = create_ad(
            ag, account, headline="Poker Night", category="GAMBLING",
            restricted_category_certified=True,
            quality_ectr_score=5, quality_relevance_score=5, quality_lp_score=5,
            final_url="https://x.example/poker",
        )
        rev1 = submit_ad_review(ad["id"], account)
        api.decide_policy_review(
            rev1["id"], {"outcome": "HUMAN_APPROVED"}, TEST_USERS["policy_reviewer_headers"]
        )
        # Campaign now has one ELIGIBLE ad; edit + resubmit puts the ad back into
        # UNDER_REVIEW (count drops to 0 via the voluntary-edit path — no auto-pause).
        api.update_ad(ad["id"], {"headline": "Poker Night Bonus"}, headers)
        rev2 = submit_ad_review(ad["id"], account)
        pre = get_success_data(api.get_campaign(campaign["id"], headers))
        assert pre["eligible_ad_count"] == 0
        assert pre["status"] == "ACTIVE"
        # HUMAN_VIOLATION on round 2 -> DISAPPROVED; count stays 0 -> auto-pause
        # fires only if the count FELL to zero on this path. The disapproval path
        # is what fires the cascade rule.
        api.decide_policy_review(
            rev2["id"],
            {"outcome": "HUMAN_VIOLATION", "reviewer_note": "unlicensed bonus offer"},
            TEST_USERS["policy_reviewer_headers"],
        )
        got_ad = get_success_data(api.get_ad(ad["id"], headers))
        assert got_ad["status"] == "DISAPPROVED"
        got_camp = get_success_data(api.get_campaign(campaign["id"], headers))
        assert got_camp["eligible_ad_count"] == 0
        assert got_camp["status"] == "PAUSED"
        assert got_camp["pause_origin"] == "NO_ELIGIBLE_ADS"

    def test_disapproval_decrements_eligible_ad_count_without_pause_when_other_ads_remain(self, api):
        """PRD §3.4: "A violation finalizes the review as `HUMAN_VIOLATION` and
        moves the ad to `DISAPPROVED`, firing the two-link cascade: the campaign's
        `eligible_ad_count` is recomputed, and if the count has fallen to zero
        while the campaign is `ACTIVE`, the campaign pauses itself with
        `pause_origin` `NO_ELIGIBLE_ADS`."

        Design: Difficulty/transitive_cascade/policy_violation_cascade_review_to_ad_to_campaign
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Cascade Corp")
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        campaign = create_and_activate_campaign(account, name="CX", daily_budget_cents=1000)
        ag = create_ad_group(campaign, account, name="AG")
        # One auto-approved GENERAL ad keeps the count at 1 after the violation.
        create_eligible_general_ad(ag, account, headline="General Ad")
        ad = create_ad(
            ag, account, headline="Poker Night", category="GAMBLING",
            restricted_category_certified=True,
            quality_ectr_score=5, quality_relevance_score=5, quality_lp_score=5,
        )
        rev = submit_ad_review(ad["id"], account)
        pre = get_success_data(api.get_campaign(campaign["id"], headers))
        assert pre["eligible_ad_count"] == 1  # restricted ad still UNDER_REVIEW
        api.decide_policy_review(
            rev["id"], {"outcome": "HUMAN_VIOLATION"}, TEST_USERS["policy_reviewer_headers"]
        )
        got_camp = get_success_data(api.get_campaign(campaign["id"], headers))
        # Count stays 1 (GENERAL ad unaffected) -> campaign stays ACTIVE.
        assert got_camp["eligible_ad_count"] == 1
        assert got_camp["status"] == "ACTIVE"


class TestAdEligibilityBlockedByOpenReview:
    def test_ad_under_review_invisible_to_auction(self, api):
        """PRD §3.6: "An ad is a candidate only when every eligibility gate
        holds: its account is `ACTIVE`, its campaign is `ACTIVE` — which includes
        the lazy `ENDED` evaluation, so a campaign whose flight has ended is out —
        the logical date lies within the campaign's flight window, the ad itself
        is `ELIGIBLE`, and at least one non-negative keyword of its ad group
        matches the query."
        PRD §3.6: "When no ad survives at all, the auction is rejected with
        `ERR_NO_ELIGIBLE_AD` (422)."

        Design: Difficulty/cross_entity_state_dependency/ad_eligibility_blocked_by_open_human_review
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Vita Corp")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CV", daily_budget_cents=1000)
        ag = create_ad_group(campaign, account, name="AG")
        ad = create_ad(
            ag, account, headline="Vitamins Plus", category="HEALTHCARE",
            restricted_category_certified=True,
            quality_ectr_score=8, quality_relevance_score=7, quality_lp_score=6,
            final_url="https://v.example/v",
        )
        create_keyword(ag, account, "vitamins", max_cpc_cents=200)
        rev = submit_ad_review(ad["id"], account)
        assert rev["outcome"] == "NEEDS_HUMAN"
        # Ad stuck UNDER_REVIEW -> invisible to the auction despite keyword match.
        resp = api.run_auction(
            {"query_text": "vitamins", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_AD)

    def test_human_approval_makes_ad_servable(self, api):
        """PRD §3.4: "Approval finalizes the review as `HUMAN_APPROVED` and moves
        the ad to `ELIGIBLE` with the same snapshot-freeze, count recompute, and
        bubble-up effects."
        PRD §3.6: "An ad is a candidate only when every eligibility gate holds:
        its account is `ACTIVE`, its campaign is `ACTIVE` — which includes the
        lazy `ENDED` evaluation, so a campaign whose flight has ended is out —
        the logical date lies within the campaign's flight window, the ad itself
        is `ELIGIBLE`, and at least one non-negative keyword of its ad group
        matches the query."

        Design: Difficulty/cross_entity_state_dependency/ad_eligibility_blocked_by_open_human_review
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Vita Corp")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CV", daily_budget_cents=1000)
        ag = create_ad_group(campaign, account, name="AG")
        ad = create_ad(
            ag, account, headline="Vitamins Plus", category="HEALTHCARE",
            restricted_category_certified=True,
            quality_ectr_score=8, quality_relevance_score=7, quality_lp_score=6,
        )
        create_keyword(ag, account, "vitamins", max_cpc_cents=200)
        rev = submit_ad_review(ad["id"], account)
        api.decide_policy_review(
            rev["id"], {"outcome": "HUMAN_APPROVED"}, TEST_USERS["policy_reviewer_headers"]
        )
        resp = api.run_auction(
            {"query_text": "vitamins", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        ev = validate_success(resp, expected_status=201)
        assert ev["winner_ad_id"] == ad["id"]
