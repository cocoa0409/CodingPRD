"""Validation corners: term containment, retro window, exact payment, tax-filing
coverage, idempotency, monopolistic exclusion and the authentication gate."""

from test_helpers import (
    NO_USER_HEADERS, NON_EXISTENT_UUID, TEST_USERS, api_client,
    class_code_entry, create_and_bind_policy, create_audit_payload,
    create_employer, create_tax_filing_payload, file_dispute, get_policy,
    get_first_class_code, make_employer_admin_headers, make_role_headers,
    payroll_line, set_clock, setup_policy_with_accepted_report,
    setup_rating_table, submit_report, validate_error, validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]
TAXFILER = TEST_USERS["tax_filer_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _bound_ca_policy(policy_number="WC-VLD-001"):
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number=policy_number,
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    return employer, policy


def test_report_period_before_policy_effective_date_is_rejected(api):
    """PRD §3.3: "The period must lie within the policy term — period_start on or
    after the effective_date and period_end on or before the expiry_date — and
    must not overlap, under half-open interval semantics, any existing SUBMITTED
    or ACCEPTED report for the policy; either violation is
    ERR_PAYROLL_PERIOD_OVERLAP (HTTP 409)."

    Design: Corner/validations/report_period_outside_policy_term_rejected
    """
    _employer, policy = _bound_ca_policy("WC-OUT-001")
    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-08-25T00:00:00Z",
        "period_end": "2026-09-01T00:00:00Z",
        "idempotency_key": "out-run-1",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=100000)],
    }, PROVIDER)
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["failure_code"] == "ERR_PAYROLL_PERIOD_OVERLAP", (
        "the period precedes the policy effective_date")


def test_dispute_with_future_effective_from_is_rejected(api):
    """PRD §3.6: "The retroactive window must be valid: an effective_from before
    the policy's effective_date, or one that is not before the current logical
    clock — future retroactivity is meaningless — is rejected with
    ERR_RETRO_WINDOW_INVALID (HTTP 422)."

    Design: Corner/validations/retro_dispute_with_future_effective_from_rejected
    """
    employer, policy = _bound_ca_policy("WC-FUT-001")
    pcc = get_first_class_code(policy["id"])
    res = api.file_dispute({
        "policy_id": policy["id"],
        "policy_class_code_id": pcc["id"],
        "requested_class_code": "8812",
        "effective_from": "2026-12-01T00:00:00Z",
    }, make_employer_admin_headers(employer["id"]))
    validate_error(res, "ERR_RETRO_WINDOW_INVALID", expected_status=422)


