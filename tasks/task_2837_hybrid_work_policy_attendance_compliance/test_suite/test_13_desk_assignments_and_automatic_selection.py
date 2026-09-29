"""Putting people at numbered desks: closed intervals, changeover and the auto selector."""
from test_helpers import (
    ApiErrorId,
    UNKNOWN_EMPLOYEE_ID,
    UNKNOWN_SEAT_ALLOCATION_ID,
    api_client,
    assign_desk,
    auto_assign,
    auto_desk_payload,
    commit_allocation,
    create_cycle,
    create_neighborhood,
    create_team,
    desk_assignment_payload,
    get_success_data,
    list_all,
    pin_clock,
    read_allocation,
    read_neighborhood,
    register_employee,
    reserve_allocation,
    same_instant,
    validate_error,
    vacate_desk,
)
from test_helpers.constants import PINNED_CLOCK_INSTANT
from test_helpers.fixtures import WPO

DESK_CYCLE = {
    "effective_from": "2026-09-01",
    "effective_to": "2026-12-31",
    "days_in_office_floor": 2,
    "badge_weight": 0.60,
    "network_weight": 0.40,
    "collaboration_target_score": 70.00,
    "equity_variance_threshold_pct": 20.00,
}

THREE_DAY_TEAM = {
    "expected_days_in_office_per_week": 3,
    "core_collaboration_days": ["TUE", "WED", "THU"],
    "headcount_planned": 12,
    "signal_corroboration_required": False,
}

LATER_INSTANT = "2026-09-02T09:00:00Z"


def _two_occupied_desks_on_one_committed_slice():
    """A thirty-desk zone where desks 7 and 9 are taken for the whole of 2026-W37."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-RT2", **DESK_CYCLE)
    team = create_team(cycle["id"], team_code="T1-CORE", **THREE_DAY_TEAM)
    people = [
        register_employee(
            team["id"], employee_number=f"E-300{index}",
            work_email=f"e300{index}@corp.example",
        )
        for index in range(1, 6)
    ]
    zone = create_neighborhood(
        cycle["id"], team["id"], neighborhood_code="N-D1", site_code="NYC-01",
        seat_count=30, buffer_seats=4, desk_index_from=1, desk_index_to=30,
    )
    allocation = commit_allocation(
        reserve_allocation(zone["id"], team["id"], 5, "2026-W37", "2026-W41")["id"]
    )
    on_desk_seven = assign_desk(
        allocation["id"], people[0]["id"], 7, "2026-09-07", "2026-09-11"
    )
    on_desk_nine = assign_desk(
        allocation["id"], people[3]["id"], 9, "2026-09-07", "2026-09-11"
    )
    return {
        "cycle": cycle,
        "team": team,
        "people": people,
        "zone": zone,
        "allocation": allocation,
        "on_desk_seven": on_desk_seven,
        "on_desk_nine": on_desk_nine,
    }


def _a_slice_reserved_but_not_yet_committed():
    """Two teams, one zone anchored on the first, and five seats still merely reserved."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CE3", **DESK_CYCLE)
    own_team = create_team(cycle["id"], team_code="T1-CORE", **THREE_DAY_TEAM)
    other_team = create_team(cycle["id"], team_code="T2-SIDE", **THREE_DAY_TEAM)
    insider = register_employee(
        own_team["id"], employee_number="E-1001", work_email="e1001@corp.example"
    )
    outsider = register_employee(
        other_team["id"], employee_number="E-2001", work_email="e2001@corp.example",
        manager_user_id="mgr-2",
    )
    zone = create_neighborhood(
        cycle["id"], own_team["id"], neighborhood_code="N-A1", site_code="NYC-01",
        seat_count=30, buffer_seats=4, desk_index_from=1, desk_index_to=30,
    )
    allocation = reserve_allocation(
        zone["id"], own_team["id"], 5, "2026-W37", "2026-W41"
    )
    return {
        "cycle": cycle,
        "own_team": own_team,
        "other_team": other_team,
        "insider": insider,
        "outsider": outsider,
        "zone": zone,
        "allocation": allocation,
    }


