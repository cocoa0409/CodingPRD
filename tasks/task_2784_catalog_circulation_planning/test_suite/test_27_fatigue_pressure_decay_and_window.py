"""Contact pressure as a live step function over immutable event rows.

Six touches are placed on the fresh side and one day past three band edges, plus
one touch a single day outside the season's fatigue window. The score is then
re-read after the clock moves a day: it must FALL, from 88 to 71, which only
happens if every event's decay is recomputed against the current clock and the
out-of-window touch is dropped. Summing the frozen per-row points reports 84.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    SEASON_DEFAULTS,
    fetch_segment,
    iso_utc,
    new_contact_event,
    new_season,
    new_segment,
    set_clock,
    validate_paginated,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}

NEXT_DAY = iso_utc("2026-08-02")

# (label, channel, contact_date) — whole-day ages as of the 2026-08-01 clock:
# 14, 15, 60, 61, 90 and 91 days.
TOUCHES = (
    ("e1", "MAIL", "2026-07-18"),
    ("e2", "MAIL", "2026-07-17"),
    ("e3", "EMAIL", "2026-06-02"),
    ("e4", "DIGITAL", "2026-06-01"),
    ("e5", "MAIL", "2026-05-03"),
    ("e6", "MAIL", "2026-05-02"),
)


def _six_touches_around_the_band_edges() -> dict:
    """One segment carrying six contacts logged while the clock still stands at
    its 2026-08-01 start, so each row freezes a different decay band."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A", **SCORING)

    events = {
        label: new_contact_event(segment["id"], iso_utc(date), channel)
        for label, channel, date in TOUCHES
    }
    return {
        "season": season,
        "segment": segment,
        "events": events,
        "scored": fetch_segment(segment["id"], ANALYST),
    }


def _the_same_touches_one_day_later() -> dict:
    """The six touches, then the clock advanced a whole day and a same-day digital
    touch logged, which forces the whole score to be recomputed."""
    world = _six_touches_around_the_band_edges()
    set_clock(NEXT_DAY)
    world["events"]["e7"] = new_contact_event(
        world["segment"]["id"], NEXT_DAY, "DIGITAL"
    )
    world["rescored"] = fetch_segment(world["segment"]["id"], ANALYST)
    return world


class TestDecayBandsAreStepFunctions:
    def test_each_band_edge_is_inclusive_on_the_fresher_side(self, api):
        """PRD §3.8: "Each contact's weight then decays in steps according to how
        many whole days separate its `contact_date` from the logical clock's current
        instant: a gap of 14 days or fewer retains the full 10000 basis points, 30
        days or fewer retains 7500, 60 days or fewer retains 5000, 90 days or fewer
        retains 2500, and anything beyond that retains nothing. The decay is a step
        function, not a continuous curve — every contact inside a band contributes
        identically — and the band edges are inclusive on the fresher side, so a
        contact exactly 14 days old still retains the full weight while one at 15 days
        retains three quarters."

        Design: Corner/calculations/fatigue_decay_bands_are_step_functions_and_the_window_drops_events
        """
        events = _six_touches_around_the_band_edges()["events"]

        assert events["e1"]["decay_factor_bps"] == 10000
        assert events["e2"]["decay_factor_bps"] == 7500
        assert events["e3"]["decay_factor_bps"] == 5000
        assert events["e4"]["decay_factor_bps"] == 2500
        assert events["e5"]["decay_factor_bps"] == 2500
        assert events["e6"]["decay_factor_bps"] == 0

        assert events["e1"]["channel_weight"] == 40
        assert events["e3"]["channel_weight"] == 12
        assert events["e4"]["channel_weight"] == 6

    def test_the_score_is_the_sum_of_individually_rounded_contributions(self, api):
        """PRD §3.8: "Each surviving contact's contribution is its channel weight
        multiplied by its decay factor, divided by ten thousand, rounded half up to
        whole points, and `fatigue_score` is the exact sum of those individually
        rounded contributions."

        Design: Corner/calculations/fatigue_decay_bands_are_step_functions_and_the_window_drops_events
        """
        world = _six_touches_around_the_band_edges()
        events = world["events"]

        assert events["e1"]["weighted_points"] == 40
        assert events["e2"]["weighted_points"] == 30
        assert events["e3"]["weighted_points"] == 6
        assert events["e4"]["weighted_points"] == 2
        assert events["e5"]["weighted_points"] == 10
        assert events["e6"]["weighted_points"] == 0

        assert world["scored"]["fatigue_score"] == 88
        assert world["scored"]["fatigue_score"] == 40 + 30 + 6 + 2 + 10 + 0


class TestTheScoreIsLiveWhileTheRowsAreFrozen:
    def test_advancing_the_clock_lowers_the_score_and_drops_a_touch(self, api):
        """PRD §3.8: "The row is immutable thereafter. A later recompute derives all
        three values locally for its own summation and never rewrites the stored row,
        so a row's frozen `weighted_points` may legitimately disagree with the
        contribution that same row is currently making to its segment's score."

        Design: Corner/calculations/fatigue_decay_bands_are_step_functions_and_the_window_drops_events
        """
        world = _the_same_touches_one_day_later()
        events = world["events"]

        assert events["e7"]["decay_factor_bps"] == 10000
        assert events["e7"]["weighted_points"] == 6

        assert world["rescored"]["fatigue_score"] == 71
        assert world["rescored"]["fatigue_score"] == 30 + 30 + 3 + 2 + 6
        assert world["rescored"]["fatigue_score"] != 84
        assert world["rescored"]["fatigue_score"] < world["scored"]["fatigue_score"]

        stored, meta = validate_paginated(
            api.list_segment_contact_events(world["segment"]["id"], ANALYST)
        )
        assert meta["total_count"] == 7
        by_id = {row["id"]: row for row in stored}
        for label in ("e1", "e2", "e3", "e4", "e5", "e6"):
            created = events[label]
            assert by_id[created["id"]]["weighted_points"] == created[
                "weighted_points"
            ]
            assert by_id[created["id"]]["decay_factor_bps"] == created[
                "decay_factor_bps"
            ]

    def test_a_falling_score_never_reaches_the_suppression_threshold(self, api):
        """PRD §3.8: "When a recomputed `fatigue_score` reaches or exceeds the
        season's `fatigue_suppression_threshold`, the segment's `contact_strategy` is
        forced to `SUPPRESS_ONLY` and its `suppressed_at` is stamped with the logical
        clock's current instant; creating a contact event increments the segment's
        `version` by one."

        Design: Corner/calculations/fatigue_decay_bands_are_step_functions_and_the_window_drops_events
        """
        world = _the_same_touches_one_day_later()
        segment = world["rescored"]

        assert segment["fatigue_score"] == 71
        assert segment["fatigue_score"] < SEASON_DEFAULTS[
            "fatigue_suppression_threshold"
        ]
        assert segment["contact_strategy"] == "PREMIUM_FULL"
        assert segment["suppressed_at"] is None
        assert segment["version"] == 8
