"""Consistency is immediate: one approve call settles the whole chain before it answers."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_int_equals,
    assert_plan_allocation,
    assert_row_count,
)
from test_helpers.constants import (
    BUDGET_NON_PFS,
    COE_APPROVED,
    ELIGIBILITY_ELIGIBLE,
    PLAN_DRAFT,
    PRIORITY_TIER_NON_PFS,
    TERM_ACTIVE,
)
from test_helpers.test_users import make_admin_headers, make_liaison_headers


def test_approve_response_already_carries_every_cascaded_value(client):
    """The approve body carries the computed window, and the reads that follow need no delay.

    "**Hop one** moves the certificate to `APPROVED` and writes the **final eligibility
    window**, which is a different variant of the same rule that produced the provisional
    window." "**Hop two**, caused by hop one, creates a new **eligibility term** for the child:
    `student_id` copied from the certificate, `coe_id` pointing at the approving certificate,
    `term_start_on` copied from `eligibility_start_on`, `term_end_on` copied from
    `eligibility_end_on`, `status` set to `ACTIVE`, and `reidentification_due_on`,
    `superseded_by_term_id` and `termination_reason` all null."

    Design: Corner/consistency_model/corner_approve_response_already_carries_every_cascaded_value
    """
    bundle = fixtures.submitted_certificate(
        client,
        coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True},
        birth_date="2010-03-20",
        school_days_interrupted=0,
        credit_deficit=0,
        math_below_grade=False,
        reading_below_grade=False,
    )
    plan = fixtures.draft_plan(client, bundle.student["id"])
    assert_int_equals(plan["status"], PLAN_DRAFT, "plan.status")
    assert_plan_allocation(plan, PRIORITY_TIER_NON_PFS, BUDGET_NON_PFS, "plan before approval")

    approved = validate_success(
        client.approve_coe(bundle.coe["id"], make_admin_headers()), 200
    )

    assert_int_equals(approved["status"], COE_APPROVED, "coe.status")
    assert_date_equals(
        approved["eligibility_start_on"], "2026-07-01", "coe.eligibility_start_on"
    )
    assert_date_equals(
        approved["eligibility_end_on"], "2029-06-30", "coe.eligibility_end_on"
    )
    assert_int_equals(approved["age_out_capped"], False, "coe.age_out_capped")

    terms, _meta = fixtures.list_rows(
        client.list_terms(make_liaison_headers(), {"student_id": bundle.student["id"]})
    )
    assert_row_count(terms, 1, "eligibility terms visible immediately after approval")
    assert_int_equals(terms[0]["status"], TERM_ACTIVE, "term.status")
    assert_date_equals(terms[0]["term_start_on"], "2026-07-01", "term.term_start_on")
    assert_date_equals(terms[0]["term_end_on"], "2029-06-30", "term.term_end_on")
    assert_int_equals(terms[0]["coe_id"], bundle.coe["id"], "term.coe_id")

    child = validate_success(
        client.get_student(bundle.student["id"], make_liaison_headers()), 200
    )
    assert_int_equals(
        child["eligibility_status"], ELIGIBILITY_ELIGIBLE, "student.eligibility_status"
    )
    assert_date_equals(
        child["eligibility_expires_on"], "2029-06-30", "student.eligibility_expires_on"
    )

    settled_plan = validate_success(
        client.get_plan(plan["id"], make_liaison_headers()), 200
    )
    assert_plan_allocation(
        settled_plan, PRIORITY_TIER_NON_PFS, BUDGET_NON_PFS, "plan after approval"
    )
