"""Depth tests for strict numeric thresholds (playtime, bomb detection)."""
from test_helpers import (
    api_client,
    buy_title,
    create_buyer,
    create_n_buyers_with_purchases,
    create_released_title,
    get_success_data,
    list_title_bomb_windows,
    make_developer_headers,
    make_user_headers,
    post_review,
    read_title,
    record_playtime,
    request_refund,
    set_clock,
    validate_success,
    TEST_USERS,
)

OPS = TEST_USERS["platform_ops_headers"]


class TestRefundPlaytimeBoundary:
    def test_119_minutes_auto_approves_120_stays_requested(self):
        """PRD §3.5: "the purchase's `playtime_minutes` is strictly below 120 —
        119 minutes qualifies, 120 does not"

        Design: Difficulty/boundary_precision_check/refund_playtime_boundary_119_vs_120
        """
        developer, title = create_released_title(base_price_usd_cents=900)
        buyer = create_buyer()
        p_119 = buy_title(buyer, title)
        record_playtime(p_119, buyer, 119)
        p_120 = buy_title(buyer, title)
        record_playtime(p_120, buyer, 120)

        rr_119 = request_refund(p_119, buyer, reason="a")
        rr_120 = request_refund(p_120, buyer, reason="b")

        assert rr_119["status"] == "APPROVED"
        assert rr_120["status"] == "REQUESTED"

        purchase_119 = validate_success(
            api_client.get_purchase(p_119["id"], make_user_headers(buyer["id"]))
        )
        purchase_120 = validate_success(
            api_client.get_purchase(p_120["id"], make_user_headers(buyer["id"]))
        )
        assert purchase_119["status"] == "REFUNDED"
        assert purchase_120["status"] == "COMPLETED"

    def test_zero_playtime_auto_approves(self):
        """PRD §3.5: "When the whole policy passes, the new request is
        immediately `APPROVED`: its `approved_amount_cents` is set — a
        zero-amount request approving for the full remaining gross — its
        `decided_at` is stamped, and the purchase cascades as described below."

        Design: Difficulty/boundary_precision_check/refund_playtime_boundary_119_vs_120
        """
        developer, title = create_released_title(base_price_usd_cents=900)
        buyer = create_buyer()
        purchase = buy_title(buyer, title)  # 0 minutes played, same instant

        rr = request_refund(purchase, buyer, reason="instant regret")
        assert rr["status"] == "APPROVED"
        assert rr["approved_amount_cents"] == 900

        purchase_read = validate_success(
            api_client.get_purchase(purchase["id"], make_user_headers(buyer["id"]))
        )
        assert purchase_read["status"] == "REFUNDED"
        assert purchase_read["refunded_cents"] == 900


class TestReviewBombThreshold:
    def _setup_title_with_reviewers(self, n):
        developer, title = create_released_title(base_price_usd_cents=500)
        users, purchases = create_n_buyers_with_purchases(title, n)
        return developer, title, users

    def test_nine_negatives_do_not_trigger_tenth_does(self):
        """PRD §3.7: "When at least 10 negative reviews have accumulated and the
        negative share reaches at least eighty percent — evaluated exactly, with
        the comparison holding whenever five times the negative count is at
        least four times the total — a review-bomb window opens."

        Design: Difficulty/boundary_precision_check/review_bomb_threshold_exact_count_and_ratio
        """
        set_clock("2026-09-03T12:00:00Z")
        developer, title, users = self._setup_title_with_reviewers(11)

        post_review(title["id"], users[0], developer, is_positive=True, body="good")
        for u in users[1:10]:  # nine negatives
            post_review(title["id"], u, developer, is_positive=False, body="bad")

        mid = read_title(title["id"], developer)
        assert mid["review_bomb_flag"] is False  # 9 negatives < 10

        post_review(title["id"], users[10], developer, is_positive=False, body="bad")

        after = read_title(title["id"], developer)
        # 10 negatives of 11 total = 0.909 >= 0.80, and count >= 10.
        assert after["review_bomb_flag"] is True

        windows = list_title_bomb_windows(title["id"], developer)
        assert len(windows) == 1
        assert windows[0]["trigger_review_count"] == 10
        assert windows[0]["end_at"] == "2026-09-10T12:00:00.000Z"

    def test_bomb_window_start_is_oldest_negative_review(self):
        """PRD §3.7: "The new window's `start_at` is the `created_at` of the
        oldest negative review in the detection window (earliest first on ties),
        its `end_at` is seven days from now, it records the triggering negative
        count in `trigger_review_count`, and it is born `ACTIVE`."

        Design: Difficulty/boundary_precision_check/review_bomb_threshold_exact_count_and_ratio
        """
        set_clock("2026-09-04T00:00:00Z")
        developer, title, users = self._setup_title_with_reviewers(11)

        first_negative = None
        for i, u in enumerate(users[1:11]):
            review = post_review(title["id"], u, developer, is_positive=False, body="bad")
            if first_negative is None:
                first_negative = review

        after = read_title(title["id"], developer)
        assert after["review_bomb_flag"] is True

        windows = list_title_bomb_windows(title["id"], developer)
        assert len(windows) == 1
        assert windows[0]["start_at"] == first_negative["created_at"]
        assert windows[0]["status"] == "ACTIVE"
        assert windows[0]["end_at"] == "2026-09-11T00:00:00.000Z"
