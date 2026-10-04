"""Difficulty queue A — non_linear_state_machine instances."""

from test_helpers import (
    ApiErrorId,
    assert_instants_equal,
    get_success_data,
    make_admin_headers,
    make_consumer_headers,
    make_reviewer_headers,
    setup_active_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_credentials_invalid_failure_enters_reauth_required_with_cooldown(api):
    """PRD §3.7: "A `CREDENTIALS_INVALID` failure moves an `ACTIVE` connection
    to `REAUTH_REQUIRED`, sets `reauth_not_before` to the clock plus the
    connection's `reauth_cooldown_seconds`, and emits a `REAUTH_REQUIRED`
    webhook to the recipient."

    Design: Difficulty/non_linear_state_machine/non_linear_connection_reauth_cycle
    """
    stack = setup_active_stack(
        api,
        institution_name="Cascade Bank",
        recipient_name="Ledgerly",
        consumer_ref="cons_e",
        reauth_cooldown_seconds=600,
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    job = validate_success(
        api.refresh_connection(
            conn_id, {"kind": "FULL", "failure_reason": "CREDENTIALS_INVALID"}, consumer
        )
    )
    assert job["status"] == "FAILED"
    assert job["failure_reason"] == "CREDENTIALS_INVALID"

    connection = validate_success(api.get_connection(conn_id, consumer))
    assert connection["status"] == "REAUTH_REQUIRED"
    assert_instants_equal(
        connection["reauth_not_before"], "2026-09-01T00:10:00Z", "reauth_not_before"
    )

    events, _ = validate_paginated(
        api.list_connection_webhook_events(conn_id, stack["admin"], params={"event_type": "REAUTH_REQUIRED"})
    )
    assert len(events) == 1, "exactly one REAUTH_REQUIRED webhook must be emitted"


def test_reauth_cooldown_rejects_then_valid_reauth_restores_active(api):
    """PRD §3.7: "if `reauth_not_before` is set and the clock has not yet
    reached it, the attempt is rejected with `ERR_REAUTH_COOLDOWN`; a clock
    exactly equal to `reauth_not_before` passes... A valid re-authentication
    moves the connection to `ACTIVE`, zeroes `consecutive_failures`, clears
    `reauth_not_before` to null."

    Design: Difficulty/non_linear_state_machine/non_linear_connection_reauth_cycle
    """
    stack = setup_active_stack(
        api,
        institution_name="Cascade Bank",
        recipient_name="Ledgerly",
        consumer_ref="cons_e",
        reauth_cooldown_seconds=600,
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]
    admin = stack["admin"]

    validate_success(
        api.refresh_connection(
            conn_id, {"kind": "FULL", "failure_reason": "CREDENTIALS_INVALID"}, consumer
        )
    )

    early = api.reauth_connection(conn_id, {"valid": True}, consumer)
    validate_error(early, ApiErrorId.ERR_REAUTH_COOLDOWN)

    validate_success(api.set_clock({"to_iso8601": "2026-09-01T00:10:00Z"}, admin))

    reauthed = validate_success(api.reauth_connection(conn_id, {"valid": True}, consumer))
    assert reauthed["status"] == "ACTIVE", (
        f"valid reauth at the cooldown instant must restore ACTIVE, got {reauthed['status']}"
    )
    assert reauthed["consecutive_failures"] == 0
    assert reauthed["reauth_not_before"] is None


def test_recipient_reject_then_appeal_approve_cycle(api):
    """PRD §3.2: "a rejection moves it to `REJECTED`... A `REJECTED` recipient
    can be approved on appeal, but only by a reviewer different from the one
    who originally rejected it."

    Design: Difficulty/non_linear_state_machine/non_linear_recipient_review_fork_and_appeal_cycle
    """
    admin = make_admin_headers("admin_1")
    recipient = get_success_data(
        api.create_recipient(
            {"name": "ForkPath", "declared_use_case": "analytics", "minimization_policy": "STANDARD"},
            admin,
        )
    )
    assert recipient["status"] == "PENDING_REVIEW"

    rejected = validate_success(
        api.review_recipient(recipient["id"], {"decision": "REJECT"}, make_reviewer_headers("reviewer_1"))
    )
    assert rejected["status"] == "REJECTED"

    appealed = validate_success(
        api.review_recipient(recipient["id"], {"decision": "APPROVE"}, make_reviewer_headers("reviewer_2"))
    )
    assert appealed["status"] == "APPROVED", (
        "appeal by a different reviewer must move REJECTED back to APPROVED"
    )


def test_recipient_suspend_reinstate_cycle_repeats(api):
    """PRD §3.2: "Suspension is the `PlatformAdmin`'s lever: an `APPROVED`
    recipient may be suspended, moving it to `SUSPENDED`... A `SUSPENDED`
    recipient can be reinstated to `APPROVED` by a reviewer whose identifier
    differs from the operator who performed the suspension, writing a
    `recipient.reinstate` audit entry."

    Design: Difficulty/non_linear_state_machine/non_linear_recipient_review_fork_and_appeal_cycle
    """
    admin_creator = make_admin_headers("admin_1")
    admin_suspender = make_admin_headers("admin_2")
    reviewer = make_reviewer_headers("reviewer_1")

    recipient = get_success_data(
        api.create_recipient(
            {"name": "ForkPath", "declared_use_case": "analytics", "minimization_policy": "STANDARD"},
            admin_creator,
        )
    )
    validate_success(
        api.review_recipient(recipient["id"], {"decision": "APPROVE"}, reviewer)
    )

    suspended = validate_success(api.suspend_recipient(recipient["id"], admin_suspender))
    assert suspended["status"] == "SUSPENDED"

    reinstated = validate_success(
        api.review_recipient(recipient["id"], {"decision": "APPROVE"}, reviewer)
    )
    assert reinstated["status"] == "APPROVED", (
        "reinstatement by a reviewer other than the suspender must restore APPROVED"
    )

    # The cycle is unbounded: suspend again, reinstate again.
    suspended2 = validate_success(api.suspend_recipient(recipient["id"], admin_suspender))
    assert suspended2["status"] == "SUSPENDED"
    reinstated2 = validate_success(
        api.review_recipient(recipient["id"], {"decision": "APPROVE"}, reviewer)
    )
    assert reinstated2["status"] == "APPROVED"
