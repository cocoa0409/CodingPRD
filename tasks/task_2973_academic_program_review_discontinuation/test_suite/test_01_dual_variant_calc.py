"""SCAFFOLD §1.8 rule_id dual_variant_calc: two variants of one formula over one input set."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prd_bench_local_runner.testing import (  # noqa: E402
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions, constants, factories, fixtures  # noqa: E402
from test_helpers.api_errors import *  # noqa: F401,F403,E402
from test_helpers.test_users import (  # noqa: E402
    make_program_chair_headers,
    make_provost_ratifier_headers,
    make_registrar_headers,
    make_review_coordinator_headers,
)


def test_cost_per_credit_hour_rolling_vs_latest_diverge(api):
    """The two variants of program_cost_per_credit_hour diverge on one snapshot set.

    Three immutable snapshots (300ch/12000000c, 240ch/11000000c, 200ch/11000000c)
    feed both variants. §3.2's rolling_three_term variant sums cost and credit
    hours across the window and divides once, landing on 34000000/740 = 45945.94...
    -> 45946 cents half-up. The latest_term variant divides the newest term alone,
    11000000/200 = 55000 cents. The forbidden divide-then-average order over the
    same three rows would produce a third value, 46944, which the program must
    never report.

    Design: Difficulty/dual_variant_calc/program_cost_per_credit_hour_rolling_vs_latest_diverge
    """
    coordinator = make_review_coordinator_headers()
    fixtures.set_clock(api, constants.CLOCK_STARTUP_DEFAULT)

    program = fixtures.create_program(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
        host_capacity_per_day=2,
    )
    program_id = program["id"]

    # The first two terms of the window.
    early = fixtures.append_snapshots(api, program_id, constants.FIXTURE_A_SNAPSHOTS[:2])

    # Trigger: the third and newest term lands.
    third = validate_success(
        api.create_metric_snapshot(
            program_id,
            factories.metric_snapshot_payload(**constants.FIXTURE_A_SNAPSHOTS[2]),
            coordinator,
        ),
        201,
    )

    # Each snapshot carries its own single-term quotient, half-up to whole cents.
    assert third["cost_per_credit_hour_cents"] == constants.FIXTURE_A_PER_SNAPSHOT_CPH_CENTS[2]
    assert early[0]["cost_per_credit_hour_cents"] == constants.FIXTURE_A_PER_SNAPSHOT_CPH_CENTS[0]
    assert early[1]["cost_per_credit_hour_cents"] == constants.FIXTURE_A_PER_SNAPSHOT_CPH_CENTS[1]

    program = fixtures.read_program(api, program_id)
    assert program["snapshot_count"] == 3
    assertions.assert_viability(
        program,
        rolling_cents=constants.FIXTURE_A_ROLLING_CPH_CENTS,
        latest_cents=constants.FIXTURE_A_LATEST_CPH_CENTS,
        composite=constants.FIXTURE_A_COMPOSITE_UNDERGRADUATE,
        band=constants.FIXTURE_A_BAND,
    )
    # The two variants must not collapse onto one another...
    assert (
        program["cost_per_credit_hour_rolling_cents"]
        != program["cost_per_credit_hour_latest_cents"]
    )
    # ...and the rolling variant must not be the divide-then-average value.
    assert (
        program["cost_per_credit_hour_rolling_cents"]
        != constants.FIXTURE_A_FORBIDDEN_AVERAGED_CPH_CENTS
    ), "the rolling variant divides the summed window once, it does not average per-term quotients"
    assertions.assert_integer_cents(
        program["cost_per_credit_hour_rolling_cents"], "cost_per_credit_hour_rolling_cents"
    )
    assertions.assert_integer_cents(
        program["cost_per_credit_hour_latest_cents"], "cost_per_credit_hour_latest_cents"
    )


def test_projection_optimistic_vs_conservative_flips_approval(api):
    """The two projection variants read one stored credits_remaining and flip approval.

    A student with credits_remaining 24 and max_credits_per_term 15 projects
    ceil(24/15) = 2 terms under OPTIMISTIC_FULL_LOAD, completing in term 4+2-1 = 5,
    which is within the plan's final_award_term_index of 5 and therefore not at
    risk. Recording advising at 9 credits per term switches the variant to
    CONSERVATIVE_ADVISED_LOAD: ceil(24/9) = 3 terms, completion term 6, beyond the
    horizon, so at_risk flips true, the plan's at_risk_student_count becomes 1 and
    the APPROVE that would have succeeded is refused with
    ERR_AT_RISK_STUDENTS_PRESENT. required_seat_count, driven by credits alone at
    ceil(24/3) = 8, is unmoved by the variant switch.

    Design: Difficulty/dual_variant_calc/displaced_student_projection_optimistic_vs_conservative_flips_approval
    """
    ctx = fixtures.setup_ratified_discontinuation(
        api,
        code="HIST-BA",
        name="History BA",
        degree_level="UNDERGRADUATE",
        department_code="HIST",
        host_capacity_per_day=2,
    )
    fixtures.acknowledge_all_notifications(api, ctx.decision["id"])

    fixtures.file_plan(
        api,
        ctx,
        last_admit_term_index=3,
        first_teach_out_term_index=4,
        final_award_term_index=5,
    )
    plan_id = ctx.plan["id"]
    fixtures.add_guarantee(api, ctx, course_code="HIST-401", term_index=4, seats_guaranteed=6)
    fixtures.add_guarantee(api, ctx, course_code="HIST-402", term_index=5, seats_guaranteed=6)
    student = fixtures.enrol_student(
        api, ctx, student_number="S-1001", credits_remaining=24, max_credits_per_term=15
    )
    fixtures.submit_plan(api, ctx)

    # Before advising: the optimistic variant, and a plan carrying no risk.
    assertions.assert_projection(
        student,
        variant="OPTIMISTIC_FULL_LOAD",
        terms_remaining=2,
        completion_term_index=5,
        at_risk=False,
        required_seat_count=8,
    )
    plan_before = fixtures.read_plan(api, plan_id)
    assertions.assert_plan_ledger(
        plan_before,
        guaranteed_seat_total=12,
        required_seat_total=8,
        seat_shortfall=0,
        at_risk_student_count=0,
    )
    assert plan_before["state"] == "SUBMITTED"

    # Trigger part 1: advising switches the variant on the same stored credits.
    advised = fixtures.record_advising(
        api, student["id"], advised_credits_per_term=9, plan_signed=True
    )
    assertions.assert_projection(
        advised,
        variant="CONSERVATIVE_ADVISED_LOAD",
        terms_remaining=3,
        completion_term_index=6,
        at_risk=True,
        required_seat_count=8,
    )

    plan_after = fixtures.read_plan(api, plan_id)
    assertions.assert_plan_ledger(
        plan_after,
        guaranteed_seat_total=12,
        required_seat_total=8,
        seat_shortfall=0,
        at_risk_student_count=1,
    )

    # Trigger part 2: the same APPROVE is now refused.
    refused = api.transition_teach_out_plan(
        plan_id, factories.plan_transition_payload("APPROVE"), make_provost_ratifier_headers()
    )
    validate_error(refused, ERR_AT_RISK_STUDENTS_PRESENT, 409)

    assert fixtures.read_plan(api, plan_id)["state"] == "SUBMITTED"
