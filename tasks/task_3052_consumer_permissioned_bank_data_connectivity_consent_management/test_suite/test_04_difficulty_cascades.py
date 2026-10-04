"""Difficulty queue A — transitive_cascade instances."""

from test_helpers import (
    add_active_connection,
    assert_instants_equal,
    setup_active_stack,
    validate_paginated,
    validate_success,
)


def _setup_two_connection_stack(api):
    stack = setup_active_stack(
        api,
        institution_name="Union Depository",
        recipient_name="MoneyMap",
        consumer_ref="cons_f",
        data_scopes=["BALANCE", "TRANSACTIONS"],
        permitted_fields_by_scope={
            "BALANCE": ["current_cents"],
            "TRANSACTIONS": ["amount_cents", "posted_at"],
        },
        tier_scopes=["BALANCE", "TRANSACTIONS"],
        rate_class="MEDIUM",
        method="CREDENTIALS",
    )
    # Second connection for the same consumer under the same consent.
    second = validate_success(
        api.create_connection(
            stack["institution"]["id"],
            {
                "consumer_ref": "cons_f",
                "consent_id": stack["consent"]["id"],
                "method": "BANK_API",
            },
            stack["consumer"],
        ),
        expected_status=201,
    )
    second = validate_success(api.complete_auth(second["id"], {}, stack["consumer"]))
    return stack, second


def test_suspend_recipient_revokes_consents_and_disconnects_connections(api):
    """PRD §3.2: "Suspension revokes every `ACTIVE` consent of the recipient
    with `revoked_at` set to the clock, disconnects each revoked consent's
    connections, emits a `CONSENT_REVOKED` webhook per disconnected
    connection, ends the recipient's currently `ACTIVE` tier assignment by
    moving it to `ENDED`, and increments the recipient's `version`."

    Design: Difficulty/transitive_cascade/cascade_suspend_recipient_revokes_consents_disconnects_connections_emits_webhooks
    """
    stack, second = _setup_two_connection_stack(api)
    admin = stack["admin"]

    suspended = validate_success(api.suspend_recipient(stack["recipient"]["id"], admin))
    assert suspended["status"] == "SUSPENDED"

    consent = validate_success(api.get_consent(stack["consent"]["id"], stack["consumer"]))
    assert consent["status"] == "REVOKED"
    assert_instants_equal(consent["revoked_at"], "2026-09-01T00:00:00Z", "revoked_at")

    for conn_id in (stack["connection"]["id"], second["id"]):
        connection = validate_success(api.get_connection(conn_id, stack["consumer"]))
        assert connection["status"] == "DISCONNECTED", (
            f"connection {conn_id} must be DISCONNECTED, got {connection['status']}"
        )

    assignments, _ = validate_paginated(
        api.list_tier_assignments(stack["recipient"]["id"], admin)
    )
    statuses = {a["status"] for a in assignments}
    assert "ACTIVE" not in statuses, "the ACTIVE tier assignment must have ended"
    assert "ENDED" in statuses


def test_suspend_recipient_emits_one_revoked_webhook_per_connection(api):
    """PRD §3.5: "the number of webhooks emitted equals the number of the
    consent's connections that were not already `DISCONNECTED` at the moment
    of revocation — one event per affected connection, all addressed to the
    consent's single recipient."

    Design: Difficulty/transitive_cascade/cascade_suspend_recipient_revokes_consents_disconnects_connections_emits_webhooks
    """
    stack, second = _setup_two_connection_stack(api)
    admin = stack["admin"]

    validate_success(api.suspend_recipient(stack["recipient"]["id"], admin))

    events, meta = validate_paginated(
        api.list_recipient_webhook_events(
            stack["recipient"]["id"], admin, params={"event_type": "CONSENT_REVOKED"}
        )
    )
    assert meta["total_count"] == 2, (
        f"two non-DISCONNECTED connections must fan out two CONSENT_REVOKED webhooks, "
        f"got {meta['total_count']}"
    )
    targets = {e["connection_id"] for e in events}
    assert targets == {stack["connection"]["id"], second["id"]}
    for event in events:
        assert event["recipient_id"] == stack["recipient"]["id"]


def test_credentials_failure_transitions_connection_and_notifies(api):
    """PRD §3.7: "A failed job is stamped `executed_at`, increments
    `attempt_count`, takes `status` `FAILED` with the caller-supplied
    `failure_reason`, increments the connection's `consecutive_failures` by
    one, and appends a `BreakageEvent` to the institution of the corresponding
    `kind`... A `CREDENTIALS_INVALID` failure moves an `ACTIVE` connection to
    `REAUTH_REQUIRED`, sets `reauth_not_before` to the clock plus the
    connection's `reauth_cooldown_seconds`, and emits a `REAUTH_REQUIRED`
    webhook to the recipient."

    Design: Difficulty/transitive_cascade/cascade_credentials_failure_reauth_prompt_webhook
    """
    stack = setup_active_stack(
        api,
        institution_name="Beacon Bank",
        recipient_name="AlertFeed",
        consumer_ref="cons_g",
        reauth_cooldown_seconds=300,
    )
    conn_id = stack["connection"]["id"]

    job = validate_success(
        api.refresh_connection(
            conn_id, {"kind": "FULL", "failure_reason": "CREDENTIALS_INVALID"}, stack["consumer"]
        )
    )
    assert job["status"] == "FAILED"
    assert job["failure_reason"] == "CREDENTIALS_INVALID"
    assert job["attempt_count"] == 1

    connection = validate_success(api.get_connection(conn_id, stack["consumer"]))
    assert connection["status"] == "REAUTH_REQUIRED"
    assert_instants_equal(
        connection["reauth_not_before"], "2026-09-01T00:05:00Z", "reauth_not_before"
    )

    events, meta = validate_paginated(
        api.list_connection_webhook_events(
            conn_id, stack["admin"], params={"event_type": "REAUTH_REQUIRED"}
        )
    )
    assert meta["total_count"] == 1


def test_credentials_failure_appends_breakage_event(api):
    """PRD §3.1: "Every refresh failure against any connection of the
    institution appends a `BreakageEvent` recording the `institution_id`, the
    `connection_id` whose refresh produced it, the failure `kind`
    (`TRANSIENT`, `INSTITUTION_DOWN`, `CREDENTIALS_INVALID`, or
    `RATE_LIMITED`), and the `occurred_at` clock time."

    Design: Difficulty/transitive_cascade/cascade_credentials_failure_reauth_prompt_webhook
    """
    stack = setup_active_stack(
        api,
        institution_name="Beacon Bank",
        recipient_name="AlertFeed",
        consumer_ref="cons_g",
        reauth_cooldown_seconds=300,
    )
    conn_id = stack["connection"]["id"]
    inst_id = stack["institution"]["id"]

    validate_success(
        api.refresh_connection(
            conn_id, {"kind": "FULL", "failure_reason": "CREDENTIALS_INVALID"}, stack["consumer"]
        )
    )

    events, meta = validate_paginated(
        api.list_institution_breakage_events(inst_id, stack["admin"])
    )
    assert meta["total_count"] == 1, (
        f"exactly one breakage event must exist, got {meta['total_count']}"
    )
    assert events[0]["kind"] == "CREDENTIALS_INVALID"
    assert events[0]["connection_id"] == conn_id
