"""Displayed rating average: rounding order and empty-set edge (PRD §2.8)."""
from test_helpers import (
    create_page,
    create_review,
    create_user,
    get_page,
    set_clock,
)


class TestDisplayedRatingAverage:
    def test_sum_then_divide_then_round_half_up(self, api):
        """PRD §2.8: "otherwise it is the sum of `rating` over the displayed
        reviews, divided by the displayed count, multiplied by 100, and rounded
        half-up at the final division only (sum first, then divide, then round;
        never round per-review)."

        Design: Corner/calculations/displayed_average_rounding_sum_then_round
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page()
        for rating in (5, 4, 4):
            author = create_user(trust_score=100)
            create_review(page["id"], author["id"], rating=rating)
        page_after = get_page(page["id"])
        assert page_after["displayed_review_count"] == 3
        # round_half_up(100 * 13 / 3) = round_half_up(433.33) = 433.
        assert page_after["displayed_rating_avg_x100"] == 433

    def test_page_with_no_displayed_reviews_reports_zero_average(self, api):
        """PRD §2.8: "when a page's `displayed_review_count` is zero, the
        average is exactly zero".

        Design: Corner/calculations/empty_page_average_is_zero
        """
        set_clock("2026-09-01T00:00:00Z")
        author = create_user()  # trust 50 -> FILTERED
        page = create_page()
        create_review(page["id"], author["id"], rating=5)
        page_after = get_page(page["id"])
        assert page_after["displayed_review_count"] == 0
        assert page_after["displayed_rating_avg_x100"] == 0

    def test_page_aggregates_start_at_zero_on_creation(self, api):
        """PRD §3.2: "The new page starts in `ACTIVE` status with
        `claimed_by_user_id` null (unclaimed), `merged_into_id` null,
        `ad_account_id` null, `displayed_review_count` equal to 0, and
        `displayed_rating_avg_x100` equal to 0."

        Design: Corner/entities/page_computed_aggregates_ignore_input
        """
        set_clock("2026-09-01T00:00:00Z")
        page = create_page(displayed_review_count=99, displayed_rating_avg_x100=99)
        assert page["status"] == "ACTIVE"
        assert page["claimed_by_user_id"] is None
        assert page["merged_into_id"] is None
        assert page["ad_account_id"] is None
        assert page["displayed_review_count"] == 0
        assert page["displayed_rating_avg_x100"] == 0
