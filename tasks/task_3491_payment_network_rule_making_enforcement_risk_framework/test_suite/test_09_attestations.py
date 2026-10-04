"""Annual compliance attestation: lazy OVERDUE derivation, submission, and the
two acceptance gates — PRD §3.9.
"""

from test_helpers import (
    ApiErrorId,
    compute_attestation_due_date,
    create_active_participant,
    create_attestation,
    create_completed_audit,
    create_enforcement_action,
    make_auditor_headers,
    set_clock,
    submit_attestation,
    transition_attestation,
    validate_error,
    validate_success,
)


def test_attestation_acceptance_gated_on_enforcement_state(api, admin_headers):
    """PRD §3.9: "Acceptance moves the attestation from `SUBMITTED` to
    `ACCEPTED` (terminal) and carries two gates, evaluated in this order: no
    enforcement action of the participant may stand in `ISSUED` or `CONTESTED`
    status, otherwise `ERR_UNRESOLVED_ENFORCEMENT`; and the participant must
    present at least one completed audit whose `end_date` falls on or after
    January 1 of `period_year`, otherwise `ERR_AUDIT_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/attestation_acceptance_gated_on_enforcement_state
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH")
    create_completed_audit(
        participant, "2026-06-01", "2026-06-30", findings_count=2,
        creator_headers=make_auditor_headers("aud-1"),
        completer_headers=make_auditor_headers("aud-2"),
    )

    set_clock("2026-09-01T09:00:00Z")
    attestation = create_attestation(participant, 2026)
    submitted = submit_attestation(attestation)
    assert submitted["status"] == "SUBMITTED"

    create_enforcement_action(participant, "LATE_ATTESTATION")

    resp = api.transition_attestation(
        attestation["id"], {"to_state": "ACCEPTED"}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_UNRESOLVED_ENFORCEMENT)

    after = validate_success(api.get_attestation(attestation["id"], admin_headers))
    assert after["status"] == "SUBMITTED"


def test_attestation_overdue_flip_and_late_submission(api, admin_headers):
    """PRD §3.9: "The attestation's `due_date` is computed as March 1 of the
    year following `period_year`, and it is born in `PENDING` status with
    `attestation_text` still null. `OVERDUE` is not scheduled but derived
    lazily: any read or write of the attestation that finds it still `PENDING`
    while the logical date is after `due_date` flips it to `OVERDUE`, and that
    flip is persisted."
    PRD §3.9: "Each submission stamps `submitted_at` from the logical clock and
    recomputes `late_submission`, which is true exactly when the accepting
    submission's date is strictly after `due_date` — necessarily true for a
    submission out of `OVERDUE`, and recomputed fresh on a resubmission out of
    `REJECTED`."

    Design: Corner/state_machines/attestation_overdue_flip_and_late_submission
    """
    set_clock("2026-01-15T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH")
    attestation = create_attestation(participant, 2025)
    assert attestation["due_date"] == compute_attestation_due_date(2025)
    assert attestation["due_date"] == "2026-03-01"

    january = validate_success(api.get_attestation(attestation["id"], admin_headers))
    assert january["status"] == "PENDING"

    set_clock("2026-03-02T09:00:00Z")
    march = validate_success(api.get_attestation(attestation["id"], admin_headers))
    assert march["status"] == "OVERDUE"

    submitted = submit_attestation(attestation)
    assert submitted["status"] == "SUBMITTED"
    assert submitted["late_submission"] is True


def test_attestation_accept_happy_path(api, admin_headers):
    """PRD §3.9: "Acceptance moves the attestation from `SUBMITTED` to
    `ACCEPTED` (terminal) and carries two gates, evaluated in this order: no
    enforcement action of the participant may stand in `ISSUED` or `CONTESTED`
    status, otherwise `ERR_UNRESOLVED_ENFORCEMENT`; and the participant must
    present at least one completed audit whose `end_date` falls on or after
    January 1 of `period_year`, otherwise `ERR_AUDIT_REQUIRED`."
    PRD §3.9: "Each submission stamps `submitted_at` from the logical clock and
    recomputes `late_submission`, which is true exactly when the accepting
    submission's date is strictly after `due_date`"

    Design: Corner/state_machines/attestation_accept_happy_path
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH")
    create_completed_audit(participant, "2026-06-01", "2026-06-30", findings_count=0)

    set_clock("2026-09-01T09:00:00Z")
    attestation = create_attestation(participant, 2026)
    submit_attestation(attestation)

    accepted = transition_attestation(attestation["id"], "ACCEPTED")
    assert accepted["status"] == "ACCEPTED"
    assert accepted["late_submission"] is False  # 2026-09-01 is before due 2027-03-01


def test_attestation_accept_without_audit_rejected(api, admin_headers):
    """PRD §3.9: "Acceptance moves the attestation from `SUBMITTED` to
    `ACCEPTED` (terminal) and carries two gates, evaluated in this order: no
    enforcement action of the participant may stand in `ISSUED` or `CONTESTED`
    status, otherwise `ERR_UNRESOLVED_ENFORCEMENT`; and the participant must
    present at least one completed audit whose `end_date` falls on or after
    January 1 of `period_year`, otherwise `ERR_AUDIT_REQUIRED`."

    Design: Corner/validations/attestation_accept_without_audit_rejected
    """
    set_clock("2026-09-01T09:00:00Z")
    participant = create_active_participant(participant_type="BOTH")
    attestation = create_attestation(participant, 2026)
    submit_attestation(attestation)

    resp = api.transition_attestation(
        attestation["id"], {"to_state": "ACCEPTED"}, admin_headers
    )
    validate_error(resp, ApiErrorId.ERR_AUDIT_REQUIRED)

    after = validate_success(api.get_attestation(attestation["id"], admin_headers))
    assert after["status"] == "SUBMITTED"
