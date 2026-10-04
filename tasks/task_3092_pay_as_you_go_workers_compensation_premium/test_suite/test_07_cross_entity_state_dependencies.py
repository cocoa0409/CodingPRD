"""Cross-entity state dependencies: billing gates payroll; invoices gate audits."""

from test_helpers import (
    TEST_USERS, get_policy, make_employer_admin_headers, payroll_line, set_clock,
    setup_policy_with_accepted_report, setup_rating_table,
    setup_verified_audit_with_trueup, submit_report, validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _suspended_policy():
    """Bound policy whose one invoice goes unpaid long enough to SUSPEND billing."""
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer, policy, _report, invoice = setup_policy_with_accepted_report(
        policy_number="WC-GAT-011")
    # Invoice issued 09-01, due 09-08; fourteen days past due is 09-22, so by
    # 09-25 billing is SUSPENDED.
    set_clock("2026-09-25T00:00:00Z")
    return employer, policy, invoice


def test_payroll_submission_rejected_while_billing_suspended(api):
    """PRD §3.4: "When an invoice remains unpaid fourteen days past its due_date,
    the policy moves from OVERDUE to SUSPENDED, and from that point new payroll
    report submissions are rejected with ERR_BILLING_SUSPENDED until every issued
    invoice is paid."

    Design: Difficulty/cross_entity_state_dependency/payroll_acceptance_gated_by_policy_billing_status
    """
    _employer, policy, _invoice = _suspended_policy()
    policy_now = get_policy(policy["id"])
    assert policy_now["billing_status"] == "SUSPENDED", (
        "Setup failed: seventeen days past due must have suspended billing")

    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-08T00:00:00Z",
        "period_end": "2026-09-15T00:00:00Z",
        "idempotency_key": "gat-run-2",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=10000000)],
    }, PROVIDER)
    validate_error(res, "ERR_BILLING_SUSPENDED", expected_status=409)


def test_payroll_submission_accepted_again_after_full_payment(api):
    """PRD §3.4: "when no unpaid ISSUED invoice remains, a policy in OVERDUE or
    SUSPENDED returns to CURRENT, and payroll submissions are accepted again."

    Design: Difficulty/cross_entity_state_dependency/payroll_acceptance_gated_by_policy_billing_status
    """
    employer, policy, invoice = _suspended_policy()
    validate_success(api.pay_invoice(
        invoice["id"], {"amount_cents": invoice["total_cents"]},
        make_employer_admin_headers(employer["id"])), 200)

    policy_now = get_policy(policy["id"])
    assert policy_now["billing_status"] == "CURRENT"

    report = submit_report(policy["id"], "gat-run-3",
                           period_start="2026-09-08T00:00:00Z",
                           period_end="2026-09-15T00:00:00Z",
                           lines=[payroll_line("CA", "8810",
                                               gross_wages_cents=10000000)])
    assert report["status"] == "ACCEPTED", (
        "the identical report body is gated purely by the parent policy's "
        "billing axis; once paid, it is accepted")


def test_verified_audit_does_not_close_while_trueup_unpaid(api):
    """PRD §3.7: "The audit closes itself: when trueup_invoice_id is null or the
    true-up invoice has been paid, the reconciliation moves from VERIFIED to
    CLOSED."

    Design: Difficulty/cross_entity_state_dependency/audit_verify_gated_by_invoice_payment_for_closure
    """
    fx = setup_verified_audit_with_trueup()
    audit = validate_success(api.get_audit(fx["audit"]["id"], AUDITOR), 200)
    assert audit["status"] == "VERIFIED", (
        "every audit-side precondition is met, yet closure waits on the invoice")
    assert audit["trueup_invoice_id"] == fx["trueup_invoice"]["id"]


def test_verified_audit_closes_once_trueup_is_paid(api):
    """PRD §3.7: "when trueup_invoice_id is null or the true-up invoice has been
    paid, the reconciliation moves from VERIFIED to CLOSED."

    Design: Difficulty/cross_entity_state_dependency/audit_verify_gated_by_invoice_payment_for_closure
    """
    fx = setup_verified_audit_with_trueup()
    trueup = fx["trueup_invoice"]
    validate_success(api.pay_invoice(
        trueup["id"], {"amount_cents": trueup["total_cents"]},
        make_employer_admin_headers(fx["employer"]["id"])), 200)

    audit = validate_success(api.get_audit(fx["audit"]["id"], AUDITOR), 200)
    assert audit["status"] == "CLOSED", (
        "the audit moved without any direct call on the audit itself")
