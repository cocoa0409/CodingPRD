"""Windows that share an endpoint: room occupancy shares and construction phases."""

from test_helpers import api_client, fixtures, validate_error
from test_helpers.assertions import assert_tranche_balances
from test_helpers.constants import FY2027_AVAILABLE_ON, FY2027_EXPIRES_ON


def _room_and_two_candidates():
    """A dry room and two arriving candidates, neither holding a package."""
    units = fixtures.setup_mini_units()
    first = fixtures.create_candidate_faculty(units["department"]["id"], full_name="Ada Reyes")
    second = fixtures.create_candidate_faculty(units["department"]["id"],
                                               full_name="Bo Nakamura")
    space = fixtures.create_lab_space(building_code="PHYS", room_number="120",
                                      space_class="DRY")
    return units, first, second, space


def test_two_shares_whose_windows_only_touch_both_fit_in_the_same_room():
    """Touching windows are not overlapping, so 60 plus 60 percent is admissible.

    PRD 3.5: "Two windows overlap when each one's effective_from is strictly earlier than
    the other's effective_to, treating a null effective_to as unbounded - so windows that
    merely touch do not overlap."

    Design: Difficulty/resource_temporal_overlap/lab_space_share_over_half_open_occupancy_windows
    """
    _, first, second, space = _room_and_two_candidates()

    early = fixtures.propose_space_assignment(
        space, first["id"], share_pct=60, effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    late = fixtures.propose_space_assignment(
        fixtures.read_space(space["id"]), second["id"], share_pct=60,
        effective_from="2026-10-01T00:00:00Z", effective_to=None,
    )
    assert early["status"] == "PROPOSED"
    assert late["status"] == "PROPOSED"


def test_a_third_share_overlapping_only_the_first_window_is_refused_then_accepted_at_the_cap():
    """The overlap peers are window-filtered, and a sum of exactly 100 is accepted.

    PRD 3.5: "If the candidate's share_pct plus the sum of the peers' share_pct exceeds
    100, the request is rejected with ERR_SPACE_SHARE_EXCEEDED; a sum of exactly 100 is
    accepted and 101 is not."

    Design: Difficulty/resource_temporal_overlap/lab_space_share_over_half_open_occupancy_windows
    """
    _, first, second, space = _room_and_two_candidates()
    fixtures.propose_space_assignment(
        space, first["id"], share_pct=60, effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    fixtures.propose_space_assignment(
        fixtures.read_space(space["id"]), second["id"], share_pct=60,
        effective_from="2026-10-01T00:00:00Z", effective_to=None,
    )

    current = fixtures.read_space(space["id"])
    response = api_client.create_space_assignment(
        {
            "space_id": space["id"],
            "faculty_id": second["id"],
            "share_pct": 50,
            "effective_from": "2026-09-01T00:00:00Z",
            "effective_to": "2026-09-15T00:00:00Z",
            "expected_space_version": current["version"],
        },
        fixtures.DEAN_OFFICE,
    )
    validate_error(response, "ERR_SPACE_SHARE_EXCEEDED", expected_status=422)

    at_the_cap = fixtures.propose_space_assignment(
        fixtures.read_space(space["id"]), second["id"], share_pct=40,
        effective_from="2026-09-01T00:00:00Z", effective_to="2026-09-15T00:00:00Z",
    )
    assert at_the_cap["status"] == "PROPOSED"


def test_the_room_reports_only_the_share_whose_window_holds_the_clock():
    """allocated_share_pct is read at the clock, not summed over the future.

    PRD 3.5: "A future-dated assignment therefore passes the overlap check - which
    compares windows to each other, not to the clock - without raising
    allocated_share_pct until the clock enters its window."

    Design: Difficulty/resource_temporal_overlap/lab_space_share_over_half_open_occupancy_windows
    """
    _, first, second, space = _room_and_two_candidates()
    today = fixtures.propose_space_assignment(
        space, first["id"], share_pct=60, effective_from="2026-08-01T00:00:00Z",
        effective_to="2026-10-01T00:00:00Z",
    )
    fixtures.propose_space_assignment(
        fixtures.read_space(space["id"]), second["id"], share_pct=60,
        effective_from="2026-10-01T00:00:00Z", effective_to=None,
    )
    fixtures.propose_space_assignment(
        fixtures.read_space(space["id"]), second["id"], share_pct=40,
        effective_from="2026-09-01T00:00:00Z", effective_to="2026-09-15T00:00:00Z",
    )

    assert fixtures.read_space(space["id"])["allocated_share_pct"] == 60

    fixtures.activate_space_assignment(today["id"])
    room = fixtures.read_space(space["id"])
    assert room["status"] == "ASSIGNED"
    assert room["allocated_share_pct"] == 60


RENOVATION_ONLY = [
    {
        "key": "renovation",
        "category": "RENOVATION",
        "fiscal_year": 2027,
        "amount_cents": 12_000_000,
        "available_on": FY2027_AVAILABLE_ON,
        "expires_on": FY2027_EXPIRES_ON,
        "carryforward_policy": "NONE",
    },
]

FIRST_PHASE = {
    "sequence_no": 1,
    "name": "Demolition",
    "planned_start": "2026-08-10T00:00:00Z",
    "planned_end": "2026-09-30T00:00:00Z",
    "budget_cents": 6_000_000,
}


def _project_with_one_phase():
    """A scoping project whose only phase runs to the last day of September."""
    scenario = fixtures.setup_active_package(tranche_specs=RENOVATION_ONLY,
                                             proposed_total_cents=12_000_000)
    space = fixtures.create_lab_space(building_code="PHYS", room_number="121",
                                      space_class="WET")
    project = fixtures.create_project(scenario["package_id"], space["id"],
                                      scope_tier="MODERATE", estimate_cents=12_000_000)
    fixtures.create_phase(project["id"], **FIRST_PHASE)
    return scenario, space, project


def _second_phase_payload(planned_start):
    return {
        "sequence_no": 2,
        "name": "Mechanical rough-in",
        "planned_start": planned_start,
        "planned_end": "2026-11-30T00:00:00Z",
        "budget_cents": 6_000_000,
    }


def test_a_second_phase_sharing_a_single_day_overlaps_as_a_closed_interval():
    """Starting on the day the first phase ends is an overlap, not a tight handover.

    PRD 3.6: "Because the intervals are closed, two phases sharing a single day do
    overlap."

    Design: Difficulty/resource_temporal_overlap/renovation_phase_windows_as_closed_intervals_with_changeover_buffer
    """
    scenario, _, project = _project_with_one_phase()

    response = api_client.create_renovation_phase(
        project["id"], _second_phase_payload("2026-09-30T00:00:00Z"),
        scenario["headers"]["facilities"],
    )
    validate_error(response, "ERR_PHASE_WINDOW_OVERLAP", expected_status=422)
    assert len(fixtures.read_phases(project["id"])) == 1


def test_a_one_day_changeover_gap_violates_the_two_day_buffer():
    """Clearing the overlap is not enough: the changeover gap must be two days.

    PRD 3.6: "the later phase's planned_start less the earlier phase's planned_end must be
    at least two calendar days. Exactly two days is accepted; one day is not."

    Design: Difficulty/resource_temporal_overlap/renovation_phase_windows_as_closed_intervals_with_changeover_buffer
    """
    scenario, _, project = _project_with_one_phase()

    response = api_client.create_renovation_phase(
        project["id"], _second_phase_payload("2026-10-01T00:00:00Z"),
        scenario["headers"]["facilities"],
    )
    validate_error(response, "ERR_PHASE_BUFFER_VIOLATION", expected_status=422)
    assert len(fixtures.read_phases(project["id"])) == 1


def test_exactly_two_days_of_changeover_is_accepted_and_leaves_the_money_alone():
    """The accepted phase is created PENDING and the plan validation moves no money.

    PRD 3.6: "A phase is created in status PENDING with actual_cost_cents, actual_start and
    actual_end null."

    Design: Difficulty/resource_temporal_overlap/renovation_phase_windows_as_closed_intervals_with_changeover_buffer
    """
    scenario, _, project = _project_with_one_phase()

    second = fixtures.create_phase(project["id"], **_second_phase_payload("2026-10-02T00:00:00Z"))
    assert second["status"] == "PENDING"
    assert second["sequence_no"] == 2
    assert second["actual_cost_cents"] is None
    assert second["actual_start"] is None
    assert second["actual_end"] is None

    phases = fixtures.read_phases(project["id"])
    assert len(phases) == 2
    assert sum(phase["budget_cents"] for phase in phases) == 12_000_000
    assert fixtures.read_project(project["id"])["status"] == "SCOPING"
    assert_tranche_balances(fixtures.read_tranche(scenario["tranche"]["renovation"]["id"]),
                            encumbered_cents=0, available_balance_cents=12_000_000)
