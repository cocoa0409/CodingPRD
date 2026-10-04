"""Licensing gates, blackout-window safety, screen exclusivity, and the
waitlist/guest cross-entity rules (depth: priority pairs, cross-entity state
dependencies, resource temporal overlap)."""

from test_helpers import (
    ApiErrorId,
    HOST_HEADERS,
    VENUE_MANAGER_HEADERS,
    add_order_line,
    advance_clock,
    call_waitlist_entry,
    create_and_activate_license,
    create_event,
    create_guest,
    create_guest_with_no_shows,
    create_open_check,
    create_screen_assignment,
    create_venue,
    create_zone,
    fantasy_contest_payload,
    get_guest,
    join_waitlist,
    license_payload,
    screen_assignment_payload,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


class TestStateVsBusinessSafetyBlackout:
    """When a request violates both state and blackout-safety, the state error
    wins by the declared validation priority."""

    def _setup(self, api):
        venue = create_venue()
        zone = create_zone(venue["id"])
        event_e1 = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Early Game",
            home_market_zip="10001",
            expected_attendance=100,
            scheduled_start="2026-09-13T16:00:00Z",
            scheduled_end="2026-09-13T18:00:00Z",
        )
        event_e2 = create_event(
            kind="BASE",
            league="NCAA",
            title="College Game",
            home_market_zip="14201",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_screen_assignment(zone["id"], event_e1["id"], audio_enabled=True)
        create_and_activate_license(venue["id"], league="NCAA")
        advance_clock("2026-09-13T18:45:00Z")
        return venue, zone, event_e1, event_e2

    def test_double_assigning_during_a_blackout_reports_invalid_state(self, api):
        """PRD §2.9: "fourth, that the target resource is in a valid state for the requested transition (`ERR_INVALID_STATE`); fifth, blackout-window safety on screen assignment (`ERR_BLACKOUT_WINDOW_ACTIVE`)."

        The screen is already occupied (a priority-4 violation) and the target
        event is inside an active blackout window (priority 5); the state
        error is reported first.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_blackout
        """
        venue, zone, event_e1, event_e2 = self._setup(api)

        resp = api.create_screen_assignment(
            zone["id"],
            screen_assignment_payload(
                event_id=event_e2["id"], screen_id="S1", audio_enabled=False
            ),
            VENUE_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_blackout_alone_on_a_free_screen_reports_blackout_error(self, api):
        """PRD §3.3: "Assigning a screen to an event whose blackout window is currently active at this venue is rejected with `ERR_BLACKOUT_WINDOW_ACTIVE`."

        The same blacked-out event on a different, unoccupied screen surfaces
        the blackout error once the priority-4 violation is removed.

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_blackout
        """
        venue, zone, event_e1, event_e2 = self._setup(api)

        resp = api.create_screen_assignment(
            zone["id"],
            screen_assignment_payload(
                event_id=event_e2["id"], screen_id="S2", audio_enabled=False
            ),
            VENUE_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_WINDOW_ACTIVE)


class TestBusinessReferentialVsFiscalContest:
    """Contest-openness is checked before prize-structure fiscal rules."""

    def test_entry_on_a_draft_contest_reports_contest_not_open(self, api):
        """PRD §3.9: "a contest that is not `OPEN` rejects registration with `ERR_CONTEST_NOT_OPEN`."

        The contest is still in DRAFT, so registration is rejected regardless
        of its prize structure.

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_contest
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        contest = validate_success(
            api.create_fantasy_contest(
                venue["id"],
                fantasy_contest_payload(prize_structure=[0.5, 0.3, 0.1]),
                VENUE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )

        resp = api.create_fantasy_entry(
            contest["id"],
            {"guest_id": guest["id"], "lineup": {"qb": "Allen"}},
            HOST_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_CONTEST_NOT_OPEN)

    def test_opening_a_contest_with_invalid_prize_structure_is_rejected(self, api):
        """PRD §3.9: "Opening it for registration requires the prize shares to sum to 1.0 within a tolerance of 0.001; a structure outside that tolerance is rejected with `ERR_PRIZE_STRUCTURE_INVALID`."

        Shares of [0.5, 0.3, 0.1] sum to 0.9, so the open transition fails on
        the fiscal rule.

        Design: Difficulty/priority_pair_validation_conflict/business_referential_vs_business_fiscal_contest
        """
        venue = create_venue()
        contest = validate_success(
            api.create_fantasy_contest(
                venue["id"],
                fantasy_contest_payload(prize_structure=[0.5, 0.3, 0.1]),
                VENUE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )

        resp = api.open_fantasy_contest(contest["id"], VENUE_MANAGER_HEADERS)
        validate_error(resp, ApiErrorId.ERR_PRIZE_STRUCTURE_INVALID)


class TestZoneAssignmentRequiresActiveLicense:
    """Screen assignment depends on the league license being ACTIVE."""

    def test_assignment_with_pending_license_is_rejected(self, api):
        """PRD §3.2: "Screen assignment and PPV registration both verify that the league's license is `ACTIVE` before proceeding; a license that is `PENDING`, `SUSPENDED`, or `TERMINATED` rejects the operation with `ERR_LICENSE_NOT_ACTIVE`."

        The NCAA license exists but was never activated, so assigning the
        NCAA game fails.

        Design: Difficulty/cross_entity_state_dependency/zone_assignment_requires_active_license
        """
        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="NCAA",
            title="College Game",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        validate_success(
            api.create_license(
                venue["id"], license_payload(league="NCAA"), VENUE_MANAGER_HEADERS
            ),
            expected_status=201,
        )

        resp = api.create_screen_assignment(
            zone["id"],
            screen_assignment_payload(event_id=event["id"], screen_id="S1"),
            VENUE_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_LICENSE_NOT_ACTIVE)

    def test_assignment_succeeds_once_the_license_is_activated(self, api):
        """PRD §3.2: "Screen assignment and PPV registration both verify that the league's license is `ACTIVE` before proceeding; a license that is `PENDING`, `SUSPENDED`, or `TERMINATED` rejects the operation with `ERR_LICENSE_NOT_ACTIVE`."

        After activation the same assignment goes through, which isolates the
        license state as the deciding dependency.

        Design: Difficulty/cross_entity_state_dependency/zone_assignment_requires_active_license
        """
        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="NCAA",
            title="College Game",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_and_activate_license(venue["id"], league="NCAA")

        assignment = validate_success(
            api.create_screen_assignment(
                zone["id"],
                screen_assignment_payload(event_id=event["id"], screen_id="S1"),
                VENUE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert assignment["event_id"] == event["id"]


class TestWaitlistSeatRequiresGuestState:
    """Seating depends on the guest's no-show count staying under 3."""

    def test_seat_after_elapsed_hold_is_rejected_as_hold_expired(self, api):
        """PRD §3.4: "A called party that does not check in before the hold elapses is moved by the system to `EXPIRED`, the guest's `no_show_count` increments, and an attempt to seat after the hold has elapsed is rejected with `ERR_TABLE_HOLD_EXPIRED`."

        The entry is called at the default clock (2026-09-01T00:00Z) and the
        clock is advanced 16 minutes — one minute past the 15-minute hold — so
        the seat attempt is rejected with the hold-expired error.

        Design: Difficulty/cross_entity_state_dependency/waitlist_seat_requires_guest_state
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        entry = join_waitlist(venue["id"], guest["id"])
        called = call_waitlist_entry(entry["id"])
        advance_clock("2026-09-01T00:16:00Z")

        resp = api.seat_waitlist_entry(
            entry["id"],
            {"expected_waitlist_entry_version": called["version"]},
            HOST_HEADERS,
        )
        # PRD names ERR_TABLE_HOLD_EXPIRED for a seat after the hold elapses,
        # but the same sentence also moves the entry to EXPIRED; a faithful
        # implementation may therefore report the expired hold or reject the
        # seat from the EXPIRED state.
        validate_error_is_one_of(
            resp, [ApiErrorId.ERR_TABLE_HOLD_EXPIRED, ApiErrorId.ERR_INVALID_STATE]
        )

    def test_seat_within_the_hold_succeeds(self, api):
        """PRD §3.4: "Seating — moving from `CALLED` to `SEATED` — is the OCC-guarded write described in §2.8: the request carries `expected_waitlist_entry_version`, a mismatch is `ERR_STALE_VERSION` (HTTP 412), and a successful seat redeems the guest by decrementing `no_show_count` when it is above zero, while the entry's own `version` increments."

        Ten minutes after the call the hold is still open and the seat lands,
        moving the entry to SEATED.

        Design: Difficulty/cross_entity_state_dependency/waitlist_seat_requires_guest_state
        """
        venue = create_venue()
        guest = create_guest(venue["id"])
        entry = join_waitlist(venue["id"], guest["id"])
        called = call_waitlist_entry(entry["id"])
        advance_clock("2026-09-01T00:10:00Z")

        seated = validate_success(
            api.seat_waitlist_entry(
                entry["id"],
                {"expected_waitlist_entry_version": called["version"]},
                HOST_HEADERS,
            )
        )
        assert seated["status"] == "SEATED"


class TestScreenAssignmentExclusiveInterval:
    """A screen can show only one event at a time."""

    def test_second_assignment_on_the_same_screen_is_rejected(self, api):
        """PRD §3.3: "Assigning a `screen_id` that already has a live assignment in the same zone is rejected with `ERR_SCREEN_ALREADY_ASSIGNED` (HTTP 409)."

        A second event on screen S1 while the first assignment is live is a
        conflict.

        Design: Difficulty/resource_temporal_overlap/screen_assignment_exclusive_interval
        """
        venue = create_venue()
        zone = create_zone(venue["id"])
        event_a = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Game A",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        event_b = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Game B",
            home_market_zip="10001",
            expected_attendance=3000,
            scheduled_start="2026-09-13T20:00:00Z",
            scheduled_end="2026-09-13T23:00:00Z",
        )
        create_screen_assignment(zone["id"], event_a["id"])

        resp = api.create_screen_assignment(
            zone["id"],
            screen_assignment_payload(
                event_id=event_b["id"], screen_id="S1", audio_enabled=False
            ),
            VENUE_MANAGER_HEADERS,
        )
        # PRD §3.3 names ERR_SCREEN_ALREADY_ASSIGNED for a duplicate screen,
        # while §2.9's priority list routes the conflict through the
        # priority-4 state bucket (ERR_INVALID_STATE); both readings are
        # faithful, so accept either error_id.
        validate_error_is_one_of(
            resp,
            [ApiErrorId.ERR_SCREEN_ALREADY_ASSIGNED, ApiErrorId.ERR_INVALID_STATE],
        )

    def test_second_assignment_after_release_is_accepted(self, api):
        """PRD §3.3: "Assigning a `screen_id` that already has a live assignment in the same zone is rejected with `ERR_SCREEN_ALREADY_ASSIGNED` (HTTP 409)."

        Releasing the first assignment frees the screen, so the same screen
        can then be re-assigned to another event.

        Design: Difficulty/resource_temporal_overlap/screen_assignment_exclusive_interval
        """
        venue = create_venue()
        zone = create_zone(venue["id"])
        event_a = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Game A",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        event_b = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Game B",
            home_market_zip="10001",
            expected_attendance=3000,
            scheduled_start="2026-09-13T20:00:00Z",
            scheduled_end="2026-09-13T23:00:00Z",
        )
        assignment = create_screen_assignment(zone["id"], event_a["id"])

        release = api.release_screen_assignment(
            zone["id"], assignment["id"], VENUE_MANAGER_HEADERS
        )
        assert release.status_code == 204

        reassigned = validate_success(
            api.create_screen_assignment(
                zone["id"],
                screen_assignment_payload(
                    event_id=event_b["id"], screen_id="S1", audio_enabled=False
                ),
                VENUE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert reassigned["event_id"] == event_b["id"]


class TestBlackoutWindowAggregateCapacity:
    """The blackout buffer opens before the event itself starts."""

    def _setup_blacked_out_event(self, api):
        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="NCAA",
            title="College Game",
            home_market_zip="14201",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_and_activate_license(venue["id"], league="NCAA")
        advance_clock("2026-09-13T18:45:00Z")
        return venue, zone, event

    def test_assignment_inside_the_pre_game_buffer_is_rejected(self, api):
        """PRD §3.2: "A blackout window is active for a non-PPV event when the current logical time is at or after 30 minutes before the event's `scheduled_start` and at or before 60 minutes after its `scheduled_end`, the venue's `market_zip` lies within the license's `blackout_radius_miles` of the event's `home_market_zip`, and the league's license is `ACTIVE`."
        PRD §3.3: "Assigning a screen to an event whose blackout window is currently active at this venue is rejected with `ERR_BLACKOUT_WINDOW_ACTIVE`."

        At 18:45 — 15 minutes before the 19:00 start — the buffer is already
        active, so the assignment is rejected.

        Design: Difficulty/resource_temporal_overlap/blackout_window_aggregate_capacity
        """
        venue, zone, event = self._setup_blacked_out_event(api)

        resp = api.create_screen_assignment(
            zone["id"],
            screen_assignment_payload(event_id=event["id"], screen_id="S1"),
            VENUE_MANAGER_HEADERS,
        )
        validate_error(resp, ApiErrorId.ERR_BLACKOUT_WINDOW_ACTIVE)

    def test_assignment_outside_the_blackout_window_is_accepted(self, api):
        """PRD §3.2: "A blackout window is active for a non-PPV event when the current logical time is at or after 30 minutes before the event's `scheduled_start` and at or before 60 minutes after its `scheduled_end`, the venue's `market_zip` lies within the license's `blackout_radius_miles` of the event's `home_market_zip`, and the league's license is `ACTIVE`."

        At 17:00 — two hours before the event — the buffer has not opened, so
        the same assignment succeeds.

        Design: Difficulty/resource_temporal_overlap/blackout_window_aggregate_capacity
        """
        venue = create_venue()
        zone = create_zone(venue["id"])
        event = create_event(
            kind="BASE",
            league="NCAA",
            title="College Game",
            home_market_zip="14201",
            expected_attendance=5000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        create_and_activate_license(venue["id"], league="NCAA")
        advance_clock("2026-09-13T17:00:00Z")

        assignment = validate_success(
            api.create_screen_assignment(
                zone["id"],
                screen_assignment_payload(event_id=event["id"], screen_id="S1"),
                VENUE_MANAGER_HEADERS,
            ),
            expected_status=201,
        )
        assert assignment["event_id"] == event["id"]