def _a_busy_anchor_zone_and_an_emptier_neighbour():
    """The same team holds seats in its own crowded zone and in a quieter foreign one."""
    pin_clock()
    cycle = create_cycle(cycle_label="FY27-CRN45", **DESK_CYCLE)
    own_team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    other_team = create_team(cycle["id"], team_code="T-B", **THREE_DAY_TEAM)
    people = [
        register_employee(
            own_team["id"], employee_number=f"E-100{index}",
            work_email=f"e100{index}@corp.example",
        )
        for index in range(1, 4)
    ]
    anchor_zone = create_neighborhood(
        cycle["id"], own_team["id"], neighborhood_code="N-ANCHOR", site_code="NYC-01",
        seat_count=13, buffer_seats=4, desk_index_from=1, desk_index_to=13,
    )
    foreign_zone = create_neighborhood(
        cycle["id"], other_team["id"], neighborhood_code="N-OTHER", site_code="NYC-01",
        seat_count=13, buffer_seats=4, desk_index_from=21, desk_index_to=33,
    )
    anchor_line = commit_allocation(
        reserve_allocation(
            anchor_zone["id"], own_team["id"], 6, "2026-W37", "2026-W40"
        )["id"]
    )
    foreign_line = commit_allocation(
        reserve_allocation(
            foreign_zone["id"], own_team["id"], 2, "2026-W37", "2026-W40"
        )["id"]
    )
    return {
        "people": people,
        "anchor_zone": anchor_zone,
        "foreign_zone": foreign_zone,
        "anchor_line": anchor_line,
        "foreign_line": foreign_line,
    }


def _one_committed_slice_and_a_stranger(cycle_label, seat_count=13, buffer_seats=4,
                                       allocated_seats=4):
    """A small zone committed to the first team, plus an employee of the second team."""
    pin_clock()
    cycle = create_cycle(cycle_label=cycle_label, **DESK_CYCLE)
    own_team = create_team(cycle["id"], team_code="T-A", **THREE_DAY_TEAM)
    other_team = create_team(cycle["id"], team_code="T-B", **THREE_DAY_TEAM)
    insider = register_employee(
        own_team["id"], employee_number="E-A", work_email="ea@corp.example"
    )
    outsider = register_employee(
        other_team["id"], employee_number="E-B", work_email="eb@corp.example",
        manager_user_id="mgr-2",
    )
    zone = create_neighborhood(
        cycle["id"], own_team["id"], neighborhood_code="N-1", site_code="NYC-01",
        seat_count=seat_count, buffer_seats=buffer_seats,
        desk_index_from=1, desk_index_to=seat_count,
    )
    allocation = commit_allocation(
        reserve_allocation(
            zone["id"], own_team["id"], allocated_seats, "2026-W37", "2026-W40"
        )["id"]
    )
    return {
        "cycle": cycle,
        "own_team": own_team,
        "insider": insider,
        "outsider": outsider,
        "zone": zone,
        "allocation": allocation,
    }


def test_01_an_abutting_or_single_gap_interval_collides_but_only_on_the_same_desk():
    """One clear day is the price of a desk, and the price is charged per desk index.

    PRD 2.2: "**Date intervals are closed**: an exception request's relief window, a
    desk assignment's occupancy, and an attendance week's seven-date span all include
    both endpoints."
    PRD 3.8: "Desks are exclusive per occupant and carry a one-day sanitation
    changeover, which makes their overlap rule deliberately different from the
    aggregate, half-open seat-allocation window."
    PRD 3.8: "Against any existing `ASSIGNED` assignment on the same zone and the same
    `desk_index`, a new closed interval is rejected when the new start date is no later
    than the existing end date plus one day **and** the existing start date is no later
    than the new end date plus one day."
    PRD 3.8: "Back-to-back assignments that merely abut therefore still conflict, and so
    do assignments separated by a single clear day; the refusal is
    `ERR_DESK_CHANGEOVER_CONFLICT` (409)."
    PRD 3.8: "A successful assignment starts in `ASSIGNED` status with `assignment_mode`
    `MANUAL` and `vacated_at` null."

    Design: Difficulty/resource_temporal_overlap/desk_assignment_closed_interval_changeover_buffer
    """
    scenario = _two_occupied_desks_on_one_committed_slice()
    allocation_id = scenario["allocation"]["id"]
    people = scenario["people"]
    incumbent = scenario["on_desk_seven"]
    assert incumbent["status"] == "ASSIGNED"
    assert incumbent["assignment_mode"] == "MANUAL"
    assert incumbent["vacated_at"] is None
    assert incumbent["desk_index"] == 7
    assert incumbent["end_date"] == "2026-09-11"

    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(
                allocation_id, people[1]["id"], 7,
                start_date="2026-09-12", end_date="2026-09-18",
            ),
            WPO,
        ),
        ApiErrorId.ERR_DESK_CHANGEOVER_CONFLICT.value,
        409,
    )

    after_one_clear_day = assign_desk(
        allocation_id, people[1]["id"], 7, "2026-09-13", "2026-09-18"
    )
    assert after_one_clear_day["status"] == "ASSIGNED", (
        "2026-09-12 is left free, which is exactly the one day the buffer wants"
    )
    assert after_one_clear_day["desk_index"] == 7
    assert after_one_clear_day["assignment_mode"] == "MANUAL"

    neighbouring_desk = assign_desk(
        allocation_id, people[2]["id"], 8, "2026-09-12", "2026-09-18"
    )
    assert neighbouring_desk["status"] == "ASSIGNED", (
        "desk 8 is untouched by desk 7's occupancy over the very same dates"
    )
    assert neighbouring_desk["desk_index"] == 8

    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(
                allocation_id, people[4]["id"], 9,
                start_date="2026-09-12", end_date="2026-09-18",
            ),
            WPO,
        ),
        ApiErrorId.ERR_DESK_CHANGEOVER_CONFLICT.value,
        409,
    )
    assert scenario["on_desk_nine"]["status"] == "ASSIGNED", (
        "the second incumbent blocks its own index in the same way as the first"
    )


