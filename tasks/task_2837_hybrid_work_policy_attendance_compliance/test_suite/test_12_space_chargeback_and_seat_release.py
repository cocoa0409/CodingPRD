"""Pricing committed seats line by line, and giving the seats back again."""
from test_helpers import (
    ApiErrorId,
    api_client,
    assign_desk,
    commit_allocation,
    create_cycle,
    create_neighborhood,
    create_team,
    draft_review,
    get_success_data,
    list_all,
    pin_clock,
    read_allocation,
    read_neighborhood,
    read_review,
    register_employee,
    release_allocation,
    release_payload,
    reserve_allocation,
    same_instant,
    seat_allocation_payload,
    set_posture,
    submit_review,
    validate_error,
)
from test_helpers.fixtures import WPO

SPACE_CYCLE = {
    "effective_from": "2026-09-01",
    "effective_to": "2026-12-31",
    "badge_weight": 0.60,
    "network_weight": 0.40,
    "collaboration_target_score": 70.00,
    "equity_variance_threshold_pct": 20.00,
}

RELEASE_INSTANT = "2026-09-14T09:00:00Z"


def _two_priced_lines_on_one_zone():
    """A four-day team's short window and a two-day team's long one, both committed."""
    pin_clock()
    cycle = create_cycle(
        cycle_label="FY27-CHG", days_in_office_floor=2, **SPACE_CYCLE
    )
    four_day_team = create_team(
        cycle["id"], team_code="T3-OPS", expected_days_in_office_per_week=4,
        core_collaboration_days=["MON", "TUE", "WED", "THU"],
        headcount_planned=20, signal_corroboration_required=False,
    )
    two_day_team = create_team(
        cycle["id"], team_code="T4-LAB", expected_days_in_office_per_week=2,
        core_collaboration_days=["TUE", "THU"],
        headcount_planned=30, signal_corroboration_required=False,
    )
    zone = create_neighborhood(
        cycle["id"], four_day_team["id"], neighborhood_code="N-A1",
        site_code="NYC-01", seat_count=30, buffer_seats=4,
        desk_index_from=1, desk_index_to=30,
    )
    short_line = commit_allocation(
        reserve_allocation(
            zone["id"], four_day_team["id"], 5, "2026-W37", "2026-W39"
        )["id"]
    )
    long_line = commit_allocation(
        reserve_allocation(
            zone["id"], two_day_team["id"], 2, "2026-W37", "2026-W42"
        )["id"]
    )
    return {
        "cycle": cycle,
        "four_day_team": four_day_team,
        "two_day_team": two_day_team,
        "zone": zone,
        "short_line": short_line,
        "long_line": long_line,
    }


def _committed_zone_with_a_desk_and_a_snapshot():
    """Two committed lines, one occupied desk, and a review taken before any release."""
    pin_clock(RELEASE_INSTANT)
    cycle = create_cycle(
        cycle_label="FY27-CI2", days_in_office_floor=1, **SPACE_CYCLE
    )
    team = create_team(
        cycle["id"], team_code="T3-BIG", expected_days_in_office_per_week=1,
        core_collaboration_days=["WED"], headcount_planned=250,
        signal_corroboration_required=False,
    )
    employee = register_employee(
        team["id"], employee_number="E-5001", work_email="e5001@corp.example"
    )
    zone = create_neighborhood(
        cycle["id"], team["id"], neighborhood_code="N-E1", site_code="NYC-01",
        seat_count=30, buffer_seats=4, desk_index_from=1, desk_index_to=30,
    )
    doomed = commit_allocation(
        reserve_allocation(zone["id"], team["id"], 5, "2026-W37", "2026-W39")["id"]
    )
    surviving = commit_allocation(
        reserve_allocation(zone["id"], team["id"], 3, "2026-W39", "2026-W43")["id"]
    )
    desk = assign_desk(doomed["id"], employee["id"], 3, "2026-09-07", "2026-09-11")
    set_posture(cycle["id"], "RECALIBRATING")
    before = submit_review(
        draft_review(cycle["id"], 0, review_label="R-BEFORE")["id"]
    )
    return {
        "cycle": cycle,
        "team": team,
        "employee": employee,
        "zone": zone,
        "doomed": doomed,
        "surviving": surviving,
        "desk": desk,
        "before": before,
    }


