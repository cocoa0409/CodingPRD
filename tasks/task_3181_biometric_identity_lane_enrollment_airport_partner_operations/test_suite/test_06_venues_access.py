"""Venues, events, and member access: padded-window conflict semantics, age-gate
birthday boundary, event cancel window, and venue creation defaults."""
from test_helpers import (
    ApiErrorId,
    create_active_member,
    create_airport,
    create_enrollment_center,
    create_venue,
    create_venue_event,
    enroll_member_at_center,
    make_member_headers,
    register_member,
    set_clock,
    setup_airport_with_active_agreement,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import OPS, VENUE


class TestVenueEventBufferArithmetic:
    def test_overlapping_padded_windows_conflict(self, api):
        """PRD §3.6: "Scheduling applies a padded-window conflict check against every other
        non-`CANCELLED` event at the same venue: each event's effective window runs
        from its start minus its buffer to its end plus its buffer, and two events
        conflict only when the padded windows strictly overlap" and "A conflict is
        refused with `ERR_EVENT_WINDOW_CONFLICT`."

        Event A 10:00-12:00 buffer 2 -> padded [08:00, 14:00). Candidate B at 13:00
        overlaps (13:00 < 14:00).

        Design: Difficulty/resource_temporal_overlap/venue_event_buffer_arithmetic_adjacent_vs_overlap
        """
        venue = create_venue(
            name="Arena V", venue_type="ARENA", city="Denver", state_code="CO",
            access_rule_mode="AGE_18_PLUS",
        )
        create_venue_event(
            venue["id"], name="Event A", start_time="2026-10-10T10:00:00Z",
            end_time="2026-10-10T12:00:00Z", buffer_hours=2,
        )
        resp = api.create_venue_event(
            {"venue_id": venue["id"], "name": "Event B overlap",
             "start_time": "2026-10-10T13:00:00Z", "end_time": "2026-10-10T15:00:00Z",
             "buffer_hours": 0},
            VENUE,
        )
        validate_error(resp, ApiErrorId.ERR_EVENT_WINDOW_CONFLICT)

    def test_touching_padded_edges_do_not_conflict(self, api):
        """PRD §3.6: "Touching edges do not conflict; the windows behave as half-open
        intervals."

        Candidate C starts at 14:00, exactly A's padded end: no conflict.

        Design: Difficulty/resource_temporal_overlap/venue_event_buffer_arithmetic_adjacent_vs_overlap
        """
        venue = create_venue(
            name="Arena V", venue_type="ARENA", city="Denver", state_code="CO",
            access_rule_mode="AGE_18_PLUS",
        )
        create_venue_event(
            venue["id"], name="Event A", start_time="2026-10-10T10:00:00Z",
            end_time="2026-10-10T12:00:00Z", buffer_hours=2,
        )
        event_c = validate_success(
            api.create_venue_event(
                {"venue_id": venue["id"], "name": "Event C adjacent",
                 "start_time": "2026-10-10T14:00:00Z", "end_time": "2026-10-10T16:00:00Z",
                 "buffer_hours": 0},
                VENUE,
            ),
            expected_status=201,
        )
        assert event_c["status"] == "SCHEDULED"


class TestVenueAgeGateBoundary:
    def _setup_age_21_venue_and_members(self):
        venue = create_venue(
            name="Club 21", venue_type="OTHER", city="Reno", state_code="NV",
            access_rule_mode="AGE_21_PLUS",
        )
        # PRD §3.6 requires a *future* start_time at scheduling time, so the
        # event is scheduled one second past the default clock and the clock is
        # then advanced into the event window for the access attempts.
        create_venue_event(
            venue["id"], name="Night", start_time="2026-09-01T00:00:01Z",
            end_time="2026-09-02T00:00:00Z", buffer_hours=0,
        )
        set_clock("2026-09-01T00:00:01Z")
        airport = create_airport("RNO")
        center = create_enrollment_center(airport["id"], name="RNO Center")
        member_a = create_active_member(
            center, email="a21@x.com", full_name="Turns Today",
            date_of_birth="2005-09-01", document_number="PN000001",
        )
        member_b = create_active_member(
            center, email="b21@x.com", full_name="Turns Tomorrow",
            date_of_birth="2005-09-02", document_number="PN000002",
        )
        return venue, member_a, member_b

    def test_twenty_first_birthday_on_access_date_admitted(self, api):
        """PRD §3.6: "The age gate follows the venue's mode using the member's age in whole
        years at the logical clock date, with a birthday reached on the day counting:
        `ALL_MEMBERS` admits any active member; `AGE_18_PLUS` admits members aged at
        least eighteen, and `AGE_21_PLUS` those at least twenty-one — a member whose
        eighteenth (respectively twenty-first) birthday is exactly the access date is
        admitted."

        Design: Corner/calculations/venue_age_gate_birthday_boundary
        """
        venue, member_a, _ = self._setup_age_21_venue_and_members()
        access = validate_success(
            api.record_venue_access(
                venue["id"], member_a["id"], make_member_headers(member_a["id"])
            ),
            expected_status=201,
        )
        assert access["outcome"] == "ADMITTED"

    def test_one_day_short_of_twenty_one_rejected(self, api):
        """PRD §3.6: "`AGE_21_PLUS` those at least twenty-one — a member whose eighteenth
        (respectively twenty-first) birthday is exactly the access date is admitted."
        PRD §3.6: "its `outcome` — `ADMITTED` or `REJECTED` with a `reject_reason` of
        `AGE_RULE`, `VENUE_SUSPENDED`, `MEMBER_INELIGIBLE`, or `NO_ACTIVE_EVENT` — is
        decided synchronously."

        Design: Corner/calculations/venue_age_gate_birthday_boundary
        """
        venue, _, member_b = self._setup_age_21_venue_and_members()
        # PRD §3.6: "A failed age gate surfaces as `ERR_AGE_RULE_VIOLATION`" —
        # the response is the error; the REJECTED outcome with reject_reason
        # AGE_RULE is recorded on the VenueAccessEvent itself.
        resp = api.record_venue_access(
            venue["id"], member_b["id"], make_member_headers(member_b["id"])
        )
        validate_error(resp, ApiErrorId.ERR_AGE_RULE_VIOLATION)
        events, _ = validate_paginated(
            api.list_venue_access_events(OPS, params={"member_id": member_b["id"]})
        )
        assert any(
            e["outcome"] == "REJECTED" and e["reject_reason"] == "AGE_RULE"
            for e in events
        ), f"expected a recorded REJECTED/AGE_RULE access event, got {events}"


class TestVenueEventCancelWindow:
    def test_cancel_at_start_time_rejected(self, api):
        """PRD §3.6: "Cancelling an event is possible only while the logical clock is still
        before its `start_time`; at or after the start the attempt fails with
        `ERR_EVENT_ALREADY_STARTED`."

        Design: Corner/endpoints/venue_event_cancel_only_before_start
        """
        venue = create_venue(
            name="Cancel Arena", venue_type="ARENA", city="Fargo", state_code="ND",
            access_rule_mode="ALL_MEMBERS",
        )
        event = create_venue_event(
            venue["id"], name="Ev", start_time="2026-09-10T00:00:00Z",
            end_time="2026-09-10T04:00:00Z", buffer_hours=0,
        )
        set_clock("2026-09-10T00:00:00Z")
        resp = api.cancel_venue_event(event["id"], VENUE)
        validate_error(resp, ApiErrorId.ERR_EVENT_ALREADY_STARTED)
        event_after = validate_success(api.get_venue_event(event["id"], VENUE))
        assert event_after["status"] == "SCHEDULED"

    def test_cancel_before_start_succeeds(self, api):
        """PRD §3.6: "Cancelling an event is possible only while the logical clock is still
        before its `start_time`; at or after the start the attempt fails with
        `ERR_EVENT_ALREADY_STARTED`." — before start the cancel succeeds.

        Design: Corner/endpoints/venue_event_cancel_only_before_start
        """
        venue = create_venue(
            name="Cancel Arena", venue_type="ARENA", city="Fargo", state_code="ND",
            access_rule_mode="ALL_MEMBERS",
        )
        event = create_venue_event(
            venue["id"], name="Ev", start_time="2026-09-10T00:00:00Z",
            end_time="2026-09-10T04:00:00Z", buffer_hours=0,
        )
        # default clock 2026-09-01 is before the start
        cancelled = validate_success(api.cancel_venue_event(event["id"], VENUE))
        assert cancelled["status"] == "CANCELLED"


class TestVenueDefaults:
    def test_omitting_access_rule_mode_defaults_age_18_plus(self, api):
        """PRD §3.6: "venues, which a `VenueOps` operator creates with a `name`, a
        `venue_type` of `STADIUM`, `ARENA`, or `OTHER`, a `city` and `state_code`, and
        an optional `access_rule_mode` defaulting to `AGE_18_PLUS`."

        Design: Corner/entities/venue_access_rule_mode_default_age_18_plus
        """
        resp = api.create_venue(
            {"name": "Default Arena", "venue_type": "ARENA", "city": "Tulsa",
             "state_code": "OK"},
            VENUE,
        )
        venue = validate_success(resp, expected_status=201)
        assert venue["access_rule_mode"] == "AGE_18_PLUS"