def test_02_vacating_the_incumbent_legalises_the_identical_request_it_had_refused():
    """The same dates that collided go through once the sitting row leaves ASSIGNED.

    PRD 3.8: "`VACATED` assignments never conflict with anything. The automatic path
    lets the server choose."
    PRD 3.8: "Vacating a desk requires `ASSIGNED` status — a second vacate, or a vacate
    of an already-`VACATED` row, is refused with `ERR_ASSIGNMENT_NOT_ACTIVE` (409)."
    PRD 3.8: "It sets `status` to `VACATED`, stamps `vacated_at` at the current logical
    instant, and immediately makes that `desk_index` available again to the automatic
    selector for overlapping date ranges, subject to the changeover buffer."
    PRD 3.8: "The employee must be on the allocation's team and the `desk_index` must
    fall inside the zone's declared band, or the request is refused with
    `ERR_TEAM_ALLOCATION_MISMATCH` (409)."
    PRD 2.3: "Several collections override that default because their business ordering
    matters more than their insertion ordering: policy cycles are returned newest first,
    by `created_at` descending; teams are ordered by `team_code` ascending; employees by
    `employee_number` ascending; eligibility classifications by `effective_from`
    descending and then `created_at` descending, which is the same ranking the
    current-class selector uses; attendance weeks by `week_start_date` ascending;
    compliance
    signals by `observed_date` ascending and then `created_at` ascending; neighborhoods
    by `neighborhood_code` ascending; and desk assignments by `start_date` ascending and
    then `desk_index` ascending."

    Design: Difficulty/resource_temporal_overlap/desk_assignment_closed_interval_changeover_buffer
    """
    scenario = _two_occupied_desks_on_one_committed_slice()
    allocation_id = scenario["allocation"]["id"]
    people = scenario["people"]
    assign_desk(allocation_id, people[1]["id"], 7, "2026-09-13", "2026-09-18")
    assign_desk(allocation_id, people[2]["id"], 8, "2026-09-12", "2026-09-18")

    refused = desk_assignment_payload(
        allocation_id, people[4]["id"], 9,
        start_date="2026-09-12", end_date="2026-09-18",
    )
    validate_error(
        api_client.create_desk_assignment(refused, WPO),
        ApiErrorId.ERR_DESK_CHANGEOVER_CONFLICT.value,
        409,
    )

    vacated = vacate_desk(scenario["on_desk_nine"]["id"])
    assert vacated["status"] == "VACATED"
    assert vacated["assignment_mode"] == "MANUAL", "vacating does not rewrite the mode"
    assert same_instant(vacated["vacated_at"], PINNED_CLOCK_INSTANT)

    accepted = get_success_data(
        api_client.create_desk_assignment(refused, WPO), 201
    )
    assert accepted["status"] == "ASSIGNED", (
        "the request was never reshaped; only the incumbent's status changed"
    )
    assert accepted["desk_index"] == 9
    assert accepted["start_date"] == "2026-09-12"

    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(
                allocation_id, people[4]["id"], 31,
                start_date="2026-09-21", end_date="2026-09-25",
            ),
            WPO,
        ),
        ApiErrorId.ERR_TEAM_ALLOCATION_MISMATCH.value,
        409,
    )

    rows, meta = list_all(
        api_client.list_desk_assignments, WPO,
        {"seat_allocation_id": allocation_id, "status": "ASSIGNED"},
    )
    assert meta["total_count"] == 4, "four live rows and one vacated one"
    assert [(row["start_date"], row["desk_index"]) for row in rows] == [
        ("2026-09-07", 7),
        ("2026-09-12", 8),
        ("2026-09-12", 9),
        ("2026-09-13", 7),
    ]


