"""Rostering lanes against HAZWOPER certification and interval geometry, the
hours ledger, and the three-leg vehicle slot capacity."""

from test_helpers import (
    COORDINATOR,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_hours,
    assert_lane_assignment,
    create_lane_assignment_payload,
    create_staffer,
    inspect_event,
    read_event,
    read_lane_assignment,
    read_staffer,
    release_lane,
    setup_canon,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_get_staffer_with_unknown_id_returns_staffer_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/get_staffer_with_unknown_id_returns_staffer_not_found
    """
    response = api.get_staffer(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_STAFFER_NOT_FOUND, 404)


def test_get_lane_assignment_with_unknown_id_returns_lane_assignment_not_found(api):
    """PRD §2.5: "Path identifier resolution, evaluated left to right along the
    URL: each identifier in the path must resolve to a stored row before the next is
    considered. The failure code names the missing entity — `ERR_PROGRAM_NOT_FOUND`,
    `ERR_SITE_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`, `ERR_RESIDENT_NOT_FOUND`,
    `ERR_APPOINTMENT_NOT_FOUND`, `ERR_MATERIAL_CATEGORY_NOT_FOUND`,
    `ERR_STAFFER_NOT_FOUND`, `ERR_LANE_ASSIGNMENT_NOT_FOUND`,
    `ERR_CONTAINER_NOT_FOUND` or `ERR_MANIFEST_NOT_FOUND` — each at HTTP 404."

    Design: Corner/entities/get_lane_assignment_with_unknown_id_returns_lane_assignment_not_found
    """
    response = api.get_lane_assignment(NON_EXISTENT_UUID, COORDINATOR)
    validate_error(response, ApiErrorId.ERR_LANE_ASSIGNMENT_NOT_FOUND, 404)


def test_staffer_whose_hazwoper_lapsed_before_the_event_cannot_take_a_lane(api):
    """PRD §3.4: "The first is certification: the staffer's `hazwoper_expires_on`
    must be no earlier than the event's `event_date`, compared as plain date strings
    so that an expiry falling exactly on the event date passes, and the staffer's
    `status` must be `ACTIVE`. A lapsed or inactive staffer is rejected with
    `ERR_CERTIFICATION_EXPIRED`."

    Design: Corner/validations/lane_assignment_with_lapsed_certification_returns_error
    """
    ctx = setup_canon(6)
    staffer = create_staffer(
        ctx["program_id"], full_name="Lapsed Larry", hazwoper_expires_on="2026-09-11"
    )

    response = api.create_lane_assignment(
        create_lane_assignment_payload(ctx["event_id"], staffer["id"]), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_EXPIRED, 422)

    assert read_staffer(staffer["id"])["assigned_hours"] == 0
    assert read_event(ctx["event_id"])["open_lane_count"] == 0
    _, meta = validate_paginated(
        api.list_lane_assignments(COORDINATOR, params={"event_id": ctx["event_id"]})
    )
    assert meta["total_count"] == 0


def test_inactive_staffer_cannot_be_put_on_a_lane(api):
    """PRD §3.4: "A staffer also carries a `status` of `ACTIVE` or `INACTIVE`,
    defaulting to `ACTIVE`; an inactive staffer remains on the roster for the record
    but may not be put on a lane."
    PRD §3.4: "The first is certification: the staffer's `hazwoper_expires_on` must
    be no earlier than the event's `event_date`, compared as plain date strings so
    that an expiry falling exactly on the event date passes, and the staffer's
    `status` must be `ACTIVE`. A lapsed or inactive staffer is rejected with
    `ERR_CERTIFICATION_EXPIRED`."

    Design: Corner/entities/inactive_staffer_cannot_be_assigned_to_a_lane
    """
    ctx = setup_canon(6)
    staffer = create_staffer(
        ctx["program_id"],
        full_name="Benched Bea",
        role_code="TRAFFIC",
        status="INACTIVE",
    )
    assert staffer["status"] == "INACTIVE"

    response = api.create_lane_assignment(
        create_lane_assignment_payload(ctx["event_id"], staffer["id"]), COORDINATOR
    )
    validate_error(response, ApiErrorId.ERR_CERTIFICATION_EXPIRED, 422)

    assert read_staffer(staffer["id"])["assigned_hours"] == 0
    assert read_event(ctx["event_id"])["open_lane_count"] == 0


def test_shift_starting_inside_the_decontamination_buffer_is_refused(api):
    """PRD §3.4: "A staffer's existing commitment occupies a **half-open** interval
    running from its own `start_utc` up to but not including its own `end_utc`, and to
    that interval the system appends — and only appends, at the trailing end — a
    thirty-minute decontamination buffer."
    PRD §3.4: "Because the buffer hangs off the tail only, a new assignment ending
    exactly when an existing one begins is accepted, while a new assignment beginning
    exactly thirty minutes after an existing one ends is also accepted; beginning
    twenty-nine minutes after it ends is not."

    Design: Difficulty/resource_temporal_overlap/staffer_half_open_interval_with_trailing_decontamination_buffer
    """
    ctx = setup_canon(8, lane={"end_utc": "2026-09-12T12:00:00.000Z"})
    assert_hours(ctx["lane"]["duration_hours"], 4.0, "first shift")

    response = api.create_lane_assignment(
        create_lane_assignment_payload(
            ctx["event_id"],
            ctx["staffer_id"],
            lane_number=2,
            start_utc="2026-09-12T12:29:00.000Z",
            end_utc="2026-09-12T20:00:00.000Z",
        ),
        COORDINATOR,
    )
    validate_error(response, ApiErrorId.ERR_STAFFER_INTERVAL_CONFLICT, 409)


def test_shift_starting_exactly_on_the_buffered_endpoint_is_accepted(api):
    """PRD §3.4: "Because the buffer hangs off the tail only, a new assignment
    ending exactly when an existing one begins is accepted, while a new assignment
    beginning exactly thirty minutes after an existing one ends is also accepted;
    beginning twenty-nine minutes after it ends is not."
    PRD §3.4: "And an event's `open_lane_count` is the number of **distinct**
    `lane_number` values across its `ACTIVE` assignments — three people rotating
    through lane 2 across the day contribute one open lane, not three."

    Design: Difficulty/resource_temporal_overlap/staffer_half_open_interval_with_trailing_decontamination_buffer
    """
    ctx = setup_canon(8, lane={"end_utc": "2026-09-12T12:00:00.000Z"})

    response = api.create_lane_assignment(
        create_lane_assignment_payload(
            ctx["event_id"],
            ctx["staffer_id"],
            lane_number=2,
            start_utc="2026-09-12T12:30:00.000Z",
            end_utc="2026-09-12T20:00:00.000Z",
        ),
        COORDINATOR,
    )
    second = validate_success(response, 201)

    assert_lane_assignment(second)
    assert_hours(second["duration_hours"], 7.5, "second shift")
    assert_hours(read_staffer(ctx["staffer_id"])["assigned_hours"], 11.5, "assigned_hours")

    event = read_event(ctx["event_id"])
    assert event["open_lane_count"] == 2
    assert_hours(event["certified_staff_hours"], 11.5, "certified_staff_hours")


def test_rostering_a_shift_loads_the_hours_ledger_and_the_derived_capacity(api):
    """PRD §3.4: "A staffer's `assigned_hours` is the sum of `duration_hours` across
    their `ACTIVE` assignments, rounded half up to two decimal places; released
    assignments are retained as history and contribute nothing."
    PRD §3.4: "An event's `staffing_cost_cents` is `certified_staff_hours` multiplied
    by the program's `staff_hourly_rate_cents`, rounded half up to whole cents."
    PRD §3.4: "The second leg is staffing. Each vehicle consumes a quarter of a
    staff-hour — fifteen minutes of certified labour per car — so the staffing leg is
    `certified_staff_hours` divided by 0.25, with any fractional vehicle discarded."

    Design: Difficulty/compensating_invariant/lane_release_restores_staffer_hour_ledger
    """
    ctx = setup_canon(7)
    inspected = inspect_event(ctx["event_id"], "PASS", finding_code="PAD-OK")
    assert inspected["slot_capacity"] == 0, "No staffed lane yields no capacity"
    assert ctx["staffer"]["assigned_hours"] == 0

    lane = validate_success(
        api.create_lane_assignment(
            create_lane_assignment_payload(
                ctx["event_id"], ctx["staffer_id"], end_utc="2026-09-12T12:00:00.000Z"
            ),
            COORDINATOR,
        ),
        201,
    )
    assert_hours(lane["duration_hours"], 4.0, "shift duration")
    assert_hours(read_staffer(ctx["staffer_id"])["assigned_hours"], 4.0, "assigned_hours")

    event = read_event(ctx["event_id"])
    assert_hours(event["certified_staff_hours"], 4.0, "certified_staff_hours")
    assert event["staffing_cost_cents"] == 16800
    assert event["open_lane_count"] == 1
    assert event["slot_capacity"] == 16, "min(144 lane, 16 staffing, 50 containment)"


def test_releasing_a_shift_returns_every_hour_it_had_taken(api):
    """PRD §3.4: "Releasing an assignment is the compensating action. An
    `EventCoordinator` releases it with an optional `released_reason`, the
    assignment's `status` becomes `RELEASED`, the staffer's `assigned_hours` drops by
    that assignment's `duration_hours`, and the event's `open_lane_count`,
    `certified_staff_hours`, `staffing_cost_cents`, `slot_capacity` and
    `projected_cost_per_participant_cents` are all recomputed."
    PRD §3.4: "A staffer's `assigned_hours` is the sum of `duration_hours` across
    their `ACTIVE` assignments, rounded half up to two decimal places; released
    assignments are retained as history and contribute nothing."

    Design: Difficulty/compensating_invariant/lane_release_restores_staffer_hour_ledger
    """
    ctx = setup_canon(7)
    inspect_event(ctx["event_id"], "PASS", finding_code="PAD-OK")
    lane = validate_success(
        api.create_lane_assignment(
            create_lane_assignment_payload(
                ctx["event_id"], ctx["staffer_id"], end_utc="2026-09-12T12:00:00.000Z"
            ),
            COORDINATOR,
        ),
        201,
    )

    released = release_lane(lane["id"])
    assert released["status"] == "RELEASED"

    assert_hours(read_staffer(ctx["staffer_id"])["assigned_hours"], 0.0, "assigned_hours")
    event = read_event(ctx["event_id"])
    assert_hours(event["certified_staff_hours"], 0.0, "certified_staff_hours")
    assert event["staffing_cost_cents"] == 0
    assert event["open_lane_count"] == 0
    assert event["slot_capacity"] == 0

    kept = read_lane_assignment(lane["id"])
    assert_hours(kept["duration_hours"], 4.0, "released shift duration")


def test_slot_capacity_settles_on_the_smallest_of_its_three_legs(api):
    """PRD §3.4: "Three independent legs are each evaluated in full, and the binding
    constraint is the smallest of the three."
    PRD §3.4: "Worked through: a single open lane on a twelve-hour window with one
    twelve-hour certified assignment at a site rated 2000 litres yields a lane leg of
    one times twelve times 12.00, or 144 vehicles; a staffing leg of 12.00 divided by
    0.25, or 48 vehicles; and a base containment figure of 2000 divided by 40, or 50
    vehicles. On a compliant pad the containment leg is 50 and `slot_capacity` settles
    at 48, the staffing leg binding."

    Design: Difficulty/combinatorial_formula/slot_capacity_three_leg_minimum_mode_a
    """
    ctx = setup_canon(9)
    event = ctx["event"]

    assert_hours(event["certified_staff_hours"], 12.0, "certified_staff_hours")
    assert event["containment_status"] == "COMPLIANT"
    assert event["slot_capacity"] == 48, "min(144 lane, 48 staffing, 50 containment)"
    assert event["staffing_cost_cents"] == 50400


def test_containment_leg_zeroes_then_halves_the_capacity(api):
    """PRD §3.4: "That base is then modulated by the event's containment axis: when
    the axis reads `COMPLIANT` the base stands unmodified; when it reads `REMEDIATED`
    the base is halved and the fraction discarded, because a remediated pad is run at
    half throughput as a precaution; and when it reads `PENDING_INSPECTION` or
    `DEFICIENT` the containment leg is zero, which drives the whole capacity to zero
    regardless of how many lanes are open."
    PRD §3.4: "On a remediated pad the containment leg halves to 25 and
    `slot_capacity` settles at 25 instead."

    Design: Difficulty/combinatorial_formula/slot_capacity_three_leg_minimum_mode_a
    """
    ctx = setup_canon(9)

    deficient = inspect_event(ctx["event_id"], "FAIL", finding_code="BERM-CRACK")
    assert deficient["containment_status"] == "DEFICIENT"
    assert deficient["slot_capacity"] == 0

    remediated = inspect_event(
        ctx["event_id"],
        "PASS",
        finding_code="BERM-PATCHED",
        remediation_note="Berm re-sealed and pressure tested",
    )
    assert remediated["containment_status"] == "REMEDIATED"
    assert remediated["slot_capacity"] == 25, "min(144, 48, floor(50 * 0.5))"
    assert remediated["lifecycle_status"] == "SITE_CONFIRMED"
