"""
Two scarce resources booked over time, with two different interval rules.

A commissioning crew cannot be in two places at once, so its windows are padded by half an
hour on both sides. A dispatch territory has a fixed aggregate ceiling instead, compared
with no padding at all. Both rules treat windows as half-open, so abutting is never a clash.
"""

from test_helpers import (
    UTILITY_REVIEWER_HEADERS,
    ApiErrorId,
    EventType,
    TerritoryCode,
    TestResult,
    TestStatus,
    TestType,
    assert_instant_equals,
    assert_quantity,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_WINDOW = ("2026-08-10T09:00:00Z", "2026-08-10T10:00:00Z")
INSIDE_BUFFER = ("2026-08-10T10:20:00Z", "2026-08-10T11:20:00Z")
AT_BUFFER_EDGE = ("2026-08-10T10:30:00Z", "2026-08-10T11:30:00Z")


class TestCommissioningWindowTravelBuffer:
    """Thirty minutes of travel on both sides of every booked window."""

    def _one_booked_window(self, api):
        """An installed bank with a single scheduled transition test from 09:00 to 10:00."""
        project = fixtures.installed_project(api)
        validate_success(
            api.create_commissioning_test(
                factories.commissioning_test_payload(
                    project.battery_system_id, TestType.BACKUP_TRANSITION, *FIRST_WINDOW
                ),
                headers=project.installer_headers,
            ),
            expected_status=201,
        )
        return project

    def _book(self, api, project, window):
        return api.create_commissioning_test(
            factories.commissioning_test_payload(
                project.battery_system_id, TestType.CAPACITY_DISCHARGE, *window
            ),
            headers=project.installer_headers,
        )

    def test_a_window_starting_inside_the_buffer_is_refused(self, api):
        """Twenty minutes after the crew finishes is not enough time to travel.

        The booked window runs to 10:00 and the padded block therefore runs to 10:30. A second
        window starting at 10:20 begins inside that padding, so the crew would have to be in
        two places at once and the booking is refused.

        PRD 3.6: "Both sides of every window are padded by 30 minutes of travel buffer before the comparison, and windows are treated as half-open intervals that include their start and exclude their end."
        PRD 3.6: "Two windows that abut exactly, or that are separated by at least the buffer, are therefore fine; anything closer is rejected with `ERR_TEST_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/installer_commissioning_windows_rejected_inside_travel_buffer_allowed_at_buffer_edge
        """
        project = self._one_booked_window(api)

        validate_error(
            self._book(api, project, INSIDE_BUFFER),
            ApiErrorId.ERR_TEST_WINDOW_CONFLICT,
            expected_status=409,
        )

    def test_a_window_starting_exactly_at_the_buffer_edge_is_accepted(self, api):
        """Ten minutes later, at the edge of the padding, the same booking is fine.

        A window starting at exactly 10:30 begins where the padded block ends, and half-open
        intervals do not clash where one ends and the other begins. The refused attempt at
        10:20 left nothing behind, so the bank ends with exactly the two bookings it accepted.

        PRD 3.6: "Two windows that abut exactly, or that are separated by at least the buffer, are therefore fine; anything closer is rejected with `ERR_TEST_WINDOW_CONFLICT`."
        PRD 3.6: "A test is created with `status` of `SCHEDULED`, `result` of `PENDING`, and `recorded_at` unset."

        Design: Difficulty/resource_temporal_overlap/installer_commissioning_windows_rejected_inside_travel_buffer_allowed_at_buffer_edge
        """
        project = self._one_booked_window(api)
        validate_error(
            self._book(api, project, INSIDE_BUFFER), ApiErrorId.ERR_TEST_WINDOW_CONFLICT
        )

        booked = validate_success(
            self._book(api, project, AT_BUFFER_EDGE), expected_status=201
        )

        assert_instant_equals(booked["window_start"], AT_BUFFER_EDGE[0], "window_start")
        assert booked["status"] == TestStatus.SCHEDULED
        assert booked["result"] == TestResult.PENDING
        tests, _ = validate_paginated(
            api.list_commissioning_tests(
                {"battery_system_id": project.battery_system_id},
                headers=project.installer_headers,
            )
        )
        assert len(tests) == 2, "expected exactly the two accepted bookings"


class TestTerritoryDispatchCapacity:
    """An aggregate ceiling of 1500 kW over the events that overlap in time."""

    def _schedule(self, api, **overrides):
        return api.create_dispatch_event(
            factories.dispatch_event_payload(**overrides), headers=UTILITY_REVIEWER_HEADERS
        )

    def _nine_hundred_kilowatts_called(self, api):
        """A 900 kW economic event occupying the western territory from 17:00 to 19:00."""
        return validate_success(
            self._schedule(api, target_kw=900, payment_rate_cents_per_kw=700),
            expected_status=201,
        )

    def test_the_aggregate_may_reach_the_cap_exactly_but_not_exceed_it(self, api):
        """Nine hundred plus six hundred is admitted; one further kilowatt is not.

        The second event occupies exactly the same window as the first, and the two together
        call for exactly the ceiling, which is admitted. A third event calling for a single
        kilowatt inside that window would push the territory total past the ceiling and is
        refused.

        PRD 3.9: "Territory capacity is finite: the aggregate `target_kw` of time-overlapping events in the same `territory_code` may not exceed 1500 kW at any instant."
        PRD 3.9: "a genuine overlap that would push the territory total above the cap is rejected with `ERR_TERRITORY_CAPACITY_EXCEEDED`"

        Design: Difficulty/resource_temporal_overlap/dispatch_event_territory_capacity_admits_exact_cap_and_abutting_window
        """
        self._nine_hundred_kilowatts_called(api)

        at_the_cap = validate_success(
            self._schedule(
                api,
                event_type=EventType.EMERGENCY,
                target_kw=600,
                payment_rate_cents_per_kw=1200,
            ),
            expected_status=201,
        )
        assert_quantity(at_the_cap, "target_kw", 600.0)

        validate_error(
            self._schedule(
                api,
                target_kw=1.0,
                payment_rate_cents_per_kw=600,
                window_start="2026-09-15T18:00:00Z",
                window_end="2026-09-15T18:30:00Z",
            ),
            ApiErrorId.ERR_TERRITORY_CAPACITY_EXCEEDED,
            expected_status=409,
        )

    def test_an_event_beginning_where_the_others_end_gets_the_whole_cap(self, api):
        """Half-open windows mean the ceiling resets the instant the earlier events close.

        With the territory already full from 17:00 to 19:00, an event beginning at exactly
        19:00 overlaps nothing and may therefore call for the entire ceiling on its own. The
        refused attempt created nothing, so the territory holds exactly three events.

        PRD 3.9: "The comparison uses half-open intervals with no buffer at all, so an event beginning at exactly the instant another ends never conflicts"
        PRD 3.9: "A new event opens in `SCHEDULED` with `enrolled_pledged_kw` and `total_net_payment_cents` at zero and `settled_at` unset."

        Design: Difficulty/resource_temporal_overlap/dispatch_event_territory_capacity_admits_exact_cap_and_abutting_window
        """
        self._nine_hundred_kilowatts_called(api)
        validate_success(
            self._schedule(
                api,
                event_type=EventType.EMERGENCY,
                target_kw=600,
                payment_rate_cents_per_kw=1200,
            ),
            expected_status=201,
        )
        validate_error(
            self._schedule(
                api,
                target_kw=1.0,
                payment_rate_cents_per_kw=600,
                window_start="2026-09-15T18:00:00Z",
                window_end="2026-09-15T18:30:00Z",
            ),
            ApiErrorId.ERR_TERRITORY_CAPACITY_EXCEEDED,
        )

        abutting = validate_success(
            self._schedule(
                api,
                target_kw=1500,
                payment_rate_cents_per_kw=700,
                window_start="2026-09-15T19:00:00Z",
                window_end="2026-09-15T21:00:00Z",
            ),
            expected_status=201,
        )

        assert_quantity(abutting, "target_kw", 1500.0)
        assert_instant_equals(
            abutting["window_start"], "2026-09-15T19:00:00Z", "window_start"
        )
        events, _ = validate_paginated(
            api.list_dispatch_events(
                {"territory_code": TerritoryCode.TER_WEST}, headers=UTILITY_REVIEWER_HEADERS
            )
        )
        assert len(events) == 3, "expected exactly the three admitted events"
