"""Reserving and committing seats: half-open week windows, capacity and entitlement."""
from test_helpers import (
    ApiErrorId,
    api_client,
    commit_allocation,
    create_cycle,
    create_neighborhood,
    create_team,
    list_all,
    pin_clock,
    read_allocation,
    read_neighborhood,
    release_allocation,
    release_payload,
    reserve_allocation,
    seat_allocation_payload,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import WPO

CAPACITY_CYCLE = {
    "effective_from": "2026-09-01",
    "effective_to": "2026-12-31",
    "days_in_office_floor": 1,
    "badge_weight": 0.60,
    "network_weight": 0.40,
    "collaboration_target_score": 70.00,
    "equity_variance_threshold_pct": 20.00,
}

WIDE_TEAM = {
    "team_code": "T3-BIG",
    "expected_days_in_office_per_week": 1,
    "core_collaboration_days": ["WED"],
    "headcount_planned": 250,
    "signal_corroboration_required": False,
}

CORE_TEAM = {
    "team_code": "T1-CORE",
    "expected_days_in_office_per_week": 3,
    "core_collaboration_days": ["TUE", "WED", "THU"],
    "headcount_planned": 12,
    "signal_corroboration_required": False,
}


def _zone_for_a_wide_team(cycle_label, headcount_planned=250,
                          neighborhood_code="N-C1"):
    """A thirty-seat zone with a four-seat buffer, so usable capacity is 26."""
    pin_clock()
    cycle = create_cycle(cycle_label=cycle_label, **CAPACITY_CYCLE)
    team_kwargs = dict(WIDE_TEAM)
    team_kwargs["headcount_planned"] = headcount_planned
    team = create_team(cycle["id"], **team_kwargs)
    zone = create_neighborhood(
        cycle["id"], team["id"], neighborhood_code=neighborhood_code,
        site_code="NYC-01", seat_count=30, buffer_seats=4,
        desk_index_from=1, desk_index_to=30,
    )
    return {"cycle": cycle, "team": team, "zone": zone}


def _zone_for_the_core_team(cycle_label, neighborhood_code="N-A1"):
    """The small team whose entitlement, not the zone, is the binding ceiling."""
    pin_clock()
    cycle_kwargs = dict(CAPACITY_CYCLE)
    cycle_kwargs["days_in_office_floor"] = 2
    cycle = create_cycle(cycle_label=cycle_label, **cycle_kwargs)
    team = create_team(cycle["id"], **CORE_TEAM)
    zone = create_neighborhood(
        cycle["id"], team["id"], neighborhood_code=neighborhood_code,
        site_code="NYC-01", seat_count=30, buffer_seats=4,
        desk_index_from=1, desk_index_to=30,
    )
    return {"cycle": cycle, "team": team, "zone": zone}


def test_01_touching_half_open_windows_never_sum_into_the_same_week():
    """Two ten-seat allocations meeting at 2026-W40 leave the peak load at ten.

    PRD 3.8: "Seat allocations are reserved by naming the `neighborhood_id`, the
    `team_id`, the `allocated_seats` as an integer from 1 through 500, the half-open
    week window `window_start_week` and `window_end_week`, and the stale-version guard
    `expected_neighborhood_version` of §2.8."
    PRD 3.8: "A successful reservation lands in `RESERVED` status with `release_reason`
    null, `line_chargeback_cents` at 0, and `weeks_in_window` set to the number of ISO
    weeks in the half-open interval — the ordinal of `window_end_week` minus the ordinal
    of `window_start_week`."
    PRD 3.8: "The load of a given week is the sum of `allocated_seats` over the zone's
    `COMMITTED` allocations whose half-open window covers that week — that is, whose
    `window_start_week` ordinal is at most the week's ordinal and whose
    `window_end_week` ordinal is strictly greater than it."
    PRD 3.8: "`utilization_pct` is 100 multiplied by `peak_committed_seats`, divided by
    usable capacity, rounded half up to two decimals."
    PRD 3.8: "`committed_seats` is the load of the ISO week the logical clock currently
    sits in, or 0 when that week falls outside the cycle window."

    Design: Difficulty/resource_temporal_overlap/seat_allocation_half_open_week_aggregate_overlap_matrix
    """
    scenario = _zone_for_a_wide_team("FY27-RT1")
    team_id = scenario["team"]["id"]
    zone_id = scenario["zone"]["id"]
    assert scenario["team"]["entitled_seats"] == 53, (
        "fifty base seats plus a six-percent buffer, so entitlement never binds here"
    )
    assert scenario["zone"]["peak_committed_seats"] == 0
    assert scenario["zone"]["utilization_pct"] == 0.00
    assert scenario["zone"]["allocation_state"] == "OPEN"

    early = reserve_allocation(zone_id, team_id, 10, "2026-W37", "2026-W40")
    assert early["status"] == "RESERVED"
    assert early["release_reason"] is None
    assert early["line_chargeback_cents"] == 0
    assert early["weeks_in_window"] == 3, "W37, W38 and W39 — the end week is excluded"

    late = reserve_allocation(zone_id, team_id, 10, "2026-W40", "2026-W43")
    assert late["weeks_in_window"] == 3, "W40, W41 and W42"

    assert commit_allocation(early["id"])["status"] == "COMMITTED"
    assert commit_allocation(late["id"])["status"] == "COMMITTED"

    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 10, (
        "2026-W40 belongs to the later allocation only, so the two never sum"
    )
    assert zone["utilization_pct"] == 38.46, "one hundred times ten over twenty-six"
    assert zone["committed_seats"] == 0, (
        "the logical clock sits in 2026-W36, ahead of both windows"
    )
    assert zone["allocation_state"] == "OPEN"


def test_02_a_straddling_window_sums_against_both_neighbours_and_the_worst_week_decides():
    """Ten plus ten leaves room for five in 2026-W39 but not for seven.

    PRD 3.8: "The capacity gate is aggregate, per week, and half-open: for every ISO
    week in this allocation's window, the sum of `allocated_seats` over the **other**
    `COMMITTED` allocations on the same zone whose own half-open windows cover that
    week, plus this allocation's seats, must not exceed the zone's usable capacity of
    `seat_count` minus `buffer_seats`."
    PRD 3.8: "Landing exactly on capacity is permitted; exceeding it in even one week is
    refused with `ERR_NEIGHBORHOOD_CAPACITY_EXCEEDED` (409)."
    PRD 3.8: "Each individual allocation may sit comfortably inside capacity — it is
    only the overlapping sum that breaches it."
    PRD 3.8: "And `allocation_state` is `FROZEN` whenever the parent cycle's posture is
    `LOCKED`; otherwise `TIGHT` when `utilization_pct` has reached 90.00; otherwise
    `OPEN`."

    Design: Difficulty/resource_temporal_overlap/seat_allocation_half_open_week_aggregate_overlap_matrix
    """
    scenario = _zone_for_a_wide_team("FY27-RT1")
    team_id = scenario["team"]["id"]
    zone_id = scenario["zone"]["id"]
    early = reserve_allocation(zone_id, team_id, 10, "2026-W37", "2026-W40")
    late = reserve_allocation(zone_id, team_id, 10, "2026-W40", "2026-W43")
    straddling = reserve_allocation(zone_id, team_id, 10, "2026-W39", "2026-W41")
    too_wide = reserve_allocation(zone_id, team_id, 7, "2026-W39", "2026-W40")
    exact = reserve_allocation(zone_id, team_id, 5, "2026-W39", "2026-W40")
    assert straddling["weeks_in_window"] == 2
    assert too_wide["weeks_in_window"] == 1
    assert exact["weeks_in_window"] == 1

    commit_allocation(early["id"])
    commit_allocation(late["id"])
    commit_allocation(straddling["id"])
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 20, (
        "W39 carries the early allocation plus the straddler, W40 the later one plus it"
    )
    assert zone["utilization_pct"] == 76.92

    validate_error(
        api_client.commit_seat_allocation(too_wide["id"], WPO),
        ApiErrorId.ERR_NEIGHBORHOOD_CAPACITY_EXCEEDED.value,
        409,
    )
    refused = read_allocation(too_wide["id"])
    assert refused["status"] == "RESERVED", "twenty-seven seats in W39 is one too many"
    assert refused["line_chargeback_cents"] == 0

    assert commit_allocation(exact["id"])["status"] == "COMMITTED", (
        "the refused commit consumed nothing, so W39 was still carrying twenty seats"
    )
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 25, "one seat below usable capacity"
    assert zone["utilization_pct"] == 96.15
    assert zone["allocation_state"] == "TIGHT", "96.15 has reached the 90.00 threshold"
    assert zone["committed_seats"] == 0

    rows, meta = list_all(
        api_client.list_seat_allocations, WPO,
        {"neighborhood_id": zone_id, "status": "COMMITTED"},
    )
    assert meta["total_count"] == 4, "everything but the refused seven-seat allocation"
    assert {row["id"] for row in rows} == {
        early["id"], late["id"], straddling["id"], exact["id"]
    }


def test_03_a_weekly_aggregate_landing_exactly_on_usable_capacity_commits():
    """Twenty plus six is twenty-six, which drives utilization to 100.00 and the zone TIGHT.

    PRD 3.8: "Landing exactly on capacity is permitted; exceeding it in even one week is
    refused with `ERR_NEIGHBORHOOD_CAPACITY_EXCEEDED` (409)."
    PRD 3.8: "`peak_committed_seats` is the largest such weekly load anywhere in the
    cycle window, or 0 when the cycle window contains no weeks at all."
    PRD 3.8: "`utilization_pct` is 100 multiplied by `peak_committed_seats`, divided by
    usable capacity, rounded half up to two decimals."
    PRD 3.8: "And `allocation_state` is `FROZEN` whenever the parent cycle's posture is
    `LOCKED`; otherwise `TIGHT` when `utilization_pct` has reached 90.00; otherwise
    `OPEN`."

    Design: Difficulty/boundary_precision_check/neighborhood_capacity_exact_fit_allowed_one_over_refused
    """
    scenario = _zone_for_a_wide_team(
        "FY27-BP3", headcount_planned=125, neighborhood_code="N-B1"
    )
    team_id = scenario["team"]["id"]
    zone_id = scenario["zone"]["id"]
    assert scenario["team"]["expected_daily_attendance"] == 25
    assert scenario["team"]["base_entitlement"] == 25
    assert scenario["team"]["buffer_seats_entitled"] == 3
    assert scenario["team"]["entitled_seats"] == 28, (
        "well above every seat count below, so the entitlement rule never binds"
    )

    bulk = reserve_allocation(zone_id, team_id, 20, "2026-W37", "2026-W41")
    top_up = reserve_allocation(zone_id, team_id, 6, "2026-W39", "2026-W43")

    commit_allocation(bulk["id"])
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 20
    assert zone["utilization_pct"] == 76.92
    assert zone["allocation_state"] == "OPEN", "76.92 has not reached 90.00"
    assert zone["committed_seats"] == 0, (
        "the current-week figure is 2026-W36, which no window covers"
    )

    assert commit_allocation(top_up["id"])["status"] == "COMMITTED", (
        "W39 and W40 each carry twenty plus six, exactly the usable capacity"
    )
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 26
    assert zone["utilization_pct"] == 100.00
    assert zone["allocation_state"] == "TIGHT"


def test_04_one_seat_above_capacity_in_a_single_week_is_refused_and_leaves_no_trace():
    """The twenty-seventh seat in 2026-W40 is refused, while 2026-W41 still has room.

    PRD 3.8: "The capacity gate is aggregate, per week, and half-open: for every ISO
    week in this allocation's window, the sum of `allocated_seats` over the **other**
    `COMMITTED` allocations on the same zone whose own half-open windows cover that
    week, plus this allocation's seats, must not exceed the zone's usable capacity of
    `seat_count` minus `buffer_seats`."
    PRD 3.8: "Landing exactly on capacity is permitted; exceeding it in even one week is
    refused with `ERR_NEIGHBORHOOD_CAPACITY_EXCEEDED` (409)."
    PRD 3.8: "A successful reservation lands in `RESERVED` status with `release_reason`
    null, `line_chargeback_cents` at 0, and `weeks_in_window` set to the number of ISO
    weeks in the half-open interval — the ordinal of `window_end_week` minus the ordinal
    of `window_start_week`."
    PRD 3.8: "The load of a given week is the sum of `allocated_seats` over the zone's
    `COMMITTED` allocations whose half-open window covers that week — that is, whose
    `window_start_week` ordinal is at most the week's ordinal and whose
    `window_end_week` ordinal is strictly greater than it."

    Design: Difficulty/boundary_precision_check/neighborhood_capacity_exact_fit_allowed_one_over_refused
    """
    scenario = _zone_for_a_wide_team(
        "FY27-BP3", headcount_planned=125, neighborhood_code="N-B1"
    )
    team_id = scenario["team"]["id"]
    zone_id = scenario["zone"]["id"]
    bulk = reserve_allocation(zone_id, team_id, 20, "2026-W37", "2026-W41")
    top_up = reserve_allocation(zone_id, team_id, 6, "2026-W39", "2026-W43")
    one_over = reserve_allocation(zone_id, team_id, 1, "2026-W40", "2026-W41")
    assert bulk["weeks_in_window"] == 4, "W37 through W40"
    assert top_up["weeks_in_window"] == 4, "W39 through W42"
    assert one_over["weeks_in_window"] == 1

    commit_allocation(bulk["id"])
    commit_allocation(top_up["id"])
    validate_error(
        api_client.commit_seat_allocation(one_over["id"], WPO),
        ApiErrorId.ERR_NEIGHBORHOOD_CAPACITY_EXCEEDED.value,
        409,
    )
    still_reserved = read_allocation(one_over["id"])
    assert still_reserved["status"] == "RESERVED"
    assert still_reserved["line_chargeback_cents"] == 0
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 26, "the refused commit moved no derived field"
    assert zone["utilization_pct"] == 100.00

    late = reserve_allocation(zone_id, team_id, 20, "2026-W41", "2026-W42")
    assert commit_allocation(late["id"])["status"] == "COMMITTED", (
        "2026-W41 carries only the six-seat allocation, because the twenty-seat "
        "window excludes its own end week"
    )
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 26


def test_05_a_stale_zone_version_outranks_the_team_entitlement_ceiling():
    """One create breaks both rules and the answer is the 412, not the 409.

    PRD 2.8: "`POST /seat-allocations` must carry `expected_neighborhood_version`, equal
    to the current `version` of the `Neighborhood` named by `neighborhood_id`."
    PRD 2.8: "A second allocation on the same zone is perfectly legitimate product
    behaviour, so the parent's `version` is the only deterministic guard against a client
    reserving seats against a capacity picture that has since moved; a mismatch is
    rejected with `ERR_STALE_NEIGHBORHOOD_VERSION` (412)."
    PRD 2.10: "Checks are grouped into precedence bands and evaluated from the top of
    this list downwards; the first band that produces a violation supplies the response,
    and later bands are never reached."
    PRD 2.10: "A seat-allocation create whose window is inverted *and* whose seats exceed
    the team's entitlement reports `ERR_INVALID_INTERVAL` (422), because interval
    well-formedness outranks aggregate capacity, and one that is merely stale as well as
    over-entitlement reports `ERR_STALE_NEIGHBORHOOD_VERSION` (412)."

    Design: Difficulty/priority_pair_validation_conflict/stale_neighborhood_version_outranks_seat_entitlement
    """
    scenario = _zone_for_the_core_team("FY27-PP1")
    team = scenario["team"]
    zone_id = scenario["zone"]["id"]
    assert team["expected_daily_attendance"] == 8
    assert team["base_entitlement"] == 8
    assert team["buffer_seats_entitled"] == 2
    assert team["entitled_seats"] == 10

    observed_version = scenario["zone"]["version"]
    held = reserve_allocation(
        zone_id, team["id"], 5, "2026-W37", "2026-W41",
        expected_neighborhood_version=observed_version,
    )
    assert held["status"] == "RESERVED"
    assert read_neighborhood(zone_id)["version"] == observed_version + 1, (
        "the reservation advanced the parent zone, so the observed version is now stale"
    )

    validate_error(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, team["id"], observed_version, allocated_seats=30,
                window_start_week="2026-W38", window_end_week="2026-W40",
            ),
            WPO,
        ),
        ApiErrorId.ERR_STALE_NEIGHBORHOOD_VERSION.value,
        412,
    )
    rows, meta = list_all(
        api_client.list_seat_allocations, WPO, {"neighborhood_id": zone_id}
    )
    assert meta["total_count"] == 1, "the refused create wrote no row"
    assert rows[0]["id"] == held["id"]
    assert read_neighborhood(zone_id)["version"] == observed_version + 1, (
        "and it did not advance the zone either"
    )


