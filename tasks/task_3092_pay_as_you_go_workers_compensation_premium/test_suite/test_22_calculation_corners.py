"""Calculation corners: the full invoice-total assembly, zero-variance audits and
inclusive day-count thresholds."""

from test_helpers import (
    TEST_USERS, api_client, class_code_entry, create_and_bind_policy,
    create_audit_payload, create_employer, create_tax_filing_payload,
    file_audit, get_integration, get_policy, make_role_headers, payroll_line,
    set_clock, setup_rating_table, sole_invoice_for_report, submit_report,
    validate_success, verify_audit,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]
TAXFILER = TEST_USERS["tax_filer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _divergence_invoice(api):
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    setup_rating_table("NV")
    employer = create_employer(legal_name="Divergence Construction Co",
                               fein="12-3456789",
                               contact_email="ops@divergence.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-DIV-001", experience_mod=1.1,
        class_codes=[class_code_entry("CA", "8810", 250000000),
                     class_code_entry("CA", "5645", 400000000),
                     class_code_entry("NV", "8810", 150000000)])
    report = submit_report(
        policy["id"], "div-run-001",
        lines=[payroll_line("CA", "8810", gross_wages_cents=100000, headcount=3),
               payroll_line("CA", "5645", gross_wages_cents=200000,
                            ot_premium_cents=10000, headcount=2),
               payroll_line("NV", "8810", gross_wages_cents=150000,
                            executive_wages_cents=150000, headcount=1)])
    return sole_invoice_for_report(policy["id"], report["id"])


def test_invoice_total_assembles_every_component_in_pinned_order(api):
    """PRD §3.3: "Per-capita fees accumulate as per_capita_fees_cents — the sum
    over lines of the line's headcount times its state's per_capita_admin_fee_cents.
    The invoice's expense_constant_cents is charged once, equal to the largest
    expense_constant_cents among the states actually appearing on the invoice —
    not the sum — and zero when no states are present."
    PRD §2.6: "the value actually applied is snapshotted onto each invoice as
    experience_mod_applied at issuance".

    Design: Corner/calculations/invoice_total_combines_all_components_with_pinned_literals
    """
    invoice = _divergence_invoice(api)
    # Manual: CA/8810 100000*125/10000 = 1250; CA/5645 190000*890/10000 = 16910;
    # NV/8810 150000*140/10000 = 2100.
    assert invoice["manual_premium_cents"] == 20260
    assert invoice["experience_mod_applied"] == 1.1, "the factor is snapshotted"
    # Post-mod: CA round(18160*1.1) = 19976 >= 10000, no substitution;
    # NV round(2100*1.1) = 2310 (threshold 0 unreachable).
    assert invoice["premium_after_mod_cents"] == 19976 + 2310
    assert invoice["per_capita_fees_cents"] == 3 * 250 + 2 * 250 + 1 * 400
    assert invoice["expense_constant_cents"] == 45000, (
        "the expense constant is the MAX across states (30000 vs 45000), not the "
        "sum 75000, and is charged once")
    assert invoice["total_cents"] == 68936


def test_zero_variance_audit_generates_no_trueup_and_closes(api):
    """PRD §3.7: "A zero or negative variance generates no invoice — premium is
    not refunded at audit — and trueup_invoice_id stays null."
    PRD §3.7: "when trueup_invoice_id is null or the true-up invoice has been
    paid, the reconciliation moves from VERIFIED to CLOSED."

    Design: Corner/calculations/audit_variance_zero_produces_no_trueup_invoice
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-ZRO-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    submit_report(policy["id"], "zro-run-1",
                  lines=[payroll_line("CA", "8810", gross_wages_cents=10000000)])
    validate_success(api.create_tax_filing(
        create_tax_filing_payload(policy["id"], quarter="2026Q3",
                                  period_start="2026-09-01T00:00:00Z",
                                  period_end="2026-10-01T00:00:00Z",
                                  reported_wages_cents=10000000), TAXFILER), 201)
    audit = validate_success(api.open_audit(
        create_audit_payload(policy["id"]), AUDITOR), 201)
    version = get_policy(policy["id"])["version"]

    filed = file_audit(audit["id"], version, filer_user_id="tf-zero")
    assert filed["variance_cents"] == 0, "filings exactly equal the reported basis"

    verified = verify_audit(audit["id"], verifier_user_id="au-zero")
    assert verified["trueup_invoice_id"] is None
    assert verified["status"] in ("VERIFIED", "CLOSED")
    final = validate_success(api.get_audit(audit["id"], AUDITOR), 200)
    assert final["status"] == "CLOSED", (
        "with no unpaid true-up, nothing blocks closure")


def test_broken_clock_boundary_twenty_days_does_not_trigger(api):
    """PRD §3.5: "At three or more missed cycles — or when the integration has been
    BROKEN for at least twenty-one consecutive days — the policy becomes
    NON_REPORTING".

    Design: Corner/calculations/cancellation_clock_inclusive_boundaries
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-THR-020",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    integration = get_integration(policy["id"])
    validate_success(api.heartbeat_integration(
        integration["id"], {"outcome": "BROKEN"}, PROVIDER), 200)

    set_clock("2026-09-21T00:00:00Z")  # exactly 20 broken days
    now = get_policy(policy["id"])
    assert now["reporting_status"] != "NON_REPORTING", (
        "twenty broken days is short of the twenty-one-day threshold")


def test_broken_clock_boundary_twenty_one_days_triggers_inclusively(api):
    """PRD §2.5: "every day-count threshold is inclusive at its lower boundary — a
    duration of exactly 21 days, zero hours, qualifies against a 21-day threshold."

    Design: Corner/calculations/cancellation_clock_inclusive_boundaries
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-THR-021",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    integration = get_integration(policy["id"])
    validate_success(api.heartbeat_integration(
        integration["id"], {"outcome": "BROKEN"}, PROVIDER), 200)

    set_clock("2026-09-22T00:00:00Z")  # exactly 21 broken days, zero hours
    now = get_policy(policy["id"])
    assert now["reporting_status"] == "NON_REPORTING", (
        "the inclusive lower boundary qualifies at exactly twenty-one days")
