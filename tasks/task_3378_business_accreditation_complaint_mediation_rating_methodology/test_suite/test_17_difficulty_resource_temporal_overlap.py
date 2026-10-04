"""Difficulty queue — resource temporal overlap: mediator sessions use
half-open [start, end) intersection so adjacency is allowed (PRD §3.5), while
hearing rooms require a closed 30-minute buffer on both sides so adjacency
itself conflicts (PRD §3.5)."""

from test_helpers import (
    ApiErrorId,
    CLOCK_START_ISO,
    TEST_USERS,
    create_bureau,
    create_business,
    create_consumer,
    schedule_hearing_payload,
    schedule_mediation_payload,
    set_clock,
    setup_arbitration_filed,
    setup_mediation_accepted,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]


def _setup_world():
    set_clock(CLOCK_START_ISO)
    bureau = create_bureau(name="Heartland Bureau",
                           territory_state_codes=["IA", "NE"],
                           local_dues_fee_cents=0)
    consumer = create_consumer(full_name="Pat Consumer",
                               email="pat@example.com", home_state_code="IA")
    business = create_business(legal_name="BigBox Services Inc",
                               home_state_code="IA", employee_count=250,
                               founded_on="2018-01-01T00:00:00Z")
    return bureau, consumer, business


def _get_mediation_case(api, complaint_id, case_id):
    rows, _meta = validate_paginated(
        api.list_mediation_cases(complaint_id, ADMIN))
    for row in rows:
        if row["id"] == case_id:
            return row
    raise AssertionError(f"mediation case {case_id} missing")


