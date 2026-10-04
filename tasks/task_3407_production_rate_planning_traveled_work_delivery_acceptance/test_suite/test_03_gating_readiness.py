"""Gating review snapshots, verdicts, and readiness boundaries (PRD §2.9, §3.2)."""
from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    api_client,
    create_customer, add_aircraft, add_work_package, travel_work_package,
    create_open_escape, create_program,
    create_rate_case_in_state,
    get_program,
    setup_gating_ready_program, setup_confirmed_commitment,
)


def test_gating_snapshot_min_selects_weaker_workforce_dimension(api, planner_headers):
    """PRD §3.2: "The readiness formula of §2.9 is evaluated against the case's
    `proposed_rate` rather than the committed rate, and the results are stamped onto the
    case as `supply_readiness_snapshot_pct`, `workforce_readiness_snapshot_pct`,
    `burden_penalty_snapshot`, and `readiness_index_snapshot`; later movement in
    commitments, hiring, or traveled work never moves a frozen snapshot."
    PRD §2.9: "Count the distinct long-lead component families — distinct `component_code`
    values — for which the program holds at least one supplier commitment whose `status` is
    `CONFIRMED`, `ORDERED`, or `AT_RISK` and whose `committed_rate_per_month` is greater
    than or equal to the target rate under evaluation."
    PRD §2.9: "The program's `readiness_index` is the smaller of the two percentages minus
    the burden penalty, rounded half-up to two decimal places."
    PRD §3.2: "The same review sets `gating_verdict` — null until this point — to `PASS`
    when the frozen readiness index is at least 85.0 and the program's `open_escape_count`
    is zero at review time, and to `FAIL` otherwise."

    Design: Difficulty/combinatorial_formula/gating_index_min_selects_weaker_dimension
    """
    env = setup_gating_ready_program()
    program = env["program"]
    case = create_rate_case_in_state(program["id"], "ANNOUNCED", proposed_rate=8)
    case = validate_success(api_client.request_gating_review(case["id"], planner_headers))
    assert case["supply_readiness_snapshot_pct"] == 100.0, "2 of 2 codes covered at 8 >= 8"
    assert case["workforce_readiness_snapshot_pct"] == 85.0, "17 of 20 hired"
    assert case["burden_penalty_snapshot"] == 0.0
    assert case["readiness_index_snapshot"] == 85.0, (
        "min(100.0, 85.0) - 0.0: the weaker workforce dimension wins the min()"
    )
    assert case["gating_verdict"] == "PASS"


def test_gating_snapshot_min_selects_weaker_supply_dimension(api, planner_headers):
    """PRD §2.9: "Multiply that count by 100 and divide by the program's
    `required_component_codes`; if `required_component_codes` is zero, supply readiness is
    defined as 100."
    PRD §2.9: "The program's `readiness_index` is the smaller of the two percentages minus
    the burden penalty, rounded half-up to two decimal places."
    PRD §3.2: "The same review sets `gating_verdict` — null until this point — to `PASS`
    when the frozen readiness index is at least 85.0 and the program's `open_escape_count`
    is zero at review time, and to `FAIL` otherwise."

    Design: Difficulty/combinatorial_formula/gating_index_min_selects_weaker_dimension
    """
    env = setup_gating_ready_program(
        components=("ENG",),
        workforce=(("AVIONICS", 10, 10),),
        program_overrides={"required_component_codes": 2},
    )
    program = env["program"]
    case = create_rate_case_in_state(program["id"], "ANNOUNCED", proposed_rate=8)
    case = validate_success(api_client.request_gating_review(case["id"], planner_headers))
    assert case["supply_readiness_snapshot_pct"] == 50.0, "1 of 2 required codes covered"
    assert case["workforce_readiness_snapshot_pct"] == 100.0, "10 of 10 hired"
    assert case["readiness_index_snapshot"] == 50.0, (
        "min(50.0, 100.0) - 0.0: the weaker supply dimension wins the min()"
    )
    assert case["gating_verdict"] == "FAIL", "50.0 is below the 85.0 gate"