def test_03_the_auto_selector_sees_nothing_until_the_allocation_is_committed():
    """A byte-identical auto request fails on a reserved slice and succeeds on a committed one.

    PRD 3.8: "The caller supplies only the `employee_id`, `start_date` and `end_date`,
    and the server picks both the zone and the desk under a pinned selector."
    PRD 3.8: "Eligibility first: consider the `COMMITTED` allocations of the employee's
    own team whose half-open week window contains **every** ISO week touched by the
    requested closed date range, and keep only those whose zone's `allocation_state` is
    `OPEN` or `TIGHT` — a `FROZEN` zone and any `RESERVED` or `RELEASED` allocation are
    excluded."
    PRD 3.8: "If the candidate pool is empty the call is refused with
    `ERR_NO_ELIGIBLE_DESK` (409)."
    PRD 3.8: "`RESERVED` and `RELEASED` allocations contribute nothing to any week's
    load."
    PRD 3.8: "Committing an allocation is what actually consumes capacity, and only a
    `COMMITTED` allocation counts anywhere."
    PRD 3.8: "The winner becomes the assignment's `seat_allocation_id` and `desk_index`,
    and the row is created in `ASSIGNED` status with `assignment_mode` `AUTO`."

    Design: Difficulty/cross_entity_state_dependency/auto_desk_requires_committed_allocation_of_the_employees_own_team
    """
    scenario = _a_slice_reserved_but_not_yet_committed()
    allocation = scenario["allocation"]
    assert allocation["status"] == "RESERVED"
    assert scenario["own_team"]["entitled_seats"] == 10
    assert read_neighborhood(scenario["zone"]["id"])["peak_committed_seats"] == 0, (
        "a reservation loads no week, which is why the selector cannot see it"
    )

    validate_error(
        api_client.auto_assign_desk(
            auto_desk_payload(
                scenario["insider"]["id"], "2026-09-07", "2026-09-11"
            ),
            WPO,
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_DESK.value,
        409,
    )

    committed = commit_allocation(allocation["id"])
    assert committed["status"] == "COMMITTED"

    placed = auto_assign(scenario["insider"]["id"], "2026-09-07", "2026-09-11")
    assert placed["seat_allocation_id"] == allocation["id"], (
        "the caller named no allocation; the selector found the only committed one"
    )
    assert placed["desk_index"] == 1, "the lowest index of the anchor-matching zone"
    assert placed["status"] == "ASSIGNED"
    assert placed["assignment_mode"] == "AUTO"
    assert placed["vacated_at"] is None
    assert placed["start_date"] == "2026-09-07"
    assert placed["end_date"] == "2026-09-11"
    assert read_allocation(allocation["id"])["status"] == "COMMITTED", (
        "seating an occupant does not move the allocation it hangs off"
    )


def test_04_neither_path_reaches_a_desk_that_belongs_to_another_team_or_another_week():
    """A foreign team is invisible to the selector and unwelcome even when it points.

    PRD 3.8: "Eligibility first: consider the `COMMITTED` allocations of the employee's
    own team whose half-open week window contains **every** ISO week touched by the
    requested closed date range, and keep only those whose zone's `allocation_state` is
    `OPEN` or `TIGHT` — a `FROZEN` zone and any `RESERVED` or `RELEASED` allocation are
    excluded."
    PRD 3.8: "If the candidate pool is empty the call is refused with
    `ERR_NO_ELIGIBLE_DESK` (409)."
    PRD 3.8: "The employee must be on the allocation's team and the `desk_index` must
    fall inside the zone's declared band, or the request is refused with
    `ERR_TEAM_ALLOCATION_MISMATCH` (409)."
    PRD 3.8: "Every ISO week touched by the closed occupancy interval must fall inside
    the allocation's half-open week window; a request whose `end_date` lands in the exact
    week named by `window_end_week` is **outside** the window, because that bound is
    exclusive, and is refused with `ERR_ASSIGNMENT_OUTSIDE_WINDOW` (409)."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
    `meta`, where `total_count` is the number of rows matching the filters before the
    window is applied and `has_more` is true exactly when rows remain after the returned
    window."

    Design: Difficulty/cross_entity_state_dependency/auto_desk_requires_committed_allocation_of_the_employees_own_team
    """
    scenario = _a_slice_reserved_but_not_yet_committed()
    allocation_id = scenario["allocation"]["id"]
    outsider_id = scenario["outsider"]["id"]
    commit_allocation(allocation_id)
    seated = auto_assign(scenario["insider"]["id"], "2026-09-07", "2026-09-11")
    assert seated["desk_index"] == 1

    validate_error(
        api_client.auto_assign_desk(
            auto_desk_payload(outsider_id, "2026-09-07", "2026-09-11"), WPO
        ),
        ApiErrorId.ERR_NO_ELIGIBLE_DESK.value,
        409,
    )
    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(
                allocation_id, outsider_id, 12,
                start_date="2026-09-07", end_date="2026-09-11",
            ),
            WPO,
        ),
        ApiErrorId.ERR_TEAM_ALLOCATION_MISMATCH.value,
        409,
    )
    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(
                allocation_id, scenario["insider"]["id"], 12,
                start_date="2026-10-05", end_date="2026-10-09",
            ),
            WPO,
        ),
        ApiErrorId.ERR_ASSIGNMENT_OUTSIDE_WINDOW.value,
        409,
    )

    _, outsider_meta = list_all(
        api_client.list_desk_assignments, WPO, {"employee_id": outsider_id}
    )
    assert outsider_meta["total_count"] == 0, "neither path seated the foreign employee"
    rows, allocation_meta = list_all(
        api_client.list_desk_assignments, WPO,
        {"seat_allocation_id": allocation_id},
    )
    assert allocation_meta["total_count"] == 1, "only the automatic placement survived"
    assert rows[0]["id"] == seated["id"]


