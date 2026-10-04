"""State machine corners: bind, cancel cascade, terminal lockdown, dispute side
effects, the auto-cancel clock and expiry-opened audits."""

from test_helpers import (
    TEST_USERS, api_client, class_code_entry, create_and_bind_policy,
    create_audit_payload, create_employer, create_policy, dispute_under_review,
    file_dispute, get_first_class_code, get_integration, get_policy,
    make_employer_admin_headers, payroll_line, set_clock, setup_rating_table,
    submit_report, validate_error, validate_paginated, validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def test_bind_activates_coverage_and_creates_connected_integration(api):
    """PRD §3.2: "Binding transitions coverage from PENDING to ACTIVE and is permitted
    only when at least one class assignment with assignment_status of ACTIVE
    exists". PRD §3.2: "Binding also creates the policy's PayrollIntegration — a
    one-to-one record identified by the payroll provider name — with
    connection_status initially CONNECTED."

    Design: Corner/state_machines/bind_transitions_policy_to_active_and_creates_integration
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_policy(employer["id"], policy_number="WC-BND-001",
                           class_codes=[class_code_entry("CA", "8810", 1000000)])
    assert policy["coverage_status"] == "PENDING"

    bound = validate_success(api.bind_policy(policy["id"], UW), 200)
    assert bound["coverage_status"] == "ACTIVE"

    rows, _meta = validate_paginated(api.get_policy_integration(policy["id"], UW))
    assert len(rows) == 1
    assert rows[0]["connection_status"] == "CONNECTED"


def test_double_bind_is_rejected_as_invalid_state(api):
    """PRD §2.9: "an action attempted on a resource that is not in a state from
    which the requested transition is declared is rejected with ERR_INVALID_STATE
    (HTTP 409)."
    PRD §3.2: "Binding transitions coverage from PENDING to ACTIVE".

    Design: Corner/state_machines/double_bind_returns_invalid_state
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-DBL-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])

    res = api.bind_policy(policy["id"], UW)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)
    assert get_policy(policy["id"])["coverage_status"] == "ACTIVE", (
        "the failed bind changes nothing")


def test_cancel_denies_open_disputes_and_waives_open_audits(api):
    """PRD §3.8: "Every open dispute — whether FILED or UNDER_REVIEW — moves to
    DENIED with resolution_reason set to policy_cancelled. Every open audit — in
    OPEN or FILED — moves to WAIVED."

    Design: Corner/state_machines/cancel_voids_draft_denies_disputes_waives_audits
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-CXL-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    pcc = get_first_class_code(policy["id"])
    dispute = file_dispute(policy["id"], pcc["id"], employer["id"])
    audit = validate_success(api.open_audit(
        create_audit_payload(policy["id"]), AUDITOR), 201)

    cancelled = validate_success(api.cancel_policy(policy["id"], UW), 200)
    assert cancelled["coverage_status"] == "CANCELLED"

    dispute_now = validate_success(api.get_dispute(dispute["id"], UW), 200)
    assert dispute_now["status"] == "DENIED"
    assert dispute_now["resolution_reason"] == "policy_cancelled"

    audit_now = validate_success(api.get_audit(audit["id"], AUDITOR), 200)
    assert audit_now["status"] == "WAIVED"


def test_cancelled_policy_locks_cancel_and_payroll_submission(api):
    """PRD §2.9: "an action attempted on a resource that is not in a state from
    which the requested transition is declared is rejected with ERR_INVALID_STATE
    (HTTP 409)."
    PRD §3.3: "A policy whose coverage is not ACTIVE rejects the submission with
    ERR_POLICY_NOT_ACTIVE (HTTP 409)".

    Design: Corner/state_machines/cancelled_policy_locks_all_transitions
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-TRM-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    validate_success(api.cancel_policy(policy["id"], UW), 200)

    res = api.cancel_policy(policy["id"], UW)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-08T00:00:00Z",
        "idempotency_key": "trm-run-1",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=10000000)],
    }, PROVIDER)
    validate_error(res, "ERR_POLICY_NOT_ACTIVE", expected_status=409)


