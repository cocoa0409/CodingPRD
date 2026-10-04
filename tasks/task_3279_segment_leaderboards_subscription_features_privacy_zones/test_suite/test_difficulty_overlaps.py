"""Difficulty queue A: resource temporal/spatial overlap gates.

segment_spatial_overlap_gate: both-endpoints-within-50m rule on activation.
event_time_overlap_half_open: half-open one-hour windows on event creation.
"""

from test_helpers import (
    ApiErrorId,
    create_active_segment,
    create_athlete,
    create_club,
    create_event,
    create_segment,
    make_athlete_headers,
    validate_error,
    validate_success,
)
from test_helpers.factories import create_event_payload


class TestSegmentSpatialOverlapGate:
    def _owner_with_base(self, api, suffix):
        owner = create_athlete(api, email=f"g_{suffix}@x.com", display_name=f"G {suffix}")
        base = create_active_segment(
            api, owner["id"], name=f"Overlap Base {suffix}", sport_type="RIDE",
            start_lat=43.000, start_lng=-128.000, end_lat=43.010, end_lng=-128.000,
            distance_m=1100, city="Overtown",
        )
        return owner, base

    def test_one_endpoint_beyond_epsilon_passes(self, api):
        """PRD 3.5: "Second, overlap: activation is rejected with `ERR_SEGMENT_OVERLAP` when another `ACTIVE` segment of the same sport has both its start point within 50 meters of the candidate's start *and* its end point within 50 meters of the candidate's end — strictly within, so a 50-meter-exact distance on either endpoint is not an overlap."

        Design: Difficulty/resource_temporal_overlap/segment_spatial_overlap_gate
        """
        owner, _ = self._owner_with_base(api, "ov1")
        # start ~11m from base start, end ~111m from base end: only one endpoint within.
        half = create_segment(
            api, owner["id"], name="Overlap Half", sport_type="RIDE",
            start_lat=43.0001, start_lng=-128.000, end_lat=43.011, end_lng=-128.000,
            distance_m=1200, city="Overtown",
        )
        activated = validate_success(api.activate_segment(half["id"], make_athlete_headers(owner["id"])), 200)
        assert activated["status"] == "ACTIVE"

    def test_both_endpoints_within_epsilon_rejected(self, api):
        """PRD 3.5: "activation is rejected with `ERR_SEGMENT_OVERLAP` when another `ACTIVE` segment of the same sport has both its start point within 50 meters of the candidate's start *and* its end point within 50 meters of the candidate's end".

        Design: Difficulty/resource_temporal_overlap/segment_spatial_overlap_gate
        """
        owner, _ = self._owner_with_base(api, "ov2")
        full = create_segment(
            api, owner["id"], name="Overlap Full", sport_type="RIDE",
            start_lat=43.0001, start_lng=-128.000, end_lat=43.0101, end_lng=-128.000,
            distance_m=1100, city="Overtown",
        )
        resp = api.activate_segment(full["id"], make_athlete_headers(owner["id"]))
        validate_error(resp, ApiErrorId.ERR_SEGMENT_OVERLAP)


class TestEventTimeOverlapHalfOpen:
    def _world(self, api, suffix):
        owner = create_athlete(api, email=f"eo_{suffix}@x.com", display_name=f"EO {suffix}")
        segment = create_active_segment(
            api, owner["id"], name=f"Event Sprint {suffix}", sport_type="RIDE",
            start_lat=44.00, start_lng=-129.00, end_lat=44.01, end_lng=-129.00,
            distance_m=1000, city="Eventville",
        )
        club = create_club(api, owner["id"], name=f"Event Club {suffix}", sport_type="RIDE", join_policy="OPEN")
        return owner, segment, club

    def test_back_to_back_event_allowed(self, api):
        """PRD 3.7: "creating an event whose window intersects any other `PUBLISHED` event of the same club is rejected with `ERR_EVENT_TIME_OVERLAP` — back-to-back scheduling, where the new start equals an existing event's end, is allowed because the intervals are half-open."

        Design: Difficulty/resource_temporal_overlap/event_time_overlap_half_open
        """
        owner, segment, club = self._world(api, "ev1")
        create_event(api, club["id"], owner["id"], segment["id"], name="Nine AM Race", scheduled_at="2026-09-05T09:00:00Z", capacity=10)
        second = validate_success(
            api.create_event(
                club["id"],
                create_event_payload(segment["id"], name="Ten AM Race", scheduled_at="2026-09-05T10:00:00Z", capacity=10),
                make_athlete_headers(owner["id"]),
            ),
            201,
        )
        assert second["status"] == "PUBLISHED"

    def test_intersecting_event_rejected(self, api):
        """PRD 3.7: "Each event occupies a half-open one-hour window from `scheduled_at` to `scheduled_at` plus 3600 seconds, and creating an event whose window intersects any other `PUBLISHED` event of the same club is rejected with `ERR_EVENT_TIME_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/event_time_overlap_half_open
        """
        owner, segment, club = self._world(api, "ev2")
        create_event(api, club["id"], owner["id"], segment["id"], name="Nine AM Race", scheduled_at="2026-09-05T09:00:00Z", capacity=10)
        resp = api.create_event(
            club["id"],
            create_event_payload(segment["id"], name="Nine Thirty Race", scheduled_at="2026-09-05T09:30:00Z", capacity=10),
            make_athlete_headers(owner["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_TIME_OVERLAP)
