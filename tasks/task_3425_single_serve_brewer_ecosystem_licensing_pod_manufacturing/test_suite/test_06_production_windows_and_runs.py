"""Production runs: windows, capacity, overlap, changeover, and conservation."""
from test_helpers import (
    PLANNER,
    ApiErrorId,
    create_brand,
    create_facility_with_line,
    create_variety,
    get_success_data,
    reserve_run,
    set_clock,
    transition_run,
    validate_error,
    validate_success,
)


def _owned_variety(name="Run Var", **overrides):
    brand = create_brand(kind="PLATFORM_OWNED", name=f"{name} Brand")
    variety = create_variety(brand["id"], name=name, **overrides)
    return brand, variety


def test_invalid_window_shape_rejected(api):
    """PRD §2.10: "**Window shape** — a run's `window_start` strictly precedes
    its `window_end`, and an agreement's `effective_start` falls on or before
    its `effective_end` (`ERR_INVALID_WINDOW`)."

    Design: Corner/validations/invalid_window_shape_rejected
    """
    _, variety = _owned_variety("Shape Var")
    _, line = create_facility_with_line()

    resp = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-10T00:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_INVALID_WINDOW)


def test_run_cannot_start_outside_its_window(api, planner_headers):
    """PRD §3.4: "`RESERVED → IN_PROGRESS` requires `window_start` to be at or
    before the clock and `window_end` to be strictly after it — outside the
    window the transition is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/run_cannot_start_outside_its_window
    """
    _, variety = _owned_variety("Gate Var")
    _, line = create_facility_with_line()
    run = reserve_run(line["id"], variety["id"],
                      window_start="2026-09-10T00:00:00Z",
                      window_end="2026-09-11T00:00:00Z", planned_units=100)

    # Clock is still 2026-09-01: the window has not opened.
    resp = transition_run(run["id"], "IN_PROGRESS")
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    read_back = get_success_data(api.get_production_run(run["id"], planner_headers))
    assert read_back["status"] == "RESERVED"


def test_in_progress_run_cannot_be_cancelled(api, planner_headers):
    """PRD §3.4: "A run still in `RESERVED` may instead be cancelled"
    PRD §2.10: "the requested (current, target) pair must be a declared
    transition of the entity's state machine and the current state must not be
    terminal (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/in_progress_run_cannot_be_cancelled
    """
    _, variety = _owned_variety("NoCancel Var")
    _, line = create_facility_with_line()
    run = reserve_run(line["id"], variety["id"], planned_units=100)
    set_clock("2026-09-10T12:00:00Z")
    get_success_data(transition_run(run["id"], "IN_PROGRESS"))

    resp = transition_run(run["id"], "CANCELLED")
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    read_back = get_success_data(api.get_production_run(run["id"], planner_headers))
    assert read_back["status"] == "IN_PROGRESS"


def test_run_units_beyond_line_capacity_rejected(api):
    """PRD §3.4: "`planned_units` must be at least 1 and at most
    `capacity_pods_per_day` multiplied by that day count, else
    `ERR_CAPACITY_EXCEEDED` (HTTP 409)."

    Design: Corner/validations/run_units_beyond_line_capacity_rejected
    """
    _, variety = _owned_variety("Cap Var")
    _, line = create_facility_with_line(capacity_pods_per_day=100000)

    over = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-11T00:00:00Z", "planned_units": 100001},
        PLANNER)
    validate_error(over, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    # Exactly capacity * 1 day is accepted (the boundary is inclusive).
    exact = validate_success(api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-11T00:00:00Z", "planned_units": 100000},
        PLANNER), 201)
    assert exact["status"] == "RESERVED"


def test_run_completion_over_capacity_rejected(api, planner_headers):
    """PRD §3.4: "Completion moves `IN_PROGRESS → COMPLETED` and requires an
    `actual_units` payload between 0 and the same capacity-times-days ceiling
    inclusive (a breach is again `ERR_CAPACITY_EXCEEDED`)"

    Design: Corner/validations/run_completion_over_capacity_rejected
    """
    _, variety = _owned_variety("Overrun Var")
    _, line = create_facility_with_line(capacity_pods_per_day=100000)
    run = reserve_run(line["id"], variety["id"], planned_units=90000)
    set_clock("2026-09-10T12:00:00Z")
    get_success_data(transition_run(run["id"], "IN_PROGRESS"))

    resp = transition_run(run["id"], "COMPLETED", actual_units=100001)
    validate_error(resp, ApiErrorId.ERR_CAPACITY_EXCEEDED)

    read_back = get_success_data(api.get_production_run(run["id"], planner_headers))
    assert read_back["status"] == "IN_PROGRESS"
    assert read_back["actual_units"] is None


