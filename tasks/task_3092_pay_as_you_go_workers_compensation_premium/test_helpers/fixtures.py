"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch out of public endpoints, because
each individual test starts against an empty database. Setup steps use
``get_success_data()`` so a broken precondition reports itself as a setup failure
rather than as a confusing assertion failure in the test body.

Identity threading: after a helper creates an ``Employer``, every ownership-gated
call in that helper uses ``make_employer_admin_headers(employer["id"])`` — never the
shared EmployerAdmin constant.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import CLOCK_START, RATING_TABLES
from .factories import (
    class_code_entry,
    create_audit_payload,
    create_dispute_payload,
    create_employer_payload,
    create_policy_payload,
    create_tax_filing_payload,
    payroll_line,
)
from .test_users import TEST_USERS, make_employer_admin_headers

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]
TAXFILER = TEST_USERS["tax_filer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


# ═══════════════════════════════════════════════════════
# Tier 0: Reference data
# ═══════════════════════════════════════════════════════

def set_clock(current_utc=CLOCK_START):
    """Set the logical clock. Returns the value the server reports back."""
    res = api_client.set_clock(current_utc, ADMIN)
    return get_success_data(res)["current_utc"]


def ensure_clock(current_utc=CLOCK_START):
    """Idempotent clock set: skip the call when the clock already reads the value.

    The threshold sweep on a clock set is time-moving logic; re-setting the same
    instant is harmless, so this exists purely to keep composite fixtures cheap.
    """
    return set_clock(current_utc)


def setup_rating_table(state_code="CA"):
    """Publish one of the shared rating-table fixtures (CA, NV, MT, OH)."""
    res = api_client.create_state_rating_table(dict(RATING_TABLES[state_code]), ADMIN)
    return get_success_data(res)


def create_employer(**overrides):
    """Register an employer; returns the created Employer (status ACTIVE)."""
    res = api_client.create_employer(create_employer_payload(**overrides), ADMIN)
    return get_success_data(res)


# ═══════════════════════════════════════════════════════
# Tier 1: Policy state progression
# ═══════════════════════════════════════════════════════

def create_policy(employer_id, policy_number="WC-TEST-001", class_codes=None,
                  **overrides):
    """Issue a PENDING policy with its class assignments in one call."""
    res = api_client.create_policy(
        create_policy_payload(employer_id, policy_number=policy_number,
                              class_codes=class_codes, **overrides), UW)
    return get_success_data(res)


def create_and_bind_policy(employer_id=None, policy_number="WC-TEST-001",
                           class_codes=None, _clock=None, **overrides):
    """Create a policy and bind it. Returns the bound (ACTIVE) policy.

    Creates its own employer when none is supplied. ``_clock`` moves the logical
    clock forward before binding, for policies whose term starts in the future.
    """
    if employer_id is None:
        employer_id = create_employer()["id"]
    policy = create_policy(employer_id, policy_number=policy_number,
                           class_codes=class_codes, **overrides)
    if _clock is not None:
        set_clock(_clock)
    return get_success_data(api_client.bind_policy(policy["id"], UW))


def get_policy(policy_id):
    return get_success_data(api_client.get_policy(policy_id, UW))


def get_first_class_code(policy_id):
    """The policy's first class assignment (creation order)."""
    rows, _meta = _list(api_client.list_policy_class_codes(policy_id, UW))
    assert rows, f"policy {policy_id} has no class assignments"
    return rows[0]


def get_integration(policy_id):
    """The policy's 1:1 payroll integration."""
    rows, _meta = _list(api_client.get_policy_integration(policy_id, UW))
    assert len(rows) == 1, "a bound policy has exactly one integration"
    return rows[0]


def _list(response):
    from prd_bench_local_runner.testing import validate_paginated
    return validate_paginated(response)


# ═══════════════════════════════════════════════════════
# Tier 2: Payroll reports and invoices
# ═══════════════════════════════════════════════════════

def submit_report(policy_id, idempotency_key,
                  period_start="2026-09-01T00:00:00Z",
                  period_end="2026-09-08T00:00:00Z",
                  lines=None):
    """Submit a payroll report expected to pass acceptance. Returns the report."""
    payload = {
        "policy_id": policy_id,
        "period_start": period_start,
        "period_end": period_end,
        "idempotency_key": idempotency_key,
        "lines": lines if lines is not None else [payroll_line()],
    }
    report = get_success_data(api_client.submit_payroll_report(payload, PROVIDER))
    assert report["status"] == "ACCEPTED", (
        f"Setup failed: report {idempotency_key} came back {report['status']} "
        f"({report.get('failure_code')})")
    return report


def list_policy_invoices(policy_id, **params):
    rows, _meta = _list(api_client.list_policy_invoices(policy_id, UW,
                                                        params=params or None))
    return rows


def sole_invoice_for_report(policy_id, report_id):
    """The single PAYROLL invoice generated by an accepted report."""
    invoices = [inv for inv in list_policy_invoices(policy_id)
                if inv.get("payroll_report_id") == report_id]
    assert len(invoices) == 1, (
        f"expected exactly one invoice for report {report_id}, got {len(invoices)}")
    return invoices[0]


def pay_invoice_in_full(invoice, employer_id):
    """Pay an ISSUED invoice for exactly its total, as the owning employer."""
    res = api_client.pay_invoice(invoice["id"], {"amount_cents": invoice["total_cents"]},
                                 make_employer_admin_headers(employer_id))
    return get_success_data(res)


def setup_policy_with_accepted_report(class_codes=None, report_lines=None,
                                      policy_number="WC-REP-001",
                                      period_start="2026-09-01T00:00:00Z",
                                      period_end="2026-09-08T00:00:00Z",
                                      idempotency_key="run-1", **policy_overrides):
    """Bound policy plus one ACCEPTED report. Returns (employer, policy, report, invoice)."""
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number=policy_number,
                                    class_codes=class_codes, **policy_overrides)
    report = submit_report(policy["id"], idempotency_key,
                           period_start=period_start, period_end=period_end,
                           lines=report_lines)
    invoice = sole_invoice_for_report(policy["id"], report["id"])
    return employer, policy, report, invoice


