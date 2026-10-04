"""Philanthropic funds: fund lifecycle, OCC on commit, allocation weighting,
and the care-plan funding gate on release."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_stage,
    commit_allocation,
    create_allocation,
    create_fund,
    get_application,
    get_care_plan,
    get_fund,
    get_stage,
    make_philanthropy_headers,
    schedule_stage,
    set_clock,
    setup_accepted_staged_application,
    setup_hospital_with_program,
    validate_error,
    validate_success,
)


# ---------------------------------------------------------------------------
# Corner/state_machines
# ---------------------------------------------------------------------------

def test_fund_close_blocked_by_pledged_allocations(api, philanthropy_headers):
    """PRD §3.9: "a locked fund may be closed, but only when no allocation is still `PLEDGED` (`ERR_PLEDGED_ALLOCATIONS_EXIST`, HTTP 409), at which point `COMMITTED` allocations stay on the books as historical records and the fund becomes read-only."

    Design: Corner/state_machines/fund_close_blocked_by_pledged_allocations
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _ = setup_hospital_with_program()
    fund = create_fund(total_committed_cents=100000)
    allocation = create_allocation(fund["id"], hospital["id"], amount_cents=5000)
    validate_success(api.lock_fund(fund["id"], philanthropy_headers))

    resp = api.close_fund(fund["id"], philanthropy_headers)
    validate_error(resp, ApiErrorId.ERR_PLEDGED_ALLOCATIONS_EXIST.value, expected_status=409)

    validate_success(api.withdraw_allocation(allocation["id"], philanthropy_headers))
    alloc_after = validate_success(api.get_allocation(allocation["id"], philanthropy_headers))
    assert alloc_after["status"] == "WITHDRAWN"

    closed = validate_success(api.close_fund(fund["id"], philanthropy_headers))
    assert closed["status"] == "CLOSED"


# ---------------------------------------------------------------------------
# Corner/calculations
# ---------------------------------------------------------------------------