def test_payment_one_cent_short_is_rejected_and_invoice_stays_issued(api):
    """PRD §3.4: "only for exact full payment: any amount_cents other than the
    invoice's total_cents, whether short or over, is rejected with
    ERR_PAYMENT_AMOUNT_MISMATCH (HTTP 422)."

    Design: Corner/validations/payment_amount_mismatch_rejected
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer, policy, _report, invoice = setup_policy_with_accepted_report(
        policy_number="WC-PAY-001")

    res = api.pay_invoice(invoice["id"],
                          {"amount_cents": invoice["total_cents"] - 1},
                          make_employer_admin_headers(employer["id"]))
    validate_error(res, "ERR_PAYMENT_AMOUNT_MISMATCH", expected_status=422)

    now = validate_success(api.get_invoice(invoice["id"], UW), 200)
    assert now["status"] == "ISSUED", "no partial payment semantics"


def test_audit_file_without_full_quarter_coverage_is_rejected(api):
    """PRD §3.7: "Filing requires complete tax coverage — every quarter
    intersecting the audit window must have at least one TaxFilingRecord, or the
    filing is rejected with ERR_TAX_FILING_MISSING (HTTP 422)."

    Design: Corner/validations/audit_file_without_quarter_coverage_rejected
    """
    _employer, policy = _bound_ca_policy("WC-QTR-001")
    validate_success(api.create_tax_filing(
        create_tax_filing_payload(policy["id"], quarter="2026Q3",
                                  period_start="2026-07-01T00:00:00Z",
                                  period_end="2026-10-01T00:00:00Z",
                                  reported_wages_cents=100000), TAXFILER), 201)
    audit = validate_success(api.open_audit(
        create_audit_payload(policy["id"],
                             period_start="2026-09-01T00:00:00Z",
                             period_end="2026-12-01T00:00:00Z"), AUDITOR), 201)
    version = get_policy(policy["id"])["version"]

    res = api.file_audit(audit["id"], {"expected_policy_version": version},
                         make_role_headers("tf-qtr", "TaxFiler"))
    validate_error(res, "ERR_TAX_FILING_MISSING", expected_status=422)


def test_idempotent_replay_returns_original_and_conflict_is_rejected(api):
    """PRD §2.12: "When a submission arrives with a key the policy has seen before
    and an identical payload, the server returns the original report as it stands
    — no duplicate report, no duplicate invoice. When the same key arrives
    carrying a different payload, the request is rejected with
    ERR_IDEMPOTENCY_CONFLICT (HTTP 409)."

    Design: Corner/validations/idempotency_replay_returns_original_conflicting_key_rejected
    """
    _employer, policy = _bound_ca_policy("WC-IDM-001")
    original = submit_report(policy["id"], "idm-1",
                             lines=[payroll_line("CA", "8810",
                                                 gross_wages_cents=10000000)])

    # PRD §4 lists payroll reports among create operations returning 201; only a
    # business-rejected report is called out as returning 200 OK, so the replay
    # of an ACCEPTED report keeps the original 201.
    replay = validate_success(api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-08T00:00:00Z",
        "idempotency_key": "idm-1",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=10000000)],
    }, PROVIDER), 201)
    assert replay["id"] == original["id"], "the replay returns the original report"

    invoices, _meta = validate_paginated(api.list_policy_invoices(policy["id"], UW))
    assert len(invoices) == 1, "no duplicate invoice is created by the replay"

    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-08T00:00:00Z",
        "period_end": "2026-09-15T00:00:00Z",
        "idempotency_key": "idm-1",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=200000,
                               headcount=2)],
    }, PROVIDER)
    validate_error(res, "ERR_IDEMPOTENCY_CONFLICT", expected_status=409)


def test_monopolistic_state_line_fails_with_the_exclusion_error(api):
    """PRD §2.10: "a payroll report containing a line for a monopolistic state
    fails with the same error. This failure is distinct from
    ERR_CLASS_CODE_NOT_ON_POLICY, which fires for non-monopolistic states lacking
    an active class assignment on the policy."

    Design: Corner/validations/monopolistic_state_line_rejected_distinct_from_unknown_class
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("OH")  # monopolistic
    employer, policy = _bound_ca_policy("WC-MON-001")

    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-08T00:00:00Z",
        "idempotency_key": "mon-run-1",
        "lines": [payroll_line("OH", "8810", gross_wages_cents=100000)],
    }, PROVIDER)
    rejected = validate_success(res, 200)
    assert rejected["status"] == "REJECTED"
    assert rejected["failure_code"] == "ERR_MONOPOLISTIC_STATE_EXCLUDED", (
        "the monopolistic exclusion surfaces even though the OH class is also "
        "absent from the policy")


def test_request_without_auth_headers_is_unauthenticated_before_anything(api):
    """PRD §2.1: "A request missing either header, or carrying a role the system
    does not recognize, is rejected with ERR_UNAUTHENTICATED (HTTP 401)."
    PRD §2.9: "Authentication comes first, then role authorization, then existence
    of every path-referenced resource".

    Design: Corner/validations/unauthenticated_request_rejected_before_everything
    """
    res = api.get_policy(NON_EXISTENT_UUID, NO_USER_HEADERS)
    validate_error(res, "ERR_UNAUTHENTICATED", expected_status=401)
