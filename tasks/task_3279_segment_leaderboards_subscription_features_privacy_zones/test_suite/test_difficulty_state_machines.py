"""Difficulty queue A: non-linear state machines.

activity_parallel_dimensions covers the independent lifecycle and integrity
axes on Activity; segment_cyclic_zero_effort covers the RETIRED -> ACTIVE
cycle gate on Segment.effort_count.
"""

from test_helpers import (
    ApiErrorId,
    create_active_segment,
    create_athlete,
    create_activity_with_effort,
    create_segment,
    flag_effort,
    make_athlete_headers,
    reject_flag,
    validate_error,
    validate_success,
)


class TestActivityParallelDimensions:
    def test_flag_moves_integrity_axis_only_lifecycle_stays_completed(self, api):
        """PRD 3.6: "Leaderboard integrity has two dimensions that evolve in parallel on every activity: the lifecycle `status` (`PROCESSING`, `COMPLETED`, `DUPLICATE`, `REJECTED`) and the integrity `flag_status` (`NONE`, `FLAGGED`, `CLEARED`, `CONFIRMED`)."
        PRD 3.6: "Creating the flag opens it (`OPEN`), moves the target effort — and every other `ELIGIBLE` effort of the same activity — to `FLAGGED` (community-flagged efforts carry no `exclusion_reason`; only auto-flagged ones do), and moves the host activity's `flag_status` from `NONE` to `FLAGGED`."

        Design: Difficulty/non_linear_state_machine/activity_parallel_dimensions
        """
        creator = create_athlete(api, email="c_par@x.com", display_name="C Par")
        flagger_target = create_athlete(api, email="f_par@x.com", display_name="F Par")
        segment = create_active_segment(
            api, creator["id"], name="Parallel Run 1k", sport_type="RUN",
            start_lat=37.60, start_lng=-122.60, end_lat=37.61, end_lng=-122.60,
            distance_m=1000, city="Parville",
        )
        pair = create_activity_with_effort(api, segment, flagger_target["id"], elapsed_time_s=100, started_at="2026-09-01T07:00:00Z")
        flag_effort(api, pair["effort"]["id"], creator["id"])
        view = validate_success(api.get_activity(pair["activity"]["id"], make_athlete_headers(flagger_target["id"])), 200)
        assert view["status"] == "COMPLETED"
        assert view["flag_status"] == "FLAGGED"

    def test_reject_returns_integrity_axis_to_cleared(self, api):
        """PRD 3.6: "**Rejecting** a flag moves it to `REJECTED`; when the rejected flag was the last `OPEN` flag on its activity, the effort moves back from `FLAGGED` to `ELIGIBLE` with `exclusion_reason` cleared to null, the activity's `flag_status` moves from `FLAGGED` to `CLEARED`".

        Design: Difficulty/non_linear_state_machine/activity_parallel_dimensions
        """
        creator = create_athlete(api, email="c_par2@x.com", display_name="C Par2")
        target = create_athlete(api, email="f_par2@x.com", display_name="F Par2")
        segment = create_active_segment(api, creator["id"], sport_type="RUN", distance_m=1000)
        pair = create_activity_with_effort(api, segment, target["id"], elapsed_time_s=100)
        flag = flag_effort(api, pair["effort"]["id"], creator["id"])
        reject_flag(api, flag["id"])
        view = validate_success(api.get_activity(pair["activity"]["id"], make_athlete_headers(target["id"])), 200)
        assert view["status"] == "COMPLETED"
        assert view["flag_status"] == "CLEARED"
        effort = validate_success(api.get_effort(pair["effort"]["id"], make_athlete_headers(target["id"])), 200)
        assert effort["flag_status"] == "ELIGIBLE"
        assert effort["exclusion_reason"] is None


class TestSegmentCyclicZeroEffort:
    def test_zero_effort_retired_segment_reactivates(self, api):
        """PRD 3.5: "One cyclic edge exists: a `RETIRED` segment may return to `ACTIVE` — by its creator, through the same activation path — but only while its `effort_count` is exactly zero and its `hazard_index` is zero."

        Design: Difficulty/non_linear_state_machine/segment_cyclic_zero_effort
        """
        owner = create_athlete(api, email="x_cyc@x.com", display_name="X Cyc")
        headers = make_athlete_headers(owner["id"])
        segment = create_active_segment(
            api, owner["id"], name="Cycle A", sport_type="RIDE",
            start_lat=38.00, start_lng=-123.00, end_lat=38.01, end_lng=-123.00,
            distance_m=1000, city="Cycville",
        )
        validate_success(api.retire_segment(segment["id"], headers), 200)
        reactivated = validate_success(api.activate_segment(segment["id"], headers), 200)
        assert reactivated["status"] == "ACTIVE"
        assert reactivated["effort_count"] == 0

    def test_retired_segment_with_efforts_cannot_reactivate(self, api):
        """PRD 3.5: "Once any effort has ever been recorded against it, the segment can never be re-activated; the attempt is rejected with `ERR_INVALID_STATE`."

        Design: Difficulty/non_linear_state_machine/segment_cyclic_zero_effort
        """
        owner = create_athlete(api, email="x_cyc2@x.com", display_name="X Cyc2")
        rider = create_athlete(api, email="y_cyc2@x.com", display_name="Y Cyc2")
        headers = make_athlete_headers(owner["id"])
        segment = create_active_segment(
            api, owner["id"], name="Cycle B", sport_type="RIDE",
            start_lat=38.10, start_lng=-123.10, end_lat=38.11, end_lng=-123.10,
            distance_m=1000, city="Cycville",
        )
        create_activity_with_effort(
            api, segment, rider["id"], elapsed_time_s=200, sport_type="RIDE",
            started_at="2026-09-01T06:00:00Z",
        )
        validate_success(api.retire_segment(segment["id"], headers), 200)
        resp = api.activate_segment(segment["id"], headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
