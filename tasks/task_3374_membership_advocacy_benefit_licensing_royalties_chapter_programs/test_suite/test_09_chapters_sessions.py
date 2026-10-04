"""Chapters and course sessions: room-buffer overlap, instructor half-open
adjacency, enrollment capacity boundary, and coordinator ownership."""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    ApiErrorId, TEST_USERS,
    set_clock, create_household_with_term, create_chapter_ok,
    create_session_ok, list_chapter_sessions,
    create_course_session_payload,
    make_chapter_coordinator_headers, make_member_headers,
)

MSA = TEST_USERS["member_services_headers"]


class TestChapterRoomBufferSemantics:
    def _setup_chapter_with_first_session(self):
        set_clock()
        chapter = create_chapter_ok(name="Austin Chapter", state_code="TX",
                                    city="Austin")
        first = create_session_ok(
            chapter["id"], course_kind="TAX_PREP", instructor_name="Robin Sage",
            start_time="2026-10-10T09:00:00Z", end_time="2026-10-10T11:00:00Z",
            capacity=20)
        return chapter, first

    def test_start_inside_turnover_buffer_rejected(self, api):
        """PRD §3.8: "The chapter-room rule protects the physical room: a new
        session conflicts with an existing session of the same chapter unless
        the new session starts at least 30 minutes after the existing one
        ends, or the existing one starts at least 30 minutes after the new
        one ends." PRD §3.8: "An existing session ending at 11:00 therefore
        blocks any new session starting before 11:30, while a start at
        exactly 11:30 is allowed; a violation is rejected with
        `ERR_SESSION_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/chapter_room_buffer_semantics
        """
        chapter, first = self._setup_chapter_with_first_session()
        assert first["id"]
        payload = create_course_session_payload(
            course_kind="DRIVER_SAFETY", instructor_name="Lee Park",
            start_time="2026-10-10T11:20:00Z", end_time="2026-10-10T12:20:00Z",
            capacity=20)
        resp = api.create_course_session(
            chapter["id"], payload, make_chapter_coordinator_headers(chapter["id"]))
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP)

    def test_start_exactly_at_buffer_boundary_admitted(self, api):
        """PRD §3.8: "An existing session ending at 11:00 therefore blocks
        any new session starting before 11:30, while a start at exactly 11:30
        is allowed". PRD §2.6: "Where a comparison against a cap or threshold
        is involved, the comparison is always "no more than" or "at least"
        exactly as stated — a value landing precisely on a boundary passes or
        fires exactly as the inclusive reading implies."

        Design: Difficulty/resource_temporal_overlap/chapter_room_buffer_semantics
        """
        chapter, _first = self._setup_chapter_with_first_session()
        payload = create_course_session_payload(
            course_kind="DRIVER_SAFETY", instructor_name="Lee Park",
            start_time="2026-10-10T11:30:00Z", end_time="2026-10-10T12:30:00Z",
            capacity=20)
        admitted = validate_success(
            api.create_course_session(
                chapter["id"], payload,
                make_chapter_coordinator_headers(chapter["id"])),
            expected_status=201)
        assert admitted["id"]
        rows = list_chapter_sessions(chapter["id"])
        assert len(rows) == 2


class TestInstructorHalfOpenAdjacency:
    def _setup_three_chapters(self):
        set_clock()
        c1 = create_chapter_ok(name="Tulsa North", state_code="OK", city="Tulsa")
        c2 = create_chapter_ok(name="Tulsa South", state_code="OK", city="Tulsa")
        c3 = create_chapter_ok(name="Norman Chapter", state_code="OK", city="Norman")
        return c1, c2, c3

    def test_back_to_back_sessions_across_chapters_admitted(self, api):
        """PRD §3.8: "The instructor rule protects the volunteer:
        `instructor_name` is a case-sensitive identity, and across all
        chapters a plain half-open overlap test applies — the new session
        conflicts exactly when its start is strictly before an existing
        session's end and that session's start is strictly before the new
        session's end." PRD §3.8: "Adjacency is allowed — a session starting
        at the exact moment another of the instructor's sessions ends does
        not conflict — and no buffer applies".

        Design: Difficulty/resource_temporal_overlap/instructor_half_open_adjacency_semantics
        """
        c1, c2, _c3 = self._setup_three_chapters()
        first = create_session_ok(
            c1["id"], course_kind="DRIVER_SAFETY", instructor_name="Jordan Vega",
            start_time="2026-10-10T09:00:00Z", end_time="2026-10-10T11:00:00Z",
            capacity=15)
        assert first["id"]
        # [09:00, 11:00) and [11:00, 13:00) do not intersect: admitted.
        adjacent = create_session_ok(
            c2["id"], course_kind="DRIVER_SAFETY", instructor_name="Jordan Vega",
            start_time="2026-10-10T11:00:00Z", end_time="2026-10-10T13:00:00Z",
            capacity=15)
        assert adjacent["id"]

    def test_overlapping_start_in_third_chapter_rejected(self, api):
        """PRD §3.8: "a violation is rejected with
        `ERR_INSTRUCTOR_DOUBLE_BOOKED` (HTTP 409)." PRD §3.8: "across all
        chapters a plain half-open overlap test applies — the new session
        conflicts exactly when its start is strictly before an existing
        session's end and that session's start is strictly before the new
        session's end."

        Design: Difficulty/resource_temporal_overlap/instructor_half_open_adjacency_semantics
        """
        c1, _c2, c3 = self._setup_three_chapters()
        create_session_ok(
            c1["id"], course_kind="DRIVER_SAFETY", instructor_name="Jordan Vega",
            start_time="2026-10-10T09:00:00Z", end_time="2026-10-10T11:00:00Z",
            capacity=15)
        # 10:30 < 11:00 intersects [09:00, 11:00); C3 has no sessions, so
        # only the instructor rule can fire.
        payload = create_course_session_payload(
            course_kind="TAX_PREP", instructor_name="Jordan Vega",
            start_time="2026-10-10T10:30:00Z", end_time="2026-10-10T12:00:00Z",
            capacity=15)
        resp = api.create_course_session(
            c3["id"], payload, make_chapter_coordinator_headers(c3["id"]))
        validate_error(resp, ApiErrorId.ERR_INSTRUCTOR_DOUBLE_BOOKED)


