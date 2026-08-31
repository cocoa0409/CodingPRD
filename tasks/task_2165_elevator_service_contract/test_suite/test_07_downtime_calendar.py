"""The downtime calendar: two overlap rules, conserved minutes and project windows."""
from test_helpers import (
    ApiErrorId,
    add_window,
    assert_downtime_window,
    plan_and_approve_project,
    read_car,
    read_project,
    read_window,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_a_modernization_window_inside_the_inter_type_buffer_is_rejected(api):
    """PRD §3.5: "The rule then adds a buffer that applies only between windows of
    *different* `window_type`: if the existing window's type differs from the
    candidate's and the gap between the two spans is less than **two hours**, the
    candidate is rejected with the same `ERR_DOWNTIME_WINDOW_CONFLICT`. In other
    words, a repair window and a modernization window on one car must be separated
    by at least 120 minutes of clear air, while two repair windows may touch."

    Design: Difficulty/resource_temporal_overlap/car_downtime_half_open_adjacency_allowed_but_inter_type_buffer_enforced
    """
    program = setup_program(
        ["CAR-R1"],
        building_name="Rho Tower",
        building_address="17 Rho St",
        building_manager_user_id="bm-r",
        contractor_user_id="sc-r",
    )
    car_id = program.car_id()
    existing = add_window(
        program, car_id, "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z", "REPAIR"
    )
    assert existing["duration_minutes"] == 240

    validate_error(
        api.create_downtime_window(
            {
                "car_id": car_id,
                "window_type": "MODERNIZATION",
                "window_start": "2026-09-10T13:00:00Z",
                "window_end": "2026-09-10T15:00:00Z",
            },
            program.contractor_headers,
        ),
        ApiErrorId.ERR_DOWNTIME_WINDOW_CONFLICT.value,
    )
    assert read_car(car_id)["scheduled_downtime_minutes"] == 240


def test_same_type_windows_may_abut_with_a_zero_minute_gap(api):
    """PRD §3.5: "Because the intersection is strictly half-open, a candidate that
    begins at the exact instant an existing window ends does not collide, and
    neither does one that ends at the exact instant an existing window begins —
    same-type windows may abut with a zero-minute gap."
    PRD §3.5: "The car's `scheduled_downtime_minutes` is, at all times, the sum of
    `duration_minutes` over that car's windows whose `status` is `SCHEDULED` or
    `COMPLETED`."

    Design: Difficulty/resource_temporal_overlap/car_downtime_half_open_adjacency_allowed_but_inter_type_buffer_enforced
    """
    program = setup_program(
        ["CAR-R1"],
        building_name="Rho Tower",
        building_address="17 Rho St",
        building_manager_user_id="bm-r",
        contractor_user_id="sc-r",
    )
    car_id = program.car_id()
    first = add_window(
        program, car_id, "2026-09-10T08:00:00Z", "2026-09-10T12:00:00Z", "REPAIR"
    )

    abutting = validate_success(
        api.create_downtime_window(
            {
                "car_id": car_id,
                "window_type": "REPAIR",
                "window_start": "2026-09-10T12:00:00Z",
                "window_end": "2026-09-10T14:00:00Z",
            },
            program.contractor_headers,
        ),
        201,
    )
    assert_downtime_window(abutting)
    assert abutting["status"] == "SCHEDULED"
    assert abutting["duration_minutes"] == 120
    assert read_window(first["id"])["duration_minutes"] == 240
    assert read_car(car_id)["scheduled_downtime_minutes"] == 360

    rows, meta = validate_paginated(
        api.list_downtime_windows(program.admin_headers, {"car_id": car_id})
    )
    assert meta["total_count"] == 2, f"expected 2 windows, got {meta['total_count']}"
    assert len(rows) == 2


def test_modernization_capacity_rejects_a_shared_calendar_date_across_cars(api):
    """PRD §3.5: "A candidate whose `window_type` is `MODERNIZATION` occupies every
    calendar date from the date of its `window_start` through the date of the
    instant one minute before its `window_end`, inclusive at both ends. For every
    *other* car on the same contract, and for every modernization window on that car
    whose `status` is `SCHEDULED` or `COMPLETED`, the same closed date range is
    computed. If the candidate's date range shares even a single calendar date with
    any of them, the reservation is rejected with
    `ERR_CONTRACT_MODERNIZATION_CAPACITY`, because the program tolerates **at most
    one car under modernization at a time** across the whole contract."

    Design: Difficulty/resource_temporal_overlap/contract_modernization_capacity_uses_closed_calendar_dates_across_cars
    """
    program = setup_program(
        ["CAR-S1", "CAR-S2"],
        building_name="Sigma Court",
        building_address="18 Sigma Ln",
        building_manager_user_id="bm-s",
        contractor_user_id="sc-s",
    )
    project = plan_and_approve_project(
        program,
        title="Two-car modernization",
        budget_cents=15_000_000,
        target_completion_date="2026-10-01",
    )
    first = add_window(
        program,
        program.car_id(0),
        "2026-09-10T08:00:00Z",
        "2026-09-12T06:00:00Z",
        "MODERNIZATION",
        project["id"],
    )
    assert first["duration_minutes"] == 2760

    validate_error(
        api.create_downtime_window(
            {
                "car_id": program.car_id(1),
                "window_type": "MODERNIZATION",
                "window_start": "2026-09-12T20:00:00Z",
                "window_end": "2026-09-14T08:00:00Z",
                "project_id": project["id"],
            },
            program.admin_headers,
        ),
        ApiErrorId.ERR_CONTRACT_MODERNIZATION_CAPACITY.value,
    )

    assert read_car(program.car_id(1))["scheduled_downtime_minutes"] == 0
    assert read_project(project["id"])["window_count"] == 1


def test_modernization_window_starting_the_next_calendar_date_is_accepted(api):
    """PRD §3.5: "A candidate whose `window_type` is `MODERNIZATION` occupies every
    calendar date from the date of its `window_start` through the date of the
    instant one minute before its `window_end`, inclusive at both ends. For every
    *other* car on the same contract, and for every modernization window on that car
    whose `status` is `SCHEDULED` or `COMPLETED`, the same closed date range is
    computed. If the candidate's date range shares even a single calendar date with
    any of them, the reservation is rejected with
    `ERR_CONTRACT_MODERNIZATION_CAPACITY`, because the program tolerates **at most
    one car under modernization at a time** across the whole contract."
    PRD §3.5: "Creating it adds that `duration_minutes` to the car's
    `scheduled_downtime_minutes`, increments the owning project's `window_count` by
    1 when a `project_id` was supplied, and increments the car's `version` by 1."

    Design: Difficulty/resource_temporal_overlap/contract_modernization_capacity_uses_closed_calendar_dates_across_cars
    """
    program = setup_program(
        ["CAR-S1", "CAR-S2"],
        building_name="Sigma Court",
        building_address="18 Sigma Ln",
        building_manager_user_id="bm-s",
        contractor_user_id="sc-s",
    )
    project = plan_and_approve_project(
        program,
        title="Two-car modernization",
        budget_cents=15_000_000,
        target_completion_date="2026-10-01",
    )
    first = add_window(
        program,
        program.car_id(0),
        "2026-09-10T08:00:00Z",
        "2026-09-12T06:00:00Z",
        "MODERNIZATION",
        project["id"],
    )

    second = validate_success(
        api.create_downtime_window(
            {
                "car_id": program.car_id(1),
                "window_type": "MODERNIZATION",
                "window_start": "2026-09-13T00:00:00Z",
                "window_end": "2026-09-14T08:00:00Z",
                "project_id": project["id"],
            },
            program.admin_headers,
        ),
        201,
    )
    assert second["status"] == "SCHEDULED"
    assert second["duration_minutes"] == 1920
    assert read_car(program.car_id(1))["scheduled_downtime_minutes"] == 1920
    assert read_project(project["id"])["window_count"] == 2
    assert read_window(first["id"])["duration_minutes"] == 2760


def test_reserving_a_window_adds_its_minutes_and_counts_it_on_the_project(api):
    """PRD §3.5: "The window is created in `SCHEDULED` with `reschedule_count` 0 and
    a derived `duration_minutes` equal to the number of whole minutes from
    `window_start` to `window_end`. Creating it adds that `duration_minutes` to the
    car's `scheduled_downtime_minutes`, increments the owning project's
    `window_count` by 1 when a `project_id` was supplied, and increments the car's
    `version` by 1."

    Design: Difficulty/compensating_invariant/downtime_cancel_conserves_car_scheduled_minutes_exactly
    """
    program = setup_program(
        ["CAR-U1"],
        building_name="Tau Place",
        building_address="19 Tau Rd",
        building_manager_user_id="bm-u",
        contractor_user_id="sc-u",
    )
    car_id = program.car_id()
    project = plan_and_approve_project(
        program,
        title="Cab interior refresh",
        budget_cents=2_500_000,
        target_completion_date="2026-09-30",
    )
    assert read_car(car_id)["scheduled_downtime_minutes"] == 0
    assert read_project(project["id"])["window_count"] == 0

    window = add_window(
        program,
        car_id,
        "2026-09-10T08:00:00Z",
        "2026-09-12T08:00:00Z",
        "MODERNIZATION",
        project["id"],
    )
    assert window["status"] == "SCHEDULED"
    assert window["reschedule_count"] == 0
    assert window["duration_minutes"] == 2880
    assert read_car(car_id)["scheduled_downtime_minutes"] == 2880
    assert read_project(project["id"])["window_count"] == 1


def test_cancelling_a_window_restores_the_pre_creation_minutes_exactly(api):
    """PRD §3.5: "This is a conserved quantity: cancelling a `SCHEDULED` window
    subtracts exactly its `duration_minutes` and restores the pre-creation figure
    exactly, while a window that has already moved to `RESCHEDULE_REQUIRED` had its
    minutes removed at that moment and its later cancellation therefore leaves the
    total unchanged."
    PRD §3.5: "Either way the window moves to `CANCELLED`, the car's
    `scheduled_downtime_minutes` is brought back into line with the definition
    above, the owning project's `window_count` is decremented by 1 when `project_id`
    is set, and the car's `version` is incremented by 1."

    Design: Difficulty/compensating_invariant/downtime_cancel_conserves_car_scheduled_minutes_exactly
    """
    program = setup_program(
        ["CAR-U1"],
        building_name="Tau Place",
        building_address="19 Tau Rd",
        building_manager_user_id="bm-u",
        contractor_user_id="sc-u",
    )
    car_id = program.car_id()
    project = plan_and_approve_project(
        program,
        title="Cab interior refresh",
        budget_cents=2_500_000,
        target_completion_date="2026-09-30",
    )
    minutes_before = read_car(car_id)["scheduled_downtime_minutes"]
    assert minutes_before == 0

    window = add_window(
        program,
        car_id,
        "2026-09-10T08:00:00Z",
        "2026-09-12T08:00:00Z",
        "MODERNIZATION",
        project["id"],
    )
    assert read_car(car_id)["scheduled_downtime_minutes"] == 2880

    cancelled = validate_success(
        api.cancel_downtime_window(window["id"], program.admin_headers)
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["duration_minutes"] == 2880

    assert read_car(car_id)["scheduled_downtime_minutes"] == 0
    assert read_car(car_id)["scheduled_downtime_minutes"] == minutes_before, (
        "cancelling must restore the pre-creation figure exactly"
    )
    assert read_project(project["id"])["window_count"] == 0


def test_completing_a_project_with_a_scheduled_window_left_is_refused(api):
    """PRD §3.5: "Closing a project out is the administrator's job again: from
    `APPROVED`, from `IN_PROGRESS` or from `AT_RISK`, a project moves to `COMPLETE`
    provided no downtime window belonging to it remains in `SCHEDULED`, at which
    point `window_count` is frozen at its then-current value."
    PRD §2.7: "The target resource must currently sit in a state from which the
    requested transition is declared, otherwise `ERR_INVALID_STATE_TRANSITION`
    (409)."

    Design: Corner/state_machines/project_complete_while_a_scheduled_window_remains_is_rejected
    """
    program = setup_program(
        ["CAR-SD"],
        building_name="SM Thirteen",
        building_address="13 SM St",
        building_manager_user_id="bm-sd",
        contractor_user_id="sc-sd",
    )
    project = plan_and_approve_project(
        program,
        title="Hoistway upgrade",
        budget_cents=5_000_000,
        target_completion_date="2026-10-15",
    )
    window = add_window(
        program,
        program.car_id(),
        "2026-10-05T08:00:00Z",
        "2026-10-07T08:00:00Z",
        "MODERNIZATION",
        project["id"],
    )

    validate_error(
        api.complete_project(project["id"], program.admin_headers),
        ApiErrorId.ERR_INVALID_STATE_TRANSITION.value,
    )

    stored = read_project(project["id"])
    assert stored["status"] == "APPROVED"
    assert stored["window_count"] == 1
    assert read_window(window["id"])["status"] == "SCHEDULED"


def test_clock_entering_and_leaving_a_modernization_window_moves_car_and_project(api):
    """PRD §3.5: "When the logical clock advances into the first scheduled
    modernization window of an approved project, the project moves
    `APPROVED → IN_PROGRESS` and the affected car's availability dimension moves
    `IN_SERVICE → UNDER_MODERNIZATION` in the same sweep; when the clock later
    reaches or passes the end of every scheduled modernization window on that car,
    each elapsed window becomes `COMPLETED` and the car returns
    `UNDER_MODERNIZATION → IN_SERVICE`."
    PRD §3.5: "The car's `scheduled_downtime_minutes` is, at all times, the sum of
    `duration_minutes` over that car's windows whose `status` is `SCHEDULED` or
    `COMPLETED`."

    Design: Corner/state_machines/clock_entering_a_modernization_window_moves_car_and_project
    """
    program = setup_program(
        ["CAR-SE"],
        building_name="SM Fourteen",
        building_address="14 SM St",
        building_manager_user_id="bm-se",
        contractor_user_id="sc-se",
    )
    car_id = program.car_id()
    project = plan_and_approve_project(
        program,
        title="Controller swap",
        budget_cents=6_000_000,
        target_completion_date="2026-10-07",
    )
    window = add_window(
        program,
        car_id,
        "2026-10-05T08:00:00Z",
        "2026-10-07T08:00:00Z",
        "MODERNIZATION",
        project["id"],
    )

    entering = validate_success(
        api.set_clock("2026-10-06T00:00:00Z", program.admin_headers)
    )
    assert entering["cars_under_modernization"] == 1
    assert read_car(car_id)["availability_state"] == "UNDER_MODERNIZATION"
    assert read_project(project["id"])["status"] == "IN_PROGRESS"
    assert read_window(window["id"])["status"] == "SCHEDULED"

    leaving = validate_success(
        api.set_clock("2026-10-08T00:00:00Z", program.admin_headers)
    )
    assert leaving["windows_completed"] == 1
    assert read_window(window["id"])["status"] == "COMPLETED"
    assert read_car(car_id)["availability_state"] == "IN_SERVICE"
    assert read_car(car_id)["scheduled_downtime_minutes"] == 2880, (
        "a COMPLETED window stays in the reserved-minutes sum"
    )


def test_window_end_equal_to_window_start_is_rejected(api):
    """PRD §3.5: "A reservation names the `car_id`, a `window_type` of
    `MODERNIZATION`, `INSPECTION` or `REPAIR`, an inclusive `window_start` and an
    exclusive `window_end` that must be strictly later than the start, and — for
    modernization work only — the `project_id` of the owning project, which is left
    null for inspection and repair windows."
    PRD §2.7: "Every required input field present; every enum field carrying a
    declared member; every datetime parsing as ISO 8601 UTC and every date as
    `YYYY-MM-DD`; every `period_month` matching a four-digit year, a hyphen, and a
    two-digit month in the range 01 through 12; `window_end` strictly after
    `window_start`; `term_end_date` strictly after `term_start_date`;
    `scheduled_date` falling inside the visit's `period_month`; and
    `passengers_trapped` at least 1 whenever `callback_type` is `ENTRAPMENT`. Any
    failure yields `ERR_VALIDATION` (400)."

    Design: Corner/validations/downtime_window_with_end_not_after_start_returns_validation
    """
    program = setup_program(
        ["CAR-VA"],
        building_name="Val Ten",
        building_address="10 Val St",
        building_manager_user_id="bm-va",
        contractor_user_id="sc-va",
    )
    car_id = program.car_id()

    validate_error(
        api.create_downtime_window(
            {
                "car_id": car_id,
                "window_type": "REPAIR",
                "window_start": "2026-09-10T08:00:00Z",
                "window_end": "2026-09-10T08:00:00Z",
            },
            program.admin_headers,
        ),
        ApiErrorId.ERR_VALIDATION.value,
    )

    assert read_car(car_id)["scheduled_downtime_minutes"] == 0
    rows, meta = validate_paginated(
        api.list_downtime_windows(program.admin_headers, {"car_id": car_id})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_downtime_window_list_filters_by_project_and_by_car(api):
    """PRD §2.11: "downtime windows by `car_id`, `project_id`, `status` and
    `window_type`"
    PRD §2.11: "Every one of these filters is optional and combinable, and all of
    them coexist with `limit` and `offset`."
    PRD §3.5: "A reservation names the `car_id`, a `window_type` of `MODERNIZATION`,
    `INSPECTION` or `REPAIR`, an inclusive `window_start` and an exclusive
    `window_end` that must be strictly later than the start, and — for modernization
    work only — the `project_id` of the owning project, which is left null for
    inspection and repair windows."

    Design: Corner/endpoints/downtime_window_list_filters_by_project_and_car_independently
    """
    program = setup_program(
        ["CAR-E2A", "CAR-E2B"],
        building_name="Ep Two",
        building_address="2 Ep St",
        building_manager_user_id="bm-e2",
        contractor_user_id="sc-e2",
    )
    project = plan_and_approve_project(
        program,
        title="Staged modernization",
        budget_cents=8_000_000,
        target_completion_date="2026-11-30",
    )
    modernization_a = add_window(
        program,
        program.car_id(0),
        "2026-11-02T08:00:00Z",
        "2026-11-04T08:00:00Z",
        "MODERNIZATION",
        project["id"],
    )
    repair_a = add_window(
        program,
        program.car_id(0),
        "2026-11-10T08:00:00Z",
        "2026-11-10T12:00:00Z",
        "REPAIR",
    )
    modernization_b = add_window(
        program,
        program.car_id(1),
        "2026-11-06T08:00:00Z",
        "2026-11-08T08:00:00Z",
        "MODERNIZATION",
        project["id"],
    )

    by_project, meta_project = validate_paginated(
        api.list_downtime_windows(program.admin_headers, {"project_id": project["id"]})
    )
    assert meta_project["total_count"] == 2
    assert {row["id"] for row in by_project} == {
        modernization_a["id"],
        modernization_b["id"],
    }

    by_car, meta_car = validate_paginated(
        api.list_downtime_windows(program.admin_headers, {"car_id": program.car_id(0)})
    )
    assert meta_car["total_count"] == 2
    assert {row["id"] for row in by_car} == {modernization_a["id"], repair_a["id"]}

    assert read_window(repair_a["id"])["project_id"] is None
    assert read_project(project["id"])["window_count"] == 2
    assert read_car(program.car_id(0))["scheduled_downtime_minutes"] == 3120
    assert read_car(program.car_id(1))["scheduled_downtime_minutes"] == 2880