# ═══════════════════════════════════════════════════════
# Tier 3: Dispute lifecycle
# ═══════════════════════════════════════════════════════

def file_dispute(policy_id, policy_class_code_id, employer_id,
                 requested_class_code="8812",
                 effective_from="2026-09-01T00:00:00Z", **overrides):
    """File a dispute as the owning EmployerAdmin. Returns the FILED dispute.

    PRD §3.6 requires the retroactive ``effective_from`` to be strictly before
    the current logical clock, so when the default window start is used the
    clock is first nudged one second past it.
    """
    if effective_from == "2026-09-01T00:00:00Z":
        set_clock("2026-09-01T00:00:01Z")
    res = api_client.file_dispute(
        create_dispute_payload(policy_id, policy_class_code_id,
                               requested_class_code=requested_class_code,
                               effective_from=effective_from, **overrides),
        make_employer_admin_headers(employer_id))
    return get_success_data(res)


def dispute_under_review(policy_id, employer_id, requested_class_code="8812",
                         effective_from="2026-09-01T00:00:00Z"):
    """File a dispute and open review. Returns (dispute, current policy version)."""
    pcc = get_first_class_code(policy_id)
    dispute = file_dispute(policy_id, pcc["id"], employer_id,
                           requested_class_code=requested_class_code,
                           effective_from=effective_from)
    dispute = get_success_data(api_client.open_dispute_review(dispute["id"], UW))
    version = get_policy(policy_id)["version"]
    return dispute, version


# ═══════════════════════════════════════════════════════
# Tier 4: Audit / variance fixtures
# ═══════════════════════════════════════════════════════

