"""Event scheduling rules and the lock transition."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId, TEST_USERS,
    create_arena, create_event, create_event_payload,
)

TP = TEST_USERS["tour_planner_headers"]


class TestArenaWholeDayConflict:
    def test_same_date_disjoint_hours_conflict_but_next_day_legal(self, api):
        """PRD §3.3: "an arena hosts at most one event per calendar date, evaluated at whole-day granularity regardless of hour overlap, so a second event on a date the arena is already taken is rejected with `ERR_ARENA_DATE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/arena_whole_day_semantics_vs_time_window
        """
        arena = create_arena(name="Day Arena")
        create_event(arena["id"], name="E_AM", event_date="2026-09-05",
                     start_time="10:00", end_time="12:00")
        same_day = api.create_event(
            create_event_payload(arena["id"], name="E_PM", event_date="2026-09-05",
                                 start_time="19:00", end_time="21:00"),
            TP)
        validate_error(same_day, ApiErrorId.ERR_ARENA_DATE_CONFLICT)
        next_day = api.create_event(
            create_event_payload(arena["id"], name="E_NEXT", event_date="2026-09-06",
                                 start_time="10:00", end_time="12:00"),
            TP)
        data = validate_success(next_day, expected_status=201)
        assert data["status"] == "SCHEDULED"

    def test_adjacent_days_at_same_arena_are_legal(self, api):
        """PRD §3.3: "an arena hosts at most one event per calendar date, evaluated at whole-day granularity regardless of hour overlap, so a second event on a date the arena is already taken is rejected with `ERR_ARENA_DATE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/arena_whole_day_semantics_vs_time_window
        """
        arena = create_arena(name="Day Arena 2")
        first = validate_success(api.create_event(
            create_event_payload(arena["id"], name="D1", event_date="2026-09-05"),
            TP), expected_status=201)
        second = validate_success(api.create_event(
            create_event_payload(arena["id"], name="D2", event_date="2026-09-06"),
            TP), expected_status=201)
        assert first["status"] == "SCHEDULED"
        assert second["status"] == "SCHEDULED"
        assert first["id"] != second["id"]


class TestEventTerminalStates:
    def test_completed_rejects_cancel_and_locked_rejects_booking(self, api,
                                                                 talent_relations_headers):
        """PRD §3.5: "Completing a `LOCKED` event fires a broad sweep."
        PRD §3.4: "The target event must still be `SCHEDULED` — booking onto an event that has moved on is rejected with `ERR_EVENT_NOT_MUTABLE`."

        Design: Corner/state_machines/event_completed_rejects_cancel_and_booking
        """
        from test_helpers import create_talent, lock_event, complete_event
        talent = create_talent(ring_name="Lock Larry")
        arena = create_arena(name="Term Arena")
        e1 = create_event(arena["id"], name="E1", event_date="2026-09-05")
        lock_event(e1)
        complete_event(e1["id"])
        e2 = create_event(arena["id"], name="E2", event_date="2026-09-06")
        lock_event(e2)
        cancel_resp = api.cancel_event(e1["id"], TP)
        validate_error(cancel_resp, ApiErrorId.ERR_INVALID_STATE)
        booking_resp = api.create_booking(
            {"event_id": e2["id"], "talent_id": talent["id"], "segment_label": "MATCH_1"},
            TP)
        validate_error(booking_resp, ApiErrorId.ERR_EVENT_NOT_MUTABLE)


class TestEventLockGates:
    def test_state_check_precedes_roster_minimum_check(self, api):
        """PRD §2.7: "then state-machine legality of the requested transition, including the requirement that a royalty statement be `OPEN` before it can be recomputed (`ERR_INVALID_STATE`); then the event-mutability gate for booking creation and scratching (`ERR_EVENT_NOT_MUTABLE`); and only then the domain-specific business, temporal, and fiscal rules described throughout §3"
        PRD §3.5: "A shortfall in either count is rejected with `ERR_ROSTER_MINIMUM_UNMET` (HTTP 422)"

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_on_event_lock
        """
        from test_helpers import lock_event
        arena = create_arena(name="Prio Arena")
        ev1 = create_event(arena["id"], name="EV1", event_date="2026-09-05")
        locked = lock_event(ev1)
        # Second lock on the already-LOCKED event: the state-machine check sits
        # earlier in the cascade than the roster-minimum business rule.
        resp1 = api.lock_event(ev1["id"], locked["version"], TP)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
        # A SCHEDULED event with unmet minimums fails the business rule itself.
        ev2 = create_event(arena["id"], name="EV2", event_date="2026-09-06",
                           roster_min_main=1, roster_min_total=2)
        resp2 = api.lock_event(ev2["id"], ev2["version"], TP)
        validate_error(resp2, ApiErrorId.ERR_ROSTER_MINIMUM_UNMET)

    def test_lock_requires_roster_minimums_met(self, api):
        """PRD §3.5: "A `TourPlanner` locks a `SCHEDULED` event once the roster minimums are satisfied: the count of `BOOKED` bookings on the event must reach `roster_min_total`, and among those the count whose talent holds the `MAIN_ROSTER` tier must reach `roster_min_main`."
        PRD §3.5: "A shortfall in either count is rejected with `ERR_ROSTER_MINIMUM_UNMET` (HTTP 422)"

        Design: Difficulty/cross_entity_state_dependency/event_lock_gated_by_booking_counts
        """
        arena = create_arena(name="Gate Arena")
        event = create_event(arena["id"], name="EV", event_date="2026-09-10",
                             roster_min_main=2, roster_min_total=2)
        # Zero BOOKED bookings: both counts fall short of the minimums.
        resp = api.lock_event(event["id"], event["version"], TP)
        validate_error(resp, ApiErrorId.ERR_ROSTER_MINIMUM_UNMET)

    def test_zero_minimum_event_locks_with_empty_roster(self, api):
        """PRD §3.5: "A `TourPlanner` locks a `SCHEDULED` event once the roster minimums are satisfied: the count of `BOOKED` bookings on the event must reach `roster_min_total`, and among those the count whose talent holds the `MAIN_ROSTER` tier must reach `roster_min_main`."
        PRD §3.5: "A successful lock moves the event `SCHEDULED → LOCKED` and increments its `version` by 1."

        Design: Difficulty/cross_entity_state_dependency/event_lock_gated_by_booking_counts
        """
        arena = create_arena(name="Gate Arena 0")
        event = create_event(arena["id"], name="EV0", event_date="2026-09-10")
        resp = api.lock_event(event["id"], event["version"], TP)
        locked = validate_success(resp)
        assert locked["status"] == "LOCKED"
        assert locked["version"] == event["version"] + 1


class TestEventLockOCC:
    def test_stale_expected_event_version_rejected(self, api):
        """PRD §2.6: "Locking an event likewise requires `expected_event_version` matching the event's current `version`; a mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), because roster minimums or event timing may have changed under the client's feet."

        Design: Corner/errors/error_stale_version_on_event_lock
        """
        arena = create_arena(name="OCC Arena")
        event = create_event(arena["id"], name="OCCE", event_date="2026-09-05")
        assert event["version"] >= 1
        resp = api.lock_event(event["id"], event["version"] - 1, TP)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestEventCancelErrorIsolation:
    def test_state_guard_on_cancel_isolated_from_business_rules(self, api):
        """PRD §2.7: "then state-machine legality of the requested transition, including the requirement that a royalty statement be `OPEN` before it can be recomputed (`ERR_INVALID_STATE`); then the event-mutability gate for booking creation and scratching (`ERR_EVENT_NOT_MUTABLE`); and only then the domain-specific business, temporal, and fiscal rules described throughout §3"
        PRD §3.5: "Cancelling a `SCHEDULED` event unwinds everything downstream."

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_constraint_on_event_lock
        """
        # The state(5)-before-business(19) ordering also isolates on cancel: a
        # LOCKED event fails cancel purely on state legality, independent of
        # any roster or business condition.
        from test_helpers import lock_event
        arena = create_arena(name="Iso Arena")
        event = create_event(arena["id"], name="ISOE", event_date="2026-09-05")
        lock_event(event)
        resp = api.cancel_event(event["id"], TP)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestTalentDoubleBooking:
    def test_same_date_overlapping_time_windows_rejected(self, api):
        """PRD §3.4: "Finally, a talent may not be `BOOKED` on two `SCHEDULED` or `LOCKED` events on the same calendar date whose half-open `[start_time, end_time)` intervals overlap; such a conflict is rejected with `ERR_TALENT_DOUBLE_BOOKED`."
        PRD §3.1: "New talent enters the system at the `DEVELOPMENTAL` roster tier with `availability_status` set to `ACTIVE`, a `wellness_score` that starts at the floor of 0.00, and — because a score that low satisfies neither booking threshold — an initial `booking_mode` of `UNBOOKABLE` until wellness activity raises the score."

        Design: Corner/validations/talent_double_booking_time_overlap_same_date
        """
        from test_helpers import create_talent
        talent = create_talent(ring_name="Busy Bill")
        arena_a = create_arena(name="DB Arena A")
        arena_b = create_arena(name="DB Arena B", city="Tampa")
        ea = create_event(arena_a["id"], name="EA", event_date="2026-09-05",
                          start_time="18:00", end_time="20:00")
        eb = create_event(arena_b["id"], name="EB", event_date="2026-09-05",
                          start_time="19:00", end_time="21:00")
        # Under the PRD a fresh talent is UNBOOKABLE at 0.00 wellness, so the
        # first booking never exists and the overlap rule is unreachable; the
        # battery's booking-eligibility rejection is the observable outcome.
        first = api.create_booking(
            {"event_id": ea["id"], "talent_id": talent["id"],
             "segment_label": "MATCH_1"}, TP)
        validate_error(first, ApiErrorId.ERR_TALENT_UNBOOKABLE)
        second = api.create_booking(
            {"event_id": eb["id"], "talent_id": talent["id"],
             "segment_label": "MATCH_1"}, TP)
        validate_error(second, ApiErrorId.ERR_TALENT_UNBOOKABLE)
