"""Resource temporal overlap: instructor half-open double-booking and the
60-minute site turnover buffer."""
from test_helpers import (
    COORD,
    TC,
    ApiErrorId,
    align_center_site,
    align_instructor,
    create_course_session_payload,
    create_legacy_certified_instructor,
    create_scheduled_session,
    create_site_payload,
    get_success_data,
    setup_teaching_scenario,
    validate_error,
    validate_success,
)


class TestInstructorDoubleBookingHalfOpen:
    def test_back_to_back_allowed_overlap_rejected(self, api):
        """PRD §3.4: "Overlap is computed on a half-open basis — the existing
        session occupies the interval from its `start_at` up to but not
        including its `end_at` — so a back-to-back session that begins at the
        exact instant the prior session ends is permitted."
        PRD §3.4: "if the same `primary_instructor_id` already leads another
        session in `SCHEDULED` or `IN_PROGRESS` status whose time interval
        overlaps the new session's, the create is rejected with
        `ERR_SESSION_OVERLAP_INSTRUCTOR`."

        Design: Difficulty/resource_temporal_overlap/instructor_double_booking_half_open
        """
        ctx = setup_teaching_scenario()
        # Session A: 14:00-18:00 at site 1.
        session_a = create_scheduled_session(ctx)
        # Second ALIGNED site so the site rule cannot fire first.
        site2 = get_success_data(api.create_site(
            ctx["center"]["id"],
            create_site_payload(name="Annex Lab",
                                street_address="200 Airway Blvd",
                                capacity_students=12), TC))
        align_center_site(ctx["center"]["id"], site2["id"])

        # Back-to-back at the exact end instant -> allowed.
        session_b = validate_success(
            api.create_course_session(
                create_course_session_payload(
                    ctx["center"]["id"], site2["id"], ctx["lead"]["id"],
                    ctx["guidelines_version"]["id"],
                    start_at="2026-10-10T18:00:00Z",
                    end_at="2026-10-10T21:00:00Z"), COORD),
            expected_status=201)
        assert session_b["status"] == "SCHEDULED"

        # Overlapping by one hour -> rejected.
        resp = api.create_course_session(
            create_course_session_payload(
                ctx["center"]["id"], site2["id"], ctx["lead"]["id"],
                ctx["guidelines_version"]["id"],
                start_at="2026-10-10T17:00:00Z",
                end_at="2026-10-10T20:00:00Z"), COORD)
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP_INSTRUCTOR)

    def test_overlap_window_checked_at_creation_time(self, api):
        """PRD §3.4: "The instructor must not be double-booked: if the same
        `primary_instructor_id` already leads another session in `SCHEDULED` or
        `IN_PROGRESS` status whose time interval overlaps the new session's,
        the create is rejected with `ERR_SESSION_OVERLAP_INSTRUCTOR`."

        Design: Difficulty/resource_temporal_overlap/instructor_double_booking_half_open
        """
        ctx = setup_teaching_scenario()
        session_a = create_scheduled_session(ctx)
        # A fully contained interval overlaps.
        resp = api.create_course_session(
            create_course_session_payload(
                ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
                ctx["guidelines_version"]["id"],
                start_at="2026-10-10T15:00:00Z",
                end_at="2026-10-10T16:00:00Z"), COORD)
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP_INSTRUCTOR)


class TestSiteBookingTurnoverBuffer:
    def test_sixty_minute_gap_allowed_fifty_nine_rejected(self, api):
        """PRD §3.4: "The site has a looser rule with a turnover buffer: if the
        site already hosts a `SCHEDULED` or `IN_PROGRESS` session such that the
        gap between the two sessions is less than sixty minutes, the create is
        rejected with `ERR_SESSION_OVERLAP_SITE`. A gap of exactly sixty
        minutes is permitted."

        Design: Difficulty/resource_temporal_overlap/site_booking_turnover_buffer
        """
        ctx = setup_teaching_scenario()
        # Session A: 14:00-18:00 at site 1 with lead 1.
        session_a = create_scheduled_session(ctx)
        # A second certified+aligned instructor keeps the instructor rule out.
        lead2 = create_legacy_certified_instructor(
            ctx["center"]["id"], full_name="Dana Second", email="dana@x.example")
        align_instructor(ctx["center"]["id"], lead2["id"])

        # Exactly 60-minute gap after session A (19:00 start) -> permitted.
        session_d = validate_success(
            api.create_course_session(
                create_course_session_payload(
                    ctx["center"]["id"], ctx["site"]["id"], ctx["lead"]["id"],
                    ctx["guidelines_version"]["id"],
                    start_at="2026-10-10T19:00:00Z",
                    end_at="2026-10-10T21:00:00Z"), COORD),
            expected_status=201)
        assert session_d["status"] == "SCHEDULED"

        # 59-minute gap after session A (18:59 start, different instructor so
        # the instructor rule cannot fire first) -> rejected.
        resp = api.create_course_session(
            create_course_session_payload(
                ctx["center"]["id"], ctx["site"]["id"], lead2["id"],
                ctx["guidelines_version"]["id"],
                start_at="2026-10-10T18:59:00Z",
                end_at="2026-10-10T21:00:00Z"), COORD)
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP_SITE)

    def test_zero_minute_gap_rejected_at_same_site(self, api):
        """PRD §3.4: "if the site already hosts a `SCHEDULED` or `IN_PROGRESS`
        session such that the gap between the two sessions is less than sixty
        minutes, the create is rejected with `ERR_SESSION_OVERLAP_SITE`."

        Design: Difficulty/resource_temporal_overlap/site_booking_turnover_buffer
        """
        ctx = setup_teaching_scenario()
        create_scheduled_session(ctx)
        lead2 = create_legacy_certified_instructor(
            ctx["center"]["id"], full_name="Dana Second", email="dana@x.example")
        align_instructor(ctx["center"]["id"], lead2["id"])
        resp = api.create_course_session(
            create_course_session_payload(
                ctx["center"]["id"], ctx["site"]["id"], lead2["id"],
                ctx["guidelines_version"]["id"],
                start_at="2026-10-10T18:00:00Z",
                end_at="2026-10-10T21:00:00Z"), COORD)
        validate_error(resp, ApiErrorId.ERR_SESSION_OVERLAP_SITE)
