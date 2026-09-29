"""Hour allocation rounds each share before summing and parks the residual."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_int_equals,
    assert_plan_allocation,
    quantize_money,
)
from test_helpers.constants import (
    DELIVERY_MODE_IN_PERSON,
    DELIVERY_MODE_VIRTUAL,
    DELIVERY_MODE_WORKSITE,
    PLAN_DRAFT,
    PLAN_TYPE_CREDIT_ACCRUAL,
    PLAN_TYPE_OSY_ALTERNATIVE,
    PLAN_TYPE_SUMMER,
    PRIORITY_TIER_NON_PFS,
)
from test_helpers.test_users import make_coordinator_headers

OSY_PROFILE = {
    "full_name": "Sara Nieto",
    "birth_date": "2007-02-08",
    "schooling_status": "OUT_OF_SCHOOL",
    "grade_level": None,
    "school_days_interrupted": 0,
    "math_below_grade": False,
    "reading_below_grade": False,
    "credit_deficit": 0,
    "has_hs_credential": True,
    "primary_language_not_english": False,
}


def _child_with_three_plans(client):
    """A non-priority child holding three live plans of weights 3, 2 and 3."""
    base = fixtures.area_and_recruiter(
        client,
        area_overrides={"name": "Columbia Basin"},
        recruiter_overrides={"full_name": "Beto Cruz"},
    )
    student = fixtures.create_student(
        client, base.recruiter["id"], base.area["id"], **OSY_PROFILE
    )
    summer = fixtures.draft_plan(
        client,
        student["id"],
        plan_type=PLAN_TYPE_SUMMER,
        delivery_mode=DELIVERY_MODE_IN_PERSON,
    )
    credit = fixtures.draft_plan(
        client,
        student["id"],
        plan_type=PLAN_TYPE_CREDIT_ACCRUAL,
        delivery_mode=DELIVERY_MODE_VIRTUAL,
    )
    osy = fixtures.draft_plan(
        client,
        student["id"],
        plan_type=PLAN_TYPE_OSY_ALTERNATIVE,
        delivery_mode=DELIVERY_MODE_WORKSITE,
    )
    base.student = student
    base.summer = summer
    base.credit = credit
    base.osy = osy
    return base


def test_each_share_is_rounded_before_summing_and_the_residual_lands_on_the_earliest_plan(
    client,
):
    """The rounded shares 28.13/18.75/28.13 overshoot, so the earliest plan absorbs -0.01.

    "That entire residual lands on one plan and one plan only - the first of the input
    set, meaning the plan with the earliest `created_at` - whose `allocated_hours`
    becomes its own rounded share plus the residual, re-rounded half up to two decimals."

    Design: Difficulty/combinatorial_formula/allocation_rounds_per_plan_before_summing_and_lands_residual_on_earliest_plan
    """
    bundle = _child_with_three_plans(client)

    summer = fixtures.read_plan(client, bundle.summer["id"])
    credit = fixtures.read_plan(client, bundle.credit["id"])
    osy = fixtures.read_plan(client, bundle.osy["id"])

    assert_plan_allocation(summer, PRIORITY_TIER_NON_PFS, "28.12", "earliest plan")
    assert_plan_allocation(credit, PRIORITY_TIER_NON_PFS, "18.75", "credit plan")
    assert_plan_allocation(osy, PRIORITY_TIER_NON_PFS, "28.13", "osy plan")


def test_the_allocated_hours_of_every_live_plan_add_back_to_the_non_priority_budget(client):
    """The three allocations sum to the 75.00 budget a child without the flag divides.

    "The budget depends on priority: a child whose `pfs_flag` is true divides 120.00
    hours, and a child whose flag is false divides 75.00 hours."

    Design: Difficulty/combinatorial_formula/allocation_rounds_per_plan_before_summing_and_lands_residual_on_earliest_plan
    """
    bundle = _child_with_three_plans(client)

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(student["pfs_flag"], False, "student.pfs_flag")
    assert_int_equals(student["pfs_score"], 55, "student.pfs_score")

    rows, _meta = fixtures.list_rows(
        client.list_plans(
            make_coordinator_headers(), {"student_id": bundle.student["id"]}
        )
    )
    total = sum(quantize_money(row["allocated_hours"]) for row in rows)
    assert_decimal_equals(total, "75.00", "sum of allocated_hours")

    for row in rows:
        assert_int_equals(row["status"], PLAN_DRAFT, "plan.status")
        assert_decimal_equals(
            row["expected_service_hours"],
            row["allocated_hours"],
            "plan.expected_service_hours",
        )
        assert_decimal_equals(row["delivered_hours"], "0.00", "plan.delivered_hours")

    earliest = validate_success(
        client.get_plan(bundle.summer["id"], make_coordinator_headers()), 200
    )
    assert (
        quantize_money(earliest["allocated_hours"]) != quantize_money("28.13")
    ), "the earliest plan must differ from its own rounded share by the residual"
