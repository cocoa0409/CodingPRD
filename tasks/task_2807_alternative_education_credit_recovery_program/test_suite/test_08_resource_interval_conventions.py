"""Two resources under opposite interval conventions: the station's buffered
half-open occupancy, and the provider's closed-interval aggregate caseload."""

from test_helpers import (
    ApiErrorId,
    CreditPolicy,
    Modality,
    ProctorSessionStatus,
    ProviderRoleType,
    ServiceCode,
    SubjectArea,
    SupportSessionStatus,
    assert_same_instant,
    fixtures as fx,
    make_placement_coordinator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

BIO1 = {
    "code": "BIO1",
    "title": "Biology I",
    "subject_area": SubjectArea.SCIENCE.value,
    "credit_value": 1.00,
    "modality": Modality.ONLINE.value,
    "total_modules": 10,
    "required_seat_hours": 60.00,
    "pacing_days": 40,
    "proctoring_required": True,
    "proctored_exam_weight": 0.40,
    "ncaa_approved": True,
    "min_passing_percent": 60.00,
}


def _station_with_one_booking(api):
    """A station holding a single 09:00-10:00 exam slot."""
    world = fx.proctored_world(
        api,
        credit_policy=CreditPolicy.COMPETENCY.value,
        course_overrides=dict(BIO1),
        referral_overrides={
            "deficiency_credits": 6.00,
            "behavior_incident_count": 1,
            "days_disengaged": 6,
        },
    )
    world["first_session"] = fx.book_proctor_session(
        api,
        world["enrollment"]["id"],
        world["station"]["id"],
        world["center"]["id"],
        scheduled_start="2026-08-05T09:00:00.000Z",
        scheduled_end="2026-08-05T10:00:00.000Z",
    )
    world["coordinator"] = make_placement_coordinator_headers(world["center"]["id"])
    return world


def _session_body(world, start, end):
    return {
        "course_enrollment_id": world["enrollment"]["id"],
        "proctor_station_id": world["station"]["id"],
        "scheduled_start": start,
        "scheduled_end": end,
    }


class TestStationOccupancyIsHalfOpenAndBuffered:
    """The 15-minute turnaround extends occupancy to 10:15, exclusive."""

    def test_a_slot_inside_the_turnaround_buffer_is_refused(self, api):
        """10:10 still falls inside the buffered occupancy of the 09:00-10:00
        booking, so the second booking is refused with ERR_STATION_CONFLICT.

        PRD: "A proctoring station admits one session at a time, compared as a
        half-open interval extended by the station's turnaround buffer
        (`ERR_STATION_CONFLICT`)"

        Design: Difficulty/resource_temporal_overlap/proctor_station_buffer_half_open_conflict
        """
        world = _station_with_one_booking(api)

        response = api.create_proctor_session(
            _session_body(
                world, "2026-08-05T10:10:00.000Z", "2026-08-05T11:00:00.000Z"
            ),
            world["coordinator"],
        )
        validate_error(response, ApiErrorId.STATION_CONFLICT.value, 409)

        station = fx.read_station(api, world["station"]["id"])
        assert station["scheduled_session_count"] == 1
        rows, _meta = validate_paginated(
            api.list_proctor_sessions(
                world["coordinator"], {"proctor_station_id": world["station"]["id"]}
            )
        )
        assert len(rows) == 1

    def test_a_slot_starting_exactly_on_the_buffer_boundary_is_accepted(self, api):
        """10:15 is the first instant outside the half-open buffered interval, so
        the booking is created SCHEDULED and unscored.

        PRD: "A station admits one session at a time, and the occupancy test is a
        **half-open** interval comparison — a session ending exactly when another
        begins does not conflict on its own — but each existing session's end is
        extended by the station's `turnaround_buffer_minutes` of 15 before the
        comparison is made, so the next booking may only begin a quarter of an
        hour after the previous session's scheduled end."

        Design: Difficulty/resource_temporal_overlap/proctor_station_buffer_half_open_conflict
        """
        world = _station_with_one_booking(api)
        api.create_proctor_session(
            _session_body(
                world, "2026-08-05T10:10:00.000Z", "2026-08-05T11:00:00.000Z"
            ),
            world["coordinator"],
        )

        session = validate_success(
            api.create_proctor_session(
                _session_body(
                    world, "2026-08-05T10:15:00.000Z", "2026-08-05T11:00:00.000Z"
                ),
                world["coordinator"],
            ),
            201,
        )
        assert session["status"] == ProctorSessionStatus.SCHEDULED.value
        assert_same_instant(
            session["scheduled_start"], "2026-08-05T10:15:00Z", "scheduled start"
        )
        assert session["score_percent"] is None

        station = fx.read_station(api, world["station"]["id"])
        assert station["scheduled_session_count"] == 2
        assert station["turnaround_buffer_minutes"] == 15

    def test_booking_a_slot_never_scores_the_exam(self, api):
        """Two scheduled sittings exist and the enrollment still reports no
        proctored exam percent.

        PRD: "`proctored_exam_percent` — defined as the `score_percent` of the
        latest `COMPLETED` session for that enrollment when ordered by
        `created_at` ascending, so the most recently created completed session
        wins, and null while no session for the enrollment has completed"

        Design: Difficulty/resource_temporal_overlap/proctor_station_buffer_half_open_conflict
        """
        world = _station_with_one_booking(api)
        validate_success(
            api.create_proctor_session(
                _session_body(
                    world, "2026-08-05T10:15:00.000Z", "2026-08-05T11:00:00.000Z"
                ),
                world["coordinator"],
            ),
            201,
        )

        enrollment = fx.read_enrollment(api, world["enrollment"]["id"])
        assert enrollment["proctored_exam_percent"] is None

        rows, _meta = validate_paginated(
            api.list_proctor_sessions(
                world["coordinator"],
                {
                    "course_enrollment_id": world["enrollment"]["id"],
                    "status": ProctorSessionStatus.SCHEDULED.value,
                },
            )
        )
        assert len(rows) == 2


def _provider_holding_two_sessions(api):
    """One counsellor capped at two concurrent students, already holding
    13:00-14:00 and 13:30-14:30 for two different placements."""
    home_school = fx.open_home_school(api)
    center = fx.open_center(api)
    placements = []
    for _ in range(3):
        student = fx.register_student(api, home_school["id"], grade_level=10, cohort_year=2028)
        referral = fx.screened_referral(
            api,
            student["id"],
            center["id"],
            home_school["id"],
            deficiency_credits=4.00,
            behavior_incident_count=1,
            days_disengaged=6,
        )
        fx.offer_seat(api, referral["id"], center["id"])
        placements.append(
            fx.accept_seat(
                api,
                referral["id"],
                home_school["id"],
                credit_policy=CreditPolicy.SEAT_TIME.value,
            )
        )
    provider = fx.assign_provider(
        api,
        center["id"],
        role_type=ProviderRoleType.COUNSELOR.value,
        max_concurrent_students=2,
    )
    coordinator = make_placement_coordinator_headers(center["id"])
    first = fx.schedule_support_session(
        api,
        provider["id"],
        placements[0]["id"],
        center["id"],
        start_at="2026-08-05T13:00:00.000Z",
        end_at="2026-08-05T14:00:00.000Z",
        service_code=ServiceCode.ACADEMIC_COUNSELING.value,
    )
    second = fx.schedule_support_session(
        api,
        provider["id"],
        placements[1]["id"],
        center["id"],
        start_at="2026-08-05T13:30:00.000Z",
        end_at="2026-08-05T14:30:00.000Z",
        service_code=ServiceCode.ACADEMIC_COUNSELING.value,
    )
    return {
        "center": center,
        "provider": provider,
        "placements": placements,
        "coordinator": coordinator,
        "first": first,
        "second": second,
    }


def _support_body(world, start, end):
    return {
        "support_provider_id": world["provider"]["id"],
        "placement_id": world["placements"][2]["id"],
        "start_at": start,
        "end_at": end,
        "service_code": ServiceCode.ACADEMIC_COUNSELING.value,
    }


class TestProviderCaseloadIsComparedOverClosedIntervals:
    """A touching endpoint counts as an intersection for the caseload cap."""

    def test_a_touching_endpoint_pushes_the_caseload_past_its_cap(self, api):
        """14:00-15:00 touches the 13:00-14:00 session and overlaps 13:30-14:30, so
        three intersecting sessions exceed a cap of two.

        PRD: "A provider may hold up to `max_concurrent_students` sessions in one
        overlapping time band, and the intersection test is a **closed** interval
        comparison — sessions that merely touch at an endpoint are treated as
        intersecting, which is the opposite of the station rule in §3.6 and is
        intentional, since a counselor cannot hand off one student at the exact
        instant they receive another."

        Design: Difficulty/resource_temporal_overlap/support_provider_aggregate_concurrency_closed_interval
        """
        world = _provider_holding_two_sessions(api)

        response = api.create_support_session(
            _support_body(
                world, "2026-08-05T14:00:00.000Z", "2026-08-05T15:00:00.000Z"
            ),
            world["coordinator"],
        )
        body = validate_error(
            response, ApiErrorId.PROVIDER_CAPACITY_EXCEEDED.value, 409
        )
        assert body["error_id"] != ApiErrorId.INVALID_INTERVAL.value
        assert body["error_id"] != ApiErrorId.PROVIDER_CENTER_MISMATCH.value

        rows, _meta = validate_paginated(
            api.list_support_sessions(
                world["coordinator"], {"support_provider_id": world["provider"]["id"]}
            )
        )
        assert len(rows) == 2

    def test_a_start_strictly_after_the_last_endpoint_is_accepted(self, api):
        """14:31 lies outside the closed interval ending at 14:30, so only two
        sessions intersect and the third booking is created.

        PRD: "When the count of intersecting sessions in `SCHEDULED` or
        `COMPLETED` status, plus the session being scheduled, would exceed the
        provider's cap, the booking is refused with
        `ERR_PROVIDER_CAPACITY_EXCEEDED`. A successful booking starts the
        session's `status` at `SCHEDULED`."

        Design: Difficulty/resource_temporal_overlap/support_provider_aggregate_concurrency_closed_interval
        """
        world = _provider_holding_two_sessions(api)
        api.create_support_session(
            _support_body(
                world, "2026-08-05T14:00:00.000Z", "2026-08-05T15:00:00.000Z"
            ),
            world["coordinator"],
        )

        session = validate_success(
            api.create_support_session(
                _support_body(
                    world, "2026-08-05T14:31:00.000Z", "2026-08-05T15:00:00.000Z"
                ),
                world["coordinator"],
            ),
            201,
        )
        assert session["status"] == SupportSessionStatus.SCHEDULED.value
        assert_same_instant(session["start_at"], "2026-08-05T14:31:00Z", "start at")
        assert session["minutes_delivered"] is None

    def test_scheduling_alone_is_never_counted_as_delivery(self, api):
        """Three scheduled sessions leave the provider's completed count at zero
        while its cap still reads two.

        PRD: "A new provider's `completed_session_count`, which counts its support
        sessions whose `status` is `COMPLETED`, reads 0."

        Design: Difficulty/resource_temporal_overlap/support_provider_aggregate_concurrency_closed_interval
        """
        world = _provider_holding_two_sessions(api)
        validate_success(
            api.create_support_session(
                _support_body(
                    world, "2026-08-05T14:31:00.000Z", "2026-08-05T15:00:00.000Z"
                ),
                world["coordinator"],
            ),
            201,
        )

        provider = fx.read_provider(api, world["provider"]["id"])
        assert provider["max_concurrent_students"] == 2
        assert provider["completed_session_count"] == 0

        rows, _meta = validate_paginated(
            api.list_support_sessions(
                world["coordinator"],
                {
                    "support_provider_id": world["provider"]["id"],
                    "status": SupportSessionStatus.SCHEDULED.value,
                },
            )
        )
        assert len(rows) == 3
