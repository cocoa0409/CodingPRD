"""Compensating invariants: billed-ledger conservation and collected-money conservation."""

from test_helpers import (
    TEST_USERS, class_code_entry, create_and_bind_policy, create_employer,
    dispute_under_review, get_policy, list_policy_invoices,
    make_employer_admin_headers, make_role_headers, payroll_line, set_clock,
    setup_policy_with_accepted_report, setup_rating_table, submit_report,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]


def _retro_fixture():
    """Cascade Ceramics fixture: one accepted report (invoice 81000) plus an
    UNDER_REVIEW dispute requesting 8812 effective 2026-09-01."""
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Cascade Ceramics Ltd",
                               fein="66-7777888",
                               contact_email="claims@cascade.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-CAS-106",
        class_codes=[class_code_entry("CA", "8810", 2000000)])
    report = submit_report(
        policy["id"], "cas-run-101",
        lines=[payroll_line("CA", "8810", gross_wages_cents=4000000, headcount=4)])
    dispute, version = dispute_under_review(
        policy["id"], employer["id"], requested_class_code="8812",
        effective_from="2026-09-01T00:00:00Z")
    return employer, policy, report, dispute, version


def _approve(api, dispute_id, version):
    return validate_success(api.decide_dispute(
        dispute_id, {"decision": "APPROVED", "expected_policy_version": version},
        make_role_headers("uw-lee", "Underwriter")), 200)


def test_retro_cascade_conserves_one_live_payroll_invoice_per_report(api):
    """PRD §3.6: "the original invoice is voided, and a replacement PAYROLL
    invoice is recomputed under the new class code".
    PRD §3.6: "a RETRO_ADJUSTMENT invoice is issued whose total_cents is that
    delta".

    Design: Difficulty/compensating_invariant/retro_reassignment_preserves_invoice_identity_multiset
    """
    _emp, policy, report, dispute, version = _retro_fixture()
    _approve(api, dispute["id"], version)

    invoices = list_policy_invoices(policy["id"])
    for_report = [inv for inv in invoices
                  if inv.get("payroll_report_id") == report["id"]]
    live_payroll = [inv for inv in for_report
                    if inv["kind"] == "PAYROLL" and inv["status"] != "VOID"]
    voided = [inv for inv in for_report if inv["status"] == "VOID"]
    assert len(voided) == 1, "exactly one original invoice is voided"
    assert len(live_payroll) == 1, (
        "exactly one replacement PAYROLL invoice stands per re-invoiced report")
    adjustments = [inv for inv in invoices if inv["kind"] == "RETRO_ADJUSTMENT"]
    assert len(adjustments) == 1
    assert adjustments[0]["total_cents"] == 14000


def test_retro_cascade_billed_delta_equals_replacement_plus_adjustment(api):
    """PRD §2.8: "cumulative_billed_cents is the sum of total_cents over all of the
    policy's invoices currently in ISSUED or PAID status".
    PRD §3.6: "The signed difference between each replacement and its original
    accumulates into a running delta".

    Design: Difficulty/compensating_invariant/retro_reassignment_preserves_invoice_identity_multiset
    """
    _emp, policy, _report, dispute, version = _retro_fixture()
    billed_before = get_policy(policy["id"])["cumulative_billed_cents"]
    assert billed_before == 81000

    _approve(api, dispute["id"], version)

    billed_after = get_policy(policy["id"])["cumulative_billed_cents"]
    # 81000 - 81000 (original voided) + 95000 (replacement) + 14000 (adjustment),
    # and the adjustment is exactly the void/replace delta 95000 - 81000.
    assert billed_after == 109000
    assert billed_after - billed_before == 95000 + 14000 - 81000
    assert 14000 == 95000 - 81000


def test_payment_moves_collected_by_exactly_the_invoice_total(api):
    """PRD §3.4: "A successful payment moves the invoice from ISSUED to PAID,
    recomputes the policy's cumulative_collected_cents".
    PRD §2.8: "cumulative_collected_cents is the sum of total_cents over invoices
    in PAID status only."

    Design: Difficulty/compensating_invariant/payment_conserves_collected_total_and_billing_axis
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer, policy, _report, invoice = setup_policy_with_accepted_report(
        policy_number="WC-CSV-013")
    # round(10000000*125/10000)=125000 at mod 1.0, + 1*250 + 30000.
    assert invoice["total_cents"] == 155250
    set_clock("2026-09-10T00:00:00Z")
    collected_before = get_policy(policy["id"])["cumulative_collected_cents"]
    assert collected_before == 0

    validate_success(api.pay_invoice(
        invoice["id"], {"amount_cents": invoice["total_cents"]},
        make_employer_admin_headers(employer["id"])), 200)

    policy_now = get_policy(policy["id"])
    assert policy_now["cumulative_collected_cents"] == 155250, (
        "the ISSUED -> PAID pair moves collected by exactly the invoice total")


def test_payment_restores_billing_axis_without_double_counting_billed(api):
    """PRD §3.4: "when no unpaid ISSUED invoice remains, a policy in OVERDUE or
    SUSPENDED returns to CURRENT".
    PRD §2.8: "Issuing an invoice, voiding an invoice, and recording a payment
    each recompute the affected aggregates in the same transaction."

    Design: Difficulty/compensating_invariant/payment_conserves_collected_total_and_billing_axis
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer, policy, _report, invoice = setup_policy_with_accepted_report(
        policy_number="WC-CSV-113")
    set_clock("2026-09-10T00:00:00Z")
    assert get_policy(policy["id"])["billing_status"] == "OVERDUE"

    validate_success(api.pay_invoice(
        invoice["id"], {"amount_cents": invoice["total_cents"]},
        make_employer_admin_headers(employer["id"])), 200)

    policy_now = get_policy(policy["id"])
    assert policy_now["billing_status"] == "CURRENT", (
        "the compensating action restores the axis")
    assert policy_now["cumulative_billed_cents"] == 155250, (
        "payment never double-counts the billed aggregate")