def test_05_a_second_vacate_is_refused_and_does_not_re_stamp_the_first_one():
    """The desk empties once, at the instant it emptied, and the seats stay paid for.

    PRD 3.8: "Vacating a desk requires `ASSIGNED` status — a second vacate, or a vacate
    of an already-`VACATED` row, is refused with `ERR_ASSIGNMENT_NOT_ACTIVE` (409)."
    PRD 3.8: "It sets `status` to `VACATED`, stamps `vacated_at` at the current logical
    instant, and immediately makes that `desk_index` available again to the automatic
    selector for overlapping date ranges, subject to the changeover buffer."
    PRD 2.6: "A caller of any role may rebind it by supplying a `current_utc` instant;
    that call returns 200, mutates no entity, and triggers no recomputation — it only
    changes what "now" means for subsequent requests."
    PRD 2.4: "`version` is an integer that starts at 1 when the row is created and
    increments by exactly 1 on every mutation of that row, including mutations a cascade
    performs rather than the caller."
    PRD 3.8: "Take the base seat rate of 4,333 cents per seat per week, multiply by
    `allocated_seats`, multiply by `weeks_in_window`, then apply the team's volume
    discount as a basis-point factor keyed on its `expected_days_in_office_per_week`: a
    five-day team pays the full 10,000 basis points, a four-day team 9,500, a three-day
    team 9,000, and a team at two, one or zero days 8,500."

    Design: Corner/state_machines/desk_assignment_vacate_twice_returns_assignment_not_active
    """
    scenario = _one_committed_slice_and_a_stranger(
        "FY27-CRN28", seat_count=30, allocated_seats=5
    )
    allocation_id = scenario["allocation"]["id"]
    seated = assign_desk(
        allocation_id, scenario["insider"]["id"], 3, "2026-09-07", "2026-09-11"
    )
    assert seated["status"] == "ASSIGNED"
    assert seated["version"] == 1

    vacated = vacate_desk(seated["id"])
    assert vacated["status"] == "VACATED"
    assert vacated["assignment_mode"] == "MANUAL"
    assert same_instant(vacated["vacated_at"], PINNED_CLOCK_INSTANT)
    assert vacated["version"] == seated["version"] + 1

    pin_clock(LATER_INSTANT)
    validate_error(
        api_client.vacate_desk_assignment(seated["id"], WPO),
        ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE.value,
        409,
    )
    unchanged = get_success_data(api_client.get_desk_assignment(seated["id"], WPO))
    assert same_instant(unchanged["vacated_at"], PINNED_CLOCK_INSTANT), (
        "the refusal did not re-stamp the departure with the advanced clock"
    )
    assert not same_instant(unchanged["vacated_at"], LATER_INSTANT)
    assert unchanged["version"] == vacated["version"], "one mutation, one version bump"

    _, meta = list_all(
        api_client.list_desk_assignments, WPO,
        {"seat_allocation_id": allocation_id, "status": "VACATED"},
    )
    assert meta["total_count"] == 1

    allocation = read_allocation(allocation_id)
    assert allocation["status"] == "COMMITTED", "seats are charged to the line, not the occupant"
    assert allocation["weeks_in_window"] == 3
    assert allocation["line_chargeback_cents"] == 58496, "a raw 58,495.5 rounded half up"
    assert read_neighborhood(scenario["zone"]["id"])["peak_committed_seats"] == 5