def _two_zones_and_an_outsider_team():
    """One cycle carrying two teams and two zones, plus a team from another cycle."""
    pin_clock()
    cycle = create_cycle(
        cycle_label="FY27-CRN11-A", days_in_office_floor=2, **SPACE_CYCLE
    )
    other_cycle = create_cycle(
        cycle_label="FY27-CRN11-B", days_in_office_floor=2, **SPACE_CYCLE
    )
    team_a = create_team(
        cycle["id"], team_code="T-A", expected_days_in_office_per_week=3,
        core_collaboration_days=["TUE", "WED", "THU"], headcount_planned=12,
        signal_corroboration_required=False,
    )
    team_b = create_team(
        cycle["id"], team_code="T-B", expected_days_in_office_per_week=4,
        core_collaboration_days=["MON", "TUE", "WED", "THU"], headcount_planned=25,
        signal_corroboration_required=False,
    )
    outsider = create_team(
        other_cycle["id"], team_code="T-Z", expected_days_in_office_per_week=3,
        core_collaboration_days=["WED"], headcount_planned=12,
        signal_corroboration_required=False,
    )
    zone_one = create_neighborhood(
        cycle["id"], team_a["id"], neighborhood_code="N-1", site_code="NYC-01",
        seat_count=40, buffer_seats=4, desk_index_from=1, desk_index_to=40,
    )
    zone_two = create_neighborhood(
        cycle["id"], team_b["id"], neighborhood_code="N-2", site_code="NYC-01",
        seat_count=40, buffer_seats=4, desk_index_from=41, desk_index_to=80,
    )
    return {
        "cycle": cycle,
        "other_cycle": other_cycle,
        "team_a": team_a,
        "team_b": team_b,
        "outsider": outsider,
        "zone_one": zone_one,
        "zone_two": zone_two,
    }


def test_01_each_committed_line_is_rounded_on_its_own_at_the_moment_of_commit():
    """Two lines that both land on an exact half cent round up to 41,164 and 36,831.

    PRD 3.8: "**Chargeback** is computed in two steps whose rounding order changes the
    answer, so the order is pinned."
    PRD 3.8: "Step one runs on each commit and writes that allocation's
    `line_chargeback_cents`."
    PRD 3.8: "Take the base seat rate of 4,333 cents per seat per week, multiply by
    `allocated_seats`, multiply by `weeks_in_window`, then apply the team's volume
    discount as a basis-point factor keyed on its `expected_days_in_office_per_week`: a
    five-day team pays the full 10,000 basis points, a four-day team 9,500, a three-day
    team 9,000, and a team at two, one or zero days 8,500."
    PRD 3.8: "Divide that basis-point product by 10,000 and round the result half up to
    a whole number of cents."
    PRD 3.8: "To see why that matters, consider two lines: a four-day team with 5 seats
    over a 2-week window computes 4,333 times 5 times 2 times 9,500, divided by 10,000,
    which is 41,163.5 and rounds to 41,164; and a two-day team with 2 seats over a
    5-week window computes 4,333 times 2 times 5 times 8,500, divided by 10,000, which
    is 36,830.5 and rounds to 36,831."

    Design: Difficulty/combinatorial_formula/chargeback_round_per_line_then_sum
    """
    scenario = _two_priced_lines_on_one_zone()
    assert scenario["four_day_team"]["entitled_seats"] == 18
    assert scenario["two_day_team"]["entitled_seats"] == 14

    short_line = scenario["short_line"]
    long_line = scenario["long_line"]
    assert short_line["status"] == "COMMITTED"
    assert short_line["weeks_in_window"] == 2, "2026-W37 and 2026-W38"
    assert short_line["line_chargeback_cents"] == 41164, (
        "a raw 41,163.5 rounded half up on its own line"
    )
    assert long_line["status"] == "COMMITTED"
    assert long_line["weeks_in_window"] == 5, "2026-W37 through 2026-W41"
    assert long_line["line_chargeback_cents"] == 36831, (
        "a raw 36,830.5 rounded half up on its own line"
    )
    assert read_allocation(short_line["id"])["line_chargeback_cents"] == 41164
    assert read_allocation(long_line["id"])["line_chargeback_cents"] == 36831

    zone = read_neighborhood(scenario["zone"]["id"])
    assert zone["peak_committed_seats"] == 7, (
        "2026-W37 and 2026-W38 carry five seats plus two"
    )
    assert zone["utilization_pct"] == 26.92
    assert zone["allocation_state"] == "OPEN"


