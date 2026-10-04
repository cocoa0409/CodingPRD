"""Accrual on a single draw and idempotency of task completion (PRD 3.5, 3.7)."""
import pytest
from test_helpers import (
    api_client, validate_success, validate_error,
    reset_clock, setup_funded_program, create_advance, approve_advance, disburse_advance,
    get_loan, build_qualified_household, create_qualification, approve_qualification,
    enroll_bridge_program, setup_referral, create_task,
    TEST_USERS, ApiErrorId,
)

COORD = TEST_USERS["coordinator_headers"]
UW = TEST_USERS["underwriter_headers"]
AGENT = TEST_USERS["agent_headers"]


def _single_draw_scenario():
    sc = setup_funded_program(
        variant="CONSERVATIVE", income_cents=30_000_000,
        departing={"address": "21 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    advance = approve_advance(
        create_advance(sc["program"]["id"], sc["loan"]["id"], "DOWN_PAYMENT", 2_000_000)["id"]
    )
    sc["advance"] = advance
    return sc


def test_a_single_draw_accrues_interest_on_the_running_balance(api):
    """PRD section 3.5: "For each event in turn, interest is added to the accrued total in an
    amount equal to the running principal multiplied by `interest_rate_bps`, multiplied by
    `INTERIM_DAY_COUNT_BPS` — 3000 — and divided by the product of ten thousand and ten
    thousand, with the division flooring."

    PRD section 3.5: "One final accrual is added after the last event, using the fully
    accumulated running principal"

    Design: Corner/calculations/interim_loan_single_draw_accrual
    """
    reset_clock()
    sc = _single_draw_scenario()
    disbursed = disburse_advance(sc["advance"]["id"])
    assert disbursed["status"] == "DISBURSED"

    loan = get_loan(sc["loan"]["id"])
    assert loan["drawn_cents"] == 2_000_000
    # The first event carries a running principal of zero, so only the post-event accrual on
    # the accumulated 2000000 counts: 2000000 * 800 * 3000 // 100000000 = 48000.
    assert loan["accrued_interest_cents"] == 48_000
    assert loan["outstanding_principal_cents"] == 2_000_000


def test_completing_a_coordination_task_twice_is_a_state_error(api):
    """PRD section 3.7: "Completion of a task is performed by the partner agent or by a
    coordinator, and it is permitted both from `OPEN` and from `IN_PROGRESS`."

    PRD section 2.11: "a resource already in a terminal state is refused with
    `ERR_ALREADY_TERMINAL`, and the specific state conflicts for the backup guarantee, the
    marketing lifecycle, a repaid loan and the exercise window each carry their own code."

    Design: Corner/state_machines/coordination_task_complete_twice_returns_invalid_state
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "11 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    agent, referral = setup_referral(bp["id"], qualified=False)
    task = create_task(bp["id"], referral["id"], task_kind="PHOTOGRAPHY",
                       due_date="2026-09-20T00:00:00Z")

    first = validate_success(api.complete_coordination_task(task["id"], COORD), 200)
    assert first["status"] == "COMPLETED"

    res = api.complete_coordination_task(task["id"], COORD)
    validate_error(res, ApiErrorId.ERR_INVALID_STATE.value, expected_status=409)


def test_completing_a_coordination_task_stamps_the_completion_time(api):
    """PRD section 3.7: "Completing a task has a knock-on effect on the referral: when the
    completed task is the referral's last open task, the system re-evaluates whether the
    referral can now be backfilled as complete, stamps the task's `completed_at` from the
    logical clock, and recomputes the agent's `active_referral_count`."

    Design: Corner/state_machines/coordination_task_complete_twice_returns_invalid_state
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "11 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    agent, referral = setup_referral(bp["id"], qualified=False)
    task = create_task(bp["id"], referral["id"], task_kind="PHOTOGRAPHY",
                       due_date="2026-09-20T00:00:00Z")

    completed = validate_success(api.complete_coordination_task(task["id"], COORD), 200)
    assert completed["status"] == "COMPLETED"
    assert completed["completed_at"] is not None, "completion is stamped from the logical clock"
    assert completed["completed_at"].startswith("2026-09-01"), "the clock has not advanced"


def test_completing_a_task_is_permitted_for_an_open_task(api):
    """PRD section 3.7: "Completion of a task is performed by the partner agent or by a
    coordinator, and it is permitted both from `OPEN` and from `IN_PROGRESS`."

    Design: Corner/state_machines/coordination_task_complete_twice_returns_invalid_state
    """
    reset_clock()
    sc = build_qualified_household(
        income_cents=30_000_000,
        departing={"address": "11 Def Way", "appraised_value_cents": 70_000_000,
                   "mortgage_payoff_cents": 30_000_000, "condition_grade": "B"},
    )
    q = approve_qualification(create_qualification(
        sc["homeowner"]["id"], sc["departing"]["id"], sc["new"]["id"],
        variant_used="CONSERVATIVE", target_purchase_price_cents=30_000_000)["id"])
    bp = enroll_bridge_program(sc, q["id"], projected_carry_months=4)
    agent, referral = setup_referral(bp["id"], qualified=False)
    task = create_task(bp["id"], referral["id"], task_kind="PHOTOGRAPHY",
                       due_date="2026-09-20T00:00:00Z")
    assert task["status"] == "OPEN"

    # A coordinator may also complete a task, not only its partner agent.
    completed = validate_success(api.complete_coordination_task(task["id"], COORD), 200)
    assert completed["status"] == "COMPLETED"