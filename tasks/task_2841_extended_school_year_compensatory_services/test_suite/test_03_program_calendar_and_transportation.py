"""The summer calendar, its transportation runs, and the day-cancellation cascade."""

import pytest

from test_helpers import (
    ApiErrorId,
    factories,
    fixtures,
    make_case_manager_headers,
    make_program_coordinator_headers,
    make_sped_director_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

CM = make_case_manager_headers()
PC = make_program_coordinator_headers()
DIR = make_sped_director_headers()

CLOCK = "2027-06-01T00:00:00Z"


def _run(program_id, route_code, service_date, start, end, seats=2):
    return factories.transportation_run_payload(
        program_id,
        route_code=route_code,
        service_date=service_date,
        window_start_time=start,
        window_end_time=end,
        vehicle_capacity_seats=seats,
    )


class TestRunWindowIntervals:
    """Run windows are closed intervals scoped by route and calendar date."""

    def test_a_touching_endpoint_collides_and_the_scope_is_route_plus_date(self, api):
        """07:45 against a run ending 07:45 collides; another route or date does not.

        The interval convention is explicit: "A run's occupied window is a **closed**
        interval: both `window_start_time` and `window_end_time` are inside it. Two
        `SCHEDULED` runs sharing a `route_code` and a `service_date` therefore collide
        whenever the new run's start time is at or before the existing run's end time
        and the existing run's start time is at or before the new run's end time. A
        touching endpoint is a conflict here — a run finishing at 07:45 and another
        starting at 07:45 on the same route and date do collide — and the collision is
        reported as `ERR_RUN_WINDOW_OVERLAP`." Nothing is persisted by a rejected
        create, and the surviving rows keep their opening values: "A run's own
        `status` starts at `SCHEDULED` and has exactly one exit." with "A run's
        `seats_committed` counts the service commitments naming that run in their
        `transportation_run_id` whose `status` is `PLANNED`, `ASSIGNED`, `ACTIVE` or
        `SUSPENDED`; commitments that have reached `COMPLETED` or `TERMINATED` have
        released their seat and no longer count."

        Design: Difficulty/resource_temporal_overlap/route_daily_windows_use_closed_intervals_plus_turnaround_buffer
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(api)

        base = validate_success(
            api.create_transportation_run(
                _run(program["id"], "R7", "2027-06-14", "07:00", "07:45"), PC
            ),
            201,
        )
        assert base["status"] == "SCHEDULED"
        assert base["seats_committed"] == 0

        touching = api.create_transportation_run(
            _run(program["id"], "R7", "2027-06-14", "07:45", "08:30"), PC
        )
        validate_error(touching, ApiErrorId.RUN_WINDOW_OVERLAP.value, 409)

        # The very window that collided is free on another route ...
        other_route = validate_success(
            api.create_transportation_run(
                _run(program["id"], "R9", "2027-06-14", "07:45", "08:30"), PC
            ),
            201,
        )
        # ... and on the same route on a different instructional date.
        other_date = validate_success(
            api.create_transportation_run(
                _run(program["id"], "R7", "2027-06-15", "07:45", "08:30"), PC
            ),
            201,
        )

        assert other_route["status"] == "SCHEDULED"
        assert other_date["status"] == "SCHEDULED"
        rows, meta = validate_paginated(
            api.list_program_transportation_runs(program["id"], PC, {"limit": 100})
        )
        assert meta["total_count"] == 3
        assert all(row["seats_committed"] == 0 for row in rows)
        assert fixtures.refresh_program(api, program["id"])["status"] == "PLANNING"

    def test_the_turnaround_rejection_band_is_open_above_zero_and_below_fifteen(
        self, api
    ):
        """A 5-minute gap is refused; exactly 15 minutes is allowed.

        The buffer test is separate from, and gentler than, the overlap test: "Runs
        that clear the overlap test face a second, gentler test. For two
        non-overlapping runs of the same `route_code` on the same `service_date`,
        measure the gap in minutes from the earlier run's `window_end_time` to the
        later run's `window_start_time`; if that gap is greater than zero but smaller
        than fifteen minutes, the request is rejected with
        `ERR_ROUTE_TURNAROUND_VIOLATION`." Because the windows do not touch, the
        closed-interval rule does not fire first: "Two `SCHEDULED` runs sharing a
        `route_code` and a `service_date` therefore collide whenever the new run's
        start time is at or before the existing run's end time and the existing run's
        start time is at or before the new run's end time."

        Design: Difficulty/resource_temporal_overlap/route_daily_windows_use_closed_intervals_plus_turnaround_buffer
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(api)

        validate_success(
            api.create_transportation_run(
                _run(program["id"], "R7", "2027-06-14", "07:00", "07:45"), PC
            ),
            201,
        )

        five_minute_gap = api.create_transportation_run(
            _run(program["id"], "R7", "2027-06-14", "07:50", "08:20"), PC
        )
        validate_error(
            five_minute_gap, ApiErrorId.ROUTE_TURNAROUND_VIOLATION.value, 422
        )

        exactly_fifteen = validate_success(
            api.create_transportation_run(
                _run(program["id"], "R7", "2027-06-14", "08:00", "08:30"), PC
            ),
            201,
        )
        assert exactly_fifteen["status"] == "SCHEDULED"
        assert exactly_fifteen["seats_committed"] == 0

        _, meta = validate_paginated(
            api.list_program_transportation_runs(program["id"], PC, {"limit": 100})
        )
        assert meta["total_count"] == 2

    @pytest.mark.parametrize(
        "service_date",
        ["2027-06-30", "2027-06-19"],
    )
    def test_a_run_must_fall_on_an_instructional_date_of_its_program(
        self, api, service_date
    ):
        """A blacked-out Wednesday and a Saturday are both refused.

        Membership in the calendar is required: "The `service_date` must be an
        instructional date of that program — right weekday, not blacked out, not
        already cancelled, inside the session window — and a date failing any of those
        tests is rejected with `ERR_NOT_INSTRUCTIONAL_DATE`." Membership itself is
        derived: "Walk the inclusive range of dates from `session_start_date` through
        `session_end_date`; keep a date when its weekday name appears in
        `instructional_weekdays`, when it does not appear in `blackout_dates`, and when
        it does not appear in `cancelled_dates`."

        Design: Corner/errors/transportation_run_on_a_non_instructional_date_rejected
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(api)

        rejected = api.create_transportation_run(
            _run(program["id"], "RT-7", service_date, "07:00", "08:00", seats=6), PC
        )

        validate_error(rejected, ApiErrorId.NOT_INSTRUCTIONAL_DATE.value, 422)
        _, meta = validate_paginated(
            api.list_program_transportation_runs(program["id"], PC)
        )
        assert meta["total_count"] == 0

    def test_a_run_on_a_plain_instructional_tuesday_is_accepted(self, api):
        """2027-06-29 is a Tuesday inside the window and not blacked out.

        The same membership rule that rejects the other two dates accepts this one:
        "The `service_date` must be an instructional date of that program — right
        weekday, not blacked out, not already cancelled, inside the session window —
        and a date failing any of those tests is rejected with
        `ERR_NOT_INSTRUCTIONAL_DATE`." A newly scheduled run opens empty: "A run's own
        `status` starts at `SCHEDULED` and has exactly one exit."

        Design: Corner/errors/transportation_run_on_a_non_instructional_date_rejected
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(api)

        run = validate_success(
            api.create_transportation_run(
                _run(program["id"], "RT-7", "2027-06-29", "07:00", "08:00", seats=6), PC
            ),
            201,
        )

        assert run["status"] == "SCHEDULED"
        assert run["seats_committed"] == 0
        assert run["service_date"] == "2027-06-29"
        assert run["vehicle_capacity_seats"] == 6
        _, meta = validate_paginated(
            api.list_program_transportation_runs(program["id"], PC)
        )
        assert meta["total_count"] == 1


class TestSeatOccupancy:
    """Seats are derived per run from the non-terminal commitments naming it."""

    def test_a_full_bus_refuses_the_next_commitment_while_a_second_run_accepts_it(
        self, api
    ):
        """Capacity is counted per run, so the same request succeeds on a run with room.

        Occupancy is derived, not booked: "A run's `seats_committed` counts the service
        commitments naming that run in their `transportation_run_id` whose `status` is
        `PLANNED`, `ASSIGNED`, `ACTIVE` or `SUSPENDED`; commitments that have reached
        `COMPLETED` or `TERMINATED` have released their seat and no longer count." The
        gate is a strict ceiling: "When a commitment attempts to occupy a seat, the
        check is that the run's current `seats_committed` plus one does not exceed its
        `vehicle_capacity_seats`; a full bus is reported as
        `ERR_RUN_CAPACITY_EXCEEDED`." Seating happens as part of commitment creation:
        "When a `transportation_run_id` is supplied, the seat check of §3.3 runs and the
        run's `seats_committed` rises."

        Design: Corner/errors/second_commitment_on_a_full_transportation_run_rejected
        """
        fixtures.set_clock(api, CLOCK)
        eligible = fixtures.make_eligible_student(
            api, student_overrides={"iep_weekly_minutes_total": 350}
        )
        student = eligible["student"]
        program = fixtures.create_program(api)
        one_seat = validate_success(
            api.create_transportation_run(
                _run(program["id"], "RT-7", "2027-06-14", "07:00", "08:00", seats=1), PC
            ),
            201,
        )
        two_seats = validate_success(
            api.create_transportation_run(
                _run(program["id"], "RT-9", "2027-06-14", "07:00", "08:00", seats=2), PC
            ),
            201,
        )
        first = fixtures.create_commitment(
            api, program["id"], student["id"], transportation_run_id=one_seat["id"]
        )

        refused = api.create_commitment(
            factories.commitment_payload(
                program["id"],
                student["id"],
                service_type="SPEECH",
                iep_weekly_minutes=100,
                staffing_ratio="ONE_TO_ONE",
                transportation_run_id=one_seat["id"],
            ),
            CM,
        )
        validate_error(refused, ApiErrorId.RUN_CAPACITY_EXCEEDED.value, 422)

        second = validate_success(
            api.create_commitment(
                factories.commitment_payload(
                    program["id"],
                    student["id"],
                    service_type="SPEECH",
                    iep_weekly_minutes=100,
                    staffing_ratio="ONE_TO_ONE",
                    transportation_run_id=two_seats["id"],
                ),
                CM,
            ),
            201,
        )

        assert second["transportation_run_id"] == two_seats["id"]
        assert fixtures.refresh_run(api, program["id"], one_seat["id"])[
            "seats_committed"
        ] == 1
        assert fixtures.refresh_run(api, program["id"], two_seats["id"])[
            "seats_committed"
        ] == 1
        _, meta = validate_paginated(
            api.list_commitments(CM, {"transportation_run_id": one_seat["id"]})
        )
        assert meta["total_count"] == 1
        assert fixtures.refresh_commitment(api, first["id"])["status"] == "PLANNED"


class TestProgramLifecycle:
    """Locking, closing, and the operations each state does or does not offer."""

    def test_staffing_cannot_lock_until_one_commitment_reaches_assigned(self, api):
        """The lock fails with a bare `PLANNED` commitment and succeeds once it is staffed.

        The precondition is explicit: "Locking staffing (`PLANNING → STAFFING_LOCKED`)
        requires the program to be in `PLANNING` and requires at least one of its
        service commitments to have reached `ASSIGNED`; a program with no staffed
        commitment at all cannot lock, and the attempt returns `ERR_INVALID_STATE`."
        Reaching `ASSIGNED` is a side effect, not a client call: "The step out of
        `PLANNED` is not a client operation at all: the moment the commitment's first
        provider assignment reaches `ACTIVE`, the system advances `PLANNED → ASSIGNED`
        and increments the commitment's `version` by one."

        Design: Corner/state_machines/staffing_lock_requires_at_least_one_assigned_commitment
        """
        baseline = fixtures.setup_baseline(
            api,
            clock=CLOCK,
            with_assignment=False,
            with_open_program=False,
            with_active_commitment=False,
            with_canonical_logs=False,
        )
        program, commitment = baseline["program"], baseline["commitment"]
        commitment_version = commitment["version"]

        too_early = api.set_program_status(program["id"], "STAFFING_LOCKED", PC)
        validate_error(too_early, ApiErrorId.INVALID_STATE.value, 409)
        assert fixtures.refresh_program(api, program["id"])["status"] == "PLANNING"

        assignment = fixtures.create_assignment(
            api, commitment["id"], baseline["provider"]["id"], commitment_version
        )
        assert assignment["status"] == "ACTIVE"
        staffed = fixtures.refresh_commitment(api, commitment["id"])
        assert staffed["status"] == "ASSIGNED"
        assert staffed["version"] == commitment_version + 1

        locked = validate_success(
            api.set_program_status(program["id"], "STAFFING_LOCKED", PC)
        )
        assert locked["status"] == "STAFFING_LOCKED"

    def test_cancel_day_is_refused_while_the_program_is_still_planning(self, api):
        """The operation exists only as an `OPEN` self-transition.

        The state precondition comes first: "The program must be `OPEN`, and the date
        must currently be an instructional date of that program — a date already
        blacked out, already cancelled, on the wrong weekday, or outside the session
        window is refused with `ERR_NOT_INSTRUCTIONAL_DATE`." Check 9 supplies the
        code: "The target resource is in a state from which the requested transition
        exists, including the cross-entity state guards — otherwise
        `ERR_INVALID_STATE`." A refused cancellation must leave the calendar alone:
        "The cancellation appends the date to `cancelled_dates` and re-derives
        `instructional_days_count` and `instructional_week_count`."

        Design: Corner/state_machines/cancel_day_on_a_planning_program_rejected
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(api)

        refused = api.cancel_program_day(
            program["id"],
            {"service_date": "2027-06-14", "cancellation_reason": "WEATHER"},
            PC,
        )

        validate_error(refused, ApiErrorId.INVALID_STATE.value, 409)
        after = fixtures.refresh_program(api, program["id"])
        assert after["cancelled_dates"] == []
        assert after["instructional_days_count"] == 22
        assert after["status"] == "PLANNING"
        assert after["version"] == program["version"]

    def test_a_planning_program_with_no_commitments_closes_directly(self, api):
        """`PLANNING → CLOSED` carries no staffing precondition at all.

        The lifecycle names the transition: "The program lifecycle runs `PLANNING →
        STAFFING_LOCKED → OPEN → CLOSED`, driven by a `ProgramCoordinator` supplying a
        `target_status`." and the abandoned-session shortcut is declared separately:
        "Closing from `PLANNING` (`PLANNING → CLOSED`) is the abandoned-session case:
        every commitment of the program moves to `TERMINATED`, and the program's
        `version` increments." A transition read answers 200: "Operations that modify
        an existing resource, including every state-transition operation and every list
        or single-resource read, return HTTP 200."

        Design: Corner/state_machines/program_planning_to_closed_is_a_valid_transition
        """
        fixtures.set_clock(api, CLOCK)
        program = fixtures.create_program(
            api, name="Cancelled Summer ESY 2027", blackout_dates=factories.OMIT
        )

        closed = validate_success(api.set_program_status(program["id"], "CLOSED", PC))

        assert closed["status"] == "CLOSED"
        assert closed["version"] == program["version"] + 1


class TestDayCancellationCascade:
    """One cancelled day, four dependent hops, and one fan-out beside them."""

    def test_one_cancelled_day_reaches_the_log_the_commitment_and_the_student(self, api):
        """Link 1 to link 3: a synthetic 57-minute miss becomes an owed balance on the student.

        The cascade's first three links are declared as one chain: "First, for every
        commitment of that program whose `status` reads exactly `ACTIVE`, a service log
        is created for that `service_date` with outcome `MISSED_DISTRICT`,
        `minutes_scheduled` set to the commitment's pinned `daily_minutes`,
        `minutes_delivered` of zero, `miss_reason_code` set to the request's
        `cancellation_reason`, `status` `VERIFIED`, `generated_by`
        `SYSTEM_DAY_CANCELLATION`, and `provider_id` left null." then "Second, each new
        log recomputes its commitment's ledger, raising `compensable_owed_minutes` by
        that log's `minutes_scheduled` and incrementing the commitment's `version` by
        one." then "Third, each commitment whose `compensable_owed_minutes` moved
        recomputes its student's ledger, raising `pending_award_minutes` and
        incrementing the student's `version` by one." The alert only trips at a full
        hour: "The moment that total reaches sixty minutes — a full hour of undelivered,
        district-fault service — the boolean `esy_service_alert` flips to true,
        flagging the case for compensatory review; below sixty minutes it reads
        false." Beside the chain, the bus is stood down: "Every
        transportation run of that program whose `service_date` equals the cancelled
        date and whose `status` reads `SCHEDULED` moves to `CANCELLED`, as §3.3
        describes."

        Design: Difficulty/transitive_cascade/cancel_day_cascades_log_to_commitment_to_student_alert_threshold
        """
        baseline = fixtures.setup_baseline(api, clock=CLOCK, with_canonical_logs=False)
        program, commitment = baseline["program"], baseline["commitment"]
        student = baseline["student"]
        run = fixtures.schedule_run(
            api,
            program["id"],
            route_code="R7",
            service_date="2027-06-14",
            window_start_time="07:00",
            window_end_time="07:45",
            vehicle_capacity_seats=2,
        )
        assert commitment["daily_minutes"] == 57

        validate_success(
            api.cancel_program_day(
                program["id"],
                {"service_date": "2027-06-14", "cancellation_reason": "WEATHER"},
                PC,
            )
        )

        logs, meta = validate_paginated(
            api.list_service_logs(CM, {"commitment_id": commitment["id"]})
        )
        assert meta["total_count"] == 1
        synthetic = logs[0]
        assert synthetic["outcome"] == "MISSED_DISTRICT"
        assert synthetic["minutes_scheduled"] == 57
        assert synthetic["minutes_delivered"] == 0
        assert synthetic["generated_by"] == "SYSTEM_DAY_CANCELLATION"
        assert synthetic["provider_id"] is None
        assert synthetic["miss_reason_code"] == "WEATHER"
        assert synthetic["status"] == "VERIFIED"

        after_commitment = fixtures.refresh_commitment(api, commitment["id"])
        assert after_commitment["compensable_owed_minutes"] == 57
        assert after_commitment["delivered_minutes"] == 0

        after_student = fixtures.refresh_student(api, student["id"])
        assert after_student["pending_award_minutes"] == 57
        assert after_student["esy_service_alert"] is False

        assert (
            fixtures.refresh_run(api, program["id"], run["id"])["status"] == "CANCELLED"
        )

    def test_the_second_cancelled_day_trips_the_alert_and_leaves_the_plan_pinned(
        self, api
    ):
        """Link 4: 114 owed minutes crosses the hour, and the pinned plan never moves.

        The fourth link is conditional on the recomputed total: "Fourth, when the
        recomputed `pending_award_minutes` reaches sixty minutes or more, that student's
        `esy_service_alert` flips to true." The threshold itself is declared on the
        student: "The moment that total reaches sixty minutes — a full hour of
        undelivered, district-fault service — the boolean `esy_service_alert` flips to
        true, flagging the case for compensatory review; below sixty minutes it reads
        false." Each cancellation re-derives the
        calendar: "The cancellation appends the date to `cancelled_dates` and re-derives
        `instructional_days_count` and `instructional_week_count`." But it deliberately
        does not touch the commitment's plan: "And the pinned figures
        `planned_total_minutes`, `weekly_minutes_committed` and `daily_minutes` on
        existing commitments are pointedly **not** recomputed — the lost day shows up as
        owed minutes, not as a quietly reduced plan."

        Design: Difficulty/transitive_cascade/cancel_day_cascades_log_to_commitment_to_student_alert_threshold
        """
        baseline = fixtures.setup_baseline(api, clock=CLOCK, with_canonical_logs=False)
        program, commitment = baseline["program"], baseline["commitment"]
        student = baseline["student"]

        validate_success(
            api.cancel_program_day(
                program["id"],
                {"service_date": "2027-06-14", "cancellation_reason": "WEATHER"},
                PC,
            )
        )
        validate_success(
            api.cancel_program_day(
                program["id"],
                {"service_date": "2027-06-15", "cancellation_reason": "STAFF_ABSENCE"},
                PC,
            )
        )

        logs, meta = validate_paginated(
            api.list_service_logs(CM, {"commitment_id": commitment["id"]})
        )
        assert meta["total_count"] == 2
        assert [row["minutes_scheduled"] for row in logs] == [57, 57]

        after_commitment = fixtures.refresh_commitment(api, commitment["id"])
        assert after_commitment["compensable_owed_minutes"] == 114

        after_student = fixtures.refresh_student(api, student["id"])
        assert after_student["pending_award_minutes"] == 114
        assert after_student["esy_service_alert"] is True

        after_program = fixtures.refresh_program(api, program["id"])
        assert after_program["cancelled_dates"] == ["2027-06-14", "2027-06-15"]
        assert after_program["instructional_days_count"] == 20
        assert after_program["instructional_week_count"] == 6

        assert after_commitment["planned_total_minutes"] == 1376
        assert after_commitment["weekly_minutes_committed"] == 229
        assert after_commitment["daily_minutes"] == 57
