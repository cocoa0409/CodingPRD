"""Station siting, operating-hours intervals, inspector standing and training cascades."""
from test_helpers import (
    ApiErrorId,
    PROGRAM_ADMIN,
    add_watercraft,
    api_client,
    assert_instant_equals,
    assert_training_record,
    create_and_open_station,
    create_water_body,
    enroll_inspector,
    fetch_inspector,
    fetch_station,
    fetch_station_hours,
    inspection_record_payload,
    log_training,
    make_inspector_headers,
    move_inspector,
    move_station,
    set_clock,
    setup_program,
    station_hours_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


def _open_record_call(station_id, watercraft_id, arrived_at, inspector_id):
    return api_client.create_inspection_record(
        inspection_record_payload(station_id, watercraft_id, arrived_at),
        make_inspector_headers(inspector_id),
    )


def _records_for(watercraft_id):
    data, _meta = validate_paginated(
        api_client.list_inspection_records(
            PROGRAM_ADMIN, params={"watercraft_id": watercraft_id}
        )
    )
    return data


class TestRecordCreationDependsOnStationBeingOpen:
    """The defect lives on the station row, and only OPEN will do."""

    def test_a_planned_station_refuses_the_arrival(self):
        """Everything else about the request is valid; the station is still PLANNED.

        PRD: "The station's `status` must be `OPEN`, not merely planned or
        suspended, or the request is rejected with `ERR_STATION_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/record_creation_depends_on_station_being_open
        """
        ctx = setup_program(risk_tier="MODERATE", open_station=False)
        vessel = add_watercraft(ctx)
        assert ctx["station"]["status"] == "PLANNED"
        station_version = ctx["station"]["version"]
        set_clock("2026-08-05T09:00:00Z")

        response = _open_record_call(
            ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z",
            ctx["inspector_a"]["id"],
        )

        validate_error(response, ApiErrorId.ERR_STATION_NOT_OPEN)
        station = fetch_station(ctx["station"]["id"])
        assert station["status"] == "PLANNED"
        assert station["version"] == station_version
        assert _records_for(vessel["id"]) == []

    def test_opening_the_station_admits_the_identical_arrival(self):
        """One transition on the other row is the whole remedy.

        PRD: "A freshly opened record is deliberately empty of judgement.
        `inspection_status` — one of `INITIATED`, `SCREENED`, `PASSED`,
        `DECON_REQUIRED`, `DECON_COMPLETED`, `DECON_FAILED_ABANDONED` or `REFUSED`
        — starts `INITIATED`"

        Design: Difficulty/cross_entity_state_dependency/record_creation_depends_on_station_being_open
        """
        ctx = setup_program(risk_tier="MODERATE", open_station=False)
        vessel = add_watercraft(ctx)
        set_clock("2026-08-05T09:00:00Z")
        move_station(ctx["station"]["id"], "OPEN")

        record = validate_success(
            _open_record_call(
                ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z",
                ctx["inspector_a"]["id"],
            ),
            201,
        )

        assert record["inspection_status"] == "INITIATED"
        assert record["station_id"] == ctx["station"]["id"]

    def test_a_suspended_station_is_refused_exactly_like_a_planned_one(self):
        """The dependency is on OPEN, not merely on not-being-CLOSED.

        PRD: "The station's `status` must be `OPEN`, not merely planned or
        suspended, or the request is rejected with `ERR_STATION_NOT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/record_creation_depends_on_station_being_open
        """
        ctx = setup_program(risk_tier="MODERATE", open_station=False)
        vessel = add_watercraft(ctx)
        set_clock("2026-08-05T09:00:00Z")
        move_station(ctx["station"]["id"], "OPEN")
        move_station(ctx["station"]["id"], "SUSPENDED")

        response = _open_record_call(
            ctx["station"]["id"], vessel["id"], "2026-08-05T09:00:00Z",
            ctx["inspector_a"]["id"],
        )

        validate_error(response, ApiErrorId.ERR_STATION_NOT_OPEN)
        assert _records_for(vessel["id"]) == []


def _station_with_a_morning_window():
    """One station whose only window is [2026-08-01T06:00:00Z, 2026-08-01T14:00:00Z)."""
    return setup_program(
        risk_tier="LOW",
        opens_at="2026-08-01T06:00:00Z",
        closes_at="2026-08-01T14:00:00Z",
        staffing_level="SINGLE",
    )


def _add_window_call(station_id, opens_at, closes_at, staffing_level=None):
    overrides = {"opens_at": opens_at, "closes_at": closes_at}
    if staffing_level is not None:
        overrides["staffing_level"] = staffing_level
    return api_client.create_station_hours(
        station_id, station_hours_payload(**overrides), PROGRAM_ADMIN
    )


class TestStationHoursWindowsAreHalfOpen:
    """Operating windows are [opens_at, closes_at), so adjacency is allowed."""

    def test_a_window_opening_exactly_when_another_closes_is_accepted(self):
        """Adjacency at a shared endpoint is not an overlap.

        PRD: "Windows that merely touch at an endpoint — one closing at the exact
        instant the next opens — are accepted, which is how a station declares
        back-to-back shifts."

        Design: Difficulty/resource_temporal_overlap/station_hours_windows_are_half_open_so_adjacency_is_allowed
        """
        ctx = _station_with_a_morning_window()

        window = validate_success(
            _add_window_call(
                ctx["station"]["id"], "2026-08-01T14:00:00Z", "2026-08-01T20:00:00Z",
                "DOUBLE",
            ),
            201,
        )

        assert_instant_equals(window["opens_at"], "2026-08-01T14:00:00Z", "opens_at")
        assert_instant_equals(window["closes_at"], "2026-08-01T20:00:00Z", "closes_at")
        assert window["staffing_level"] == "DOUBLE"
        assert len(fetch_station_hours(ctx["station"]["id"])) == 2

    def test_a_window_overlapping_by_one_minute_is_refused(self):
        """Retreating the start by a minute makes both comparisons true.

        PRD: "Windows at the same station must not overlap: a new window collides
        with an existing one when the new window's `opens_at` falls strictly
        before the existing window's `closes_at` *and* the existing window's
        `opens_at` falls strictly before the new window's `closes_at`, and a
        collision is rejected with `ERR_HOURS_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/station_hours_windows_are_half_open_so_adjacency_is_allowed
        """
        ctx = _station_with_a_morning_window()

        response = _add_window_call(
            ctx["station"]["id"], "2026-08-01T13:59:00Z", "2026-08-01T20:00:00Z"
        )

        validate_error(response, ApiErrorId.ERR_HOURS_WINDOW_OVERLAP)
        assert len(fetch_station_hours(ctx["station"]["id"])) == 1

    def test_adjacency_chains_a_second_time(self):
        """Three back-to-back windows all coexist.

        PRD: "Windows that merely touch at an endpoint — one closing at the exact
        instant the next opens — are accepted, which is how a station declares
        back-to-back shifts."

        Design: Difficulty/resource_temporal_overlap/station_hours_windows_are_half_open_so_adjacency_is_allowed
        """
        ctx = _station_with_a_morning_window()
        validate_success(
            _add_window_call(
                ctx["station"]["id"], "2026-08-01T14:00:00Z", "2026-08-01T20:00:00Z"
            ),
            201,
        )

        third = validate_success(
            _add_window_call(
                ctx["station"]["id"], "2026-08-01T20:00:00Z", "2026-08-02T02:00:00Z"
            ),
            201,
        )

        assert_instant_equals(third["opens_at"], "2026-08-01T20:00:00Z", "opens_at")
        assert len(fetch_station_hours(ctx["station"]["id"])) == 3

    def test_a_duplicate_window_is_refused(self):
        """An identical window overlaps itself on both comparisons.

        PRD: "Windows at the same station must not overlap: a new window collides
        with an existing one when the new window's `opens_at` falls strictly
        before the existing window's `closes_at` *and* the existing window's
        `opens_at` falls strictly before the new window's `closes_at`, and a
        collision is rejected with `ERR_HOURS_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/station_hours_windows_are_half_open_so_adjacency_is_allowed
        """
        ctx = _station_with_a_morning_window()

        response = _add_window_call(
            ctx["station"]["id"], "2026-08-01T06:00:00Z", "2026-08-01T14:00:00Z"
        )

        validate_error(response, ApiErrorId.ERR_HOURS_WINDOW_OVERLAP)
        assert len(fetch_station_hours(ctx["station"]["id"])) == 1


def _suspended_inspector_at_the_closing_instant():
    """The season window closes at 2026-10-01T00:00:00Z and Ada is SUSPENDED."""
    ctx = setup_program(risk_tier="LOW")
    vessel = add_watercraft(ctx)
    move_inspector(ctx["inspector_a"]["id"], "SUSPENDED")
    set_clock("2026-10-01T00:00:00Z")
    return ctx, vessel


class TestInspectorStandingBeatsOperatingHours:
    """Standing is announced before the temporal window check."""

    def test_the_suspended_inspector_is_reported_before_the_closed_window(self):
        """Both rules are violated; the standing rule answers.

        PRD: "The acting inspector is not supplied in the body — `inspector_id` is
        copied from `X-User-ID`, and the acting inspector must be in `ACTIVE`
        standing or the request fails with `ERR_INSPECTOR_NOT_ACTIVE`."

        Design: Difficulty/priority_pair_validation_conflict/inspector_status_check_beats_operating_hours_check_on_record_creation
        """
        ctx, vessel = _suspended_inspector_at_the_closing_instant()

        response = _open_record_call(
            ctx["station"]["id"], vessel["id"], "2026-10-01T00:00:00Z",
            ctx["inspector_a"]["id"],
        )

        validate_error(response, ApiErrorId.ERR_INSPECTOR_NOT_ACTIVE)
        assert _records_for(vessel["id"]) == []

    def test_reinstating_the_inspector_exposes_the_closed_window(self):
        """An arrival at exactly closes_at is outside the half-open window.

        PRD: "an arrival at exactly `opens_at` is inside the window, an arrival at
        exactly `closes_at` is not, and a station that has declared no windows at
        all rejects every arrival. A miss here is
        `ERR_STATION_OUTSIDE_OPERATING_HOURS`."

        Design: Difficulty/priority_pair_validation_conflict/inspector_status_check_beats_operating_hours_check_on_record_creation
        """
        ctx, vessel = _suspended_inspector_at_the_closing_instant()
        reinstated = move_inspector(ctx["inspector_a"]["id"], "ACTIVE")
        assert reinstated["status"] == "ACTIVE"

        response = _open_record_call(
            ctx["station"]["id"], vessel["id"], "2026-10-01T00:00:00Z",
            ctx["inspector_a"]["id"],
        )

        validate_error(response, ApiErrorId.ERR_STATION_OUTSIDE_OPERATING_HOURS)
        assert _records_for(vessel["id"]) == []

    def test_one_second_inside_the_window_the_arrival_is_accepted(self):
        """2026-09-30T23:59:59Z is still inside [opens_at, closes_at).

        PRD: "And `arrived_at` must fall inside at least one of the station's
        declared operating windows, evaluated as the half-open interval from
        `opens_at` up to but not including `closes_at`"

        Design: Difficulty/priority_pair_validation_conflict/inspector_status_check_beats_operating_hours_check_on_record_creation
        """
        ctx, vessel = _suspended_inspector_at_the_closing_instant()
        move_inspector(ctx["inspector_a"]["id"], "ACTIVE")

        record = validate_success(
            _open_record_call(
                ctx["station"]["id"], vessel["id"], "2026-09-30T23:59:59Z",
                ctx["inspector_a"]["id"],
            ),
            201,
        )

        assert record["inspection_status"] == "INITIATED"
        assert_instant_equals(
            record["arrived_at"], "2026-09-30T23:59:59Z", "arrived_at"
        )


def _station_one_certified_inspector_short():
    """A station with one DECON_CERTIFIED inspector and one LEVEL_1 at 24.00 hours.

    The LEVEL_1 inspector also carries a failed 20-hour module, which must credit
    nothing.

    The station is hot-water capable, because `decon_service_available` "is true
    exactly when the station's `certified_inspector_count` has reached two *and*
    `hot_water_capable` is true" — the staffing count alone cannot turn it on.
    """
    set_clock("2026-08-01T00:00:00Z")
    water_body = create_water_body(risk_tier="MODERATE")
    station = create_and_open_station(
        water_body["id"], staffing_level="SINGLE", hot_water_capable=True
    )
    technician = enroll_inspector(
        station["id"], credited_hours=40, decon_endorsement=True,
        full_name="Bo Tech", completed_at="2026-08-01T00:00:00Z",
    )
    verifier = enroll_inspector(
        station["id"], credited_hours=24, full_name="Cy Verify",
        completed_at="2026-08-01T00:00:00Z",
    )
    log_training(verifier["id"], 20, False, completed_at="2026-08-01T00:00:00Z")
    set_clock("2026-08-02T00:00:00Z")
    return {"station": station, "technician": technician, "verifier": verifier}


class TestTrainingRecordCascadesToDeconServiceAvailability:
    """A credited module promotes the inspector and re-derives the station's service."""

    def test_the_credited_hours_exclude_the_failed_module_and_lift_the_level(self):
        """24.00 plus 16 reaches exactly 40.00, and the failed 20 hours credit nothing.

        PRD: "`training_hours_total` is the sum of `hours` over that inspector's
        training records whose `passed` is true, rounded half up to two decimal
        places; modules with `passed` false credit zero hours and are excluded from
        the sum entirely."  PRD: "from 40 credited hours upward the level is
        `LEVEL_2` when the inspector has no decontamination endorsement, and
        `DECON_CERTIFIED` when they do."

        Design: Difficulty/transitive_cascade/training_record_cascades_to_station_decon_service_availability
        """
        program = _station_one_certified_inspector_short()
        before = fetch_inspector(program["verifier"]["id"])
        assert float(before["training_hours_total"]) == 24.00
        assert before["certification_level"] == "LEVEL_1"

        record = log_training(
            program["verifier"]["id"], 16, True, completed_at="2026-08-02T00:00:00Z"
        )

        assert_training_record(record)
        assert float(record["hours"]) == 16
        assert record["passed"] is True
        after = fetch_inspector(program["verifier"]["id"])
        assert float(after["training_hours_total"]) == 40.00
        assert after["certification_level"] == "LEVEL_2"

    def test_the_promotion_makes_the_station_offer_decontamination(self):
        """The second certified inspector is what turns the service on.

        PRD: "If the level lands at `LEVEL_2` or `DECON_CERTIFIED`, the promotion
        also flows through to the home station: `certified_inspector_count` — the
        number of that station's inspectors who are simultaneously in `ACTIVE`
        standing and at level `LEVEL_2` or `DECON_CERTIFIED` — is recomputed, and
        `decon_service_available` is recomputed from the new count."

        Design: Difficulty/transitive_cascade/training_record_cascades_to_station_decon_service_availability
        """
        program = _station_one_certified_inspector_short()
        before = fetch_station(program["station"]["id"])
        assert before["certified_inspector_count"] == 1
        assert before["decon_service_available"] is False

        log_training(
            program["verifier"]["id"], 16, True, completed_at="2026-08-02T00:00:00Z"
        )

        after = fetch_station(program["station"]["id"])
        assert after["certified_inspector_count"] == 2
        assert after["decon_service_available"] is True

    def test_the_promotion_does_not_restamp_the_certification_expiry(self):
        """Only the promotion out of TRAINEE stamps certification_expires_at.

        PRD: "When a credited module lifts a `PROBATIONARY` inspector's
        `certification_level` above `TRAINEE`, the service moves them
        `PROBATIONARY → ACTIVE` in the same request, stamps
        `certification_expires_at` at the current logical time plus 8,760 hours —
        one 365-day year — and advances the inspector's `version` by 1."

        Design: Difficulty/transitive_cascade/training_record_cascades_to_station_decon_service_availability
        """
        program = _station_one_certified_inspector_short()

        log_training(
            program["verifier"]["id"], 16, True, completed_at="2026-08-02T00:00:00Z"
        )

        verifier = fetch_inspector(program["verifier"]["id"])
        assert verifier["status"] == "ACTIVE"
        assert_instant_equals(
            verifier["certification_expires_at"], "2027-08-01T00:00:00Z",
            "certification_expires_at",
        )
        technician = fetch_inspector(program["technician"]["id"])
        assert technician["certification_level"] == "DECON_CERTIFIED"
        assert float(technician["training_hours_total"]) == 40.00
