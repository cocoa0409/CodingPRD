"""Breadth coverage for cross-cutting cascades and derived review fields."""
from test_helpers import (
    api_client,
    buy_title,
    create_buyer,
    create_n_buyers_with_purchases,
    create_released_title,
    get_success_data,
    list_title_bomb_windows,
    make_user_headers,
    post_review,
    read_title,
    set_clock,
    validate_success,
    TEST_USERS,
)

TRUST = TEST_USERS["trust_safety_headers"]


class TestReviewBanCascade:
    def test_ban_removes_reviews_and_clears_score(self):
        """PRD §3.5: "Banning moves an account from `ACTIVE` or `RESTRICTED` to
        the terminal `BANNED` and cascades every `PUBLISHED` review the account
        has authored to `REMOVED`, triggering the score recomputes of §3.7 for
        each affected title."

        Design: Corner/cross_cutting_layers/review_ban_cascade_removes_reviews_and_recomputes
        """
        developer, title = create_released_title(base_price_usd_cents=500)
        author = create_buyer()
        buy_title(author, title)
        review = post_review(title["id"], author, developer, is_positive=True, body="nice")

        title_mid = read_title(title["id"], developer)
        assert title_mid["review_score_bps"] == 10000

        get_success_data(api_client.ban_user(author["id"], TRUST))

        review_read = validate_success(api_client.get_review(review["id"], TRUST))
        assert review_read["status"] == "REMOVED"

        title_read = read_title(title["id"], developer)
        assert title_read["review_score_bps"] is None
        assert title_read["recent_review_summary"] is None


class TestBombWindowOffTopicHandling:
    def _bomb_scenario(self):
        """RELEASED title, 1 positive review, then 10 negatives triggering a
        bomb window. Returns (developer, title, users)."""
        set_clock("2026-09-03T00:00:00Z")
        developer, title = create_released_title(base_price_usd_cents=500)
        users, _ = create_n_buyers_with_purchases(title, 11)
        post_review(title["id"], users[0], developer, is_positive=True, body="g")
        for u in users[1:11]:
            post_review(title["id"], u, developer, is_positive=False, body="b")
        return developer, title, users

    def test_off_topic_reviews_excluded_from_score(self):
        """PRD §3.7: "If the review's `created_at` falls inside any active
        review-bomb window for the title, it is immediately marked `off_topic` —
        it still publishes, but never scores."

        Design: Corner/cross_cutting_layers/off_topic_reviews_excluded_from_score
        """
        developer, title, users = self._bomb_scenario()

        mid = read_title(title["id"], developer)
        assert mid["review_bomb_flag"] is True
        # 10/11 negatives = 0.909 >= 0.80 and count >= 10.

        # A new positive review posted inside the ACTIVE window is off-topic.
        late_buyer = create_buyer()
        buy_title(late_buyer, title)
        late_review = post_review(
            title["id"], late_buyer, developer, is_positive=True, body="late positive"
        )
        assert late_review["off_topic"] is True

        final = read_title(title["id"], developer)
        # Only the pre-window positive review scores; window negatives are
        # retro-marked off_topic and the late positive is off-topic too.
        assert final["review_score_bps"] == 10000

    def test_bomb_window_close_restores_covered_reviews(self):
        """PRD §3.7: "Closing a window moves it from `ACTIVE` to `CLOSED`: if no
        other active window still covers the present, the title's
        `review_bomb_flag` clears, and the score and recent summary are
        recomputed — while the `off_topic` marks placed on reviews created
        inside the window are lifted, restoring them to scoring eligibility."

        Design: Corner/cross_cutting_layers/bomb_window_close_restores_covered_reviews
        """
        developer, title, users = self._bomb_scenario()

        windows = list_title_bomb_windows(title["id"], developer)
        assert len(windows) == 1
        window_id = windows[0]["id"]

        get_success_data(api_client.close_review_bomb_window(window_id, TRUST))

        title_read = read_title(title["id"], developer)
        assert title_read["review_bomb_flag"] is False
        # All 11 reviews (1 positive + 10 negatives, all weight 1) score again:
        # round_half_up(10000 * 1/11) = 909.
        assert title_read["review_score_bps"] == 909

        window_read = validate_success(api_client.get_review_bomb_window(window_id, TRUST))
        assert window_read["status"] == "CLOSED"