def test_temporal_beats_overlap_on_run_create(api):
    """PRD §2.10: "the server evaluates them in a fixed priority order so that
    the reported failure is deterministic" — temporal windows (9.) precede
    conflicts and capability (10.), and "An earlier failure in this ordering
    masks every later one: the client sees exactly one error, from the first
    class that fails."
    PRD §3.4: "a `window_start` before the logical clock is
    `ERR_WINDOW_IN_PAST` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_overlap_on_run_create
    """
    _, variety = _owned_variety("Overlap Var")
    _, line = create_facility_with_line(capacity_pods_per_day=100000)
    reserve_run(line["id"], variety["id"],
                window_start="2026-09-10T00:00:00Z",
                window_end="2026-09-12T00:00:00Z", planned_units=100)

    set_clock("2026-09-11T00:00:00Z")

    # This window both overlaps the existing run AND starts in the past.
    resp = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T12:00:00Z",
         "window_end": "2026-09-11T12:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)


def test_window_in_past_rejected_without_any_overlap(api):
    """PRD §3.4: "it must not lie in the past: a `window_start` before the
    logical clock is `ERR_WINDOW_IN_PAST` (HTTP 422)."

    Design: Difficulty/priority_pair_validation_conflict/temporal_beats_overlap_on_run_create
    """
    _, variety = _owned_variety("PastOnly Var")
    _, line = create_facility_with_line(capacity_pods_per_day=100000)

    set_clock("2026-09-11T00:00:00Z")

    # No other runs exist: only the temporal gate can fire.
    resp = api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T12:00:00Z",
         "window_end": "2026-09-11T12:00:00Z", "planned_units": 100},
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_WINDOW_IN_PAST)


def test_state_beats_capacity_on_run_complete(api, planner_headers):
    """PRD §2.10: the state-machine precondition (7.) is evaluated before
    capacity and fiscal floors (12.), and "An earlier failure in this ordering
    masks every later one: the client sees exactly one error, from the first
    class that fails."
    PRD §2.9: "Terminal states are absorbing — a resource in a terminal state
    accepts no further transitions, and any attempt to drive one is rejected
    with `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_run_complete
    """
    _, variety = _owned_variety("Priority Var")
    _, line = create_facility_with_line(capacity_pods_per_day=10000)
    run = reserve_run(line["id"], variety["id"], planned_units=5000)
    get_success_data(transition_run(run["id"], "CANCELLED"))

    # Over-capacity payload on a terminal run: state wins over capacity.
    resp = transition_run(run["id"], "COMPLETED", actual_units=99999)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    read_back = get_success_data(api.get_production_run(run["id"], planner_headers))
    assert read_back["status"] == "CANCELLED"
    assert read_back["actual_units"] is None


def test_reserved_run_cannot_skip_in_progress(api, planner_headers):
    """PRD §2.10: "the requested (current, target) pair must be a declared
    transition of the entity's state machine and the current state must not be
    terminal (`ERR_INVALID_STATE`)."
    PRD §3.4 declares only `RESERVED → IN_PROGRESS`, `IN_PROGRESS → COMPLETED`,
    and `RESERVED → CANCELLED` for production runs.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_capacity_on_run_complete
    """
    _, variety = _owned_variety("Skip Var")
    _, line = create_facility_with_line(capacity_pods_per_day=10000)
    run = reserve_run(line["id"], variety["id"], planned_units=5000)

    # In-capacity payload, but (RESERVED, COMPLETED) is not a declared pair.
    resp = transition_run(run["id"], "COMPLETED", actual_units=50)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    read_back = get_success_data(api.get_production_run(run["id"], planner_headers))
    assert read_back["status"] == "RESERVED"


