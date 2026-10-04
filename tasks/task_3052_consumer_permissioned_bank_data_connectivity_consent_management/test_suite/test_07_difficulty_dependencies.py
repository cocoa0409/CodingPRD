"""Difficulty queue A — cross_entity_state_dependency instances."""

from test_helpers import (
    ApiErrorId,
    create_pending_connection,
    activate_connection,
    setup_active_stack,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_connection_create_on_revoked_consent_rejected(api):
    """PRD §3.6: "The referenced consent must be `ACTIVE` and not past
    `expires_at`, the institution must not be `BROKEN`, and the consent must
    belong to the caller — violations surface as `ERR_CONSENT_NOT_ACTIVE` or
    `ERR_PARENT_NOT_OPERABLE` as appropriate."

    Design: Difficulty/cross_entity_state_dependency/dependency_connection_create_requires_consent_active
    """
    stack = setup_active_stack(
        api,
        institution_name="ConsentGate Bank",
        recipient_name="GateApp",
        consumer_ref="cons_l",
    )
    consumer = stack["consumer"]

    validate_success(api.revoke_consent(stack["consent"]["id"], consumer))

    resp = api.create_connection(
        stack["institution"]["id"],
        {
            "consumer_ref": "cons_l",
            "consent_id": stack["consent"]["id"],
            "method": "CREDENTIALS",
        },
        consumer,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)


def test_connection_create_on_revoked_consent_persists_nothing(api):
    """PRD §3.5: "Revocation stamps `revoked_at` with the clock, moves every
    connection of the consent in `PENDING_AUTH`, `ACTIVE`, `REAUTH_REQUIRED`,
    `BROKEN`, or `MIGRATING` to `DISCONNECTED`."

    Design: Difficulty/cross_entity_state_dependency/dependency_connection_create_requires_consent_active
    """
    stack = setup_active_stack(
        api,
        institution_name="ConsentGate Bank",
        recipient_name="GateApp",
        consumer_ref="cons_l",
    )
    consumer = stack["consumer"]
    admin = stack["admin"]

    # The stack's own connection was DISCONNECTED by the revocation cascade.
    validate_success(api.revoke_consent(stack["consent"]["id"], consumer))
    connection = validate_success(api.get_connection(stack["connection"]["id"], consumer))
    assert connection["status"] == "DISCONNECTED"

    resp = api.create_connection(
        stack["institution"]["id"],
        {
            "consumer_ref": "cons_l",
            "consent_id": stack["consent"]["id"],
            "method": "CREDENTIALS",
        },
        consumer,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)

    connections, meta = validate_paginated(
        api.list_consent_connections(stack["consent"]["id"], admin)
    )
    assert meta["total_count"] == 1, (
        "the rejected creation must not persist a second connection on the revoked consent"
    )


def _setup_migration_stack(api):
    stack = setup_active_stack(
        api,
        institution_name="Migrate Bank",
        recipient_name="MigrateApp",
        consumer_ref="cons_m",
        target_method="BANK_API",
        method="CREDENTIALS",
    )
    admin = stack["admin"]
    validate_success(api.set_clock({"to_iso8601": "2026-09-15T00:00:00Z"}, admin))
    started = validate_success(api.start_migration(stack["institution"]["id"], admin))
    assert started["migration_state"] == "IN_PROGRESS"
    return stack


def test_migration_complete_blocked_by_unmigrated_connection(api):
    """PRD §3.8: "A `PlatformAdmin` completes the program only when
    `migration_state` is `IN_PROGRESS` and every non-`DISCONNECTED` connection
    of the institution already runs on the `target_method`; if any live
    connection still uses a non-target method, completion is rejected with
    `ERR_MIGRATION_INCOMPLETE` — the platform never force-disconnects
    stragglers to force the program closed."

    Design: Difficulty/cross_entity_state_dependency/dependency_migration_complete_requires_connections_on_target
    """
    stack = _setup_migration_stack(api)
    admin = stack["admin"]

    resp = api.complete_migration(stack["institution"]["id"], admin)
    validate_error(resp, ApiErrorId.ERR_MIGRATION_INCOMPLETE)

    institution = validate_success(api.get_institution(stack["institution"]["id"], admin))
    assert institution["migration_state"] == "IN_PROGRESS", (
        "a rejected completion must leave the migration IN_PROGRESS"
    )


def test_migration_complete_after_connection_moves_to_target(api):
    """PRD §3.8: "Migration moves the connection to `MIGRATING` and rewrites
    its `method` to the target method. The consumer then re-proves
    authentication under the new method: completing authentication on a
    `MIGRATING` connection (with the consent still `ACTIVE`) returns it to
    `ACTIVE` and emits a `CONNECTION_MIGRATED` webhook to the recipient...
    Successful completion sets `migration_state` to `COMPLETE`, flips
    `connectivity_mode` to `API_ONLY`."

    Design: Difficulty/cross_entity_state_dependency/dependency_migration_complete_requires_connections_on_target
    """
    stack = _setup_migration_stack(api)
    admin = stack["admin"]
    consumer = stack["consumer"]
    conn_id = stack["connection"]["id"]

    validate_error(
        api.complete_migration(stack["institution"]["id"], admin),
        ApiErrorId.ERR_MIGRATION_INCOMPLETE,
    )

    migrating = validate_success(api.migrate_connection(conn_id, consumer))
    assert migrating["status"] == "MIGRATING"
    assert migrating["method"] == "BANK_API"

    reactivated = validate_success(api.complete_auth(conn_id, {}, consumer))
    assert reactivated["status"] == "ACTIVE"

    completed = validate_success(api.complete_migration(stack["institution"]["id"], admin))
    assert completed["migration_state"] == "COMPLETE"
    assert completed["connectivity_mode"] == "API_ONLY"

    events, meta = validate_paginated(
        api.list_connection_webhook_events(
            conn_id, admin, params={"event_type": "CONNECTION_MIGRATED"}
        )
    )
    assert meta["total_count"] == 1, "migration re-proof must emit one CONNECTION_MIGRATED webhook"
