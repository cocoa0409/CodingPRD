"""Shift capacity lifecycle, assignment overlap and confirm/cancel
compensation, coverage threshold boundary, hours accumulation, and the
no-show suspension cascade."""
from test_helpers import (
    ApiClient,
    ApiErrorId,
    TEST_USERS,
    assert_shift_capacity_invariant,
    assign_volunteer,
    complete_assignment,
    confirm_assignment,
    create_center_with_active_agreement,
    create_cleared_volunteer,
    create_shift,
    get_assignment,
    get_center,
    get_shift,
    get_volunteer,
    make_volunteer_headers,
    mark_no_show,
    set_clock,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["manager_headers"]


def test_shift_fills_at_capacity_auto(api: ApiClient):
    """PRD §3.3: "A shift is born `OPEN` with `confirmed_count` 0; its `status` is derived — `FILLED` exactly when `confirmed_count` equals `capacity`, and back to `OPEN` whenever the count drops below."
    PRD §3.3: "Success increments the shift's `confirmed_count` by one, flips the shift to `FILLED` when the count reaches `capacity`, promotes a `CLEARED` volunteer to `ACTIVE` on this first confirm, and recomputes the center's coverage ratio and posture — the confirmed slot counts toward today's coverage when the shift starts on the current clock date."

    Design: Corner/state_machines/shift_fills_at_capacity_auto
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Aleph Center",
            "airport_code": "BWI",
            "occupancy_cap": 25,
            "required_daily_confirmed_assignments": 1,
        }
    )
    volunteer = create_cleared_volunteer(center["id"], full_name="V Fill")
    shift = create_shift(
        center["id"],
        start_at="2026-09-02T08:00:00Z",
        end_at="2026-09-02T12:00:00Z",
        role_required="DESK",
        capacity=1,
    )
    assert shift["status"] == "OPEN" and shift["confirmed_count"] == 0

    assignment = assign_volunteer(shift["id"], volunteer["id"])
    confirm_assignment(assignment["id"], volunteer["id"])

    after = get_shift(shift["id"])
    assert after["confirmed_count"] == 1
    assert after["status"] == "FILLED", (
        f"shift must flip to FILLED exactly at capacity, got {after['status']!r}"
    )
    assert_shift_capacity_invariant(after)


def test_shift_full_on_confirm_rejected(api: ApiClient):
    """PRD §3.3: "Confirmation belongs to the volunteer. Confirming moves an `ASSIGNED` assignment to `CONFIRMED` — a volunteer caller whose `X-User-ID` differs from the assignment's `volunteer_id` is `ERR_FORBIDDEN` — provided the volunteer is still `CLEARED` or `ACTIVE` (`ERR_VOLUNTEER_NOT_ELIGIBLE`) and the shift still has room: confirming into a shift whose `confirmed_count` has reached `capacity` is rejected with `ERR_SHIFT_FULL`."

    Design: Corner/errors/shift_full_on_confirm_rejected
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Dalet2 Center",
            "airport_code": "MLI",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        }
    )
    v1 = create_cleared_volunteer(center["id"], full_name="V Full1")
    v2 = create_cleared_volunteer(center["id"], full_name="V Full2")
    shift = create_shift(
        center["id"],
        start_at="2026-09-02T08:00:00Z",
        end_at="2026-09-02T12:00:00Z",
        role_required="DESK",
        capacity=1,
    )
    a1 = assign_volunteer(shift["id"], v1["id"])
    a2 = assign_volunteer(shift["id"], v2["id"])
    confirm_assignment(a1["id"], v1["id"])

    resp = api.confirm_assignment(a2["id"], make_volunteer_headers(v2["id"]))
    validate_error(resp, ApiErrorId.ERR_SHIFT_FULL)

    a2_after = get_assignment(a2["id"])
    assert a2_after["status"] == "ASSIGNED", (
        f"a rejected confirm must leave the assignment ASSIGNED, got "
        f"{a2_after['status']!r}"
    )
    shift_after = get_shift(shift["id"])
    assert shift_after["confirmed_count"] == 1
    assert shift_after["status"] == "FILLED"


