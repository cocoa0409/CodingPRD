"""Auction mechanics tests: rank computation, tie-breaking, reserve gate,
actual-CPC pinned order, quality snapshot vs live score."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_verified_account,
    create_and_activate_campaign,
    create_ad_group,
    create_eligible_general_ad,
    create_keyword,
    set_clock,
    make_advertiser_headers,
    validate_error,
    validate_success,
    get_success_data,
)


def _two_ad_group_scenario(account, campaign, keyword_text, ad_specs):
    """Create one ad group + ELIGIBLE ad + EXACT keyword per spec.

    ad_specs: list of (headline, quality_triple, bid). Returns list of ads in
    creation order.
    """
    ads = []
    for i, (headline, q, bid) in enumerate(ad_specs):
        ag = create_ad_group(campaign, account, name=f"G{i+1}")
        ad = create_eligible_general_ad(
            ag, account, headline=headline,
            quality_ectr_score=q[0], quality_relevance_score=q[1], quality_lp_score=q[2],
            final_url=f"https://b.example/{i}",
        )
        create_keyword(ag, account, keyword_text, max_cpc_cents=bid)
        ads.append(ad)
    return ads


class TestAdRankReserveTiebreakAndBidCap:
    def test_ad_rank_tie_broken_by_earliest_ad_creation(self, api):
        """PRD §3.6: "The ad's rank is its bid in cents multiplied by its live
        quality centi-score, and any ad whose rank falls below the reserve of
        20000 is excluded. The winner is the highest-ranked surviving ad, with
        ties broken by earliest ad creation; the runner-up is the next-highest
        surviving rank, or null when no second ad survives."

        Design: Difficulty/combinatorial_formula/ad_rank_reserve_tiebreak_and_bid_cap
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Boot Corp")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CB", daily_budget_cents=100000)
        ads = _two_ad_group_scenario(
            account, campaign, "boots",
            [("Boots A", (8, 7, 6), 200), ("Boots B", (8, 7, 6), 200)],
        )
        resp = api.run_auction(
            {"query_text": "boots", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        data = validate_success(resp, expected_status=201)
        # Equal bids and quality -> tie at rank 200 * 730 = 146000; the earlier-
        # created ad (Boots A) wins.
        assert data["winner_ad_id"] == ads[0]["id"]
        assert data["winner_ad_rank"] == 146000
        assert data["runner_up_ad_rank"] == 146000

    def test_ad_rank_cpc_capped_at_winner_bid(self, api):
        """PRD §3.7: "Third, cap the price at the winner's bid: the actual cost
        per click is the smaller of the winner's bid and the incremented base."

        Design: Difficulty/combinatorial_formula/ad_rank_reserve_tiebreak_and_bid_cap
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Boot Corp")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CB", daily_budget_cents=100000)
        _two_ad_group_scenario(
            account, campaign, "boots",
            [("Boots A", (8, 7, 6), 200), ("Boots B", (8, 7, 6), 200)],
        )
        resp = api.run_auction(
            {"query_text": "boots", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        data = validate_success(resp, expected_status=201)
        # floor(146000 / 730) + 1 = 201, capped at min(200, 201) = 200.
        assert data["charged_cents"] == 200

    def test_ad_rank_below_reserve_yields_no_eligible_ad(self, api):
        """PRD §3.6: "The ad's rank is its bid in cents multiplied by its live
        quality centi-score, and any ad whose rank falls below the reserve of
        20000 is excluded."
        PRD §3.6: "When no ad survives at all, the auction is rejected with
        `ERR_NO_ELIGIBLE_AD` (422)."

        Design: Difficulty/combinatorial_formula/ad_rank_reserve_tiebreak_and_bid_cap
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Boot Corp")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CB", daily_budget_cents=100000)
        # Only ad: quality (1,1,1) -> q=100, bid 100 -> rank 10000 < 20000.
        _two_ad_group_scenario(account, campaign, "clogs", [("Clogs", (1, 1, 1), 100)])
        resp = api.run_auction(
            {"query_text": "clogs", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_AD)


class TestActualCpcPinnedOrder:
    def test_actual_cpc_floor_then_increment_beats_round_half_up(self, api):
        """PRD §3.7: "First, divide the runner-up's rank by the winner's live
        quality score — an exact rational division — and floor the result to
        integer cents. Second, add exactly one cent to that floored base. Third,
        cap the price at the winner's bid: the actual cost per click is the
        smaller of the winner's bid and the incremented base."
        PRD §3.7: "The floor happens before the increment, and the cap applies
        last — reordering any of the three steps changes the price and is
        non-conformant."

        Design: Difficulty/combinatorial_formula/actual_cpc_floor_then_increment_vs_rounding_trap
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Round Corp")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CR", daily_budget_cents=100000)
        # Winner W: q=730 bid 200 -> rank 146000. Runner R: q=500 bid 290 -> rank 145000.
        ads = _two_ad_group_scenario(
            account, campaign, "shoes",
            [("Shoe W", (8, 7, 6), 200), ("Shoe R", (5, 5, 5), 290)],
        )
        resp = api.run_auction(
            {"query_text": "shoes", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        data = validate_success(resp, expected_status=201)
        assert data["winner_ad_id"] == ads[0]["id"]  # 146000 > 145000
        # floor(145000 / 730) = 198, +1 = 199; round-half-up-first would give 200.
        assert data["charged_cents"] == 199

    def test_actual_cpc_no_runner_up_pays_reserve(self, api):
        """PRD §3.7: "When no runner-up exists, the actual cost per click is
        simply the smaller of the winner's bid and the reserve price of 5 cents."

        Design: Difficulty/combinatorial_formula/actual_cpc_floor_then_increment_vs_rounding_trap
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Round Corp")
        account = ctx["account"]
        campaign = create_and_activate_campaign(account, name="CR", daily_budget_cents=100000)
        _two_ad_group_scenario(account, campaign, "sandals", [("Solo S", (8, 7, 6), 200)])
        resp = api.run_auction(
            {"query_text": "sandals", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        data = validate_success(resp, expected_status=201)
        assert data["charged_cents"] == 5  # min(200, 5)
        assert data["runner_up_ad_rank"] is None


class TestQualitySnapshotVsLive:
    def test_quality_snapshot_frozen_at_approval_live_recomputed(self, api):
        """PRD §3.6: "The provisional variant is the advertiser-visible
        diagnostic: `quality_score_snapshot_centi` freezes the score at the ad's
        most recent transition into `ELIGIBLE` and does not move when component
        scores are edited afterward. The final variant is live: at auction time
        the score is recomputed from the ad's current component scores, so an ad
        whose scores changed since approval bids and prices on the new values even
        though its snapshot stays frozen."

        Design: Difficulty/dual_variant_calc/quality_snapshot_vs_live_at_auction
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Shoe Corp")
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        campaign = create_and_activate_campaign(account, name="CQ", daily_budget_cents=1000)
        ag = create_ad_group(campaign, account, name="AG1")
        ad = create_eligible_general_ad(
            ag, account, headline="Comfy Shoes",
            quality_ectr_score=8, quality_relevance_score=7, quality_lp_score=6,
            final_url="https://shoe.example/lp",
        )
        create_keyword(ag, account, "shoes", max_cpc_cents=200)
        # Edit scores to (10,10,10) — snapshot must stay frozen.
        resp = api.update_ad(
            ad["id"],
            {"quality_ectr_score": 10, "quality_relevance_score": 10, "quality_lp_score": 10},
            headers,
        )
        validate_success(resp)
        got = get_success_data(api.get_ad(ad["id"], headers))
        assert got["quality_score_snapshot_centi"] == 730  # 50*8 + 30*7 + 20*6
        auction = api.run_auction(
            {"query_text": "shoes", "clicked": True}, TEST_USERS["platform_admin_headers"]
        )
        ev = validate_success(auction, expected_status=201)
        assert ev["winner_ad_id"] == ad["id"]
        assert ev["quality_score_final_centi"] == 1000  # live recompute
        assert ev["winner_ad_rank"] == 200 * 1000
        assert ev["charged_cents"] == 5  # solo winner: min(bid 200, reserve 5)

    def test_quality_snapshot_recomputed_at_next_approval(self, api):
        """PRD §3.6: "The provisional variant is the advertiser-visible
        diagnostic: `quality_score_snapshot_centi` freezes the score at the ad's
        most recent transition into `ELIGIBLE` and does not move when component
        scores are edited afterward."
        PRD §3.4: "The first approval of an ad freezes `quality_score_snapshot_centi`
        at the live quality score computed at that moment (§3.6), and every
        transition into `ELIGIBLE` recomputes the campaign's `eligible_ad_count`."

        Design: Difficulty/dual_variant_calc/quality_snapshot_vs_live_at_auction
        """
        set_clock("2026-09-01T00:00:00Z")
        ctx = create_verified_account("Shoe Corp")
        account = ctx["account"]
        headers = make_advertiser_headers(account["id"])
        campaign = create_and_activate_campaign(account, name="CQ", daily_budget_cents=1000)
        ag = create_ad_group(campaign, account, name="AG1")
        ad = create_eligible_general_ad(
            ag, account, headline="Comfy Shoes",
            quality_ectr_score=8, quality_relevance_score=7, quality_lp_score=6,
        )
        create_keyword(ag, account, "shoes", max_cpc_cents=200)
        got = get_success_data(api.get_ad(ad["id"], headers))
        assert got["quality_score_snapshot_centi"] == 730
        # Edit scores AND headline -> ad returns to DRAFT; re-submit -> auto-approved.
        api.update_ad(
            ad["id"],
            {"headline": "Comfier Shoes", "quality_ectr_score": 10,
             "quality_relevance_score": 10, "quality_lp_score": 10},
            headers,
        )
        api.submit_ad_review(ad["id"], headers)
        got2 = get_success_data(api.get_ad(ad["id"], headers))
        assert got2["status"] == "ELIGIBLE"
        # The snapshot freezes at the MOST RECENT transition into ELIGIBLE.
        assert got2["quality_score_snapshot_centi"] == 1000
