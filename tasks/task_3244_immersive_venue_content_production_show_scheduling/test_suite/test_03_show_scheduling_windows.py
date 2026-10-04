"""Show scheduling: changeover combinatorics, peak-rush boundary, half-open
reserved-window conflicts, and maintenance-buffer closed-interval conflicts."""
from test_helpers import (
    TEST_USERS,
    create_show,
    setup_active_production_with_approved_asset,
    setup_show_in_rehearsal,
    validate_success,
    create_maintenance_window_payload,
    create_venue_system,
)

VS = TEST_USERS["venue_scheduler_headers"]
VO = TEST_USERS["venue_ops_engineer_headers"]


class TestChangeoverCombinatorics:

    def test_same_format_adjacency_adds_no_format_transition(self, api):
        """PRD: "The changeover that follows the show is computed from the base
        60 minutes, plus 30 minutes for each format transition between this show
        and its temporally adjacent prior or next non-cancelled show (a "format
        transition" occurs whenever the neighbour's `show_format` differs from
        this show's), plus an additional 20 minutes when the show's
        `peak_rush_minutes` is at least 30."

        Design: Difficulty/combinatorial_formula/changeover_combinatorial_format_rush_inputs
        """
        prod, asset = setup_active_production_with_approved_asset(base_price_cents=10000)
        show_a = create_show(
            prod["id"],
            show_format="FILM",
            start_time="2026-09-03T19:00:00Z",
            length_minutes=120,
            peak_rush_minutes=0,
        )
        a = validate_success(api.schedule_rehearsal(show_a["id"], VS))
        show_b = create_show(
            prod["id"],
            show_format="FILM",
            start_time="2026-09-06T19:00:00Z",
            length_minutes=120,
            peak_rush_minutes=0,
        )
        b = validate_success(api.schedule_rehearsal(show_b["id"], VS))
        # Same-format neighbour adds nothing: 60 + 0 + 0 = 60
        assert b["changeover_minutes"] == 60
        assert a["changeover_minutes"] == 60


class TestPeakRushThresholdBoundary:

    def test_peak_rush_exactly_30_crosses_threshold(self, api):
        """PRD: "The changeover that follows the show is computed from the base
        60 minutes, plus 30 minutes for each format transition between this show
        and its temporally adjacent prior or next non-cancelled show (a "format
        transition" occurs whenever the neighbour's `show_format` differs from
        this show's), plus an additional 20 minutes when the show's
        `peak_rush_minutes` is at least 30."

        Design: Difficulty/boundary_precision_check/peak_rush_threshold_at_exactly_30_minutes
        """
        prod, asset = setup_active_production_with_approved_asset(base_price_cents=10000)
        show = create_show(
            prod["id"],
            show_format="FILM",
            start_time="2026-09-03T19:00:00Z",
            length_minutes=90,
            peak_rush_minutes=30,
        )
        data = validate_success(api.schedule_rehearsal(show["id"], VS))
        # 30 >= 30 crosses the threshold: 60 + 0 + 20 = 80
        assert data["changeover_minutes"] == 80

    def test_peak_rush_29_does_not_cross_threshold(self, api):
        """PRD: "The changeover that follows the show is computed from the base
        60 minutes, plus 30 minutes for each format transition between this show
        and its temporally adjacent prior or next non-cancelled show (a "format
        transition" occurs whenever the neighbour's `show_format` differs from
        this show's), plus an additional 20 minutes when the show's
        `peak_rush_minutes` is at least 30."

        Design: Difficulty/boundary_precision_check/peak_rush_threshold_at_exactly_30_minutes
        """
        prod, asset = setup_active_production_with_approved_asset(base_price_cents=10000)
        show = create_show(
            prod["id"],
            show_format="FILM",
            start_time="2026-09-03T19:00:00Z",
            length_minutes=90,
            peak_rush_minutes=29,
        )
        data = validate_success(api.schedule_rehearsal(show["id"], VS))
        # 29 < 30 does not cross the threshold: 60 + 0 + 0 = 60
        assert data["changeover_minutes"] == 60


class TestShowReservedWindowHalfOpen:

    def test_boundary_touching_show_allowed_under_half_open_semantics(self, api):
        """PRD: "The show's reserved window for conflict detection is the
        half-open interval from `start_time` minus the rehearsal minutes through
        `start_time` plus `length_minutes` plus the changeover minutes. Two
        shows conflict whenever their reserved windows overlap strictly — that
        is, one's start precedes the other's end and vice versa."

        Design: Difficulty/resource_temporal_overlap/show_reserved_window_half_open_overlap
        """
        prod, asset = setup_active_production_with_approved_asset(base_price_cents=10000)
        # Show A reserved window: [17:00, 22:20).
        show_a = create_show(
            prod["id"],
            show_format="FILM",
            start_time="2026-09-03T19:00:00Z",
            length_minutes=120,
            peak_rush_minutes=35,
        )
        validate_success(api.schedule_rehearsal(show_a["id"], VS))
        # Show B: start 00:20 next day, length 60 -> reserved start 22:20 == A's
        # reserved end; touching but not strictly overlapping under half-open semantics.
        data = validate_success(
            api.create_show(
                {
                    "production_id": prod["id"],
                    "show_format": "CONCERT",
                    "start_time": "2026-09-04T00:20:00Z",
                    "length_minutes": 60,
                },
                VS,
            ),
            expected_status=201,
        )
        assert data["status"] == "TENTATIVE"


class TestMaintenanceBufferClosedInterval:

    def test_buffer_ending_just_before_reserved_start_is_allowed(self, api):
        """PRD: "Two constraints govern scheduling: the window's `end_time` must
        be strictly later than its `start_time`, and the window plus its buffer
        must not overlap the reserved window of any non-cancelled show on the
        calendar. Either violation is rejected with `ERR_MAINTENANCE_CONFLICT`
        (HTTP 422)."

        Design: Difficulty/resource_temporal_overlap/maintenance_buffer_closed_interval_conflict
        """
        prod, asset, show = setup_show_in_rehearsal(
            base_price_cents=10000,
            show_overrides={
                "show_format": "FILM",
                "start_time": "2026-09-03T19:00:00Z",
                "length_minutes": 90,
                "peak_rush_minutes": 0,
            },
        )
        # Show reserved window: [17:00, 21:30).
        system = create_venue_system(name="EnvFX-4", kind="ENV_FX")
        # Window 15:30-16:29 + buffer 30 -> buffer end 16:59, strictly before 17:00.
        data = validate_success(
            api.create_maintenance_window(
                create_maintenance_window_payload(
                    system["id"],
                    start_time="2026-09-03T15:30:00Z",
                    end_time="2026-09-03T16:29:00Z",
                    buffer_minutes=30,
                ),
                VO,
            ),
            expected_status=201,
        )
        assert data["status"] == "SCHEDULED"