def test_volunteer_shift_half_open_adjacency(api: ApiClient):
    """PRD §3.3: "Overlap is evaluated half-open against the shifts of that volunteer's `ASSIGNED` or `CONFIRMED` assignments — `CANCELLED`, `NO_SHOW`, and `COMPLETED` assignments are ignored — and any overlap is rejected with `ERR_SHIFT_OVERLAP`. Back-to-back adjacency, the new shift starting exactly when an existing one ends, does not overlap."

    Design: Difficulty/resource_temporal_overlap/volunteer_shift_half_open_adjacency
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Omicron Center",
            "airport_code": "AUS",
            "occupancy_cap": 30,
            "required_daily_confirmed_assignments": 2,
        }
    )
    volunteer = create_cleared_volunteer(center["id"], full_name="V Overlap")
    s1 = create_shift(
        center["id"],
        start_at="2026-09-03T08:00:00Z",
        end_at="2026-09-03T12:00:00Z",
        role_required="DESK",
        capacity=2,
    )
    s2 = create_shift(
        center["id"],
        start_at="2026-09-03T12:00:00Z",
        end_at="2026-09-03T16:00:00Z",
        role_required="KITCHEN",
        capacity=2,
    )
    s3 = create_shift(
        center["id"],
        start_at="2026-09-03T11:00:00Z",
        end_at="2026-09-03T15:00:00Z",
        role_required="EVENTS",
        capacity=2,
    )

    a1 = assign_volunteer(s1["id"], volunteer["id"])
    a2 = assign_volunteer(s2["id"], volunteer["id"])
    assert a1["status"] == "ASSIGNED" and a2["status"] == "ASSIGNED", (
        "back-to-back shifts (12:00 == 12:00) do not overlap; both "
        "assignments must be created"
    )

    resp = api.create_assignment(
        s3["id"], {"volunteer_id": volunteer["id"]}, MGR
    )
    validate_error(resp, ApiErrorId.ERR_SHIFT_OVERLAP)


def test_shift_confirm_cancel_capacity_invariant(api: ApiClient):
    """PRD §3.3: "Success increments the shift's `confirmed_count` by one, flips the shift to `FILLED` when the count reaches `capacity`, promotes a `CLEARED` volunteer to `ACTIVE` on this first confirm, and recomputes the center's coverage ratio and posture — the confirmed slot counts toward today's coverage when the shift starts on the current clock date."
    PRD §3.3: "From `CONFIRMED`, cancelling releases the reserved slot: `confirmed_count` decrements by one, a `FILLED` shift reopens to `OPEN` when it drops below `capacity`, and coverage and posture are recomputed, returning the shift's count to its pre-confirm value."

    Design: Difficulty/compensating_invariant/shift_confirm_cancel_capacity_invariant
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Rho Center",
            "airport_code": "PDX",
            "occupancy_cap": 30,
            "required_daily_confirmed_assignments": 1,
        }
    )
    volunteer = create_cleared_volunteer(center["id"], full_name="V Rho")
    shift = create_shift(
        center["id"],
        start_at="2026-09-02T08:00:00Z",
        end_at="2026-09-02T12:00:00Z",
        role_required="DESK",
        capacity=1,
    )
    assert shift["confirmed_count"] == 0 and shift["status"] == "OPEN"

    assignment = assign_volunteer(shift["id"], volunteer["id"])
    confirm_assignment(assignment["id"], volunteer["id"])
    mid = get_shift(shift["id"])
    assert mid["confirmed_count"] == 1 and mid["status"] == "FILLED"
    assert_shift_capacity_invariant(mid)

    resp = api.cancel_assignment(
        assignment["id"], make_volunteer_headers(volunteer["id"])
    )
    cancelled = validate_success(resp, 200)
    assert cancelled["status"] == "CANCELLED"

    end = get_shift(shift["id"])
    assert end["confirmed_count"] == 0 and end["status"] == "OPEN", (
        "the compensating cancel returns confirmed_count to its pre-confirm "
        f"value (0) and reopens the shift, got count={end['confirmed_count']} "
        f"status={end['status']!r}"
    )
    assert_shift_capacity_invariant(end)