def test_02_the_review_total_sums_the_already_rounded_lines_and_never_re_rounds():
    """77,995 is the pinned total; the 77,994 of a single late rounding is wrong.

    PRD 3.8: "Step two, described in §3.9, sums the already-rounded lines and never
    re-rounds."
    PRD 3.8: "The pinned total is 77,995. Summing the unrounded values first would give
    77,994.0 and a total of 77,994, which is wrong."
    PRD 3.9: "Take every seat allocation whose `status` is `COMMITTED` on any
    neighborhood belonging to this policy cycle, order them by `created_at` ascending,
    and sum their `line_chargeback_cents` exactly as those lines were already rounded."
    PRD 3.9: "The sum is written to `total_space_chargeback_cents` and is **never**
    re-rounded — no second rounding step exists anywhere in this calculation."
    PRD 3.9: "A successful submit sets `state` to `SUBMITTED`, records
    `submitted_by_user_id` as the calling `X-User-ID`, and writes four measurements."
    PRD 3.9: "Consider only the cycle's teams that have at least one settled attendance
    week — a week whose `status` is `FINALIZED` or `LOCKED` — for at least one of their
    employees; teams with no settled week are excluded from both the numerator and the
    denominator entirely, and if that leaves no teams the index is exactly 0.00 rather
    than a division by zero."
    PRD 3.9: "When fewer than 2 bands qualify, `equity_variance_pct` is exactly 0.00 —
    not null and not an error — because a spread between fewer than two points is
    meaningless."

    Design: Difficulty/combinatorial_formula/chargeback_round_per_line_then_sum
    """
    scenario = _two_priced_lines_on_one_zone()
    cycle_id = scenario["cycle"]["id"]
    draft = draft_review(cycle_id, 0, review_label="Q4-PASS-1")
    assert draft["state"] == "DRAFT"
    assert draft["total_space_chargeback_cents"] == 0, "a draft carries no measurements"

    set_posture(cycle_id, "RECALIBRATING")
    submitted = submit_review(draft["id"])
    assert submitted["state"] == "SUBMITTED"
    assert submitted["total_space_chargeback_cents"] == 77995, (
        "41,164 plus 36,831, each rounded before the sum"
    )
    assert submitted["total_space_chargeback_cents"] != 77994, (
        "summing the raw 41,163.5 and 36,830.5 and rounding once is the wrong order"
    )
    assert submitted["collaboration_index"] == 0.00, (
        "no attendance week in the cycle is settled, so no team qualifies"
    )
    assert submitted["meets_collaboration_target"] is False
    assert submitted["qualifying_band_count"] == 0, "the cycle holds no employees at all"
    assert submitted["equity_variance_pct"] == 0.00
    assert submitted["equity_flag"] is False
    assert read_review(submitted["id"])["total_space_chargeback_cents"] == 77995


