"""The transfer cap tier is keyed on the pre-cap total, never on the final total."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_int_equals,
    assert_student_ledgers,
    quantize_money,
)
from test_helpers.constants import (
    DELIVERY_MODE_VIRTUAL,
    PLAN_TYPE_CREDIT_ACCRUAL,
    TRANSFER_RECONCILED,
)
from test_helpers.test_users import make_liaison_headers

STUDENT_A = {
    "full_name": "Ivan Solis",
    "birth_date": "2008-05-05",
    "grade_level": 11,
    "school_days_interrupted": 0,
    "math_below_grade": False,
    "reading_below_grade": False,
    "credit_deficit": 0,
}


def _received_request(client):
    """A child holding 6.00 local credits and a RECEIVED request claiming 14.00 more."""
    bundle = fixtures.certified_child(
        client,
        coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True},
        **STUDENT_A
    )
    plan = fixtures.active_plan(
        client,
        bundle.student["id"],
        plan_type=PLAN_TYPE_CREDIT_ACCRUAL,
        delivery_mode=DELIVERY_MODE_VIRTUAL,
    )
    for delivered_on in ("2026-07-10", "2026-07-17", "2026-07-24"):
        fixtures.post_credit_delivery(
            client, plan["id"], 2.00, 2.00, delivered_on=delivered_on
        )

    prior_profile = dict(STUDENT_A)
    prior_profile["full_name"] = "Ivan Solis (CA record)"
    prior_profile["current_state_code"] = "CA"
    prior = fixtures.create_student(
        client, bundle.recruiter["id"], bundle.area["id"], **prior_profile
    )
    request = fixtures.open_transfer_request(
        client,
        bundle.student["id"],
        exchange_reference="NX-2833-0001",
        reported_prior_credits=14.00,
    )
    fixtures.carry_transfer_to_received(client, request["id"], prior["id"])

    bundle.plan = plan
    bundle.prior = prior
    bundle.request = request
    return bundle


def test_reconcile_applies_the_percentage_of_the_pre_cap_tier_key(client):
    """6.00 local plus 14.00 claimed keys the 35 percent tier, admitting exactly 7.00.

    "Third, the tier key is formed as the locally accrued total plus that full uncapped
    amount: this is the **pre-cap** total, and it is the only figure the tier lookup
    ever sees."

    Design: Difficulty/combinatorial_formula/transfer_cap_tier_keyed_on_pre_cap_total_not_re_derived_from_final_total
    """
    bundle = _received_request(client)

    reconciled = validate_success(
        client.reconcile_transfer_request(bundle.request["id"], make_liaison_headers()),
        200,
    )

    assert_int_equals(reconciled["status"], TRANSFER_RECONCILED, "request.status")
    assert_decimal_equals(
        reconciled["applied_transferred_credits"],
        "7.00",
        "request.applied_transferred_credits",
    )
    assert quantize_money(reconciled["applied_transferred_credits"]) != quantize_money(
        "4.55"
    ), "the cap must not be re-derived from the awarded total"


def test_reconcile_writes_the_three_child_credit_figures_without_moving_hours(client):
    """The child's credit picture becomes 6.00 local, 7.00 transferred and 13.00 awarded.

    "Sixth, the awarded total is the locally accrued credits plus that accepted
    transfer, rounded half up to two decimals; the tier chosen in the third step is
    final and is never re-derived from this total, and re-deriving it produces a
    different, wrong answer."

    Design: Difficulty/combinatorial_formula/transfer_cap_tier_keyed_on_pre_cap_total_not_re_derived_from_final_total
    """
    bundle = _received_request(client)

    validate_success(
        client.reconcile_transfer_request(bundle.request["id"], make_liaison_headers()),
        200,
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_student_ledgers(
        student, hours="6.00", transferred="7.00", locally="6.00", awarded="13.00"
    )
    assert_decimal_equals(
        student["total_awarded_credits"], "13.00", "student.total_awarded_credits"
    )
