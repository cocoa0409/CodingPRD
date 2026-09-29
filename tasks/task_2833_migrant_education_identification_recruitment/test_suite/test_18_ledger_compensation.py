"""Reversing a session returns the child's hour and credit ledgers to their prior values."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_immutable_row_shape,
    assert_int_equals,
    assert_is_null,
    assert_row_count,
    assert_student_ledgers,
)
from test_helpers.constants import (
    DELIVERY_MODE_VIRTUAL,
    PLAN_TYPE_CREDIT_ACCRUAL,
)
from test_helpers.test_users import make_coordinator_headers


def _child_with_two_settled_sessions(client):
    """A credit-accrual plan carrying 3.75 delivered hours and 1.25 earned credits."""
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    bundle.plan = fixtures.active_plan(
        client,
        bundle.student["id"],
        plan_type=PLAN_TYPE_CREDIT_ACCRUAL,
        delivery_mode=DELIVERY_MODE_VIRTUAL,
    )
    bundle.first = fixtures.post_credit_delivery(
        client, bundle.plan["id"], 1.50, 0.50, delivered_on="2026-07-10"
    )
    bundle.second = fixtures.post_credit_delivery(
        client, bundle.plan["id"], 2.25, 0.75, delivered_on="2026-07-15"
    )
    return bundle


def test_the_reversal_row_copies_the_target_and_flags_it(client):
    """Compensation mints a new immutable row rather than editing the session it undoes.

    "Reversal creates a **new** immutable delivery record whose `reverses_delivery_id`
    points at the target and which copies the target's `plan_id`, `delivered_on`,
    `hours`, `service_category` and `credits_awarded` verbatim, and it flags the target's
    `is_reversed` as true."

    Design: Difficulty/compensating_invariant/student_hours_and_credits_ledger_returns_to_its_exact_pre_create_decimals_after_reversal
    """
    bundle = _child_with_two_settled_sessions(client)
    third = fixtures.post_credit_delivery(
        client, bundle.plan["id"], 4.00, 1.00, delivered_on="2026-07-20"
    )

    reversal = validate_success(
        client.reverse_delivery(third["id"], make_coordinator_headers()), 201
    )

    assert_immutable_row_shape(reversal, "reversal")
    assert reversal["id"] != third["id"], "the reversal must be a distinct row"
    assert_int_equals(
        reversal["reverses_delivery_id"], third["id"], "reversal.reverses_delivery_id"
    )
    assert_int_equals(reversal["plan_id"], bundle.plan["id"], "reversal.plan_id")
    assert_decimal_equals(reversal["hours"], "4.00", "reversal.hours")
    assert_decimal_equals(reversal["credits_awarded"], "1.00", "reversal.credits_awarded")
    assert_int_equals(reversal["is_reversed"], False, "reversal.is_reversed")

    target = fixtures.read_delivery(client, third["id"])
    assert_int_equals(target["is_reversed"], True, "target.is_reversed")
    assert_is_null(target["reverses_delivery_id"], "target.reverses_delivery_id")


def test_the_ledgers_return_to_the_exact_decimals_they_held_before_the_session(client):
    """3.75 hours and 1.25 credits climb, then land back on precisely the same figures.

    "Because the reversal record is excluded from every sum by virtue of carrying a
    `reverses_delivery_id`, and the target is excluded by virtue of its `is_reversed`
    flag, the conservation invariant holds exactly: posting a session and then reversing
    it returns `total_service_hours_ledger` to precisely the value it held beforehand, and
    `locally_accrued_credits` likewise - no residual fraction, no drift."

    Design: Difficulty/compensating_invariant/student_hours_and_credits_ledger_returns_to_its_exact_pre_create_decimals_after_reversal
    """
    bundle = _child_with_two_settled_sessions(client)
    before = fixtures.read_student(client, bundle.student["id"])
    assert_student_ledgers(before, hours="3.75", locally="1.25", awarded="1.25")
    assert_decimal_equals(
        fixtures.read_plan(client, bundle.plan["id"])["delivered_hours"],
        "3.75",
        "plan.delivered_hours",
    )

    third = fixtures.post_credit_delivery(
        client, bundle.plan["id"], 4.00, 1.00, delivered_on="2026-07-20"
    )
    peak = fixtures.read_student(client, bundle.student["id"])
    assert_student_ledgers(peak, hours="7.75", locally="2.25", awarded="2.25")

    fixtures.reverse_delivery(client, third["id"])

    after = fixtures.read_student(client, bundle.student["id"])
    assert_student_ledgers(after, hours="3.75", locally="1.25", awarded="1.25")
    assert_decimal_equals(
        fixtures.read_plan(client, bundle.plan["id"])["delivered_hours"],
        "3.75",
        "plan.delivered_hours",
    )

    rows, _meta = fixtures.list_rows(
        client.list_deliveries(make_coordinator_headers(), {"plan_id": bundle.plan["id"]})
    )
    assert_row_count(rows, 4, "delivery records on the plan")
    reversals = [row for row in rows if row.get("reverses_delivery_id")]
    assert_row_count(reversals, 1, "compensating records on the plan")
