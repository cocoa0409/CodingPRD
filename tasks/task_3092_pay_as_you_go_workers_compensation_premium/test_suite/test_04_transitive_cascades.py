"""Transitive cascades: dispute approval re-invoicing and true-up payment closure."""

from test_helpers import (
    TEST_USERS, class_code_entry, create_and_bind_policy, create_employer,
    dispute_under_review, get_policy, list_policy_invoices,
    make_employer_admin_headers, make_role_headers, payroll_line, set_clock,
    setup_rating_table, setup_verified_audit_with_trueup, sole_invoice_for_report,
    submit_report, validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def _cascade_fixture():
    """Bound CA policy with one accepted report (original invoice 81000) and an
    UNDER_REVIEW dispute requesting class 8812 effective 2026-09-01."""
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Cascade Ceramics Ltd",
                               fein="66-7777888",
                               contact_email="claims@cascade.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-CAS-006",
        class_codes=[class_code_entry("CA", "8810", 2000000)])
    report = submit_report(
        policy["id"], "cas-run-001",
        lines=[payroll_line("CA", "8810", gross_wages_cents=4000000, headcount=4)])
    original = sole_invoice_for_report(policy["id"], report["id"])
    dispute, version = dispute_under_review(
        policy["id"], employer["id"], requested_class_code="8812",
        effective_from="2026-09-01T00:00:00Z")
    return employer, policy, report, original, dispute, version


def _approve(api, dispute_id, version):
    return validate_success(api.decide_dispute(
        dispute_id, {"decision": "APPROVED", "expected_policy_version": version},
        make_role_headers("uw-lee", "Underwriter")), 200)


def test_approval_supersedes_report_and_replaces_its_invoice(api):
    """PRD §3.6: "every ACCEPTED payroll report whose period intersects the
    retroactive window — from the dispute's effective_from through the policy's
    expiry_date, which in practice means any report whose period_end falls on or
    after the dispute's effective_from — is superseded and re-invoiced."
    PRD §3.6: "For each affected report, moving from ACCEPTED to SUPERSEDED: the
    original PAYROLL invoice's total_cents is captured, the original invoice is
    voided, and a replacement PAYROLL invoice is recomputed under the new class
    code using the rate of the requested_class_code in force during the report's
    period, with every other formula and constant unchanged."

    Design: Difficulty/transitive_cascade/dispute_approval_supersede_reinvoice_adjustment_chain
    """
    _emp, policy, report, original, dispute, version = _cascade_fixture()
    assert original["total_cents"] == 81000  # 50000 post-mod + 4*250 + 30000

    _approve(api, dispute["id"], version)

    report_now = validate_success(api.get_payroll_report(report["id"], UW), 200)
    assert report_now["status"] == "SUPERSEDED", (
        "hop 2: the reassignment superseded the report with no direct report call")
    original_now = validate_success(api.get_invoice(original["id"], UW), 200)
    assert original_now["status"] == "VOID", "hop 3: the original invoice is voided"

    replacements = [inv for inv in list_policy_invoices(policy["id"])
                    if inv["kind"] == "PAYROLL" and inv["status"] == "ISSUED"]
    assert len(replacements) == 1
    # Replacement under rate 160: round(4000000*160/10000)=64000 + 1000 + 30000.
    assert replacements[0]["total_cents"] == 95000


def test_approval_issues_retro_adjustment_for_the_signed_delta(api):
    """PRD §3.6: "The signed difference between each replacement and its original
    accumulates into a running delta, and a RETRO_ADJUSTMENT invoice is issued
    whose total_cents is that delta — negative when the reassignment reduces
    premium, in which case it stands as a credit."
    PRD §2.8: "cumulative_billed_cents is the sum of total_cents over all of the
    policy's invoices currently in ISSUED or PAID status".

    Design: Difficulty/transitive_cascade/dispute_approval_supersede_reinvoice_adjustment_chain
    """
    _emp, policy, _report, _original, dispute, version = _cascade_fixture()
    _approve(api, dispute["id"], version)

    adjustments = [inv for inv in list_policy_invoices(policy["id"])
                   if inv["kind"] == "RETRO_ADJUSTMENT"]
    assert len(adjustments) == 1, "hop 4: exactly one adjustment invoice"
    assert adjustments[0]["total_cents"] == 14000  # 95000 - 81000

    policy_now = get_policy(policy["id"])
    # VOID is excluded from billed: replacement 95000 + adjustment 14000.
    assert policy_now["cumulative_billed_cents"] == 109000


def test_trueup_payment_flips_billing_back_to_current(api):
    """PRD §3.4: "A successful payment moves the invoice from ISSUED to PAID,
    recomputes the policy's cumulative_collected_cents, increments the policy's
    version, and re-evaluates billing health: when no unpaid ISSUED invoice
    remains, a policy in OVERDUE or SUSPENDED returns to CURRENT".

    Design: Difficulty/transitive_cascade/invoice_payment_billing_current_audit_closure_chain
    """
    fx = setup_verified_audit_with_trueup()
    trueup = fx["trueup_invoice"]
    set_clock("2026-10-20T00:00:00Z")
    overdue = get_policy(fx["policy"]["id"])
    assert overdue["billing_status"] == "OVERDUE", (
        "Setup failed: the unpaid true-up invoice is past due, billing must be OVERDUE")

    paid = validate_success(api.pay_invoice(
        trueup["id"], {"amount_cents": trueup["total_cents"]},
        make_employer_admin_headers(fx["employer"]["id"])), 200)
    assert paid["status"] == "PAID", "hop 1: the true-up invoice is paid"

    now = get_policy(fx["policy"]["id"])
    assert now["billing_status"] == "CURRENT", (
        "hop 2: no unpaid ISSUED invoice remains, so billing recovers")
    assert trueup["total_cents"] > 0
    assert now["cumulative_collected_cents"] >= trueup["total_cents"], (
        "collected includes the true-up total")


def test_trueup_payment_closes_the_verified_audit(api):
    """PRD §3.7: "The audit closes itself: when trueup_invoice_id is null or the
    true-up invoice has been paid, the reconciliation moves from VERIFIED to
    CLOSED."

    Design: Difficulty/transitive_cascade/invoice_payment_billing_current_audit_closure_chain
    """
    fx = setup_verified_audit_with_trueup()
    trueup = fx["trueup_invoice"]

    before = validate_success(api.get_audit(fx["audit"]["id"],
                                            TEST_USERS["auditor_headers"]), 200)
    assert before["status"] == "VERIFIED", (
        "while the true-up is unpaid the audit holds in VERIFIED")

    validate_success(api.pay_invoice(
        trueup["id"], {"amount_cents": trueup["total_cents"]},
        make_employer_admin_headers(fx["employer"]["id"])), 200)

    after = validate_success(api.get_audit(fx["audit"]["id"],
                                           TEST_USERS["auditor_headers"]), 200)
    assert after["status"] == "CLOSED", (
        "hop 3: the payment satisfied the closure precondition with no direct "
        "call on the audit")