def test_06_a_fresh_version_exposes_the_entitlement_breach_and_an_exact_fit_reserves():
    """Thirty seats against an entitlement of ten is the 409 that the 412 was hiding.

    PRD 3.8: "And the team's entitlement is enforced week by week: for every ISO week in
    the requested window, the sum of `allocated_seats` over that team's non-`RELEASED`
    allocations covering that week, plus the requested seats, must not exceed the team's
    `entitled_seats`; a breach in any single week is refused with
    `ERR_SEAT_ENTITLEMENT_EXCEEDED` (409)."
    PRD 3.8: "A successful reservation lands in `RESERVED` status with `release_reason`
    null, `line_chargeback_cents` at 0, and `weeks_in_window` set to the number of ISO
    weeks in the half-open interval — the ordinal of `window_end_week` minus the ordinal
    of `window_start_week`."
    PRD 3.8: "It also advances the parent neighborhood's `version` by one."
    PRD 3.1: "Step five: `entitled_seats` is `base_entitlement` plus
    `buffer_seats_entitled`, and it is the per-week ceiling on how many seats the team
    may hold."

    Design: Difficulty/priority_pair_validation_conflict/stale_neighborhood_version_outranks_seat_entitlement
    """
    scenario = _zone_for_the_core_team("FY27-PP1")
    team = scenario["team"]
    zone_id = scenario["zone"]["id"]
    first_version = scenario["zone"]["version"]
    reserve_allocation(
        zone_id, team["id"], 5, "2026-W37", "2026-W41",
        expected_neighborhood_version=first_version,
    )
    current_version = read_neighborhood(zone_id)["version"]
    assert current_version == first_version + 1

    validate_error(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, team["id"], current_version, allocated_seats=30,
                window_start_week="2026-W38", window_end_week="2026-W40",
            ),
            WPO,
        ),
        ApiErrorId.ERR_SEAT_ENTITLEMENT_EXCEEDED.value,
        409,
    )
    assert read_neighborhood(zone_id)["version"] == current_version, (
        "a refused create advances nothing"
    )

    exact_fit = validate_success(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_id, team["id"], current_version, allocated_seats=5,
                window_start_week="2026-W38", window_end_week="2026-W40",
            ),
            WPO,
        ),
        201,
    )
    assert exact_fit["status"] == "RESERVED", (
        "five held seats plus five requested is exactly the entitlement of ten"
    )
    assert exact_fit["weeks_in_window"] == 2
    assert exact_fit["line_chargeback_cents"] == 0

    rows, meta = list_all(
        api_client.list_seat_allocations, WPO, {"neighborhood_id": zone_id}
    )
    assert meta["total_count"] == 2, "only the two accepted reservations exist"
    assert len(rows) == 2
    assert read_neighborhood(zone_id)["version"] == first_version + 2