def test_coverage_threshold_exact_075(api: ApiClient):
    """PRD §2.6: "The derivation uses the confirmed-only coverage variant: `coverage_ratio` is the number of `CONFIRMED` shift assignments whose shift's `start_at` falls on the current clock date, divided by the center's `required_daily_confirmed_assignments`; assignments in `ASSIGNED`, `CANCELLED`, `NO_SHOW`, or `COMPLETED` never count toward it."
    PRD §2.6: "If the center has no `ACTIVE` site agreement, posture is `CLOSED`. Otherwise, when `coverage_ratio` is at least 0.75 the posture is `OPEN`, and below that threshold it is `RESTRICTED`."

    Design: Difficulty/boundary_precision_check/coverage_threshold_exact_075
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Lambda Center",
            "airport_code": "IAD",
            "occupancy_cap": 50,
            "required_daily_confirmed_assignments": 4,
        }
    )
    v1 = create_cleared_volunteer(center["id"], full_name="V A")
    v2 = create_cleared_volunteer(center["id"], full_name="V B")
    v3 = create_cleared_volunteer(center["id"], full_name="V C")
    shift = create_shift(
        center["id"],
        start_at="2026-09-01T08:00:00Z",
        end_at="2026-09-01T12:00:00Z",
        role_required="DESK",
        capacity=3,
    )

    a1 = assign_volunteer(shift["id"], v1["id"])
    confirm_assignment(a1["id"], v1["id"])
    a2 = assign_volunteer(shift["id"], v2["id"])
    confirm_assignment(a2["id"], v2["id"])

    mid = get_center(center["id"])
    assert mid["coverage_ratio"] == 0.5, (
        f"2 confirmed of 4 required must give ratio 0.5, got {mid['coverage_ratio']}"
    )
    assert mid["posture"] == "RESTRICTED", (
        f"0.5 is below the 0.75 threshold: posture must stay RESTRICTED, "
        f"got {mid['posture']!r}"
    )

    a3 = assign_volunteer(shift["id"], v3["id"])
    confirm_assignment(a3["id"], v3["id"])
    end = get_center(center["id"])
    assert end["coverage_ratio"] == 0.75, (
        f"3 confirmed of 4 required must give ratio exactly 0.75, got "
        f"{end['coverage_ratio']}"
    )
    assert end["posture"] == "OPEN", (
        f"the threshold is >= 0.75 (at least), so exactly 0.75 is OPEN, "
        f"got {end['posture']!r}"
    )


def test_derived_hours_accumulate(api: ApiClient):
    """PRD §3.3: "Completion records `actual_hours`, which must be greater than 0 (`ERR_VALIDATION`), on the assignment, moves it to `COMPLETED`, and adds those hours into the volunteer's `total_hours`"
    PRD §3.2: "The volunteer's `total_hours`, the sum of `actual_hours` across the volunteer's `COMPLETED` assignments, survives all of these transitions."

    Design: Corner/complexity_layers/derived_hours_accumulate
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Pe2 Center",
            "airport_code": "CWA",
            "occupancy_cap": 10,
            "required_daily_confirmed_assignments": 1,
        }
    )
    volunteer = create_cleared_volunteer(center["id"], full_name="V Hours")
    sh1 = create_shift(
        center["id"],
        start_at="2026-09-01T06:00:00Z",
        end_at="2026-09-01T08:00:00Z",
        role_required="DESK",
        capacity=1,
    )
    sh2 = create_shift(
        center["id"],
        start_at="2026-09-01T10:00:00Z",
        end_at="2026-09-01T12:00:00Z",
        role_required="KITCHEN",
        capacity=1,
    )
    a1 = assign_volunteer(sh1["id"], volunteer["id"])
    a2 = assign_volunteer(sh2["id"], volunteer["id"])
    confirm_assignment(a1["id"], volunteer["id"])
    confirm_assignment(a2["id"], volunteer["id"])

    # Completion requires the shift's end_at to have passed.
    set_clock("2026-09-01T08:30:00Z")
    done1 = complete_assignment(a1["id"], 2.5)
    assert done1["status"] == "COMPLETED" and done1["actual_hours"] == 2.5

    set_clock("2026-09-01T12:30:00Z")
    done2 = complete_assignment(a2["id"], 2.0)
    assert done2["status"] == "COMPLETED" and done2["actual_hours"] == 2.0

    volunteer_after = get_volunteer(volunteer["id"])
    assert volunteer_after["total_hours"] == 4.5, (
        f"total_hours must accumulate 2.5 + 2.0 = 4.5 across completions, "
        f"got {volunteer_after['total_hours']}"
    )


