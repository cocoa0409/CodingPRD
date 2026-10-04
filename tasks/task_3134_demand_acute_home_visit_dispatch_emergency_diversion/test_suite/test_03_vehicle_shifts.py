"""Vehicle shift window overlap semantics and overtime computation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_vehicle_shift_payload,
    get_success_data,
    set_clock,
    setup_market_team_shift,
    validate_error,
    validate_success,
)

DISPATCHER = TEST_USERS["dispatcher_headers"]


class TestVehicleShiftOverlap:
    def test_back_to_back_shifts_do_not_overlap_but_one_second_earlier_does(
        self, api
    ):
        """PRD §3.4: "Two shifts for the same care team may not overlap — the
        system tests half-open intersection of their windows, and an overlap
        is rejected with `ERR_SHIFT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/vehicle_shift_window_overlap_half_open
        """
        ctx = setup_market_team_shift(
            app_user="app-N", tech_user="tech-N", go_available=False,
            start_shift=False,
            shift_overrides={
                "window_start": "2026-09-14T08:00:00Z",
                "window_end": "2026-09-14T20:00:00Z",
            },
        )
        team_id = ctx["team"]["id"]
        market_id = ctx["market"]["id"]
        shift_1 = get_success_data(
            api.create_vehicle_shift(
                create_vehicle_shift_payload(
                    team_id, market_id,
                    window_start="2026-09-15T10:00:00Z",
                    window_end="2026-09-15T18:00:00Z",
                ),
                DISPATCHER,
            )
        )
        # Back-to-back: [18:00, 23:00) does NOT overlap [10:00, 18:00).
        shift_2 = validate_success(
            api.create_vehicle_shift(
                create_vehicle_shift_payload(
                    team_id, market_id, vehicle_plate="TX-N2",
                    window_start="2026-09-15T18:00:00Z",
                    window_end="2026-09-15T23:00:00Z",
                ),
                DISPATCHER,
            ),
            expected_status=201,
        )
        assert shift_2["status"] == "SCHEDULED"
        # One second earlier start DOES overlap.
        resp = api.create_vehicle_shift(
            create_vehicle_shift_payload(
                team_id, market_id, vehicle_plate="TX-N3",
                window_start="2026-09-15T17:59:59Z",
                window_end="2026-09-15T23:00:00Z",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)
        s1 = validate_success(api.get_vehicle_shift(shift_1["id"], DISPATCHER))
        assert s1["status"] == "SCHEDULED"

    def test_fully_overlapping_shift_rejected(self, api):
        """PRD §3.4: "Two shifts for the same care team may not overlap — the
        system tests half-open intersection of their windows, and an overlap
        is rejected with `ERR_SHIFT_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/vehicle_shift_window_overlap_half_open
        """
        ctx = setup_market_team_shift(
            app_user="app-N4", tech_user="tech-N4", go_available=False,
            start_shift=False,
            shift_overrides={
                "window_start": "2026-09-14T08:00:00Z",
                "window_end": "2026-09-14T20:00:00Z",
            },
        )
        team_id = ctx["team"]["id"]
        market_id = ctx["market"]["id"]
        get_success_data(
            api.create_vehicle_shift(
                create_vehicle_shift_payload(
                    team_id, market_id,
                    window_start="2026-09-15T10:00:00Z",
                    window_end="2026-09-15T18:00:00Z",
                ),
                DISPATCHER,
            )
        )
        resp = api.create_vehicle_shift(
            create_vehicle_shift_payload(
                team_id, market_id, vehicle_plate="TX-N5",
                window_start="2026-09-15T12:00:00Z",
                window_end="2026-09-15T14:00:00Z",
            ),
            DISPATCHER,
        )
        validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


class TestShiftCloseOvertime:
    def test_close_after_window_end_computes_overtime_minutes(self, api):
        """PRD §3.4: "At close the shift computes `overtime_minutes` as the
        whole minutes by which the logical clock has passed the (possibly
        extended) `window_end`, floored at zero — a close before the window
        ends yields zero overtime."

        Design: Corner/state_machines/shift_close_computes_overtime_minutes
        """
        set_clock("2026-09-15T10:00:00Z")
        ctx = setup_market_team_shift(
            app_user="app-Z", tech_user="tech-Z", go_available=False,
            shift_overrides={
                "window_start": "2026-09-15T10:00:00Z",
                "window_end": "2026-09-15T18:00:00Z",
            },
        )
        set_clock("2026-09-15T19:30:00Z")
        closed = validate_success(
            api.close_vehicle_shift(ctx["shift"]["id"], DISPATCHER)
        )
        assert closed["status"] == "CLOSED"
        assert closed["overtime_minutes"] == 90

    def test_close_before_window_end_yields_zero_overtime(self, api):
        """PRD §3.4: "a close before the window ends yields zero overtime."

        Design: Corner/state_machines/shift_close_computes_overtime_minutes
        """
        set_clock("2026-09-15T10:00:00Z")
        ctx = setup_market_team_shift(
            app_user="app-Z2", tech_user="tech-Z2", go_available=False,
            shift_overrides={
                "window_start": "2026-09-15T10:00:00Z",
                "window_end": "2026-09-15T18:00:00Z",
            },
        )
        set_clock("2026-09-15T17:00:00Z")
        closed = validate_success(
            api.close_vehicle_shift(ctx["shift"]["id"], DISPATCHER)
        )
        assert closed["status"] == "CLOSED"
        assert closed["overtime_minutes"] == 0
