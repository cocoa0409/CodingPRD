"""Trivia scoring (depth: dual-variant points) and the compound zone posture
machine (depth: non-linear state machine, capacity boundary)."""

from test_helpers import (
    HOST_HEADERS,
    PLATFORM_ADMIN_HEADERS,
    VENUE_MANAGER_HEADERS,
    advance_clock,
    create_and_activate_license,
    create_event,
    create_screen_assignment,
    create_trivia_entry_scenario,
    create_venue,
    create_zone,
    screen_assignment_payload,
    trivia_answer_payload,
    validate_success,
)


class TestTriviaPointsSpeedStreakVsFlat:
    """The same answer sequence scores differently once speed and streak
    bonuses engage."""

    def test_three_ten_second_correct_answers_earn_speed_and_streak_bonuses(self, api):
        """PRD §3.8: "A correct answer awards 100 base points, plus a speed bonus that starts at 50 points and decays by 2.5 points per full second of response time — the bonus is 50 minus 2.5 times the whole seconds elapsed, floored at zero so a slow answer is never negative — plus a streak bonus of 25 points whenever the answer completes a streak whose length, after counting this answer, is an exact multiple of 3."

        Three correct answers at 10 seconds each score 125, 125, and 150
        (the third completes a streak of three), totalling 400 with a
        consecutive-correct count of 3.

        Design: Difficulty/dual_variant_calc/trivia_points_speed_streak_vs_flat
        """
        scenario = create_trivia_entry_scenario()
        entry_id = scenario["entry"]["id"]

        validate_success(
            api.submit_trivia_answer(
                entry_id, trivia_answer_payload(response_time_ms=10000), HOST_HEADERS
            )
        )
        validate_success(
            api.submit_trivia_answer(
                entry_id, trivia_answer_payload(response_time_ms=10000), HOST_HEADERS
            )
        )
        entry = validate_success(
            api.submit_trivia_answer(
                entry_id, trivia_answer_payload(response_time_ms=10000), HOST_HEADERS
            )
        )

        assert entry["points"] == 400
        assert entry["correct_count"] == 3
        assert entry["consecutive_correct"] == 3

    def test_flat_scoring_without_speed_or_streak_bonus(self, api):
        """PRD §3.8: "A correct answer awards 100 base points, plus a speed bonus that starts at 50 points and decays by 2.5 points per full second of response time — the bonus is 50 minus 2.5 times the whole seconds elapsed, floored at zero so a slow answer is never negative."

        Two correct answers at 20 seconds each earn exactly 100 apiece — the
        speed bonus is floored at zero and no streak completes — for 200
        points in total.

        Design: Difficulty/dual_variant_calc/trivia_points_speed_streak_vs_flat
        """
        scenario = create_trivia_entry_scenario()
        entry_id = scenario["entry"]["id"]

        validate_success(
            api.submit_trivia_answer(
                entry_id, trivia_answer_payload(response_time_ms=20000), HOST_HEADERS
            )
        )
        entry = validate_success(
            api.submit_trivia_answer(
                entry_id, trivia_answer_payload(response_time_ms=20000), HOST_HEADERS
            )
        )

        assert entry["points"] == 200
        assert entry["correct_count"] == 2
        assert entry["consecutive_correct"] == 2

    def test_an_incorrect_answer_earns_nothing_and_resets_the_streak(self, api):
        """PRD §3.8: "A correct answer also increments `consecutive_correct`; an incorrect answer earns nothing and resets `consecutive_correct` to zero."

        Two correct answers build a streak of two; an incorrect answer leaves
        the points at 250 and drops the streak back to zero.

        Design: Difficulty/dual_variant_calc/trivia_points_speed_streak_vs_flat
        """
        scenario = create_trivia_entry_scenario()
        entry_id = scenario["entry"]["id"]

        validate_success(
            api.submit_trivia_answer(
                entry_id, trivia_answer_payload(is_correct=True, response_time_ms=10000), HOST_HEADERS
            )
        )
        validate_success(
            api.submit_trivia_answer(
                entry_id, trivia_answer_payload(is_correct=True, response_time_ms=10000), HOST_HEADERS
            )
        )
        entry = validate_success(
            api.submit_trivia_answer(
                entry_id, trivia_answer_payload(is_correct=False, response_time_ms=1000), HOST_HEADERS
            )
        )

        assert entry["points"] == 250
        assert entry["correct_count"] == 2
        assert entry["consecutive_correct"] == 0