def test_06_the_selector_prefers_the_busier_anchor_zone_and_reuses_a_freed_index():
    """Anchor match beats lower utilization, and a vacated desk returns at its own index.

    PRD 3.8: "Otherwise the candidates are ranked: zones whose `anchor_team_id` is the
    employee's own team come first; among those, lower `utilization_pct` comes first;
    among those, lower `desk_index` comes first; remaining ties break on the zone's
    `created_at` ascending and then the allocation's `created_at` ascending."
    PRD 3.8: "No random value and no entity `id` participates in the ranking, so the same
    world always yields the same desk."
    PRD 3.8: "`utilization_pct` is 100 multiplied by `peak_committed_seats`, divided by
    usable capacity, rounded half up to two decimals."
    PRD 3.8: "And `allocation_state` is `FROZEN` whenever the parent cycle's posture is
    `LOCKED`; otherwise `TIGHT` when `utilization_pct` has reached 90.00; otherwise
    `OPEN`."
    PRD 3.8: "Then, for each surviving allocation and each desk index in its zone's band,
    the pair is a candidate only when no `ASSIGNED` assignment on that zone and index
    fails the one-day changeover predicate above against the requested dates."
    PRD 3.8: "The winner becomes the assignment's `seat_allocation_id` and `desk_index`,
    and the row is created in `ASSIGNED` status with `assignment_mode` `AUTO`."

    Design: Corner/calculations/auto_desk_selection_prefers_the_anchor_team_over_lower_utilization
    """
    world = _a_busy_anchor_zone_and_an_emptier_neighbour()
    anchor_zone = read_neighborhood(world["anchor_zone"]["id"])
    foreign_zone = read_neighborhood(world["foreign_zone"]["id"])
    assert anchor_zone["utilization_pct"] == 66.67, "six of nine usable seats"
    assert foreign_zone["utilization_pct"] == 22.22, "two of nine usable seats"
    assert anchor_zone["allocation_state"] == "OPEN"
    assert foreign_zone["allocation_state"] == "OPEN"

    first = auto_assign(world["people"][0]["id"], "2026-09-07", "2026-09-11")
    assert first["seat_allocation_id"] == world["anchor_line"]["id"], (
        "the crowded home zone outranks the emptier foreign one"
    )
    assert first["desk_index"] == 1
    assert first["assignment_mode"] == "AUTO"
    assert first["status"] == "ASSIGNED"
    assert first["start_date"] == "2026-09-07"
    assert first["end_date"] == "2026-09-11"

    second = auto_assign(world["people"][1]["id"], "2026-09-07", "2026-09-11")
    assert second["seat_allocation_id"] == world["anchor_line"]["id"], (
        "a taken desk does not push the selector out of the anchor zone"
    )
    assert second["desk_index"] == 2, "the next-lowest index in the same band"

    vacate_desk(first["id"])
    third = auto_assign(world["people"][2]["id"], "2026-09-07", "2026-09-11")
    assert third["desk_index"] == 1, (
        "index 1 re-entered the pool and still outranks the untouched index 3"
    )
    assert third["seat_allocation_id"] == world["anchor_line"]["id"]

    rows, meta = list_all(
        api_client.list_desk_assignments, WPO,
        {"employee_id": world["people"][2]["id"], "status": "ASSIGNED"},
    )
    assert meta["total_count"] == 1
    assert rows[0]["desk_index"] == 1
    _, foreign_meta = list_all(
        api_client.list_desk_assignments, WPO,
        {"seat_allocation_id": world["foreign_line"]["id"]},
    )
    assert foreign_meta["total_count"] == 0, "the foreign zone was never selected"


