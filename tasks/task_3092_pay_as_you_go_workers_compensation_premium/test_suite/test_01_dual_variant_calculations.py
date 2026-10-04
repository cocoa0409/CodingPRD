"""Dual-variant calculations: the PAYG design binds the actual-wages variant only."""

from test_helpers import (
    RATING_TABLES, TEST_USERS, class_code_entry, create_and_bind_policy,
    create_employer, get_success_data, payroll_line, set_clock,
    setup_rating_table, setup_variance_audit, file_audit,
    sole_invoice_for_report, submit_report, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]


def _divergence_policy():
    """CA+NV rating tables and a bound three-class policy at mod 1.1."""
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
    return employer, policy


def _divergence_report(policy_id):
    return submit_report(
        policy_id, "div-run-001",
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-08T00:00:00Z",
        lines=[
            payroll_line("CA", "8810", gross_wages_cents=100000, headcount=3),
            payroll_line("CA", "5645", gross_wages_cents=200000,
                         ot_premium_cents=10000, headcount=2),
            payroll_line("NV", "8810", gross_wages_cents=150000,
                         executive_wages_cents=150000, headcount=1),
        ])


def test_first_payroll_run_bills_actual_wages_not_the_estimated_basis(api):
    """PRD §3.2: "That estimated variant exists only to show what the PAYG design
    eliminates — the estimate is stored as a quote and is never invoiced; only
    actual reported wages ever produce an invoice."
    PRD §3.3: "In the same transaction the system computes and issues a
    **PremiumInvoice** of kind `PAYROLL`."

    Design: Difficulty/dual_variant_calc/issuance_estimate_vs_actual_payroll_invoice_diverge
    """
    _employer, policy = _divergence_policy()
    report = _divergence_report(policy["id"])

    assert report["status"] == "ACCEPTED"
    invoices, _meta = validate_paginated(
        api.list_policy_invoices(policy["id"], UW))
    assert len(invoices) == 1, (
        "the estimated-issuance variant is never invoiced: the only invoice on the "
        f"policy is the one the actual payroll run produced, got {len(invoices)}")
    assert invoices[0]["kind"] == "PAYROLL"
    assert invoices[0]["payroll_report_id"] == report["id"]


def test_actual_variant_invoice_total_diverges_from_estimated_scale(api):
    """PRD §3.3: "each line's premium is its remuneration_basis_cents multiplied by
    the rate_per_100_cents for its state and class from the rating table effective
    over the period, divided by ten thousand — the per-hundred-dollars factor and
    the cents conversion combined — and rounded half up to whole cents."
    PRD §3.2: "the same premium math described in §3.3, but with each assignment's
    estimated_annual_payroll_cents standing in for actual wages."

    Design: Difficulty/dual_variant_calc/issuance_estimate_vs_actual_payroll_invoice_diverge
    """
    _employer, policy = _divergence_policy()
    report = _divergence_report(policy["id"])

    invoice = sole_invoice_for_report(policy["id"], report["id"])
    # Actual variant on the reported week: CA/8810 basis 100000 -> 125;
    # CA/5645 basis 190000 (NET: OT premium out) -> 1691; NV/8810 basis 150000
    # (executive capped at 200000/wk, so uncapped) -> 210. Manual 20260.
    # Post-mod at 1.1: CA round(18350*1.1)=20185, NV round(2100*1.1)=2310.
    # Fees 3*250 + 2*250 + 1*400 = 1650; expense constant max(30000, 45000)=45000.
    assert invoice["manual_premium_cents"] == 20260
    assert invoice["per_capita_fees_cents"] == 1650
    assert invoice["expense_constant_cents"] == 45000
    assert invoice["total_cents"] == 68936
    # The estimated variant over the same classes uses the annual estimates as
    # basis (millions of dollars of payroll), so it lands orders of magnitude
    # away from the actual-week invoice — the two variants observably diverge.
    estimated_basis_total = 250000000 + 400000000 + 150000000
    assert invoice["manual_premium_cents"] * 1000 < estimated_basis_total, (
        "the actual payroll-run invoice is computed from the week's reported "
        "wages, not from the annual estimated payroll carried on the classes")


def test_audit_variance_counts_accepted_reports_only_with_full_quarters(api):
    """PRD §3.7: "The reported side, reported_payroll_cents, is the sum of
    remuneration_basis_cents across all lines of reports in ACCEPTED status whose
    periods fall fully inside the half-open audit window; submitted-but-not-yet-accepted
    reports are excluded from this binding, filing-time variant."
    PRD §3.7: "The filing side, filing_payroll_cents, is the sum of
    reported_wages_cents over every TaxFilingRecord whose filing period intersects
    the audit window; a quarter that only partially overlaps counts in full, with
    no proration. The variance_cents is the filing side minus the reported side."

    Design: Difficulty/dual_variant_calc/audit_variance_forward_looking_vs_filing_time_reported_side
    """
    fx = setup_variance_audit()
    assert fx["report_c"]["status"] == "REJECTED"
    assert fx["report_c"]["failure_code"] == "ERR_CLASS_CODE_NOT_ON_POLICY"

    filed = file_audit(fx["audit"]["id"], fx["policy_version"])
    # ACCEPTED reports fully inside [09-01, 10-01): A (190000) + B (10000000).
    assert filed["reported_payroll_cents"] == 10190000
    # Intersecting quarters counted in full: 200000000 + 500000.
    assert filed["filing_payroll_cents"] == 200500000
    assert filed["variance_cents"] == 200500000 - 10190000


def test_forward_looking_variant_is_not_the_binding_one(api):
    """PRD §3.7: "(Forward-looking exposure dashboards may run the same aggregation
    including SUBMITTED reports, which produces a higher reported figure and a lower
    apparent variance for identical data — that variant is explicitly non-binding.)"

    Design: Difficulty/dual_variant_calc/audit_variance_forward_looking_vs_filing_time_reported_side
    """
    fx = setup_variance_audit()
    filed = file_audit(fx["audit"]["id"], fx["policy_version"])

    # The REJECTED report C carries 100000 of would-be basis; a forward-looking
    # aggregation over the same data would show 10190000 + 100000 = 10290000 and
    # variance 190210000. The binding filing-time variant must not.
    assert filed["reported_payroll_cents"] == 10190000 != 10290000
    assert filed["variance_cents"] == 190310000 != 190210000