class TestMediatorHalfOpenSessions:
    def _setup_three_accepted(self):
        _bureau, consumer, business = _setup_world()
        triples = []
        for description in ("m1", "m2", "m3"):
            complaint, case = setup_mediation_accepted(consumer, business)
            triples.append((complaint, case))
        return business, triples

    def test_back_to_back_sessions_do_not_conflict(self, api):
        """PRD §3.5: "A mediator cannot hold overlapping sessions: the new
        session conflicts with any other `SCHEDULED` case carrying the same
        `mediator_id` whose half-open interval — start inclusive, end
        exclusive — intersects the requested one, and such a request is
        rejected with `ERR_MEDIATOR_SCHEDULE_CONFLICT`; back-to-back sessions,
        where one session ends exactly as another begins, do not conflict."

        Design: Difficulty/resource_temporal_overlap/mediator_sessions_half_open_adjacency_allowed_overlap_rejected
        """
        _business, triples = self._setup_three_accepted()
        (_c1, m1), (_c2, m2), _unused = triples
        resp = api.schedule_mediation(
            m1["id"], schedule_mediation_payload(
                mediator_id="med-9",
                session_start_at="2026-09-21T10:00:00Z",
                session_end_at="2026-09-21T11:00:00Z"), ADMIN)
        assert validate_success(resp, 200)["status"] == "SCHEDULED"
        # Adjacent at 11:00: one session ends exactly as the other begins.
        resp = api.schedule_mediation(
            m2["id"], schedule_mediation_payload(
                mediator_id="med-9",
                session_start_at="2026-09-21T11:00:00Z",
                session_end_at="2026-09-21T12:00:00Z"), ADMIN)
        scheduled = validate_success(resp, 200)
        assert scheduled["status"] == "SCHEDULED"
        assert scheduled["mediator_id"] == "med-9"

    def test_intersecting_session_rejected(self, api):
        """PRD §3.5: "A mediator cannot hold overlapping sessions: the new
        session conflicts with any other `SCHEDULED` case carrying the same
        `mediator_id` whose half-open interval — start inclusive, end
        exclusive — intersects the requested one, and such a request is
        rejected with `ERR_MEDIATOR_SCHEDULE_CONFLICT`; back-to-back sessions,
        where one session ends exactly as another begins, do not conflict."

        Design: Difficulty/resource_temporal_overlap/mediator_sessions_half_open_adjacency_allowed_overlap_rejected
        """
        _business, triples = self._setup_three_accepted()
        (c1, m1), (c2, m2), (c3, m3) = triples
        api.schedule_mediation(m1["id"], schedule_mediation_payload(
            mediator_id="med-9", session_start_at="2026-09-21T10:00:00Z",
            session_end_at="2026-09-21T11:00:00Z"), ADMIN)
        api.schedule_mediation(m2["id"], schedule_mediation_payload(
            mediator_id="med-9", session_start_at="2026-09-21T11:00:00Z",
            session_end_at="2026-09-21T12:00:00Z"), ADMIN)
        # 10:30-11:30 intersects both scheduled neighbors.
        resp = api.schedule_mediation(
            m3["id"], schedule_mediation_payload(
                mediator_id="med-9",
                session_start_at="2026-09-21T10:30:00Z",
                session_end_at="2026-09-21T11:30:00Z"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_MEDIATOR_SCHEDULE_CONFLICT)
        current = _get_mediation_case(api, c3["id"], m3["id"])
        assert current["status"] == "ACCEPTED"
        assert current["mediator_id"] is None


class TestHearingRoomBuffer:
    def _setup_two_arbitrations(self):
        _bureau, consumer, business = _setup_world()
        _complaint1, arb1 = setup_arbitration_filed(
            consumer, business, mediator_id="med-a",
            session_start_at="2026-09-22T09:00:00Z",
            session_end_at="2026-09-22T10:00:00Z")
        _complaint2, arb2 = setup_arbitration_filed(
            consumer, business, mediator_id="med-b",
            session_start_at="2026-09-22T09:00:00Z",
            session_end_at="2026-09-22T10:00:00Z")
        return business, arb1, arb2

    def test_fifteen_minute_gap_conflicts(self, api):
        """PRD §3.5: "Hearing rooms are scheduled with a safety buffer on both
        sides: for every other `HEARING_SCHEDULED` case in the same room, the
        new hearing must start no earlier than 30 minutes after the existing
        hearing's end, or else end no later than 30 minutes before the
        existing hearing's start, and any violation is rejected with
        `ERR_HEARING_ROOM_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/hearing_room_requires_thirty_minute_buffer_adjacency_conflicts
        """
        _business, arb1, arb2 = self._setup_two_arbitrations()
        resp = api.schedule_hearing(
            arb1["id"], schedule_hearing_payload(
                hearing_room_id="room-A",
                hearing_start_at="2026-10-05T10:00:00Z",
                hearing_end_at="2026-10-05T11:00:00Z"), ADMIN)
        assert validate_success(resp, 200)["status"] == "HEARING_SCHEDULED"
        # 11:15 leaves only a 15-minute buffer after the 11:00 end.
        resp = api.schedule_hearing(
            arb2["id"], schedule_hearing_payload(
                hearing_room_id="room-A",
                hearing_start_at="2026-10-05T11:15:00Z",
                hearing_end_at="2026-10-05T12:00:00Z"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_HEARING_ROOM_CONFLICT)

    def test_adjacency_conflicts_but_exact_buffer_is_allowed(self, api):
        """PRD §3.5: "Unlike mediation sessions, adjacency itself conflicts: a
        hearing that begins exactly when another hearing in the same room ends
        leaves no buffer and is rejected."

        Design: Difficulty/resource_temporal_overlap/hearing_room_requires_thirty_minute_buffer_adjacency_conflicts
        """
        _business, arb1, arb2 = self._setup_two_arbitrations()
        validate_success(api.schedule_hearing(
            arb1["id"], schedule_hearing_payload(
                hearing_room_id="room-A",
                hearing_start_at="2026-10-05T10:00:00Z",
                hearing_end_at="2026-10-05T11:00:00Z"), ADMIN), 200)
        # Exactly adjacent (11:00): no buffer at all — rejected.
        resp = api.schedule_hearing(
            arb2["id"], schedule_hearing_payload(
                hearing_room_id="room-A",
                hearing_start_at="2026-10-05T11:00:00Z",
                hearing_end_at="2026-10-05T12:00:00Z"), ADMIN)
        validate_error(resp, ApiErrorId.ERR_HEARING_ROOM_CONFLICT)
        # Exactly the 30-minute buffer (11:30): satisfies the >= rule.
        resp = api.schedule_hearing(
            arb2["id"], schedule_hearing_payload(
                hearing_room_id="room-A",
                hearing_start_at="2026-10-05T11:30:00Z",
                hearing_end_at="2026-10-05T12:30:00Z"), ADMIN)
        assert validate_success(resp, 200)["status"] == "HEARING_SCHEDULED"
