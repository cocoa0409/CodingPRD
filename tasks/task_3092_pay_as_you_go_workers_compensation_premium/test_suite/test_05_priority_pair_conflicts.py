"""Priority pair conflicts: which rule fires when two violations coincide."""

from test_helpers import (
    TEST_USERS, class_code_entry, create_and_bind_policy, create_policy,
    create_employer, dispute_under_review, get_policy, make_role_headers,
    payroll_line, set_clock, setup_rating_table, submit_report, validate_error,
)

ADMIN = TEST_USERS["platform_admin_headers"]
UW = TEST_USERS["underwriter_headers"]
PROVIDER = TEST_USERS["payroll_provider_headers"]


def _pending_policy():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Pending Pistons Co",
                               fein="77-8888999",
                               contact_email="hr@pending.example",
                               home_state="CA")
    policy = create_policy(employer["id"], policy_number="WC-PEN-007",
                           class_codes=[class_code_entry("CA", "8810", 1000000)])
    return employer, policy


def test_payroll_submission_on_pending_policy_rejected_not_active(api):
    """PRD §3.3: "A policy whose coverage is not ACTIVE rejects the submission with
    ERR_POLICY_NOT_ACTIVE (HTTP 409)".

    Design: Difficulty/priority_pair_validation_conflict/payroll_overlap_state_vs_temporal_on_pending_policy
    """
    _employer, policy = _pending_policy()
    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-08T00:00:00Z",
        "idempotency_key": "pen-run-001",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=100000)],
    }, PROVIDER)
    validate_error(res, "ERR_POLICY_NOT_ACTIVE", expected_status=409)


def test_pending_policy_submission_is_a_hard_fault_not_a_rejected_report(api):
    """PRD §3.3: "Hard request faults behave differently: a missing or non-active
    policy, suspended billing, an idempotency conflict, or a malformed body each
    return their 4xx status directly."

    Design: Difficulty/priority_pair_validation_conflict/payroll_overlap_state_vs_temporal_on_pending_policy
    """
    _employer, policy = _pending_policy()
    res = api.submit_payroll_report({
        "policy_id": policy["id"],
        "period_start": "2026-09-01T00:00:00Z",
        "period_end": "2026-09-08T00:00:00Z",
        "idempotency_key": "pen-run-002",
        "lines": [payroll_line("CA", "8810", gross_wages_cents=100000)],
    }, PROVIDER)
    error = validate_error(res, "ERR_POLICY_NOT_ACTIVE", expected_status=409)
    assert res.status_code == 409, (
        "a non-active policy is a hard request fault — no REJECTED report is "
        "persisted as business data for it")


def _under_review_dispute():
    set_clock("2026-09-01T00:00:00Z")
    setup_rating_table("CA")
    employer = create_employer(legal_name="Conflict Castings Inc",
                               fein="88-9999000",
                               contact_email="legal@conflict.example",
                               home_state="CA")
    policy = create_and_bind_policy(
        employer["id"], policy_number="WC-CON-008",
        class_codes=[class_code_entry("CA", "8810", 1000000)])
    dispute, version = dispute_under_review(policy["id"], employer["id"])
    return employer, policy, dispute, version


def test_stale_version_beats_segregation_of_duties_on_decide(api):
    """PRD §2.7: "On the two guarded endpoints, the staleness check is evaluated
    after the target resource's state check and before the segregation-of-duties
    check, so a dispute decision on a stale snapshot surfaces ERR_STALE_VERSION
    rather than a duties violation."

    Design: Difficulty/priority_pair_validation_conflict/dispute_decide_sod_vs_stale_version_priority
    """
    employer, _policy, dispute, version = _under_review_dispute()
    # The decider is simultaneously the filer (SoD violation) AND carries a stale
    # version (OCC violation). The OCC rule is evaluated first.
    res = api.decide_dispute(
        dispute["id"],
        {"decision": "APPROVED", "expected_policy_version": version - 1},
        make_role_headers(employer["id"], "Underwriter"))
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_segregation_of_duties_fires_once_the_version_is_current(api):
    """PRD §2.11: "the dispute records the filer's X-User-ID as filed_by, and a
    decision request whose X-User-ID equals filed_by is rejected with
    ERR_SEGREGATION_OF_DUTIES (HTTP 403)."

    Design: Difficulty/priority_pair_validation_conflict/dispute_decide_sod_vs_stale_version_priority
    """
    employer, _policy, dispute, version = _under_review_dispute()
    res = api.decide_dispute(
        dispute["id"],
        {"decision": "APPROVED", "expected_policy_version": version},
        make_role_headers(employer["id"], "Underwriter"))
    validate_error(res, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)