def test_same_spec_adjacency_legal_and_interior_overlap_conflicts(api):
    """PRD §3.4: "Windows are **half-open** — they include their start instant
    and exclude their end — so two runs conflict exactly when each starts
    before the other ends, and a run starting at the precise instant another
    ends is legal. A true overlap is `ERR_LINE_WINDOW_CONFLICT` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/line_half_open_plus_changeover_buffer
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Window Beans")
    v1 = create_variety(brand["id"], name="Window Medium", roast_level="MEDIUM")
    _, line = create_facility_with_line(capacity_pods_per_day=100000,
                                        changeover_hours=4)

    reserve_run(line["id"], v1["id"], window_start="2026-09-10T08:00:00Z",
                window_end="2026-09-10T16:00:00Z", planned_units=10)

    # Same-spec run starting at the precise instant the first ends: legal.
    adjacent = validate_success(api.create_production_run(
        {"line_id": line["id"], "variety_id": v1["id"],
         "window_start": "2026-09-10T16:00:00Z",
         "window_end": "2026-09-10T20:00:00Z", "planned_units": 10},
        PLANNER), 201)
    assert adjacent["status"] == "RESERVED"

    # Interior overlap against the first run conflicts.
    overlap = api.create_production_run(
        {"line_id": line["id"], "variety_id": v1["id"],
         "window_start": "2026-09-10T15:59:00Z",
         "window_end": "2026-09-10T17:00:00Z", "planned_units": 10},
        PLANNER)
    validate_error(overlap, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)


def test_changeover_buffer_required_between_different_roasts(api):
    """PRD §3.4: "when two runs on the same line differ in `roast_level` or in
    material, the later run must start no earlier than the earlier run's end
    plus the line's `changeover_hours`; a tighter gap is
    `ERR_CHANGEOVER_BUFFER_VIOLATION` (HTTP 409). Same-roast, same-material
    runs may sit back to back with no idle time at all."

    Design: Difficulty/resource_temporal_overlap/line_half_open_plus_changeover_buffer
    """
    brand = create_brand(kind="PLATFORM_OWNED", name="Buffer Beans")
    v1 = create_variety(brand["id"], name="Buffer Medium", roast_level="MEDIUM")
    v2 = create_variety(brand["id"], name="Buffer Dark", roast_level="DARK")
    _, line = create_facility_with_line(capacity_pods_per_day=100000,
                                        changeover_hours=4)

    reserve_run(line["id"], v1["id"], window_start="2026-09-10T08:00:00Z",
                window_end="2026-09-10T16:00:00Z", planned_units=10)
    reserve_run(line["id"], v1["id"], window_start="2026-09-10T16:00:00Z",
                window_end="2026-09-10T20:00:00Z", planned_units=10)

    # Different roast starting exactly at the prior end: needs +4h, rejected.
    tight = api.create_production_run(
        {"line_id": line["id"], "variety_id": v2["id"],
         "window_start": "2026-09-10T20:00:00Z",
         "window_end": "2026-09-10T22:00:00Z", "planned_units": 10},
        PLANNER)
    validate_error(tight, ApiErrorId.ERR_CHANGEOVER_BUFFER_VIOLATION)

    # Starting exactly at end + changeover_hours (20:00 + 4h) is legal.
    exact_gap = validate_success(api.create_production_run(
        {"line_id": line["id"], "variety_id": v2["id"],
         "window_start": "2026-09-11T00:00:00Z",
         "window_end": "2026-09-11T02:00:00Z", "planned_units": 10},
        PLANNER), 201)
    assert exact_gap["status"] == "RESERVED"


def test_capacity_reserve_cancel_conservation(api, planner_headers):
    """PRD §3.4: "cancellation releases the window's capacity, and the
    compensating invariant holds exactly: creating a run and then cancelling it
    leaves the line's bookable windows precisely as they were, with no capacity
    drift."

    Design: Difficulty/compensating_invariant/capacity_reserve_cancel_conservation
    """
    _, variety = _owned_variety("Conservation Var")
    facility, line = create_facility_with_line(capacity_pods_per_day=10000)

    # 2-day window: capacity 10000 * 2 == 20000; the boundary uses <=.
    first = validate_success(api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-12T00:00:00Z", "planned_units": 20000},
        PLANNER), 201)

    cancelled = get_success_data(transition_run(first["id"], "CANCELLED"))
    assert cancelled["status"] == "CANCELLED"

    # The identical reservation books again: zero capacity drift.
    second = validate_success(api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-12T00:00:00Z", "planned_units": 20000},
        PLANNER), 201)
    assert second["status"] == "RESERVED"

    facility_after = get_success_data(
        api.get_facility(facility["id"], planner_headers))
    assert facility_after["total_capacity_pods_per_day"] == 10000


def test_partial_reserve_cancel_then_full_window_rebooks(api, planner_headers):
    """PRD §3.4: "creating a run and then cancelling it leaves the line's
    bookable windows precisely as they were, with no capacity drift."
    PRD §3.4: "it is the sum of `capacity_pods_per_day` across all of the
    facility's filling lines, and it starts at 0 for a facility with no lines
    yet."

    Design: Difficulty/compensating_invariant/capacity_reserve_cancel_conservation
    """
    _, variety = _owned_variety("Partial Var")
    facility, line = create_facility_with_line(capacity_pods_per_day=10000)

    partial = reserve_run(line["id"], variety["id"],
                          window_start="2026-09-10T00:00:00Z",
                          window_end="2026-09-12T00:00:00Z", planned_units=5000)
    get_success_data(transition_run(partial["id"], "CANCELLED"))

    full = validate_success(api.create_production_run(
        {"line_id": line["id"], "variety_id": variety["id"],
         "window_start": "2026-09-10T00:00:00Z",
         "window_end": "2026-09-12T00:00:00Z", "planned_units": 20000},
        PLANNER), 201)
    assert full["status"] == "RESERVED"

    facility_after = get_success_data(
        api.get_facility(facility["id"], planner_headers))
    assert facility_after["total_capacity_pods_per_day"] == 10000
