"""Boundary precision: minimum-premium substitution and half-open payroll intervals."""

from test_helpers import (
    TEST_USERS, class_code_entry, create_and_bind_policy, create_employer,
    payroll_line, set_clock, setup_rating_table, sole_invoice_for_report,
    submit_report, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]


def _mt_policy():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("MT")
    employer = create_employer(legal_name="Boundary Builders MT",
                               fein="22-3333444",
                               contact_email="payroll@boundary.example",
                               home_state="MT")
    return create_and_bind_policy(
        employer["id"], policy_number="WC-BND-009",
        class_codes=[class_code_entry("MT", "8810", 500000)])


def test_subtotal_strictly_below_threshold_is_replaced_by_state_minimum(api):
    """PRD §3.3: "when a state's post-modification subtotal is strictly less than
    that state's min_payroll_threshold_cents, the subtotal is replaced by the
    state's state_minimum_premium_cents".

    Design: Difficulty/boundary_precision_check/minimum_premium_substitution_strictly_less_than
    """
    policy = _mt_policy()
    report = submit_report(
        policy["id"], "bnd-run-below",
        lines=[payroll_line("MT", "8810", gross_wages_cents=10000)])
    invoice = sole_invoice_for_report(policy["id"], report["id"])
    # Subtotal round(10000 * 100 / 10000) = 100 < 5000 -> replaced by 30000;
    # total = 30000 + 1*300 + 20000.
    assert invoice["premium_after_mod_cents"] == 30000
    assert invoice["total_cents"] == 50300


def test_subtotal_exactly_at_threshold_is_not_replaced(api):
    """PRD §3.3: "a subtotal exactly equal to the threshold is not replaced."

    Design: Difficulty/boundary_precision_check/minimum_premium_substitution_strictly_less_than
    """
    policy = _mt_policy()
    report = submit_report(
        policy["id"], "bnd-run-at",
        lines=[payroll_line("MT", "8810", gross_wages_cents=500000)])
    invoice = sole_invoice_for_report(policy["id"], report["id"])
    # Subtotal round(500000 * 100 / 10000) = 5000 == 5000 -> no substitution;
    # total = 5000 + 300 + 20000.
    assert invoice["premium_after_mod_cents"] == 5000
    assert invoice["total_cents"] == 25300


def _adjacency_policy_with_first_report():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Adjacency Athletics",
                               fein="33-4444555",
                               contact_email="pay@adjacency.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-ADJ-010",
        class_codes=[class_code_entry("CA", "8810", 1000000)])
    submit_report(policy["id"], "adj-run-1",
                  period_start="2026-09-01T00:00:00Z",
                  period_end="2026-09-08T00:00:00Z",
                  lines=[payroll_line("CA", "8810", gross_wages_cents=10000000)])
    return policy


def test_report_starting_at_prior_period_end_is_accepted(api):
    """PRD §3.3: "must not overlap, under half-open interval semantics, any
    existing SUBMITTED or ACCEPTED report for the policy".

    Design: Difficulty/boundary_precision_check/payroll_interval_half_open_adjacency_vs_overlap
    """
    policy = _adjacency_policy_with_first_report()
    report = submit_report(policy["id"], "adj-run-2",
                           period_start="2026-09-08T00:00:00Z",
                           period_end="2026-09-15T00:00:00Z",
                           lines=[payroll_line("CA", "8810",
                                               gross_wages_cents=10000000)])
    assert report["status"] == "ACCEPTED", (
        "touching at period_end is an empty intersection, not an overlap")


def test_report_starting_one_second_before_prior_end_is_rejected(api):
    """PRD §3.3: "A submission that passes request-level validation but fails an
    acceptance check is not discarded: it is persisted as a report in REJECTED
    status, its failure_code set to the error identifier of the failed check".

    Design: Difficulty/boundary_precision_check/payroll_interval_half_open_adjacency_vs_overlap
    """
    policy = _adjacency_policy_with_first_report()
    submit_report(policy["id"], "adj-run-2",
                  period_start="2026-09-08T00:00:00Z",
                  period_end="2026-09-15T00:00:00Z",
                  lines=[payroll_line("CA", "8810", gross_wages_cents=10000000)])

    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-14T23:59:59Z",
        "period_end": "2026-09-22T00:00:00Z",
        "idempotency_key": "adj-run-3",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=10000000)],
    }, PROVIDER)
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["failure_code"] == "ERR_PAYROLL_PERIOD_OVERLAP", (
        "one second of real intersection violates the half-open overlap rule")

    reports, _meta = validate_paginated(api.list_policy_reports(policy["id"], UW))
    by_status = {}
    for r in reports:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    assert by_status.get("ACCEPTED") == 2
    assert by_status.get("REJECTED") == 1
