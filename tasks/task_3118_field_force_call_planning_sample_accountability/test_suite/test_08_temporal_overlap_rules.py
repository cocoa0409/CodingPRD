"""Resource temporal overlap: half-open visit intervals and the 24-hour
count-window gap.

Queue A — difficulty design rule ``resource_temporal_overlap``.
"""

from test_helpers import (
    ApiErrorId,
    get_success_data,
    make_district_manager_headers,
    make_field_rep_headers,
    validate_error,
    validate_success,
)
from test_helpers import fixtures as fx
from test_helpers import factories as f


class TestVisitIntervalsAreHalfOpen:
    """Back-to-back is legal; one second of overlap is not."""

    def _setup_two_entries(self, api):
        ctx = fx.setup_published_plan_with_rep(
            api, tier="B", planned_sample_units=20, budget=100
        )
        second_prescriber = fx.create_eligible_prescriber(api)
        second_entry = fx.add_target_entry(
            api,
            ctx["territory"]["id"],
            second_prescriber["id"],
            ctx["product"]["id"],
            ctx["manager"],
            tier="B",
            planned_sample_units=20,
        )
        # The plan was created before the second entry existed; scheduling
        # against the published plan with the new entry is allowed until the
        # plan locks (no completed visits yet in these probes).
        ctx["entry2"] = second_entry
        # Existing visit 10:00-11:00 on the default-clock day minus one.
        fx.schedule_visit(
            api,
            ctx["plan"]["id"],
            ctx["entry"]["id"],
            ctx["rep"],
            scheduled_start="2026-08-31T10:00:00Z",
            scheduled_end="2026-08-31T11:00:00Z",
        )
        return ctx

    def test_back_to_back_visit_allowed(self, api):
        """PRD section 3.4: "back-to-back scheduling — one visit's scheduled_end equal
        to the next's scheduled_start — is allowed because half-open intervals do not
        intersect at a shared endpoint."

        Design: Difficulty/resource_temporal_overlap/visit_intervals_half_open_back_to_back_allowed_overlap_rejected
        """
        ctx = self._setup_two_entries(api)
        response = api.create_call_visit(
            f.create_call_visit_payload(
                ctx["plan"]["id"],
                ctx["entry2"]["id"],
                scheduled_start="2026-08-31T11:00:00Z",
                scheduled_end="2026-08-31T12:00:00Z",
            ),
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        validate_success(response, expected_status=201)

    def test_one_second_overlap_rejected(self, api):
        """PRD section 3.4: "a new visit whose half-open interval from scheduled_start
        to scheduled_end intersects the interval of any existing non-cancelled visit
        of the same representative is rejected with ERR_VISIT_SCHEDULE_OVERLAP."

        Design: Difficulty/resource_temporal_overlap/visit_intervals_half_open_back_to_back_allowed_overlap_rejected
        """
        ctx = self._setup_two_entries(api)
        response = api.create_call_visit(
            f.create_call_visit_payload(
                ctx["plan"]["id"],
                ctx["entry2"]["id"],
                scheduled_start="2026-08-31T10:59:59Z",
                scheduled_end="2026-08-31T12:00:00Z",
            ),
            headers=make_field_rep_headers(ctx["rep"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_VISIT_SCHEDULE_OVERLAP)


class TestCountWindowGap:
    """Non-overlap alone is insufficient: a 24h gap is required, and VOIDED
    sessions do not constrain the schedule."""

    def _setup_cast_with_prior_session(self, api):
        ctx = fx.setup_count_session_cast(api, custodian_issue_qty=0)
        # Session S1 voided; session S2 active with window 09-10 .. 09-11.
        s1 = fx.open_count_session(
            api,
            ctx["custodian"],
            ctx["counter"],
            ctx["manager"],
            window_start="2026-09-03T00:00:00Z",
            window_end="2026-09-04T00:00:00Z",
        )
        get_success_data(
            api.void_count_session(
                s1["id"],
                headers=make_district_manager_headers(ctx["manager"]["id"]),
            )
        )
        s2 = fx.open_count_session(
            api,
            ctx["custodian"],
            ctx["counter"],
            ctx["manager"],
            window_start="2026-09-10T00:00:00Z",
            window_end="2026-09-11T00:00:00Z",
        )
        ctx["s1"] = s1
        ctx["s2"] = s2
        return ctx

    def test_twelve_hour_gap_rejected(self, api):
        """PRD section 3.6: "additionally there must be a minimum gap of 24 hours
        between the earlier session's window_end and the later session's
        window_start; a conflict is rejected with ERR_COUNT_WINDOW_CONFLICT."

        Design: Difficulty/resource_temporal_overlap/count_session_windows_require_24h_gap_not_mere_non_overlap
        """
        ctx = self._setup_cast_with_prior_session(api)
        response = api.create_count_session(
            f.create_count_session_payload(
                ctx["custodian"]["id"],
                ctx["counter"]["id"],
                window_start="2026-09-11T12:00:00Z",
                window_end="2026-09-12T00:00:00Z",
            ),
            headers=make_district_manager_headers(ctx["manager"]["id"]),
        )
        validate_error(response, ApiErrorId.ERR_COUNT_WINDOW_CONFLICT)

    def test_exactly_twenty_four_hour_gap_allowed_and_voided_ignored(self, api):
        """PRD section 3.6: "no two non-VOIDED sessions may have overlapping windows,
        and additionally there must be a minimum gap of 24 hours between the earlier
        session's window_end and the later session's window_start."

        Design: Difficulty/resource_temporal_overlap/count_session_windows_require_24h_gap_not_mere_non_overlap
        """
        ctx = self._setup_cast_with_prior_session(api)
        # Exactly 24h after S2's window_end (09-11T00:00Z + 24h = 09-12T00:00Z).
        response = api.create_count_session(
            f.create_count_session_payload(
                ctx["custodian"]["id"],
                ctx["counter"]["id"],
                window_start="2026-09-12T00:00:00Z",
                window_end="2026-09-13T00:00:00Z",
            ),
            headers=make_district_manager_headers(ctx["manager"]["id"]),
        )
        validate_success(response, expected_status=201)
        # The VOIDED S1's window is well within 24h of nothing new — but also
        # probe directly: a session 12h after the VOIDED window's end is fine.
        response2 = api.create_count_session(
            f.create_count_session_payload(
                ctx["custodian"]["id"],
                ctx["counter"]["id"],
                window_start="2026-09-04T12:00:00Z",
                window_end="2026-09-05T00:00:00Z",
            ),
            headers=make_district_manager_headers(ctx["manager"]["id"]),
        )
        validate_success(response2, expected_status=201)
