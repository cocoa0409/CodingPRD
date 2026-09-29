"""Recency-frequency-monetary scoring, and the tier and strategy it selects.

Five segments are placed across five tiers, two of them one band step apart on
either side of the CORE/OCCASIONAL edge, because the strategy column is not
monotonic in the tier: CORE and OCCASIONAL share STANDARD while LAPSED gets its
own REACTIVATION. Every band edge here is inclusive on the favourable side, so a
handler that banded with a strict comparison lands one tier low.
"""
from test_helpers import (
    CLOCK_START,
    assert_housefile_segment,
    new_season,
    new_segment,
    set_clock,
)

SCORING_INPUTS = {
    "S_BEST": {
        "recency_days": 45,
        "orders_12mo": 7,
        "ltv_cents": 62000,
        "housefile_count": 30000,
        "avg_order_value_cents": 18500,
        "historical_response_rate_bps": 620,
    },
    "S_EDGE600": {
        "recency_days": 90,
        "orders_12mo": 2,
        "ltv_cents": 5000,
        "housefile_count": 12000,
        "avg_order_value_cents": 9000,
        "historical_response_rate_bps": 300,
    },
    "S_EDGE580": {
        "recency_days": 180,
        "orders_12mo": 3,
        "ltv_cents": 5000,
        "housefile_count": 12000,
        "avg_order_value_cents": 9000,
        "historical_response_rate_bps": 300,
    },
    "S_LAPSE200": {
        "recency_days": 730,
        "orders_12mo": 1,
        "ltv_cents": 5000,
        "housefile_count": 8000,
        "avg_order_value_cents": 7000,
        "historical_response_rate_bps": 120,
    },
    "S_DORM": {
        "recency_days": 731,
        "orders_12mo": 0,
        "ltv_cents": 4999,
        "housefile_count": 5000,
        "avg_order_value_cents": 6000,
        "historical_response_rate_bps": 40,
    },
}


def _five_segments_across_five_tiers() -> dict:
    """One season holding five segments whose scoring inputs sit on five
    different combinations of the three point scales."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segments = {
        code: new_segment(season["id"], segment_code=code, **inputs)
        for code, inputs in SCORING_INPUTS.items()
    }
    return segments


class TestRecencyFrequencyMonetaryScoring:
    def test_the_three_point_scales_sum_and_multiply_to_the_rfm_score(self, api):
        """PRD §3.1: "The three point awards are added together and the sum is
        multiplied by ten to yield `rfm_score`, an exact integer between 0 and 1000
        that never involves rounding. Every band edge is inclusive on the favourable
        side, so a segment whose `recency_days` is exactly 90 earns the full 40
        recency points while one at 91 earns 30."

        Design: Corner/calculations/rfm_band_constants_map_to_tier_and_contact_strategy
        """
        segments = _five_segments_across_five_tiers()

        for segment in segments.values():
            assert_housefile_segment(segment)

        assert segments["S_BEST"]["rfm_score"] == 1000
        assert segments["S_EDGE600"]["rfm_score"] == 600
        assert segments["S_EDGE580"]["rfm_score"] == 580
        assert segments["S_LAPSE200"]["rfm_score"] == 200
        assert segments["S_DORM"]["rfm_score"] == 0

    def test_the_score_selects_the_tier_and_the_tier_supplies_the_strategy(self, api):
        """PRD §3.1: "Here too the boundary is inclusive on the favourable side — a
        score of exactly 200 is `LAPSED`, not `DORMANT`. The tier in turn supplies a
        default `contact_strategy` when the planner does not name one: `BEST`
        defaults to `PREMIUM_FULL`, both `CORE` and `OCCASIONAL` default to
        `STANDARD`, `LAPSED` defaults to `REACTIVATION`, and `DORMANT` defaults to
        `SUPPRESS_ONLY`."

        Design: Corner/calculations/rfm_band_constants_map_to_tier_and_contact_strategy
        """
        segments = _five_segments_across_five_tiers()

        assert segments["S_BEST"]["segment_tier"] == "BEST"
        assert segments["S_BEST"]["contact_strategy"] == "PREMIUM_FULL"

        assert segments["S_EDGE600"]["segment_tier"] == "CORE"
        assert segments["S_EDGE600"]["contact_strategy"] == "STANDARD"

        assert segments["S_EDGE580"]["segment_tier"] == "OCCASIONAL"
        assert segments["S_EDGE580"]["contact_strategy"] == "STANDARD"

        assert segments["S_LAPSE200"]["segment_tier"] == "LAPSED"
        assert segments["S_LAPSE200"]["contact_strategy"] == "REACTIVATION"

        assert segments["S_DORM"]["segment_tier"] == "DORMANT"
        assert segments["S_DORM"]["contact_strategy"] == "SUPPRESS_ONLY"