class TestZonePostureCompoundFullBlackout:
    """Zone posture is derived: OPEN -> FULL -> BLACKOUT_LOCKED -> OPEN with no
    direct zone mutation."""

    def _setup_full_zone_in_blackout(self, api):
        """Venue (capacity 200, market 14201) + zone S1 + NCAA event (exp 9000)
        + ACTIVE NCAA license + assignment; clock parked before the window."""
        venue = create_venue()
        create_and_activate_license(venue["id"], league="NCAA")
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="NCAA",
            title="College Game",
            home_market_zip="14201",
            expected_attendance=9000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_screen_assignment(zone["id"], event["id"])
        advance_clock("2026-09-13T18:00:00Z")
        return venue, zone, event

    def test_zone_walks_full_then_blackout_locked_then_open(self, api):
        """PRD §3.3: "A zone becomes `FULL` when its `primary_event_id` is not null, the primary event's `expected_attendance` is at least the venue's `capacity_seats`, and no blackout window is active for the primary event's league."
        PRD §3.3: "A zone becomes `BLACKOUT_LOCKED` when a blackout window opens for an event the zone is currently showing — whether as the primary event or merely carried on audio — under an `ACTIVE` license and within radius; at that moment the screen assignments for the blacked-out event are removed and `primary_event_id` is recomputed among the remaining assignments."
        PRD §3.3: "When the logical clock passes 60 minutes beyond the blacked-out event's `scheduled_end`, the window closes and the zone returns to `OPEN`, accepting assignments again."

        At 18:00 (15 minutes before the 18:30 window edge) the zone is FULL;
        at 18:45 it is BLACKOUT_LOCKED; at 23:30 — past 22:00 + 60 minutes —
        it is OPEN again with no primary event.

        Design: Difficulty/non_linear_state_machine/zone_posture_compound_full_blackout
        """
        venue, zone, event = self._setup_full_zone_in_blackout(api)

        zone_before = validate_success(api.get_zone(zone["id"], VENUE_MANAGER_HEADERS))
        advance_clock("2026-09-13T18:45:00Z")
        zone_during = validate_success(api.get_zone(zone["id"], VENUE_MANAGER_HEADERS))
        advance_clock("2026-09-13T23:30:00Z")
        zone_after = validate_success(api.get_zone(zone["id"], VENUE_MANAGER_HEADERS))

        assert zone_before["posture"] == "FULL"
        assert zone_during["posture"] == "BLACKOUT_LOCKED"
        assert zone_after["posture"] == "OPEN"
        assert zone_after["primary_event_id"] is None

    def test_blackout_lock_removes_the_blacked_out_assignment(self, api):
        """PRD §3.3: "A zone becomes `BLACKOUT_LOCKED` when a blackout window opens for an event the zone is currently showing — whether as the primary event or merely carried on audio — under an `ACTIVE` license and within radius; at that moment the screen assignments for the blacked-out event are removed and `primary_event_id` is recomputed among the remaining assignments."

        While the blackout is active the zone lists no remaining screen
        assignments for the blacked-out event.

        Design: Difficulty/non_linear_state_machine/zone_posture_compound_full_blackout
        """
        venue, zone, event = self._setup_full_zone_in_blackout(api)

        advance_clock("2026-09-13T18:45:00Z")
        assignments = validate_success(
            api.list_zone_screen_assignments(zone["id"], VENUE_MANAGER_HEADERS)
        )

        assert all(a["event_id"] != event["id"] for a in assignments)


class TestZoneFullCapacityBoundary:
    """The FULL posture engages at expected_attendance == capacity_seats."""

    def test_attendance_equal_to_capacity_makes_the_zone_full(self, api):
        """PRD §3.3: "A zone becomes `FULL` when its `primary_event_id` is not null, the primary event's `expected_attendance` is at least the venue's `capacity_seats`, and no blackout window is active for the primary event's league."

        At exactly 200 expected attendees against 200 seats the zone turns
        FULL with the event as its primary.

        Design: Difficulty/boundary_precision_check/zone_full_capacity_boundary
        """
        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Boundary Game",
            expected_attendance=200,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_screen_assignment(zone["id"], event["id"])

        zone_after = validate_success(api.get_zone(zone["id"], VENUE_MANAGER_HEADERS))

        assert zone_after["posture"] == "FULL"
        assert zone_after["primary_event_id"] == event["id"]

    def test_attendance_one_below_capacity_keeps_the_zone_open(self, api):
        """PRD §3.3: "A zone becomes `FULL` when its `primary_event_id` is not null, the primary event's `expected_attendance` is at least the venue's `capacity_seats`, and no blackout window is active for the primary event's league."

        At 199 expected attendees against 200 seats the zone stays OPEN.

        Design: Difficulty/boundary_precision_check/zone_full_capacity_boundary
        """
        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Boundary Game",
            expected_attendance=199,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_screen_assignment(zone["id"], event["id"])

        zone_after = validate_success(api.get_zone(zone["id"], VENUE_MANAGER_HEADERS))

        assert zone_after["posture"] == "OPEN"
        assert zone_after["primary_event_id"] == event["id"]
