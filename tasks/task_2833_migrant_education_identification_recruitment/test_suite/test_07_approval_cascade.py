"""Approval walks four hops from a certificate down to reallocated plan hours."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_int_equals,
    assert_pfs_triple,
    assert_plan_allocation,
    assert_row_count,
)
from test_helpers.constants import (
    COE_APPROVED,
    ELIGIBILITY_ELIGIBLE,
    PFS_VARIANT_INTERRUPTION_WEIGHTED,
    PLAN_DRAFT,
    PRIORITY_TIER_NON_PFS,
    PRIORITY_TIER_PFS,
    SERVICE_STATUS_PLAN_DRAFTED,
    TERM_ACTIVE,
)
from test_helpers.test_users import make_admin_headers


def _submitted_with_a_priority_funded_plan(client):
    """A SUBMITTED certificate, a DRAFT plan funded at the priority budget, clock at 2027."""
    bundle = fixtures.submitted_certificate(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    student_before = fixtures.read_student(client, bundle.student["id"])
    assert_pfs_triple(student_before, PFS_VARIANT_INTERRUPTION_WEIGHTED, 60, True)

    bundle.plan = fixtures.draft_plan(client, bundle.student["id"])
    assert_plan_allocation(
        fixtures.read_plan(client, bundle.plan["id"]),
        PRIORITY_TIER_PFS,
        "120.00",
        "plan before approval",
    )

    fixtures.set_clock(client, "2027-07-01T00:00:00Z")
    return bundle


def test_approval_writes_the_window_the_term_and_the_child_eligibility(client):
    """Hops one through three run certificate, term and child in that causal order.

    "**Hop two**, caused by hop one, creates a new **eligibility term** for the child:
    `student_id` copied from the certificate, `coe_id` pointing at the approving
    certificate, `term_start_on` copied from `eligibility_start_on`, `term_end_on`
    copied from `eligibility_end_on`, `status` set to `ACTIVE`, and
    `reidentification_due_on`, `superseded_by_term_id` and `termination_reason` all null."

    Design: Difficulty/transitive_cascade/cascade_a_coe_approval_walks_four_hops_to_reallocated_plan_hours
    """
    bundle = _submitted_with_a_priority_funded_plan(client)

    approved = validate_success(
        client.approve_coe(bundle.coe["id"], make_admin_headers()), 200
    )

    assert_int_equals(approved["status"], COE_APPROVED, "certificate.status")
    assert_date_equals(
        approved["eligibility_start_on"], "2026-07-01", "certificate.eligibility_start_on"
    )
    assert_date_equals(
        approved["eligibility_end_on"], "2029-06-30", "certificate.eligibility_end_on"
    )
    assert_int_equals(approved["age_out_capped"], False, "certificate.age_out_capped")

    terms, _meta = fixtures.list_rows(
        client.list_terms(make_admin_headers(), {"student_id": bundle.student["id"]})
    )
    assert_row_count(terms, 1, "eligibility terms for the child")
    term = terms[0]
    assert_int_equals(term["status"], TERM_ACTIVE, "term.status")
    assert_int_equals(term["coe_id"], bundle.coe["id"], "term.coe_id")
    assert_date_equals(term["term_start_on"], "2026-07-01", "term.term_start_on")
    assert_date_equals(term["term_end_on"], "2029-06-30", "term.term_end_on")

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"], ELIGIBILITY_ELIGIBLE, "student.eligibility_status"
    )
    assert_date_equals(
        student["eligibility_expires_on"], "2029-06-30", "student.eligibility_expires_on"
    )


def test_the_fourth_hop_rescores_the_child_and_reallocates_the_draft_plan(client):
    """The move has aged out of the recency window, so the plan drops to the lower budget.

    "**Hop four**, caused by hop three's mutation of the child, re-runs priority scoring,
    persisting `pfs_score`, `pfs_variant` and `pfs_flag`, and then re-runs the
    hour-allocation rule over every service plan of that child in `DRAFT` or `ACTIVE`
    status, rewriting each plan's `priority_tier`, `allocated_hours` and
    `expected_service_hours` and incrementing each touched plan's `version` by 1."

    Design: Difficulty/transitive_cascade/cascade_a_coe_approval_walks_four_hops_to_reallocated_plan_hours
    """
    bundle = _submitted_with_a_priority_funded_plan(client)

    validate_success(client.approve_coe(bundle.coe["id"], make_admin_headers()), 200)

    student = fixtures.read_student(client, bundle.student["id"])
    assert_pfs_triple(student, PFS_VARIANT_INTERRUPTION_WEIGHTED, 42, False)
    assert_int_equals(
        student["service_status"], SERVICE_STATUS_PLAN_DRAFTED, "student.service_status"
    )

    plan = fixtures.read_plan(client, bundle.plan["id"])
    assert_plan_allocation(plan, PRIORITY_TIER_NON_PFS, "75.00", "plan after approval")
    assert_int_equals(plan["status"], PLAN_DRAFT, "plan.status")