def test_no_show_strike_suspension_cascade(api: ApiClient):
    """PRD §3.3: "Marking a no-show moves `CONFIRMED` to `NO_SHOW`, adds a strike to `no_show_strikes`, decrements the shift's `confirmed_count` (reopening a `FILLED` shift to `OPEN` when it falls below `capacity`), and recomputes the center's coverage and posture; when the strike count reaches 3, the suspension cascade of §3.2 fires."
    PRD §3.2: "Each no-show adds a strike to `no_show_strikes`, and when the count reaches the strike limit of 3 the volunteer is `SUSPENDED`: every future-dated `ASSIGNED` or `CONFIRMED` assignment of that volunteer is cancelled, each affected shift's `confirmed_count` is decremented where applicable — a `FILLED` shift that drops below `capacity` reopens to `OPEN` — and coverage and posture are recomputed for the affected centers."

    Design: Difficulty/transitive_cascade/no_show_strike_suspension_cascade
    """
    set_clock()
    center, _agreement = create_center_with_active_agreement(
        center_overrides={
            "name": "Theta Center",
            "airport_code": "BOS",
            "occupancy_cap": 40,
            "required_daily_confirmed_assignments": 4,
        }
    )
    volunteer = create_cleared_volunteer(center["id"], full_name="V Strike")
    s1 = create_shift(
        center["id"],
        start_at="2026-09-01T06:00:00Z",
        end_at="2026-09-01T08:00:00Z",
        role_required="DESK",
        capacity=1,
    )
    s2 = create_shift(
        center["id"],
        start_at="2026-09-01T10:00:00Z",
        end_at="2026-09-01T12:00:00Z",
        role_required="KITCHEN",
        capacity=1,
    )
    s3 = create_shift(
        center["id"],
        start_at="2026-09-01T13:00:00Z",
        end_at="2026-09-01T15:00:00Z",
        role_required="EVENTS",
        capacity=1,
    )
    s4 = create_shift(
        center["id"],
        start_at="2026-09-02T06:00:00Z",
        end_at="2026-09-02T08:00:00Z",
        role_required="FAMILY",
        capacity=1,
    )
    assignments = [
        assign_volunteer(shift["id"], volunteer["id"])
        for shift in (s1, s2, s3, s4)
    ]
    for assignment in assignments:
        confirm_assignment(assignment["id"], volunteer["id"])

    # Each no-show is marked after its shift's end_at has passed.
    set_clock("2026-09-01T09:00:00Z")
    mark_no_show(assignments[0]["id"])
    set_clock("2026-09-01T12:30:00Z")
    mark_no_show(assignments[1]["id"])
    set_clock("2026-09-01T15:30:00Z")

    resp = api.mark_no_show(assignments[2]["id"], MGR)
    third = validate_success(resp, 200)
    assert third["status"] == "NO_SHOW"

    volunteer_after = get_volunteer(volunteer["id"])
    assert volunteer_after["no_show_strikes"] == 3, (
        f"three no-shows must accumulate 3 strikes, got "
        f"{volunteer_after['no_show_strikes']}"
    )
    assert volunteer_after["status"] == "SUSPENDED", (
        f"the strike limit of 3 suspends the volunteer, got "
        f"{volunteer_after['status']!r}"
    )

    fourth = get_assignment(assignments[3]["id"])
    assert fourth["status"] == "CANCELLED", (
        "the suspension cascade cancels the future-dated (2026-09-02) "
        f"CONFIRMED assignment, got {fourth['status']!r}"
    )
    s4_after = get_shift(s4["id"])
    assert s4_after["confirmed_count"] == 0
    assert s4_after["status"] == "OPEN", (
        f"the cancelled confirm releases s4's slot: FILLED -> OPEN, got "
        f"{s4_after['status']!r}"
    )
