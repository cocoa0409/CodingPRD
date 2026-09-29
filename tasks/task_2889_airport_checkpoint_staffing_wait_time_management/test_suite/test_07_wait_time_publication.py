"""The published wait time: window geometry, thin data and the weighted mean.

Covers PRD section 3.8 - the inclusive twenty-minute window, the ``>=`` breach
comparison at the exact threshold, and the switch from the most recent sample to
a method-and-size weighted mean at the third sample.
"""

from test_helpers import (
    MANAGER_HEADERS,
    assert_breach_counters,
    assert_posture,
    assert_publication,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import CLOCK_1000, Scenario

CLOCK_1005 = "2026-09-10T10:05:00Z"
CLOCK_1020 = "2026-09-10T10:20:00Z"
CLOCK_1021 = "2026-09-10T10:21:00Z"


def _wait_time(scenario: Scenario, lane_type: str = "STANDARD", headers=None) -> dict:
    return validate_success(
        scenario.api.get_published_wait_time(
            scenario.checkpoint_id, headers or MANAGER_HEADERS, {"lane_type": lane_type}
        )
    )


class TestBreachAtExactThreshold:
    """PRD 3.8 - the breach comparison is >= against threshold_minutes."""

    def test_one_second_short_of_the_threshold_does_not_breach(self, base: Scenario):
        """869 seconds rounds to 14 minutes, one minute below the 15-minute threshold.

        Design: Difficulty/boundary_precision_check/published_wait_breach_at_exact_threshold_on_observation_post
        """
        base.set_clock(CLOCK_1000)
        observation = base.post_observation(
            lane_type="STANDARD",
            sampled_wait_seconds=869,
            measurement_method="BLE_SENSOR",
            sample_size=1,
        )
        assert observation["published_wait_minutes_snapshot"] == 14
        assert observation["breached_threshold"] is False

        assert_publication(
            _wait_time(base),
            published_wait_minutes=14,
            weighted_average_seconds="869.00",
            sample_count=1,
            threshold_minutes=15,
            breached=False,
        )
        checkpoint = validate_success(
            base.api.get_checkpoint(base.checkpoint_id, MANAGER_HEADERS)
        )
        assert_breach_counters(checkpoint, standard=0)

    def test_exactly_at_the_threshold_breaches_and_moves_the_run_counter(
        self, base: Scenario
    ):
        """870 seconds rounds to 15 minutes, which is a breach rather than a near miss.

        Design: Difficulty/boundary_precision_check/published_wait_breach_at_exact_threshold_on_observation_post
        """
        base.set_clock(CLOCK_1000)
        base.post_observation(
            lane_type="STANDARD",
            sampled_wait_seconds=869,
            measurement_method="BLE_SENSOR",
            sample_size=1,
        )

        base.set_clock(CLOCK_1005)
        at_threshold = base.post_observation(
            lane_type="STANDARD",
            sampled_wait_seconds=870,
            measurement_method="BLE_SENSOR",
            sample_size=1,
        )
        # Two samples is still the thin-data path, so the publication is the most
        # recent sample: 870 / 60 = 14.5, which rounds half up to 15.
        assert at_threshold["published_wait_minutes_snapshot"] == 15
        assert at_threshold["breached_threshold"] is True

        checkpoint = validate_success(
            base.api.get_checkpoint(base.checkpoint_id, MANAGER_HEADERS)
        )
        assert_breach_counters(checkpoint, standard=1)
        assert_posture(checkpoint, "NORMAL")

        tickets, _meta = validate_paginated(
            base.api.list_escalation_tickets(
                MANAGER_HEADERS, {"checkpoint_id": base.checkpoint_id}
            )
        )
        assert tickets == [], "one breach is short of the two-breach escalation run"


class TestPublicationWindowGeometry:
    """PRD 3.8 - the twenty-minute window is inclusive at both ends."""

    def test_a_sample_exactly_twenty_minutes_old_is_still_in_the_window(
        self, base: Scenario
    ):
        """The window [10:00, 10:20] still contains the 10:00 sample.

        Design: Difficulty/boundary_precision_check/wait_time_window_inclusive_end_and_empty_window
        """
        base.set_clock(CLOCK_1000)
        observation = base.post_observation(
            lane_type="STANDARD",
            sampled_wait_seconds=600,
            measurement_method="MANUAL_TIMESTAMP",
            sample_size=4,
        )

        base.set_clock(CLOCK_1020)
        assert_publication(
            _wait_time(base),
            published_wait_minutes=10,
            weighted_average_seconds="600.00",
            sample_count=1,
            window_start_utc=CLOCK_1000,
            window_end_utc=CLOCK_1020,
        )

        snapshot = validate_success(
            base.api.get_wait_observation(observation["id"], MANAGER_HEADERS)
        )
        assert snapshot["published_wait_minutes_snapshot"] == 10
        assert snapshot["breached_threshold"] is False

    def test_one_minute_later_the_window_is_empty_and_publishes_nothing(
        self, base: Scenario
    ):
        """An empty window returns null minutes, a null average and zero samples.

        Design: Difficulty/boundary_precision_check/wait_time_window_inclusive_end_and_empty_window
        """
        base.set_clock(CLOCK_1000)
        base.post_observation(
            lane_type="STANDARD",
            sampled_wait_seconds=600,
            measurement_method="MANUAL_TIMESTAMP",
            sample_size=4,
        )

        base.set_clock(CLOCK_1020)
        assert _wait_time(base, "EXPEDITED")["sample_count"] == 0
        assert _wait_time(base, "EXPEDITED")["published_wait_minutes"] is None

        base.set_clock(CLOCK_1021)
        assert_publication(
            _wait_time(base),
            published_wait_minutes=None,
            weighted_average_seconds=None,
            sample_count=0,
            breached=False,
        )
        assert_publication(
            _wait_time(base, "EXPEDITED"),
            published_wait_minutes=None,
            weighted_average_seconds=None,
            sample_count=0,
        )


class TestWeightedMeanAboveThreeSamples:
    """PRD 3.8 - thin data publishes the latest sample; three samples publish a mean."""

    def test_two_samples_publish_the_most_recent_one_rather_than_their_mean(
        self, supervised_floor: Scenario
    ):
        """The second sample publishes 15, not the 13 that averaging 600 and 900 gives.

        Design: Corner/calculations/published_wait_weights_by_method_and_sample_size_above_three_samples
        """
        headers = supervised_floor.supervisor_headers
        first = supervised_floor.post_observation(
            headers=headers,
            lane_type="STANDARD",
            sampled_wait_seconds=600,
            measurement_method="BLE_SENSOR",
            sample_size=10,
        )
        assert first["published_wait_minutes_snapshot"] == 10
        assert first["breached_threshold"] is False

        second = supervised_floor.post_observation(
            headers=headers,
            lane_type="STANDARD",
            sampled_wait_seconds=900,
            measurement_method="MANUAL_TIMESTAMP",
            sample_size=5,
        )
        assert second["published_wait_minutes_snapshot"] == 15, (
            "the mean of 600 and 900 would publish 13; the thin-data path publishes 15"
        )
        assert second["breached_threshold"] is True

    def test_the_third_sample_switches_to_the_method_weighted_mean(
        self, supervised_floor: Scenario
    ):
        """Weights 3x10, 2x5 and 1x4 sum to 44 and 31800/44 publishes 12 minutes.

        Design: Corner/calculations/published_wait_weights_by_method_and_sample_size_above_three_samples
        """
        headers = supervised_floor.supervisor_headers
        for seconds, method, size in (
            (600, "BLE_SENSOR", 10),
            (900, "MANUAL_TIMESTAMP", 5),
        ):
            supervised_floor.post_observation(
                headers=headers,
                lane_type="STANDARD",
                sampled_wait_seconds=seconds,
                measurement_method=method,
                sample_size=size,
            )

        third = supervised_floor.post_observation(
            headers=headers,
            lane_type="STANDARD",
            sampled_wait_seconds=1200,
            measurement_method="STAFF_ESTIMATE",
            sample_size=4,
        )
        assert third["published_wait_minutes_snapshot"] == 12
        assert third["breached_threshold"] is False

        assert_publication(
            _wait_time(supervised_floor, "STANDARD", headers),
            published_wait_minutes=12,
            weighted_average_seconds="722.73",
            sample_count=3,
            threshold_minutes=15,
            breached=False,
        )
        assert_publication(
            _wait_time(supervised_floor, "EXPEDITED", headers),
            published_wait_minutes=None,
            weighted_average_seconds=None,
            sample_count=0,
        )

        checkpoint = validate_success(
            supervised_floor.api.get_checkpoint(
                supervised_floor.checkpoint_id, MANAGER_HEADERS
            )
        )
        assert_breach_counters(checkpoint, standard=0)
        tickets, _meta = validate_paginated(
            supervised_floor.api.list_escalation_tickets(
                MANAGER_HEADERS, {"checkpoint_id": supervised_floor.checkpoint_id}
            )
        )
        assert tickets == [], "the breach run reset before it reached two"