def test_03_releasing_a_committed_line_withdraws_its_own_load_and_vacates_its_desks():
    """The peak falls back to the surviving three seats and the occupied desk empties.

    PRD 3.8: "Releasing is the compensating action, and it is legal from both `RESERVED`
    and `COMMITTED`; only a `RELEASED` allocation refuses, with
    `ERR_ALLOCATION_TERMINAL`."
    PRD 3.8: "Releasing a committed one does that and three things more:
    `line_chargeback_cents` returns to 0, every desk assignment on that allocation whose
    `status` is `ASSIGNED` transitions to `VACATED` with `vacated_at` stamped at the
    current logical instant, and the zone's derived fields are recomputed downward."
    PRD 3.8: "`peak_committed_seats` is the largest such weekly load anywhere in the
    cycle window, or 0 when the cycle window contains no weeks at all."
    PRD 3.8: "`committed_seats` is the load of the ISO week the logical clock currently
    sits in, or 0 when that week falls outside the cycle window."
    PRD 3.8: "`utilization_pct` is 100 multiplied by `peak_committed_seats`, divided by
    usable capacity, rounded half up to two decimals."

    Design: Difficulty/compensating_invariant/seat_release_restores_peak_utilization_and_chargeback
    """
    scenario = _committed_zone_with_a_desk_and_a_snapshot()
    zone_id = scenario["zone"]["id"]
    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 5, "2026-W37 and 2026-W38 carry five seats"
    assert zone["utilization_pct"] == 19.23
    assert zone["committed_seats"] == 5, "the logical clock sits inside 2026-W38"
    assert scenario["desk"]["status"] == "ASSIGNED"
    assert scenario["desk"]["vacated_at"] is None
    assert scenario["desk"]["assignment_mode"] == "MANUAL"

    released = release_allocation(
        scenario["doomed"]["id"], "team consolidated into a different zone"
    )
    assert released["status"] == "RELEASED"
    assert released["release_reason"] == "team consolidated into a different zone"
    assert released["line_chargeback_cents"] == 0

    vacated = get_success_data(
        api_client.get_desk_assignment(scenario["desk"]["id"], WPO)
    )
    assert vacated["status"] == "VACATED", "the release cascaded into the occupied desk"
    assert same_instant(vacated["vacated_at"], RELEASE_INSTANT)

    zone = read_neighborhood(zone_id)
    assert zone["peak_committed_seats"] == 3, "only the surviving allocation still loads"
    assert zone["utilization_pct"] == 11.54
    assert zone["committed_seats"] == 0, (
        "2026-W38 falls outside the surviving allocation's window"
    )
    survivor = read_allocation(scenario["surviving"]["id"])
    assert survivor["status"] == "COMMITTED"
    assert survivor["allocated_seats"] == 3
    assert survivor["weeks_in_window"] == 4
    assert survivor["line_chargeback_cents"] == 44197, "untouched by the other release"


def test_04_the_chargeback_total_loses_exactly_the_released_line_and_a_second_release_refuses():
    """81,028 before, 44,197 after, and the released row is terminal for good.

    PRD 3.9: "Take every seat allocation whose `status` is `COMMITTED` on any
    neighborhood belonging to this policy cycle, order them by `created_at` ascending,
    and sum their `line_chargeback_cents` exactly as those lines were already rounded."
    PRD 3.9: "`RESERVED` and `RELEASED` allocations contribute nothing, because their
    `line_chargeback_cents` is 0."
    PRD 3.8: "The zone's `committed_seats` returns to exactly what it was before the
    commit — that conservation is the guarantee release is held to."
    PRD 3.8: "Releasing is the compensating action, and it is legal from both `RESERVED`
    and `COMMITTED`; only a `RELEASED` allocation refuses, with
    `ERR_ALLOCATION_TERMINAL`."
    PRD 3.8: "Divide that basis-point product by 10,000 and round the result half up to
    a whole number of cents."

    Design: Difficulty/compensating_invariant/seat_release_restores_peak_utilization_and_chargeback
    """
    scenario = _committed_zone_with_a_desk_and_a_snapshot()
    doomed_id = scenario["doomed"]["id"]
    assert scenario["doomed"]["line_chargeback_cents"] == 36831, "a raw 36,830.5"
    assert scenario["surviving"]["line_chargeback_cents"] == 44197, "a raw 44,196.6"
    assert scenario["before"]["total_space_chargeback_cents"] == 81028, (
        "the sum of the two already-rounded lines"
    )

    release_allocation(doomed_id, "team consolidated into a different zone")
    after = submit_review(
        draft_review(scenario["cycle"]["id"], 0, review_label="R-AFTER")["id"]
    )
    assert after["total_space_chargeback_cents"] == 44197, (
        "the released line was withdrawn once and only once"
    )
    assert after["collaboration_index"] == 0.00
    assert after["qualifying_band_count"] == 0
    assert after["equity_variance_pct"] == 0.00
    assert after["equity_flag"] is False

    validate_error(
        api_client.release_seat_allocation(
            doomed_id, release_payload("duplicate release attempt"), WPO
        ),
        ApiErrorId.ERR_ALLOCATION_TERMINAL.value,
        409,
    )
    still_released = read_allocation(doomed_id)
    assert still_released["status"] == "RELEASED"
    assert still_released["release_reason"] == "team consolidated into a different zone"
    assert read_neighborhood(scenario["zone"]["id"])["peak_committed_seats"] == 3


