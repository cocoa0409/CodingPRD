"""Corner queue B — state_machines section instances."""

from test_helpers import (
    ApiErrorId,
    add_active_connection,
    assert_instants_equal,
    drive_consecutive_failures,
    setup_active_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_revoke_already_revoked_consent_returns_invalid_state(api):
    """PRD §3.5: "Revoking a consent requires that the consent currently be
    `ACTIVE` (anything else yields `ERR_INVALID_STATE`) and that the caller's
    `X-User-ID` equal the consent's `consumer_ref`."

    Design: Corner/state_machines/revoke_already_revoked_consent_returns_invalid_state
    """
    stack = setup_active_stack(
        api,
        institution_name="DoubleRevoke Bank",
        recipient_name="RevokeApp",
        consumer_ref="cons_t",
    )
    consumer = stack["consumer"]

    revoked = validate_success(api.revoke_consent(stack["consent"]["id"], consumer))
    first_revoked_at = revoked["revoked_at"]

    resp = api.revoke_consent(stack["consent"]["id"], consumer)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    reread = validate_success(api.get_consent(stack["consent"]["id"], consumer))
    assert reread["status"] == "REVOKED"
    assert_instants_equal(reread["revoked_at"], first_revoked_at, "revoked_at unchanged")


def test_refresh_disconnected_connection_returns_invalid_state(api):
    """PRD §3.7: "The connection must be in `ACTIVE` or `MIGRATING` — anything
    else is `ERR_INVALID_STATE`."

    Design: Corner/state_machines/refresh_disconnected_connection_returns_invalid_state
    """
    stack = setup_active_stack(
        api,
        institution_name="DiscBank",
        recipient_name="DiscApp",
        consumer_ref="cons_u",
    )
    consumer = stack["consumer"]
    conn_id = stack["connection"]["id"]

    validate_success(api.revoke_consent(stack["consent"]["id"], consumer))
    connection = validate_success(api.get_connection(conn_id, consumer))
    assert connection["status"] == "DISCONNECTED"

    resp = api.refresh_connection(conn_id, {"kind": "FULL"}, consumer)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    jobs, meta = validate_paginated(api.list_refresh_jobs(conn_id, stack["admin"]))
    assert meta["total_count"] == 1, (
        "a state-rejected refresh must not record a job beyond the initial complete_auth job"
    )


def test_reauth_from_active_returns_invalid_state(api):
    """PRD §3.7: "Re-authentication is the consumer's recovery path, available
    from `REAUTH_REQUIRED` and from `BROKEN`."
    PRD §2.9: "State legality — the target resource is in a state that permits
    the transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/reauth_from_active_returns_invalid_state
    """
    stack = setup_active_stack(
        api,
        institution_name="ActiveReauth Bank",
        recipient_name="ActiveReauthApp",
        consumer_ref="cons_v",
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    resp = api.reauth_connection(conn_id, {"valid": True}, consumer)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    connection = validate_success(api.get_connection(conn_id, consumer))
    assert connection["status"] == "ACTIVE"
    assert connection["consecutive_failures"] == 0


def test_institution_broken_cascades_reauth_prompts_to_all_active_connections(api):
    """PRD §3.1: "Once `BROKEN`, every connection of the institution sitting
    in `ACTIVE` or `MIGRATING` is moved to `REAUTH_REQUIRED` as an
    institution-level re-authentication prompt, an `INSTITUTION_BROKEN`
    webhook event is emitted to each affected connection's recipient, and
    refreshes against the institution are refused until recovery: attempts to
    refresh, to create a new connection, or to re-authenticate while the
    institution is `BROKEN` are rejected with `ERR_PARENT_NOT_OPERABLE`
    (HTTP 422)."

    Design: Corner/state_machines/institution_broken_cascades_reauth_prompts_to_all_active_connections
    """
    stack = setup_active_stack(
        api,
        institution_name="CascadeBreak Bank",
        recipient_name="BreakApp",
        consumer_ref="cons_w1",
        reauth_cooldown_seconds=0,
    )
    second = add_active_connection(api, stack, "cons_w2")
    conn1_id = stack["connection"]["id"]
    conn2_id = second["connection"]["id"]

    drive_consecutive_failures(api, conn1_id, "cons_w1", 5)

    institution = validate_success(api.get_institution(stack["institution"]["id"], stack["admin"]))
    assert institution["status"] == "BROKEN", (
        f"5 breakage events must break the institution, got {institution['status']}"
    )

    for conn_id, headers in ((conn1_id, stack["consumer"]), (conn2_id, second["consumer"])):
        connection = validate_success(api.get_connection(conn_id, headers))
        assert connection["status"] == "REAUTH_REQUIRED", (
            "every ACTIVE connection must be parked in REAUTH_REQUIRED by the outage"
        )

    events, meta = validate_paginated(
        api.list_recipient_webhook_events(
            stack["recipient"]["id"], stack["admin"], params={"event_type": "INSTITUTION_BROKEN"}
        )
    )
    assert meta["total_count"] == 2, (
        f"one INSTITUTION_BROKEN webhook per prompted connection expected, got {meta['total_count']}"
    )

    # Re-auth is futile while the institution itself is BROKEN.
    resp = api.reauth_connection(conn1_id, {"valid": True}, stack["consumer"])
    validate_error(resp, ApiErrorId.ERR_PARENT_NOT_OPERABLE)


def test_complete_auth_on_broken_consent_rejected_consent_not_active(api):
    """PRD §3.5: "Revocation stamps `revoked_at` with the clock, moves every
    connection of the consent in `PENDING_AUTH`, `ACTIVE`, `REAUTH_REQUIRED`,
    `BROKEN`, or `MIGRATING` to `DISCONNECTED`."
    PRD §2.9: "State legality — the target resource is in a state that permits
    the transition (`ERR_INVALID_STATE`)."

    Design: Corner/state_machines/complete_auth_on_broken_consent_rejected_consent_not_active
    """
    stack = setup_active_stack(
        api,
        institution_name="MidFlow Bank",
        recipient_name="MidFlowApp",
        consumer_ref="cons_x",
    )
    consumer = stack["consumer"]

    # A fresh PENDING_AUTH connection whose consent is revoked mid-flow.
    pending = validate_success(
        api.create_connection(
            stack["institution"]["id"],
            {
                "consumer_ref": "cons_x",
                "consent_id": stack["consent"]["id"],
                "method": "CREDENTIALS",
            },
            consumer,
        ),
        expected_status=201,
    )
    validate_success(api.revoke_consent(stack["consent"]["id"], consumer))

    resp = api.complete_auth(pending["id"], {}, consumer)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    connection = validate_success(api.get_connection(pending["id"], consumer))
    assert connection["status"] == "DISCONNECTED", (
        "the revocation cascade must have moved the PENDING_AUTH connection to DISCONNECTED"
    )
