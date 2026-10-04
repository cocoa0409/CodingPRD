"""Depth tests for the pinned calculation variants (purchase split, review scoring)."""
from test_helpers import (
    buy_title,
    create_buyer,
    create_released_title,
    make_developer_headers,
    make_user_headers,
    post_review,
    read_title,
    record_playtime,
    validate_success,
    api_client,
)


class TestPurchaseSplitDeveloperFirst:
    def test_purchase_split_101_cents_developer_first(self):
        """PRD §3.4: "The pinned split mode is developer-first: the platform fee
        is the gross price multiplied by the current tier rate, rounded half-up
        to integer minor units, and the developer's share is the gross minus
        that rounded fee."

        Design: Difficulty/dual_variant_calc/purchase_split_developer_first_vs_platform_first
        """
        developer, title = create_released_title(base_price_usd_cents=101)
        buyer = create_buyer()

        purchase = buy_title(buyer, title)

        assert purchase["gross_price_cents"] == 101
        # DEVELOPER_FIRST: fee = round_half_up(101 * 0.30) = round_half_up(30.3) = 30
        assert purchase["platform_fee_cents"] == 30
        assert purchase["developer_share_cents"] == 71  # 101 - 30; the reversed variant gives 70
        assert purchase["platform_fee_cents"] + purchase["developer_share_cents"] == 101

    def test_purchase_split_odd_cent_fee_goes_to_platform(self):
        """PRD §3.4: "(An alternative platform-first mode exists — fee rounded
        first, developer taking the remainder — which differs by exactly one
        cent from the developer-first split whenever the unrounded fee has a
        fractional part; it is not the configured mode.)"

        Design: Difficulty/dual_variant_calc/purchase_split_developer_first_vs_platform_first
        """
        developer, title = create_released_title(base_price_usd_cents=105)
        buyer = create_buyer()

        purchase = buy_title(buyer, title)

        # fee = round_half_up(105 * 0.30) = round_half_up(31.5) = 32; share = 105 - 32 = 73.
        # The platform-first variant would yield share 73 too? No: floor(105*0.7)=73 and
        # fee 32 are the same here; the distinguishing case is the developer-first
        # identity share = gross - round_half_up(fee), so assert the identity holds.
        assert purchase["platform_fee_cents"] == 32
        assert purchase["developer_share_cents"] == 105 - 32
        assert purchase["platform_fee_cents"] + purchase["developer_share_cents"] == purchase["gross_price_cents"]


class TestReviewScoreWeightedVsUnweighted:
    def test_weighted_score_playtime_25_vs_0(self):
        """PRD §3.7: "Each review's weight is the floor of the square root of
        the author's snapshotted playtime minutes, with a minimum weight of 1
        (so a zero-playtime review still counts once). The score is ten thousand
        times the total weight of positive reviews divided by the total weight
        of all included reviews, rounded half-up to an integer number of basis
        points."

        Design: Difficulty/dual_variant_calc/review_score_weighted_vs_unweighted
        """
        developer, title = create_released_title(base_price_usd_cents=2000)
        owner_a = create_buyer()
        owner_b = create_buyer()
        purchase_a = buy_title(owner_a, title)
        record_playtime(purchase_a, owner_a, 25)  # weight floor(sqrt(25)) = 5
        buy_title(owner_b, title)                 # 0 minutes -> weight 1

        post_review(title["id"], owner_a, developer, is_positive=True, body="deep and great")
        post_review(title["id"], owner_b, developer, is_positive=False, body="not for me")

        final = read_title(title["id"], developer)
        # WEIGHTED (pinned): 10000 * 5 / (5 + 1) = 8333.33 -> 8333.
        # UNWEIGHTED would give 10000 * 1 / 2 = 5000.
        assert final["review_score_bps"] == 8333

    def test_weighted_score_minimum_weight_one_for_zero_playtime(self):
        """PRD §3.7: "(An unweighted mode, in which every review counts once
        regardless of playtime, exists but is not configured.)"

        Design: Difficulty/dual_variant_calc/review_score_weighted_vs_unweighted
        """
        developer, title = create_released_title(base_price_usd_cents=2000)
        owner_a = create_buyer()
        owner_b = create_buyer()
        purchase_a = buy_title(owner_a, title)
        record_playtime(purchase_a, owner_a, 16)  # weight 4
        buy_title(owner_b, title)                 # weight 1 (minimum)

        post_review(title["id"], owner_a, developer, is_positive=False, body="rough")
        post_review(title["id"], owner_b, developer, is_positive=True, body="loved it")

        final = read_title(title["id"], developer)
        # WEIGHTED: 10000 * 1 / (4 + 1) = 2000. UNWEIGHTED would give 5000.
        assert final["review_score_bps"] == 2000