def test_07_a_manual_assignment_dereferences_both_ends_before_it_believes_either():
    """Two unknown ids, two two-hop refusals, and only then the last desk in the band.

    PRD 2.5: "Path parameters and payload foreign keys are resolved left to right, path
    segments before body fields, and the first identifier that fails to resolve
    determines the error."
    PRD 2.5: "Each entity has its own not-found code, all at HTTP 404:
    `ERR_POLICY_CYCLE_NOT_FOUND`, `ERR_TEAM_NOT_FOUND`, `ERR_EMPLOYEE_NOT_FOUND`,
    `ERR_CLASSIFICATION_NOT_FOUND`, `ERR_ATTENDANCE_WEEK_NOT_FOUND`,
    `ERR_COMPLIANCE_SIGNAL_NOT_FOUND`, `ERR_EXCEPTION_REQUEST_NOT_FOUND`,
    `ERR_RELOCATION_REQUEST_NOT_FOUND`, `ERR_NEIGHBORHOOD_NOT_FOUND`,
    `ERR_SEAT_ALLOCATION_NOT_FOUND`, `ERR_DESK_ASSIGNMENT_NOT_FOUND`,
    `ERR_ESCALATION_CASE_NOT_FOUND` and `ERR_RECALIBRATION_REVIEW_NOT_FOUND`."
    PRD 3.8: "A desk is assigned manually by a `WorkplaceProgramOffice` operator or a
    `PeopleManager`, naming the `seat_allocation_id`, the `employee_id`, the `desk_index`,
    and the inclusive occupancy dates `start_date` and `end_date`."
    PRD 3.8: "The employee must be on the allocation's team and the `desk_index` must
    fall inside the zone's declared band, or the request is refused with
    `ERR_TEAM_ALLOCATION_MISMATCH` (409)."
    PRD 3.8: "A successful assignment starts in `ASSIGNED` status with `assignment_mode`
    `MANUAL` and `vacated_at` null."

    Design: Corner/endpoints/manual_desk_assignment_validates_both_ends_of_the_junction
    """
    scenario = _one_committed_slice_and_a_stranger("FY27-CRN54")
    allocation_id = scenario["allocation"]["id"]
    insider_id = scenario["insider"]["id"]

    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(UNKNOWN_SEAT_ALLOCATION_ID, insider_id, 1),
            WPO,
        ),
        ApiErrorId.ERR_SEAT_ALLOCATION_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(allocation_id, UNKNOWN_EMPLOYEE_ID, 1), WPO
        ),
        ApiErrorId.ERR_EMPLOYEE_NOT_FOUND.value,
        404,
    )
    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(allocation_id, scenario["outsider"]["id"], 1), WPO
        ),
        ApiErrorId.ERR_TEAM_ALLOCATION_MISMATCH.value,
        409,
    )
    validate_error(
        api_client.create_desk_assignment(
            desk_assignment_payload(allocation_id, insider_id, 14), WPO
        ),
        ApiErrorId.ERR_TEAM_ALLOCATION_MISMATCH.value,
        409,
    )

    seated = get_success_data(
        api_client.create_desk_assignment(
            desk_assignment_payload(allocation_id, insider_id, 13), WPO
        ),
        201,
    )
    assert seated["desk_index"] == 13, "the last index of the band 1..13 is inside it"
    assert seated["assignment_mode"] == "MANUAL"
    assert seated["status"] == "ASSIGNED"
    assert seated["vacated_at"] is None

    _, meta = list_all(
        api_client.list_desk_assignments, WPO,
        {"seat_allocation_id": allocation_id, "status": "ASSIGNED"},
    )
    assert meta["total_count"] == 1, "the four refusals created nothing"
    assert read_neighborhood(scenario["zone"]["id"])["peak_committed_seats"] == 4, (
        "desk-level activity never moves the zone's committed load"
    )