class TestEnrollmentCapacityBoundary:
    def _setup_capacity_one_session(self):
        set_clock()
        _hh1, _t1, m1 = create_household_with_term(
            state_code="OR", term_years=1, primary_full_name="Nina Nash",
            primary_date_of_birth="1966-10-10")
        _hh2, _t2, m2 = create_household_with_term(
            state_code="OR", term_years=1, primary_full_name="Omar Ortiz",
            primary_date_of_birth="1973-02-02")
        chapter = create_chapter_ok(name="Portland Chapter", state_code="OR",
                                    city="Portland")
        session = create_session_ok(
            chapter["id"], course_kind="TAX_PREP", instructor_name="Sam Alder",
            start_time="2026-10-10T09:00:00Z", end_time="2026-10-10T11:00:00Z",
            capacity=1)
        return m1, m2, session

    def test_enrollment_reaching_exactly_capacity_succeeds(self, api):
        """PRD §3.8: "Capacity last: when `enrolled_count` has already
        reached `capacity`, the next enrollment is rejected with
        `ERR_SESSION_FULL` (HTTP 409) — which means the enrollment that
        brings the count exactly to capacity succeeds." PRD §3.8: "A
        successful enrollment appends the member id to `enrolled_member_ids`,
        recomputes `enrolled_count` as the list's length, and returns the
        updated session with HTTP 200."

        Design: Difficulty/boundary_precision_check/enrollment_capacity_boundary
        """
        m1, _m2, session = self._setup_capacity_one_session()
        resp = api.enroll_member(session["id"], {"member_id": m1},
                                 make_member_headers(m1))
        updated = validate_success(resp)
        assert updated["enrolled_count"] == 1
        assert updated["enrolled_member_ids"] == [m1]

    def test_enrollment_beyond_capacity_rejected_without_append(self, api):
        """PRD §3.8: "Capacity last: when `enrolled_count` has already
        reached `capacity`, the next enrollment is rejected with
        `ERR_SESSION_FULL` (HTTP 409)".

        Design: Difficulty/boundary_precision_check/enrollment_capacity_boundary
        """
        m1, m2, session = self._setup_capacity_one_session()
        first = validate_success(
            api.enroll_member(session["id"], {"member_id": m1},
                              make_member_headers(m1)))
        assert first["enrolled_count"] == 1
        resp = api.enroll_member(session["id"], {"member_id": m2},
                                 make_member_headers(m2))
        validate_error(resp, ApiErrorId.ERR_SESSION_FULL)
        rows = list_chapter_sessions(session["chapter_id"])
        row = next(r for r in rows if r["id"] == session["id"])
        assert row["enrolled_member_ids"] == [m1]
        assert row["enrolled_count"] == 1


class TestCoordinatorOwnership:
    def test_coordinator_cannot_schedule_in_other_chapter(self, api):
        """PRD §2.1: "When `X-User-Role` is `ChapterCoordinator`, `X-User-ID`
        is the `id` of the acting `Chapter`; creating a course session
        compares it to the chapter identified in the path — a mismatch is
        `ERR_FORBIDDEN`."

        Design: Corner/rbac/coordinator_cannot_schedule_in_other_chapter
        """
        set_clock()
        c1 = create_chapter_ok(name="Boise North", state_code="ID", city="Boise")
        c2 = create_chapter_ok(name="Boise South", state_code="ID", city="Boise")
        payload = create_course_session_payload(
            course_kind="TAX_PREP", instructor_name="Dana Duff",
            start_time="2026-10-10T09:00:00Z", end_time="2026-10-10T11:00:00Z",
            capacity=10)
        resp = api.create_course_session(
            c2["id"], payload, make_chapter_coordinator_headers(c1["id"]))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)
        rows, meta = validate_paginated(
            api.list_chapter_sessions(
                c2["id"], make_chapter_coordinator_headers(c2["id"])))
        assert len(rows) == 0
        assert meta["total_count"] == 0