def test_allocation_weight_strain_factor_snapshot_order_strained(api, philanthropy_headers):
    """PRD §3.9: "The weight starts from a base of 1.0, is multiplied by 1.5 when a `program_id` is present, multiplied by 2.0 when a `care_plan_id` is present, and multiplied by 1.25 when the receiving hospital's `admissions_ytd` is less than half of its `annual_capacity` (the capacity-strain factor, measured from the pre-commit snapshot)."

    Design: Corner/calculations/allocation_weight_strain_factor_snapshot_order
    """
    set_clock("2026-09-01T00:00:00Z")
    # H1 capacity 4 with one prior acceptance: 1 < 0.5*4 = 2 -> strained.
    h1, p1a, source = setup_hospital_with_program(
        hospital_overrides={"hospital_code": "H1", "annual_capacity": 4},
    )
    p1b = __import__("test_helpers").create_program(
        h1["id"], category="BURN", staged_care_required=False,
    )
    from test_helpers import (
        cast_vote, create_application, decide, open_review,
    )
    a_h1 = create_application(source["id"], p1a["id"], patient_full_name="Kid H1")
    open_review(a_h1["id"])
    cast_vote(a_h1["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a_h1["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    decide(a_h1["id"], decision="ACCEPT", decision_reason="ok")

    fund = create_fund(fund_name="Weight Fund", total_committed_cents=1000000)
    al1 = create_allocation(fund["id"], h1["id"], program_id=p1b["id"], amount_cents=10000)
    committed = commit_allocation(al1["id"], expected_fund_version=fund["version"])
    # 1.0 * 1.5 (program) * 1.25 (strained) = 1.875.
    assert committed["allocation_weight"] == pytest.approx(1.875, abs=0.0001)


def test_allocation_weight_strain_factor_snapshot_order_unstrained(api, philanthropy_headers):
    """PRD §3.9: "At commit time the system computes and stores the allocation's `allocation_weight`, rounded to four decimal places half-up, following a pinned evaluation order: first snapshot the receiving hospital's `admissions_ytd` and `annual_capacity` before this commit touches anything, then compute the weight from that snapshot, then apply the balance mutation."

    Design: Corner/calculations/allocation_weight_strain_factor_snapshot_order
    """
    set_clock("2026-09-01T00:00:00Z")
    # H2 capacity 2 with one prior acceptance: 1 < 0.5*2 = 1 false -> not strained.
    from test_helpers import (
        cast_vote, create_application, create_program, decide, open_review,
    )
    h2, p2a, source = setup_hospital_with_program(
        hospital_overrides={
            "hospital_code": "H2", "name": "Hospital Two", "city": "Spokane",
            "state_code": "WA", "latitude": 47.6, "longitude": -117.4,
            "annual_capacity": 2,
        },
    )
    p2b = create_program(h2["id"], category="CLEFT_CRANIOFACIAL", staged_care_required=False)
    a_h2 = create_application(
        source["id"], p2a["id"], patient_full_name="Kid H2",
        home_latitude=47.6, home_longitude=-117.0,
    )
    open_review(a_h2["id"])
    cast_vote(a_h2["id"], vote="ACCEPT", vote_weight=2, reviewer="rcm-1")
    cast_vote(a_h2["id"], vote="ACCEPT", vote_weight=1, reviewer="rcm-2")
    decide(a_h2["id"], decision="ACCEPT", decision_reason="ok")

    fund = create_fund(fund_name="Weight Fund", total_committed_cents=1000000)
    al2 = create_allocation(fund["id"], h2["id"], program_id=p2b["id"], amount_cents=10000)
    committed = commit_allocation(al2["id"], expected_fund_version=fund["version"])
    # 1.0 * 1.5 (program) * 1.0 (not strained) = 1.5.
    assert committed["allocation_weight"] == pytest.approx(1.5, abs=0.0001)


# ---------------------------------------------------------------------------
# Difficulty/boundary_precision_check
# ---------------------------------------------------------------------------

def test_fund_commit_at_exact_available_balance_leaves_zero(api, philanthropy_headers):
    """PRD §3.9: "requires the fund's `available_cents` to be at least the allocation's `amount_cents` — equality commits cleanly and leaves `available_cents` at exactly 0, while a shortfall is rejected with `ERR_INSUFFICIENT_FUND_BALANCE` (HTTP 402)."

    Design: Difficulty/boundary_precision_check/fund_commit_at_exact_available_balance_leaves_zero
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _ = setup_hospital_with_program()
    fund = create_fund(total_committed_cents=100000)
    al1 = create_allocation(fund["id"], hospital["id"], amount_cents=100000)
    al2 = create_allocation(fund["id"], hospital["id"], amount_cents=1)

    committed = validate_success(api.commit_allocation(
        al1["id"], fund["version"], philanthropy_headers,
    ))
    assert committed["status"] == "COMMITTED"
    fund_after = get_fund(fund["id"])
    assert fund_after["available_cents"] == 0
    assert fund_after["allocated_cents"] == 100000

    resp = api.commit_allocation(al2["id"], fund_after["version"], philanthropy_headers)
    validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUND_BALANCE.value, expected_status=402)


def test_fund_commit_at_exact_balance_preserves_conservation(api, philanthropy_headers):
    """PRD §3.9: "At all times the invariant `allocated_cents` plus `available_cents` equals `total_committed_cents` holds."

    Design: Difficulty/boundary_precision_check/fund_commit_at_exact_available_balance_leaves_zero
    """
    set_clock("2026-09-01T00:00:00Z")
    hospital, _, _ = setup_hospital_with_program()
    fund = create_fund(total_committed_cents=100000)
    al1 = create_allocation(fund["id"], hospital["id"], amount_cents=100000)
    al2 = create_allocation(fund["id"], hospital["id"], amount_cents=1)

    validate_success(api.commit_allocation(al1["id"], fund["version"], philanthropy_headers))
    fund_after = get_fund(fund["id"])
    validate_error(
        api.commit_allocation(al2["id"], fund_after["version"], philanthropy_headers),
        ApiErrorId.ERR_INSUFFICIENT_FUND_BALANCE.value, expected_status=402,
    )

    al2_after = validate_success(api.get_allocation(al2["id"], philanthropy_headers))
    assert al2_after["status"] == "PLEDGED"
    final_fund = get_fund(fund["id"])
    assert (
        final_fund["allocated_cents"] + final_fund["available_cents"]
        == final_fund["total_committed_cents"]
    )


# ---------------------------------------------------------------------------
# Difficulty/cross_entity_state_dependency
# ---------------------------------------------------------------------------

def _setup_committed_designated_allocation():
    """Staged acceptance + one SCHEDULED stage (plan ACTIVE_TREATMENT) + a
    COMMITTED plan-designated allocation. Returns (plan, stage, fund, allocation)."""
    _, _, _, _, _, plan = setup_accepted_staged_application()
    stage = add_stage(plan["id"])
    schedule_stage(stage["id"])
    fund = create_fund(fund_name="Burn Fund 2026", total_committed_cents=500000)
    allocation = create_allocation(
        fund["id"],
        # receiving hospital of the plan's program
        None or _hospital_id_of(plan),
        care_plan_id=plan["id"], amount_cents=200000,
    )
    commit_allocation(allocation["id"], expected_fund_version=fund["version"])
    return plan, stage, fund, allocation


def _hospital_id_of(plan):
    from test_helpers import make_care_headers
    # The plan -> application -> program -> hospital walk; tests here always run
    # against the fixture hospital, discovered via the application record.
    application = get_application(plan["application_id"])
    from test_helpers import api_client, make_admin_headers
    program = __import__("test_helpers").get_success_data(
        api_client.get_program(application["program_id"], make_admin_headers("admin-1"))
    )
    return program["hospital_id"]


def test_allocation_release_gated_by_careplan_stage_in_flight_blocked(api, philanthropy_headers):
    """PRD §3.9: "provided that, when it designates a care plan, that plan is not in `ACTIVE_TREATMENT` with a `SCHEDULED` stage (releasing mid-flight would strand a patient, so the release fails with `ERR_PLAN_HAS_STAGE_IN_FLIGHT`, HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/allocation_release_gated_by_careplan_stage_in_flight
    """
    set_clock("2026-09-01T00:00:00Z")
    plan, stage, fund, allocation = _setup_committed_designated_allocation()
    resp = api.release_allocation(allocation["id"], philanthropy_headers)
    validate_error(resp, ApiErrorId.ERR_PLAN_HAS_STAGE_IN_FLIGHT.value, expected_status=409)

    fund_after = get_fund(fund["id"])
    assert fund_after["allocated_cents"] == 200000
    assert fund_after["available_cents"] == 300000


def test_allocation_release_unblocked_after_defer(api, philanthropy_headers, care_headers):
    """PRD §3.9: "Release subtracts `amount_cents` from `allocated_cents`, adds it back to `available_cents`, and bumps the fund's `version`."

    Design: Difficulty/cross_entity_state_dependency/allocation_release_gated_by_careplan_stage_in_flight
    """
    set_clock("2026-09-01T00:00:00Z")
    plan, stage, fund, allocation = _setup_committed_designated_allocation()

    validate_success(api.defer_stage(stage["id"], care_headers))
    stage_after = get_stage(stage["id"])
    assert stage_after["status"] == "DEFERRED"

    released = validate_success(api.release_allocation(allocation["id"], philanthropy_headers))
    assert released["status"] == "RELEASED"
    fund_after = get_fund(fund["id"])
    assert fund_after["allocated_cents"] == 0
    assert fund_after["available_cents"] == 500000
    plan_after = get_care_plan(plan["id"])
    assert plan_after["funding_status"] == "UNFUNDED"