def test_gating_index_exactly_85_passes_then_84_5_fails(api, planner_headers, line_manager_headers):
    """PRD §3.2: "The same review sets `gating_verdict` — null until this point — to `PASS`
    when the frozen readiness index is at least 85.0 and the program's `open_escape_count`
    is zero at review time, and to `FAIL` otherwise."
    PRD §2.9: "Open traveled work subtracts readiness directly: half a point per open
    traveled-work hour — 0.5 times `traveled_work_open_hours` — capped at 20.0 points."
    PRD §3.2: "Committing (`GATED_REVIEW` → `COMMITTED`) is gated on a `PASS` verdict; any
    other verdict draws `ERR_GATING_CRITERIA_UNMET` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/gating_index_85_passes_84_5_fails
    """
    env = setup_gating_ready_program()
    program = env["program"]
    customer = create_customer()
    aircraft = add_aircraft(program["id"], customer["id"])
    work_package = add_work_package(aircraft["id"], planned_hours=10)

    case_a = create_rate_case_in_state(program["id"], "ANNOUNCED", proposed_rate=8)
    case_a = validate_success(api_client.request_gating_review(case_a["id"], planner_headers))
    assert case_a["readiness_index_snapshot"] == 85.0, "boundary is inclusive: 85.0 passes"
    assert case_a["gating_verdict"] == "PASS"

    travel_work_package(work_package["id"], traveled_hours=1)
    program = get_program(program["id"])
    assert program["traveled_work_open_hours"] == 1

    case_b = create_rate_case_in_state(program["id"], "ANNOUNCED", proposed_rate=7)
    case_b = validate_success(api_client.request_gating_review(case_b["id"], planner_headers))
    assert case_b["readiness_index_snapshot"] == 84.5, "one open hour subtracts 0.5 points"
    assert case_b["gating_verdict"] == "FAIL"
    resp = api_client.commit_rate_case(case_b["id"], planner_headers)
    validate_error(resp, ApiErrorId.ERR_GATING_CRITERIA_UNMET)


def test_gating_index_exactly_85_commits_successfully(api, planner_headers):
    """PRD §3.2: "The same review sets `gating_verdict` — null until this point — to `PASS`
    when the frozen readiness index is at least 85.0 and the program's `open_escape_count`
    is zero at review time, and to `FAIL` otherwise."
    PRD §3.2: "Committing (`GATED_REVIEW` → `COMMITTED`) is gated on a `PASS` verdict; any
    other verdict draws `ERR_GATING_CRITERIA_UNMET` (HTTP 422). A commit lands with a
    four-link cascade. First, the program's `current_rate_per_month` becomes the case's
    `proposed_rate`, and the program's `version` advances."

    Design: Difficulty/boundary_precision_check/gating_index_85_passes_84_5_fails
    """
    env = setup_gating_ready_program()
    program = env["program"]
    case = create_rate_case_in_state(program["id"], "GATED_REVIEW", proposed_rate=8)
    assert case["readiness_index_snapshot"] == 85.0
    assert case["gating_verdict"] == "PASS"
    case = validate_success(api_client.commit_rate_case(case["id"], planner_headers))
    assert case["status"] == "COMMITTED"
    assert get_program(program["id"])["current_rate_per_month"] == 8


def test_gating_verdict_fail_with_open_escape_despite_perfect_readiness(api, planner_headers):
    """PRD §3.2: "The same review sets `gating_verdict` — null until this point — to `PASS`
    when the frozen readiness index is at least 85.0 and the program's `open_escape_count`
    is zero at review time, and to `FAIL` otherwise."
    PRD §2.9: "`open_escape_count` counts quality escapes on the program's aircraft whose
    status is `OPEN`, `ROOT_CAUSE`, or `DISPOSITIONED`."

    Design: Corner/calculations/gating_verdict_fail_with_open_escape_despite_perfect_readiness
    """
    env = setup_gating_ready_program(
        components=("ENG",),
        workforce=(("AVIONICS", 10, 10),),
    )
    program = env["program"]
    customer = create_customer()
    aircraft = add_aircraft(program["id"], customer["id"])
    create_open_escape(aircraft["id"], severity="MAJOR", description="Dent")

    case = create_rate_case_in_state(program["id"], "ANNOUNCED", proposed_rate=8)
    case = validate_success(api_client.request_gating_review(case["id"], planner_headers))
    assert case["readiness_index_snapshot"] == 100.0, (
        "supply and workforce both perfect, no traveled burden"
    )
    assert case["gating_verdict"] == "FAIL", "solely because open_escape_count == 1"


def test_traveled_burden_penalty_capped_at_twenty_points(api, admin_headers):
    """PRD §2.9: "Open traveled work subtracts readiness directly: half a point per open
    traveled-work hour — 0.5 times `traveled_work_open_hours` — capped at 20.0 points."
    PRD §2.9: "The live variant evaluates everything against the program's currently
    committed rate; the gating-review variant of §3.2 evaluates the same formula against a
    proposed rate and freezes it onto the case."
    PRD §2.9: "`traveled_work_open_hours` sums `traveled_hours` over work packages in
    `TRAVELED` status whose linked rework order is neither `CLOSED` nor `CREDITED`."

    Design: Corner/calculations/traveled_burden_penalty_capped_at_twenty_points
    """
    program = create_program()
    setup_confirmed_commitment(program["id"], committed_rate=5)
    customer = create_customer()
    aircraft = add_aircraft(program["id"], customer["id"])
    work_package = add_work_package(aircraft["id"], planned_hours=10)
    travel_work_package(work_package["id"], traveled_hours=100)

    program = get_program(program["id"])
    assert program["traveled_work_open_hours"] == 100
    # supply 1/1 at committed rate 5 >= 5 -> 100.0; no workforce plans -> 100.0;
    # burden min(20.0, 0.5 * 100) = 20.0; index = 100.0 - 20.0.
    assert program["readiness_index"] == 80.0
