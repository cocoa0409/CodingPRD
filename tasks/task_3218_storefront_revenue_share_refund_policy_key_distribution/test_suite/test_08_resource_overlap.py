"""Depth tests for interval semantics (bomb-window extension, redeem velocity)."""
from test_helpers import (
    api_client,
    create_and_approve_key_batch,
    create_buyer,
    create_n_buyers_with_purchases,
    create_released_title,
    get_success_data,
    list_batch_keys,
    list_title_bomb_windows,
    make_user_headers,
    post_review,
    read_title,
    set_clock,
    validate_error,
    validate_success,
    ApiErrorId,
    TEST_USERS,
)


class TestReviewBombWindowExtension:
    def test_second_trigger_extends_existing_window_instead_of_creating(self):
        """PRD §3.7: "Only one window per title may be `ACTIVE` at a time: a
        second trigger while one is open instead extends the existing window's
        `end_at` to seven days from now."

        Design: Difficulty/resource_temporal_overlap/review_bomb_window_extension_semantics
        """
        set_clock("2026-09-03T12:00:00Z")
        developer, title = create_released_title(base_price_usd_cents=500)
        users, _ = create_n_buyers_with_purchases(title, 20)

        # First trigger: ten negatives inside 24h (10/10 >= 0.80, count >= 10).
        for u in users[:10]:
            post_review(title["id"], u, developer, is_positive=False, body="b")

        windows = list_title_bomb_windows(title["id"], developer)
        assert len(windows) == 1
        assert windows[0]["end_at"] == "2026-09-10T12:00:00.000Z"
        window_id = windows[0]["id"]

        # Advance two days; ten more negatives trigger again while the window
        # is ACTIVE. Note: reviews from the first batch are >= 48h old by now
        # and fall outside the trailing-24h detection window.
        set_clock("2026-09-05T12:00:00Z")
        for u in users[10:20]:
            post_review(title["id"], u, developer, is_positive=False, body="b")

        windows = list_title_bomb_windows(title["id"], developer)
        assert len(windows) == 1, "a second trigger must extend, not create"
        assert windows[0]["id"] == window_id
        assert windows[0]["status"] == "ACTIVE"
        assert windows[0]["end_at"] == "2026-09-12T12:00:00.000Z"

    def test_extended_window_keeps_bomb_flag_true(self):
        """PRD §3.7: "While any `ACTIVE` window covers the present, the title's
        `review_bomb_flag` is true."

        Design: Difficulty/resource_temporal_overlap/review_bomb_window_extension_semantics
        """
        set_clock("2026-09-03T12:00:00Z")
        developer, title = create_released_title(base_price_usd_cents=500)
        users, _ = create_n_buyers_with_purchases(title, 20)

        for u in users[:10]:
            post_review(title["id"], u, developer, is_positive=False, body="b")
        assert read_title(title["id"], developer)["review_bomb_flag"] is True

        set_clock("2026-09-05T12:00:00Z")
        for u in users[10:20]:
            post_review(title["id"], u, developer, is_positive=False, body="b")

        title_read = read_title(title["id"], developer)
        assert title_read["review_bomb_flag"] is True
        windows = list_title_bomb_windows(title["id"], developer)
        assert len(windows) == 1
        assert windows[0]["end_at"] == "2026-09-12T12:00:00.000Z"


class TestKeyRedemptionVelocityWindow:
    def _setup_keys(self, quantity=10):
        set_clock("2026-09-06T00:00:00Z")
        developer, title = create_released_title(base_price_usd_cents=500)
        batch = create_and_approve_key_batch(title, developer, requested_quantity=quantity)
        keys = list_batch_keys(batch["id"], developer)
        redeemer = create_buyer()
        return developer, title, keys, redeemer

    def test_fourth_redemption_in_sixty_minutes_rejected(self):
        """PRD §3.6: "A velocity guard then applies as gray-market protection:
        within the trailing sixty minutes the redeeming account must have fewer
        than 3 successful redemptions, and across all accounts the trailing
        sixty minutes must show fewer than 50 successful redemptions — either
        breach is rejected with `ERR_REDEEM_VELOCITY` (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/key_redemption_velocity_account_window
        """
        developer, title, keys, redeemer = self._setup_keys()
        headers = make_user_headers(redeemer["id"])

        for key in keys[:3]:
            redeemed = get_success_data(
                api_client.redeem_key({"key_code": key["key_code"]}, headers)
            )
            assert redeemed["status"] == "REDEEMED"

        res = api_client.redeem_key({"key_code": keys[3]["key_code"]}, headers)
        validate_error(res, ApiErrorId.ERR_REDEEM_VELOCITY)

        key3 = validate_success(api_client.get_key(keys[3]["id"], TEST_USERS["platform_ops_headers"]))
        assert key3["status"] == "UNUSED"

    def test_redemption_allowed_again_after_window_slides(self):
        """PRD §2.4: "All temporal reasoning in the storefront — refund windows,
        abuse-score windows, review-bomb detection windows, release scheduling —
        is evaluated against a server-side logical clock, never against
        wall-clock time."

        Design: Difficulty/resource_temporal_overlap/key_redemption_velocity_account_window
        """
        developer, title, keys, redeemer = self._setup_keys()
        headers = make_user_headers(redeemer["id"])

        for key in keys[:3]:
            get_success_data(
                api_client.redeem_key({"key_code": key["key_code"]}, headers)
            )
        res = api_client.redeem_key({"key_code": keys[3]["key_code"]}, headers)
        validate_error(res, ApiErrorId.ERR_REDEEM_VELOCITY)

        # Move the logical clock 61 minutes forward; the sliding window empties.
        set_clock("2026-09-06T01:01:00Z")
        redeemed = get_success_data(
            api_client.redeem_key({"key_code": keys[4]["key_code"]}, headers)
        )
        assert redeemed["status"] == "REDEEMED"
        assert redeemed["redeemed_by_account_id"] == redeemer["id"]