def test_open_review_marks_assignment_disputed_but_reporting_still_works(api):
    """PRD §3.6: "An Underwriter opens review, moving the dispute from FILED to
    UNDER_REVIEW; the disputed assignment's assignment_status becomes DISPUTED,
    though payroll may still be reported under it per §3.3."
    PRD §3.3: "Class-code resolution requires that every line's class_code map to
    a PolicyClassCode for that state whose assignment_status is ACTIVE or
    DISPUTED — payroll may still be reported under a disputed class".

    Design: Corner/state_machines/open_review_marks_class_assignment_disputed_but_reportable
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-DSP-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    pcc = get_first_class_code(policy["id"])
    dispute = file_dispute(policy["id"], pcc["id"], employer["id"])

    validate_success(api.open_dispute_review(dispute["id"], UW), 200)

    rows, _meta = validate_paginated(api.list_policy_class_codes(policy["id"], UW))
    assert rows[0]["assignment_status"] == "DISPUTED"

    report = submit_report(policy["id"], "dsp-run-1",
                           lines=[payroll_line("CA", "8810",
                                               gross_wages_cents=10000000)])
    assert report["status"] == "ACCEPTED", (
        "DISPUTED does not block payroll reporting, unlike REASSIGNED")


def _broken_integration_policy():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(employer["id"], policy_number="WC-AUT-001",
                                    class_codes=[class_code_entry("CA", "8810", 1000000)])
    integration = get_integration(policy["id"])
    validate_success(api_client.heartbeat_integration(
        integration["id"], {"outcome": "BROKEN"}, PROVIDER), 200)
    return policy


def test_non_reporting_at_21_broken_days_then_auto_cancel_at_56(api):
    """PRD §3.8: "the system cancels automatically once reporting_status has been
    NON_REPORTING for at least thirty-five consecutive days — the day count whole
    UTC days, the boundary inclusive, so exactly thirty-five days qualifies."
    PRD §3.5: "At three or more missed cycles — or when the integration has been
    BROKEN for at least twenty-one consecutive days — the policy becomes
    NON_REPORTING, starting the thirty-five-day auto-cancellation clock".

    Design: Corner/state_machines/auto_cancel_after_35_days_non_reporting
    """
    policy = _broken_integration_policy()

    set_clock("2026-09-22T00:00:00Z")  # exactly 21 broken days
    now = get_policy(policy["id"])
    assert now["reporting_status"] == "NON_REPORTING"
    assert now["coverage_status"] == "ACTIVE", (
        "the cancel clock has run zero of its thirty-five days")

    set_clock("2026-10-27T00:00:00Z")  # 21 + 35 broken days
    final = get_policy(policy["id"])
    assert final["coverage_status"] == "CANCELLED", (
        "the system sweep cancels with no API call on the policy")


def test_expiry_at_expiry_date_opens_full_term_audit(api):
    """PRD §3.8: "Expiry is automatic: when the logical clock reaches the
    expiry_date, coverage moves from ACTIVE to EXPIRED and the system opens an
    AuditReconciliation covering the full policy term in OPEN status".

    Design: Corner/state_machines/expiry_opens_full_term_audit
    """
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer()
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-EXP-001",
        effective_date="2026-09-01T00:00:00Z",
        expiry_date="2026-10-01T00:00:00Z",
        class_codes=[class_code_entry("CA", "8810", 500000)])

    set_clock("2026-10-01T00:00:00Z")
    expired = get_policy(policy["id"])
    assert expired["coverage_status"] == "EXPIRED", (
        "reaching the expiry_date expires the policy")

    audits, _meta = validate_paginated(api.list_policy_audits(policy["id"], AUDITOR))
    assert len(audits) == 1
    assert audits[0]["status"] == "OPEN"
    # PRD §2.4: timestamps are ISO 8601 UTC with three fractional digits.
    assert audits[0]["period_start"] == "2026-09-01T00:00:00.000Z"
    assert audits[0]["period_end"] == "2026-10-01T00:00:00.000Z"
