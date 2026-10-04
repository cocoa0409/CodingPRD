"""Class assignment disputes and the assignment lifecycle.

Covers the PRD's classification dispute workflow (section 3.4), including the
dispute-driven reassignment cycle and dispute withdrawal compensation.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_class_code,
    file_dispute,
    make_employer_representative_headers,
    set_clock,
    setup_assigned_class_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bureau_admin_headers"]
ANALYST = TEST_USERS["bureau_analyst_headers"]


def test_class_assignment_cycles_assigned_disputed_reassigned(api):
    """PRD section 3.4: "Resolving with `resolution` of `REASSIGNED`
    additionally requires a `new_class_code_id` naming an `ACTIVE` class code;
    the original assignment moves to `REASSIGNED`, the dispute closes as
    `RESOLVED` with that resolution recorded, and a brand-new
    `ClassAssignment` is created directly in `ASSIGNED` status carrying the
    new classification."

    Design: Difficulty/non_linear_state_machine/class_assignment_cycles_assigned_disputed_reassigned
    """
    set_clock("2026-03-01T00:00:00Z")
    bureau, employer, class_code, assignment = setup_assigned_class_assignment()
    other_code = create_class_code(code="8810", description="Clerical Office Employees")

    dispute = file_dispute(assignment, employer, reason="WRONG_CLASS")
    validate_success(api.review_class_assignment_dispute(dispute["id"], ANALYST))
    resolved = validate_success(
        api.resolve_class_assignment_dispute(
            dispute["id"],
            {"resolution": "REASSIGNED", "new_class_code_id": other_code["id"]},
            ANALYST,
        ),
        expected_status=200,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "REASSIGNED"

    original = validate_success(api.get_class_assignment(assignment["id"], ADMIN))
    assert original["status"] == "REASSIGNED", (
        f"Original assignment must move to REASSIGNED, got {original['status']}"
    )

    assignments, meta = validate_paginated(
        api.list_employer_class_assignments(employer["id"], ADMIN)
    )
    assert meta["total_count"] == 2, (
        f"Reassignment must create a new assignment, got {meta['total_count']}"
    )
    new_rows = [a for a in assignments if a["id"] != assignment["id"]]
    assert len(new_rows) == 1
    assert new_rows[0]["class_code_id"] == other_code["id"]
    assert new_rows[0]["status"] == "ASSIGNED", (
        f"Replacement assignment must be created in ASSIGNED, got "
        f"{new_rows[0]['status']}"
    )


def test_dispute_resolve_confirmed_closes_cycle_back_to_confirmed(api):
    """PRD section 3.4: "Resolving with `resolution` of `CONFIRMED` closes the
    dispute as `RESOLVED` with the original classification upheld: the
    assignment moves to `CONFIRMED` and the dispute's `resolved_at` is
    stamped."

    Design: Difficulty/non_linear_state_machine/class_assignment_cycles_assigned_disputed_reassigned
    """
    set_clock("2026-03-01T00:00:00Z")
    bureau, employer, class_code, assignment = setup_assigned_class_assignment()
    dispute = file_dispute(assignment, employer, reason="PAYROLL_MISMATCH")
    validate_success(api.review_class_assignment_dispute(dispute["id"], ANALYST))
    resolved = validate_success(
        api.resolve_class_assignment_dispute(
            dispute["id"], {"resolution": "CONFIRMED"}, ANALYST
        ),
        expected_status=200,
    )
    assert resolved["status"] == "RESOLVED"
    assert resolved["resolution"] == "CONFIRMED"
    assert resolved.get("resolved_at"), "resolved_at must be stamped on resolution"

    after = validate_success(api.get_class_assignment(assignment["id"], ADMIN))
    assert after["status"] == "CONFIRMED", (
        f"Confirming resolution must move the assignment to CONFIRMED, got "
        f"{after['status']}"
    )
    # No new assignment is spawned on the CONFIRMED branch.
    assignments, meta = validate_paginated(
        api.list_employer_class_assignments(employer["id"], ADMIN)
    )
    assert meta["total_count"] == 1


def test_dispute_withdraw_reverts_assignment_to_assigned(api):
    """PRD section 3.4: "the employer may instead withdraw a dispute that is
    still `OPEN`, which returns the assignment to its prior status -
    `ASSIGNED` or `CONFIRMED` as the case was."

    Design: Corner/state_machines/dispute_withdraw_reverts_assignment_to_assigned
    """
    set_clock("2026-03-01T00:00:00Z")
    bureau, employer, class_code, assignment = setup_assigned_class_assignment()
    dispute = file_dispute(assignment, employer, reason="WRONG_CLASS")
    disputed = validate_success(api.get_class_assignment(assignment["id"], ADMIN))
    assert disputed["status"] == "DISPUTED"

    withdrawn = validate_success(
        api.withdraw_class_assignment_dispute(
            dispute["id"], make_employer_representative_headers(employer["id"])
        ),
        expected_status=200,
    )
    assert withdrawn["status"] == "WITHDRAWN"
    after = validate_success(api.get_class_assignment(assignment["id"], ADMIN))
    assert after["status"] == "ASSIGNED", (
        f"Withdrawing the dispute must return the assignment to ASSIGNED, got "
        f"{after['status']}"
    )
