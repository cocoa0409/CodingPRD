"""Breadth coverage for calculation results (tiers, summaries, key allowance)."""
from test_helpers import (
    api_client,
    buy_title,
    create_and_approve_key_batch,
    create_buyer,
    create_key_batch_payload,
    create_n_buyers_with_purchases,
    create_released_title,
    get_success_data,
    make_developer_headers,
    make_user_headers,
    post_review,
    read_title,
    request_refund,
    set_clock,
    validate_error,
    validate_success,
    ApiErrorId,
    TEST_USERS,
)

OPS = TEST_USERS["platform_ops_headers"]


class TestTierBoundaryInclusive:
    def test_tier_two_at_exactly_ten_million_dollars(self):
        """PRD §3.4: "The thresholds are inclusive: recognized revenue of exactly
        ten million dollars earns tier 2."

        Design: Corner/calculations/tier_boundary_inclusive_crossing
        """
        developer, title = create_released_title(base_price_usd_cents=100)
        dev_headers = make_developer_headers(developer["id"])
        version = read_title(title["id"], developer)["version"]

        get_success_data(
            api_client.adjust_title_revenue(
                title["id"],
                {"delta_usd_cents": 1_000_000_000, "reason": "seed",
                 "expected_title_version": version},
                OPS,
            )
        )

        title_read = read_title(title["id"], developer)
        assert title_read["current_tier"] == 2
        assert title_read["lifetime_recognized_revenue_usd_cents"] == 1_000_000_000

        buyer = create_buyer()
        purchase = buy_title(buyer, title)
        # tier 2 rate 25%: round_half_up(100 * 0.25) = 25
        assert purchase["platform_fee_cents"] == 25

    def test_tier_degrades_after_refund_pulls_revenue_below_threshold(self):
        """PRD §3.4: "There is no hysteresis — the tier is fully re-derived each
        time, so a refund that drags recognized revenue back below a threshold
        degrades the tier, and a title that climbs to tier 3 can fall back to
        tier 2."

        Design: Corner/calculations/tier_boundary_inclusive_crossing
        """
        set_clock("2026-09-02T00:00:00Z")
        developer, title = create_released_title(base_price_usd_cents=100)
        version = read_title(title["id"], developer)["version"]
        get_success_data(
            api_client.adjust_title_revenue(
                title["id"],
                {"delta_usd_cents": 1_000_000_000, "reason": "seed",
                 "expected_title_version": version},
                OPS,
            )
        )

        buyer = create_buyer()
        purchase = buy_title(buyer, title)
        assert purchase["platform_fee_cents"] == 25  # tier 2

        # Full refund of the 100-cent purchase: revenue 1_000_000_100 -> 1_000_000_000.
        rr = request_refund(purchase, buyer, reason="full")
        assert rr["status"] == "APPROVED"
        mid = read_title(title["id"], developer)
        assert mid["current_tier"] == 2  # exactly at the boundary, still tier 2

        # Push one cent below the threshold with a negative adjustment.
        version = mid["version"]
        get_success_data(
            api_client.adjust_title_revenue(
                title["id"],
                {"delta_usd_cents": -1, "reason": "one cent under",
                 "expected_title_version": version},
                OPS,
            )
        )
        low = read_title(title["id"], developer)
        assert low["lifetime_recognized_revenue_usd_cents"] == 999_999_999
        assert low["current_tier"] == 1

        # The next purchase splits at the tier 1 rate again.
        buyer2 = create_buyer()
        purchase2 = buy_title(buyer2, title)
        assert purchase2["platform_fee_cents"] == 30  # round_half_up(100 * 0.30)

        purchase_read = validate_success(
            api_client.get_purchase(purchase["id"], make_user_headers(buyer["id"]))
        )
        assert purchase_read["status"] == "REFUNDED"


class TestRecentReviewSummaryThresholds:
    def _setup_summary_scenario(self):
        developer, title = create_released_title(base_price_usd_cents=500)
        users, _ = create_n_buyers_with_purchases(title, 10)
        return developer, title, users

    def test_seventy_percent_positive_is_mostly_positive(self):
        """PRD §3.7: "Alongside the score, `recent_review_summary` classifies the
        trailing thirty days — inclusive of now, exclusive of the instant thirty
        days earlier — over the same included set: the summary is
        `MOSTLY_POSITIVE` when the positive share is at least seventy percent,
        `MIXED` when it is at least forty percent but below seventy, and
        `MOSTLY_NEGATIVE` below that; an empty window yields null."

        Design: Corner/calculations/recent_review_summary_thresholds
        """
        developer, title, users = self._setup_summary_scenario()
        for u in users[:7]:
            post_review(title["id"], u, developer, is_positive=True, body="g")
        for u in users[7:]:
            post_review(title["id"], u, developer, is_positive=False, body="b")

        title_read = read_title(title["id"], developer)
        # 7/10 = 0.70 exactly -> MOSTLY_POSITIVE (inclusive threshold).
        assert title_read["recent_review_summary"] == "MOSTLY_POSITIVE"
        # All reviewers at 0 playtime -> weight 1 each; 10000 * 7/10 = 7000.
        assert title_read["review_score_bps"] == 7000
        # 3 negatives < 10 -> no bomb window.
        assert title_read["review_bomb_flag"] is False

    def test_forty_percent_positive_is_mixed(self):
        """PRD §3.7: "`MIXED` when it is at least forty percent but below
        seventy"

        Design: Corner/calculations/recent_review_summary_thresholds
        """
        developer, title, users = self._setup_summary_scenario()
        for u in users[:4]:
            post_review(title["id"], u, developer, is_positive=True, body="g")
        for u in users[4:]:
            post_review(title["id"], u, developer, is_positive=False, body="b")

        title_read = read_title(title["id"], developer)
        # 4/10 = 0.40 exactly -> MIXED (inclusive lower threshold).
        assert title_read["recent_review_summary"] == "MIXED"
        assert title_read["review_score_bps"] == 4000


class TestFreeKeyAllowanceSnapshot:
    def test_allowance_snapshot_is_max_5000_and_sales(self):
        """PRD §3.6: "The batch is created in `REQUESTED`, and at that moment
        the server snapshots `free_key_allowance_at_request` as the larger of
        5000 and the title's lifetime completed sale count — purchases in
        `COMPLETED` or `PARTIALLY_REFUNDED`, with `REFUNDED` purchases no longer
        counting."

        Design: Corner/calculations/free_key_allowance_snapshot_at_request
        """
        developer, title = create_released_title(base_price_usd_cents=500)
        dev_headers = make_developer_headers(developer["id"])

        batch = get_success_data(
            api_client.create_key_batch(
                create_key_batch_payload(
                    title["id"], requested_quantity=5001, free_keys_in_batch=5001
                ),
                dev_headers,
            )
        )
        assert batch["free_key_allowance_at_request"] == 5000  # max(5000, 0 sales)
        assert batch["status"] == "REQUESTED"

        res = api_client.approve_key_batch(batch["id"], OPS)
        validate_error(res, ApiErrorId.ERR_FREE_KEY_ALLOWANCE_EXCEEDED)

        batch_read = get_success_data(api_client.get_key_batch(batch["id"], dev_headers))
        assert batch_read["status"] == "REQUESTED"
