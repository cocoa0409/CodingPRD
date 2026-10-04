"""Unit statistical reporting: validation, corrections, and report locking.

Covers the PRD's unit statistical reporting workflow (section 3.3) and the
report/sheet promulgation interplay (section 3.5).
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_report_for_policy,
    create_sheet_for_employer,
    create_unit_stat_report_payload,
    get_employer,
    get_success_data,
    make_carrier_data_reporter_headers,
    make_employer_representative_headers,
    set_clock,
    setup_employer_with_validated_report,
    setup_promulgated_sheet,
    setup_rated_policy,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
ANALYST = TEST_USERS["bureau_analyst_headers"]

_BASE_CLAIMS = [
    {
        "claim_number": "C1",
        "claim_type": "INDEMNITY",
        "incurred_cents": 1600000,
        "paid_cents": 1600000,
        "claim_status": "CLOSED",
        "state_code": "TX",
    },
    {
        "claim_number": "C2",
        "claim_type": "INDEMNITY",
        "incurred_cents": 2400000,
        "paid_cents": 2400000,
        "claim_status": "CLOSED",
        "state_code": "TX",
    },
]


def test_validate_unit_stat_report_moves_submitted_to_validated(api):
    """PRD section 3.3: "A report that passes all four checks moves to
    `VALIDATED`, and the policy's `unit_stat_report_id` is set to point at it."

    Design: Corner/state_machines/validate_unit_stat_report_moves_submitted_to_validated
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy = setup_rated_policy(
        payroll_dollars=100000
    )
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    report = validate_success(
        api.create_unit_stat_report(
            create_unit_stat_report_payload(policy_id=policy["id"]), reporter
        ),
        expected_status=201,
    )
    assert report["status"] == "SUBMITTED"

    validated = validate_success(
        api.validate_unit_stat_report(report["id"], ANALYST), expected_status=200
    )
    assert validated["status"] == "VALIDATED", (
        f"Validate must move the report to VALIDATED, got {validated['status']}"
    )
    policy_after = validate_success(api.get_policy(policy["id"], ADMIN))
    assert policy_after["unit_stat_report_id"] == report["id"], (
        "Validation must back-fill the policy's unit_stat_report_id"
    )


def test_second_validate_on_validated_report_returns_invalid_state(api):
    """PRD section 3.3: "A report that passes all four checks moves to
    `VALIDATED`, and the policy's `unit_stat_report_id` is set to point at
    it." PRD section 2.7: "Next comes resource existence (`ERR_NOT_FOUND`),
    followed by state-machine legality (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/second_validate_on_validated_report_returns_invalid_state
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report = (
        setup_employer_with_validated_report(payroll_dollars=100000)
    )
    assert report["status"] == "VALIDATED"

    resp = api.validate_unit_stat_report(report["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert after["status"] == "VALIDATED", (
        f"Rejected validate must not mutate the report, got {after['status']}"
    )


def test_locked_report_is_terminal_for_direct_transitions(api):
    """PRD section 3.3: "Reports locked into a promulgated sheet are otherwise
    immutable: a report moves from `VALIDATED` to `LOCKED` automatically when
    the policy's experience modification sheet is promulgated, and likewise
    when the policy is cancelled or expires, after which only the correction
    path can supersede it."; PRD section 5: ERR_INVALID_STATE maps to HTTP 409.

    Design: Corner/state_machines/locked_report_is_terminal_for_direct_transitions
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy, report, sheet = (
        setup_promulgated_sheet(payroll_dollars=2000000, claim_lines=_BASE_CLAIMS)
    )
    locked = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert locked["status"] == "LOCKED"

    resp = api.validate_unit_stat_report(report["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)
    after = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert after["status"] == "LOCKED"


def test_new_class_assignment_starts_pending_inspection(api):
    """PRD section 3.4: "The assignment enters in `PENDING_INSPECTION`.";
    PRD section 2.4: "`version`, an integer that starts at 1 and increments
    by one on every mutation of that resource."

    Design: Corner/state_machines/new_class_assignment_starts_pending_inspection
    """
    from test_helpers import (
        create_bureau,
        create_class_code,
        create_employer,
        create_class_assignment_payload,
    )

    set_clock("2026-03-01T00:00:00Z")
    create_bureau()
    employer = create_employer()
    class_code = create_class_code()
    assignment = validate_success(
        api.create_class_assignment(
            create_class_assignment_payload(
                employer_id=employer["id"], class_code_id=class_code["id"]
            ),
            ANALYST,
        ),
        expected_status=201,
    )
    assert assignment["status"] == "PENDING_INSPECTION", (
        f"New assignment must be PENDING_INSPECTION, got {assignment['status']}"
    )
    assert assignment["version"] == 1


def test_confirm_assignment_with_open_inspection_returns_inspection_required(api):
    """PRD section 3.4: "Confirmation - moving the assignment from `ASSIGNED`
    to `CONFIRMED` - requires every inspection for the assignment to be
    `COMPLETED` or `WAIVED`; confirming with an outstanding scheduled
    inspection fails with `ERR_INSPECTION_REQUIRED`."; PRD section 5:
    ERR_INSPECTION_REQUIRED maps to HTTP 409.

    Design: Corner/state_machines/confirm_assignment_with_open_inspection_returns_inspection_required
    """
    from test_helpers import setup_assigned_class_assignment

    set_clock("2026-03-01T00:00:00Z")
    bureau, employer, class_code, assignment = setup_assigned_class_assignment()
    assert assignment["status"] == "ASSIGNED"
    assert assignment.get("inspection_id"), (
        "Setup failed: first-ever assignment must auto-create an inspection"
    )

    resp = api.confirm_class_assignment(assignment["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_INSPECTION_REQUIRED, expected_status=409)
    after = validate_success(api.get_class_assignment(assignment["id"], ADMIN))
    assert after["status"] == "ASSIGNED"


def test_claim_state_mismatch_returns_state_mismatch(api):
    """PRD section 3.3: "every claim line's `state_code` must match the
    policy's state, failing with `ERR_STATE_MISMATCH` on the first
    divergence"; PRD section 5: ERR_STATE_MISMATCH maps to HTTP 409.

    Design: Corner/errors/claim_state_mismatch_returns_state_mismatch
    """
    set_clock("2026-06-01T00:00:00Z")
    bureau, carrier, employer, class_code, table, policy = setup_rated_policy(
        payroll_dollars=100000
    )
    reporter = make_carrier_data_reporter_headers(carrier["id"])
    report = validate_success(
        api.create_unit_stat_report(
            create_unit_stat_report_payload(
                policy_id=policy["id"],
                claim_lines=[
                    {
                        "claim_number": "M1",
                        "claim_type": "MEDICAL",
                        "incurred_cents": 10000,
                        "paid_cents": 10000,
                        "claim_status": "CLOSED",
                        "state_code": "CA",
                    }
                ],
            ),
            reporter,
        ),
        expected_status=201,
    )
    resp = api.validate_unit_stat_report(report["id"], ANALYST)
    validate_error(resp, ApiErrorId.ERR_STATE_MISMATCH, expected_status=409)
    after = validate_success(api.get_unit_stat_report(report["id"], ADMIN))
    assert after["status"] == "SUBMITTED", (
        f"Rejected validation must leave the report SUBMITTED, got {after['status']}"
    )