def setup_variance_audit(pay_ab_invoices=False):
    """The audit-variance fixture: a bound CA-only policy (mod 1.0) with

    - report A [2026-09-01, 2026-09-08) ACCEPTED, one CA/5645 line, basis 190000
      (gross 200000, OT premium 10000 in a NET state),
    - report B [2026-09-08, 2026-09-15) ACCEPTED, one CA/8810 line, basis 10000000,
    - report C [2026-09-15, 2026-09-22) REJECTED (class 9999 not on the policy),
    - report D [2026-10-01, 2026-10-08) ACCEPTED (outside the audit window),
    - filings 2026Q3 wages 200000000 and 2026Q4 wages 500000,
    - an OPEN audit over [2026-09-01, 2026-10-01).

    Billing health on the way to October: report D is submitted on day 31, past
    the fourteen-days-past-due suspension point of PRD §3.4 for the unpaid A
    invoice. When ``pay_ab_invoices`` is false the A/B invoices are voided by
    the underwriter before the clock jump — PRD §3.4 permits voiding an ISSUED
    invoice, voiding only removes the invoice from the billed/collected
    aggregates, and the §3.7 filing-time variance reads report status, line
    basis, and tax filings only, so the audit math is untouched. When true, the
    A/B invoices are paid in full instead (for tests that exercise billing
    recovery through payment).

    Returns a dict with employer, policy, reports, audit and the policy version.
    """
    setup_rating_table("CA")
    employer = create_employer(legal_name="Variance Farms Inc",
                               fein="98-7654321",
                               contact_email="tax@variance.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-VAR-002",
        class_codes=[class_code_entry("CA", "8810", 1000000),
                     class_code_entry("CA", "5645", 2000000)])

    report_a = submit_report(
        policy["id"], "var-run-a",
        period_start="2026-09-01T00:00:00Z", period_end="2026-09-08T00:00:00Z",
        lines=[payroll_line("CA", "5645", gross_wages_cents=200000,
                            ot_premium_cents=10000, headcount=2)])
    report_b = submit_report(
        policy["id"], "var-run-b",
        period_start="2026-09-08T00:00:00Z", period_end="2026-09-15T00:00:00Z",
        lines=[payroll_line("CA", "8810", gross_wages_cents=10000000, headcount=2)])
    rejected = get_success_data(api_client.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-15T00:00:00Z",
        "period_end": "2026-09-22T00:00:00Z",
        "idempotency_key": "var-run-c",
        "lines": [payroll_line("CA", "9999", gross_wages_cents=100000)],
    }, PROVIDER))
    assert rejected["status"] == "REJECTED", (
        f"Setup failed: var-run-c came back {rejected['status']}")

    # Clear the A/B invoices before advancing the clock (see docstring):
    # otherwise the fourteen-days-past-due suspension of PRD §3.4 would block
    # report D with ERR_BILLING_SUSPENDED.
    if pay_ab_invoices:
        pay_invoice_in_full(sole_invoice_for_report(policy["id"], report_a["id"]),
                            employer["id"])
        pay_invoice_in_full(sole_invoice_for_report(policy["id"], report_b["id"]),
                            employer["id"])
    else:
        for rep in (report_a, report_b):
            inv = sole_invoice_for_report(policy["id"], rep["id"])
            get_success_data(api_client.void_invoice(inv["id"], UW))

    set_clock("2026-10-02T00:00:00Z")
    report_d = submit_report(
        policy["id"], "var-run-d",
        period_start="2026-10-01T00:00:00Z", period_end="2026-10-08T00:00:00Z",
        lines=[payroll_line("CA", "8810", gross_wages_cents=200000, headcount=2)])

    get_success_data(api_client.create_tax_filing(
        create_tax_filing_payload(policy["id"], quarter="2026Q3",
                                  period_start="2026-07-01T00:00:00Z",
                                  period_end="2026-10-01T00:00:00Z",
                                  reported_wages_cents=200000000), TAXFILER))
    get_success_data(api_client.create_tax_filing(
        create_tax_filing_payload(policy["id"], quarter="2026Q4",
                                  period_start="2026-10-01T00:00:00Z",
                                  period_end="2027-01-01T00:00:00Z",
                                  reported_wages_cents=500000), TAXFILER))

    audit = get_success_data(api_client.open_audit(
        create_audit_payload(policy["id"]), AUDITOR))
    # With the A/B invoices voided and no reports after the window, report D's
    # invoice is the only one that could linger past its due date; pay it so
    # downstream billing assertions key off the true-up invoice alone.
    if not pay_ab_invoices:
        pay_invoice_in_full(sole_invoice_for_report(policy["id"], report_d["id"]),
                            employer["id"])
    version = get_success_data(api_client.get_policy(policy["id"], TAXFILER))["version"]
    return {
        "employer": employer,
        "policy": policy,
        "report_a": report_a,
        "report_b": report_b,
        "report_c": rejected,
        "report_d": report_d,
        "audit": audit,
        "policy_version": version,
    }


def file_audit(audit_id, policy_version, filer_user_id="tf-nina"):
    """File an OPEN audit with the current policy version. Returns the FILED audit."""
    from .test_users import make_role_headers
    res = api_client.file_audit(audit_id,
                                {"expected_policy_version": policy_version},
                                make_role_headers(filer_user_id, "TaxFiler"))
    return get_success_data(res)


def verify_audit(audit_id, verifier_user_id="au-sam"):
    """Verify a FILED audit as a different user than the filer."""
    from .test_users import make_role_headers
    res = api_client.verify_audit(audit_id, make_role_headers(verifier_user_id, "Auditor"))
    return get_success_data(res)


def setup_verified_audit_with_trueup():
    """The variance fixture taken through filing and verification.

    Returns the fixture dict plus the VERIFIED audit (carrying a non-null
    trueup_invoice_id) and the AUDIT_TRUEUP invoice. The A/B invoices are
    voided (not paid) so the only outstanding ISSUED invoice after
    verification is the true-up itself — billing recovery then hinges solely
    on the true-up payment, per PRD §3.4.
    """
    fx = setup_variance_audit()
    filed = file_audit(fx["audit"]["id"], fx["policy_version"])
    verified = verify_audit(filed["id"])
    assert verified["status"] == "VERIFIED", (
        f"Setup failed: audit came back {verified['status']}")
    trueup_id = verified.get("trueup_invoice_id")
    assert trueup_id, "Setup failed: positive variance produced no true-up invoice"
    trueup = get_success_data(api_client.get_invoice(trueup_id, AUDITOR))
    fx["audit"] = verified
    fx["trueup_invoice"] = trueup
    return fx