def test_07_commit_demands_a_reserved_row_while_release_is_legal_from_both_live_states():
    """A second commit names the state it needed; anything aimed at a released row is terminal.

    PRD 3.8: "Commit requires `RESERVED` status: an allocation already `COMMITTED` is
    refused with `ERR_ALLOCATION_NOT_RESERVED` (409), while an allocation that has been
    `RELEASED` — a terminal status neither trigger can ever apply to again — is refused
    with `ERR_ALLOCATION_TERMINAL` (409)."
    PRD 3.8: "A successful commit sets `status` to `COMMITTED`, writes the allocation's
    chargeback line, and recomputes the zone's four derived fields."
    PRD 3.8: "Releasing is the compensating action, and it is legal from both `RESERVED`
    and `COMMITTED`; only a `RELEASED` allocation refuses, with
    `ERR_ALLOCATION_TERMINAL`."
    PRD 3.8: "Releasing a merely reserved allocation sets `status` to `RELEASED` and
    records the reason."
    PRD 3.8: "`RESERVED` and `RELEASED` allocations contribute nothing to any week's
    load."
    PRD 3.8: "Take the base seat rate of 4,333 cents per seat per week, multiply by
    `allocated_seats`, multiply by `weeks_in_window`, then apply the team's volume
    discount as a basis-point factor keyed on its `expected_days_in_office_per_week`: a
    five-day team pays the full 10,000 basis points, a four-day team 9,500, a three-day
    team 9,000, and a team at two, one or zero days 8,500."

    Design: Corner/state_machines/seat_allocation_commit_is_not_idempotent_and_release_from_reserved_is_legal
    """
    scenario = _zone_for_the_core_team("FY27-CRN27", neighborhood_code="N-1")
    team = scenario["team"]
    zone_id = scenario["zone"]["id"]
    assert team["team_code"] == "T1-CORE"
    early = reserve_allocation(zone_id, team["id"], 5, "2026-W37", "2026-W39")
    late = reserve_allocation(zone_id, team["id"], 5, "2026-W39", "2026-W41")

    committed = commit_allocation(early["id"])
    assert committed["status"] == "COMMITTED"
    assert committed["weeks_in_window"] == 2
    assert committed["line_chargeback_cents"] == 38997, (
        "four thousand three hundred and thirty-three cents for five seats over two "
        "weeks, discounted by the three-day bracket of 9,000 basis points"
    )
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 5
    assert zone["utilization_pct"] == 19.23
    assert zone["committed_seats"] == 0

    validate_error(
        api_client.commit_seat_allocation(early["id"], WPO),
        ApiErrorId.ERR_ALLOCATION_NOT_RESERVED.value,
        409,
    )
    assert read_allocation(early["id"])["line_chargeback_cents"] == 38997, (
        "the refused second commit charged nothing twice"
    )
    assert read_neighborhood(zone_id)["peak_committed_seats"] == 5

    released = release_allocation(early["id"], "project cancelled")
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "project cancelled"
    assert released["line_chargeback_cents"] == 0
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 0
    assert zone["utilization_pct"] == 0.00

    validate_error(
        api_client.commit_seat_allocation(early["id"], WPO),
        ApiErrorId.ERR_ALLOCATION_TERMINAL.value,
        409,
    )

    abandoned = validate_success(
        api_client.release_seat_allocation(
            late["id"], release_payload("reservation abandoned before commitment"), WPO
        )
    )
    assert abandoned["status"] == "RELEASED", "release needs no prior commit"
    assert abandoned["line_chargeback_cents"] == 0

    rows, meta = list_all(
        api_client.list_seat_allocations, WPO,
        {"neighborhood_id": zone_id, "status": "RELEASED"},
    )
    assert meta["total_count"] == 2
    assert all(row["status"] == "RELEASED" for row in rows)
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 0
    assert zone["allocation_state"] == "OPEN"