def test_05_a_seat_allocation_joins_teams_to_zones_from_either_side_inside_one_cycle():
    """Two teams share a zone, one team spans two zones, and an outside team cannot join.

    PRD 3.8: "It has three layers: a **neighborhood** is a zone of the floor plan; a
    **seat allocation** reserves a slice of that zone for a team over a run of ISO weeks;
    and a **desk assignment** puts a named employee at a numbered desk over a run of
    calendar dates."
    PRD 3.8: "Team and zone must belong to the same policy cycle, or the request is
    refused with `ERR_TEAM_ALLOCATION_MISMATCH` (409)."
    PRD 3.8: "A successful reservation lands in `RESERVED` status with `release_reason`
    null, `line_chargeback_cents` at 0, and `weeks_in_window` set to the number of ISO
    weeks in the half-open interval — the ordinal of `window_end_week` minus the ordinal
    of `window_start_week`."
    PRD 3.8: "`RESERVED` and `RELEASED` allocations contribute nothing to any week's
    load."
    PRD 2.3: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside
    `meta`, where `total_count` is the number of rows matching the filters before the
    window is applied and `has_more` is true exactly when rows remain after the returned
    window."

    Design: Corner/entities/seat_allocation_is_the_many_to_many_junction_between_team_and_neighborhood
    """
    world = _two_zones_and_an_outsider_team()
    zone_one_id = world["zone_one"]["id"]
    zone_two_id = world["zone_two"]["id"]
    team_a_id = world["team_a"]["id"]
    assert world["team_a"]["entitled_seats"] == 10
    assert world["team_b"]["entitled_seats"] == 23

    first = reserve_allocation(zone_one_id, team_a_id, 6, "2026-W37", "2026-W40")
    second = reserve_allocation(
        zone_one_id, world["team_b"]["id"], 8, "2026-W37", "2026-W40"
    )
    third = reserve_allocation(zone_two_id, team_a_id, 4, "2026-W37", "2026-W40")
    for row in (first, second, third):
        assert row["status"] == "RESERVED"
        assert row["release_reason"] is None
        assert row["line_chargeback_cents"] == 0
        assert row["weeks_in_window"] == 3, "W37, W38 and W39"

    validate_error(
        api_client.create_seat_allocation(
            seat_allocation_payload(
                zone_one_id, world["outsider"]["id"],
                read_neighborhood(zone_one_id)["version"],
                allocated_seats=2, window_start_week="2026-W37",
                window_end_week="2026-W40",
            ),
            WPO,
        ),
        ApiErrorId.ERR_TEAM_ALLOCATION_MISMATCH.value,
        409,
    )

    by_zone, zone_meta = list_all(
        api_client.list_seat_allocations, WPO, {"neighborhood_id": zone_one_id}
    )
    assert zone_meta["total_count"] == 2, "two teams share the first zone"
    assert {row["id"] for row in by_zone} == {first["id"], second["id"]}

    by_team, team_meta = list_all(
        api_client.list_seat_allocations, WPO, {"team_id": team_a_id}
    )
    assert team_meta["total_count"] == 2, "one team spans two zones"
    assert {row["id"] for row in by_team} == {first["id"], third["id"]}

    zone = read_neighborhood(zone_one_id)
    assert zone["committed_seats"] == 0
    assert zone["peak_committed_seats"] == 0, "nothing here has been committed yet"
