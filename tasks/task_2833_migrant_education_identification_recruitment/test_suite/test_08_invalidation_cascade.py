"""Invalidation walks three hops and leaves already-earned hours standing."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_int_equals,
    assert_is_null,
    assert_row_count,
)
from test_helpers.constants import (
    CLOSURE_REASON_ELIGIBILITY_LOST,
    COE_INVALIDATED,
    ELIGIBILITY_TERM_EXPIRED,
    PLAN_CLOSED,
    SERVICE_CATEGORY_INSTRUCTION,
    SERVICE_STATUS_EXITED,
    TERMINATION_REASON_CERTIFICATE_INVALIDATED,
    TERM_TERMINATED,
)
from test_helpers.test_users import make_admin_headers, make_coordinator_headers

REASON = "Residency documentation withdrawn by the family."


def _serviced_child(client):
    """A certified child with an ACTIVE plan carrying one 2.00-hour delivered session."""
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    bundle.term = fixtures.only_term_for(client, bundle.student["id"])
    bundle.plan = fixtures.active_plan(client, bundle.student["id"])
    bundle.delivery = fixtures.post_delivery(
        client, bundle.plan["id"], delivered_on="2026-07-25", hours=2.00,
        service_category=SERVICE_CATEGORY_INSTRUCTION,
    )
    return bundle


def test_invalidation_terminates_the_term_and_closes_the_open_plan(client):
    """One invalidate call terminates the term and closes the plan with the cascade's reason.

    "Hop two, caused by hop one, finds every eligibility term whose `coe_id` is that
    certificate and whose `status` is `ACTIVE`, `EXPIRING` or `EXPIRED`, moves each to
    `TERMINATED`, sets each one's `termination_reason` to `CERTIFICATE_INVALIDATED`, and
    increments each term's `version` by 1."

    Design: Difficulty/transitive_cascade/cascade_b_coe_invalidation_walks_three_hops_and_preserves_earned_hours
    """
    bundle = _serviced_child(client)

    invalidated = validate_success(
        client.invalidate_coe(
            bundle.coe["id"], factories.invalidate_payload(REASON), make_admin_headers()
        ),
        200,
    )

    assert_int_equals(invalidated["status"], COE_INVALIDATED, "certificate.status")
    assert_int_equals(
        invalidated["invalidation_reason"], REASON, "certificate.invalidation_reason"
    )

    term = fixtures.read_term(client, bundle.term["id"])
    assert_int_equals(term["status"], TERM_TERMINATED, "term.status")
    assert_int_equals(
        term["termination_reason"],
        TERMINATION_REASON_CERTIFICATE_INVALIDATED,
        "term.termination_reason",
    )

    plan = fixtures.read_plan(client, bundle.plan["id"])
    assert_int_equals(plan["status"], PLAN_CLOSED, "plan.status")
    assert_int_equals(
        plan["closure_reason"], CLOSURE_REASON_ELIGIBILITY_LOST, "plan.closure_reason"
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_TERM_EXPIRED,
        "student.eligibility_status",
    )
    assert_is_null(student["eligibility_expires_on"], "student.eligibility_expires_on")
    assert_int_equals(
        student["service_status"], SERVICE_STATUS_EXITED, "student.service_status"
    )


def test_the_hours_already_delivered_survive_the_termination_cascade(client):
    """Closure inside the cascade never rewrites a ledger that plan status does not filter.

    "Closure never touches `delivered_hours` or the child's
    `total_service_hours_ledger` - hours already earned survive closure, exactly as
    earned credits do."

    Design: Difficulty/transitive_cascade/cascade_b_coe_invalidation_walks_three_hops_and_preserves_earned_hours
    """
    bundle = _serviced_child(client)

    validate_success(
        client.invalidate_coe(
            bundle.coe["id"], factories.invalidate_payload(REASON), make_admin_headers()
        ),
        200,
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_decimal_equals(
        student["total_service_hours_ledger"],
        "2.00",
        "student.total_service_hours_ledger",
    )

    plan = fixtures.read_plan(client, bundle.plan["id"])
    assert_decimal_equals(plan["delivered_hours"], "2.00", "plan.delivered_hours")

    rows, _meta = fixtures.list_rows(
        client.list_deliveries(make_coordinator_headers(), {"plan_id": bundle.plan["id"]})
    )
    assert_row_count(rows, 1, "delivered sessions on the closed plan")
    assert_int_equals(rows[0]["is_reversed"], False, "delivery.is_reversed")
    assert_decimal_equals(rows[0]["hours"], "2.00", "delivery.hours")
