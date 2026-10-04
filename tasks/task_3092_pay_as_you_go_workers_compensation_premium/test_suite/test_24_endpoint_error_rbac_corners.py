"""Endpoint, error-catalog and RBAC corners: conditional payment action, stale
versions, forbidden roles, segregation of duties and employer ownership."""

from test_helpers import (
    TEST_USERS, api_client, class_code_entry, create_and_bind_policy,
    create_audit_payload, create_employer, create_tax_filing_payload,
    dispute_under_review, file_audit, get_first_class_code, get_policy,
    make_employer_admin_headers, make_role_headers, payroll_line, set_clock,
    setup_policy_with_accepted_report, setup_rating_table, submit_report,
    validate_error, validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]
TAXFILER = TEST_USERS["tax_filer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _paid_invoice_fixture():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer, policy, _report, invoice = setup_policy_with_accepted_report(
        policy_number="WC-CND-001")
    validate_success(api_client.pay_invoice(
        invoice["id"], {"amount_cents": invoice["total_cents"]},
        make_employer_admin_headers(employer["id"])), 200)
    return employer, policy, invoice


def test_paying_an_already_paid_invoice_fails_the_state_check(api):
    """PRD §3.4: "Payment is accepted only against an invoice in ISSUED status —
    an attempt against any other status fails the state check with
    ERR_INVALID_STATE".

    Design: Corner/endpoints/invoice_payment_endpoint_is_conditional_action
    """
    employer, _policy, invoice = _paid_invoice_fixture()
    res = api.pay_invoice(invoice["id"], {"amount_cents": invoice["total_cents"]},
                          make_employer_admin_headers(employer["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_audit_file_with_stale_policy_version_is_rejected(api):
    """PRD §2.7: "Filing an audit reconciliation likewise requires
    expected_policy_version; any mutation of the policy since the filer's last
    read — a new report, an invoice payment, a dispute decision — invalidates the
    variance snapshot the filer computed against, and the filing is rejected as
    stale."

    Design: Corner/errors/stale_version_on_audit_file
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-OCC-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    validate_success(api.create_tax_filing(
        create_tax_filing_payload(policy["id"], quarter="2026Q3",
                                  period_start="2026-09-01T00:00:00Z",
                                  period_end="2026-10-01T00:00:00Z",
                                  reported_wages_cents=10000000), TAXFILER), 201)
    audit = validate_success(api.open_audit(
        create_audit_payload(policy["id"]), AUDITOR), 201)
    stale_version = get_policy(policy["id"])["version"]

    # A report acceptance mutates the policy after the filer's read.
    submit_report(policy["id"], "occ-run-1",
                  lines=[payroll_line("CA", "8810", gross_wages_cents=10000000)])

    res = api.file_audit(audit["id"], {"expected_policy_version": stale_version},
                         make_role_headers("tf-occ", "TaxFiler"))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_authenticated_employer_admin_cannot_create_policies(api):
    """PRD §2.1: "an authenticated caller whose role is not permitted for the
    endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."

    Design: Corner/errors/forbidden_role_error_distinct_from_unauthenticated
    """
    employer = create_employer()
    res = api.create_policy({
        "employer_id": employer["id"],
        "policy_number": "WC-FRB-001",
        "effective_date": "2026-09-01T00:00:00Z",
        "expiry_date": "2027-09-01T00:00:00Z",
        "experience_mod": 1.0,
        "class_codes": [class_code_entry("CA", "8810", 1000000)],
    }, make_employer_admin_headers(employer["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_audit_verifier_must_differ_from_the_filer(api):
    """PRD §2.11: "the audit records filed_by at filing time, and a verification
    whose X-User-ID equals that value is rejected with the same error."

    Design: Corner/errors/segregation_of_duties_on_audit_verify
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-SOD-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    validate_success(api.create_tax_filing(
        create_tax_filing_payload(policy["id"], quarter="2026Q3",
                                  period_start="2026-09-01T00:00:00Z",
                                  period_end="2026-10-01T00:00:00Z",
                                  reported_wages_cents=0), TAXFILER), 201)
    audit = validate_success(api.open_audit(
        create_audit_payload(policy["id"]), AUDITOR), 201)
    version = get_policy(policy["id"])["version"]
    file_audit(audit["id"], version, filer_user_id="tf-same")

    res = api.verify_audit(audit["id"], make_role_headers("tf-same", "Auditor"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    audit_now = validate_success(api.get_audit(audit["id"], AUDITOR), 200)
    assert audit_now["status"] == "FILED", "the rejected verify changes nothing"


def test_payroll_provider_cannot_decide_disputes(api):
    """PRD §2.1: "an authenticated caller whose role is not permitted for the
    endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4 endpoint table row: "| POST | `/wc/disputes/{id}/decide` | Approve or
    deny a dispute under review | Underwriter |".

    Design: Corner/rbac/payroll_provider_cannot_decide_disputes
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-RBK-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    dispute, version = dispute_under_review(policy["id"], employer["id"])

    res = api.decide_dispute(
        dispute["id"],
        {"decision": "APPROVED", "expected_policy_version": version},
        PROVIDER)
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_tax_filer_cannot_verify_audits(api):
    """PRD §2.1: "an authenticated caller whose role is not permitted for the
    endpoint is rejected with ERR_FORBIDDEN (HTTP 403)."
    PRD §4 endpoint table row: "| POST | `/wc/audits/{id}/verify` | Verify a filed
    reconciliation | Auditor |".

    Design: Corner/rbac/taxfiler_cannot_verify_audits
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-RBK-002",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    validate_success(api.create_tax_filing(
        create_tax_filing_payload(policy["id"], quarter="2026Q3",
                                  period_start="2026-09-01T00:00:00Z",
                                  period_end="2026-10-01T00:00:00Z",
                                  reported_wages_cents=0), TAXFILER), 201)
    audit = validate_success(api.open_audit(
        create_audit_payload(policy["id"]), AUDITOR), 201)
    version = get_policy(policy["id"])["version"]
    file_audit(audit["id"], version, filer_user_id="tf-filer")

    # A different TaxFiler user than the filer is still role-denied.
    res = api.verify_audit(audit["id"], make_role_headers("tf-other", "TaxFiler"))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)


def test_employer_admin_cannot_pay_another_employers_invoice(api):
    """PRD §2.1: "When X-User-Role is EmployerAdmin, X-User-ID is the id of the
    acting Employer; ownership checks on any resource that references an Employer
    — for instance, a policy's employer_id — compare that foreign-key field to
    X-User-ID."

    Design: Corner/rbac/employer_admin_acts_on_own_employer_only
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    owner, policy, _report, invoice = setup_policy_with_accepted_report(
        policy_number="WC-OWN-001")
    other = create_employer(legal_name="Other Owner Inc", fein="10-0000099",
                            contact_email="o@other.example", home_state="CA")

    res = api.pay_invoice(invoice["id"], {"amount_cents": invoice["total_cents"]},
                          make_employer_admin_headers(other["id"]))
    validate_error(res, "ERR_FORBIDDEN", expected_status=403)

    now = validate_success(api.get_invoice(invoice["id"], UW), 200)
    assert now["status"] == "ISSUED"
