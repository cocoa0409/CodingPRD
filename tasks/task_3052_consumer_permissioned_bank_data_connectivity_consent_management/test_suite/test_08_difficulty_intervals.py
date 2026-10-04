"""Difficulty queue A — resource_temporal_overlap instances."""

from test_helpers import (
    ApiErrorId,
    setup_active_stack,
    validate_error,
    validate_success,
)


def test_connection_create_one_second_before_consent_expiry_succeeds(api):
    """PRD §3.4: "the `expires_at` instant after which the consent lapses (the
    expiry boundary is exclusive: once the clock reaches `expires_at`, the
    consent is expired)."

    Design: Difficulty/resource_temporal_overlap/overlap_consent_duration_half_open_expiry
    """
    stack = setup_active_stack(
        api,
        institution_name="HalfOpen Bank",
        recipient_name="HalfOpenApp",
        consumer_ref="cons_n",
        expires_at="2026-09-02T00:00:00Z",
    )
    admin = stack["admin"]
    consumer = stack["consumer"]

    validate_success(api.set_clock({"to_iso8601": "2026-09-01T23:59:59Z"}, admin))

    second = validate_success(
        api.create_connection(
            stack["institution"]["id"],
            {
                "consumer_ref": "cons_n",
                "consent_id": stack["consent"]["id"],
                "method": "CREDENTIALS",
            },
            consumer,
        ),
        expected_status=201,
    )
    assert second["status"] == "PENDING_AUTH", (
        "one second inside the half-open consent interval the consent is still ACTIVE"
    )


def test_consent_expires_at_boundary_and_disconnects_connections(api):
    """PRD §3.4: "the expiry boundary is exclusive: once the clock reaches
    `expires_at`, the consent is expired."
    PRD §3.5: "When the clock reaches or passes a consent's `expires_at` —
    discovered lazily on any access to the consent, or eagerly when the clock
    is advanced — the consent moves to `EXPIRED`. The cascade mirrors
    revocation: connections are disconnected."

    Design: Difficulty/resource_temporal_overlap/overlap_consent_duration_half_open_expiry
    """
    stack = setup_active_stack(
        api,
        institution_name="HalfOpen Bank",
        recipient_name="HalfOpenApp",
        consumer_ref="cons_n",
        expires_at="2026-09-02T00:00:00Z",
    )
    admin = stack["admin"]
    consumer = stack["consumer"]

    validate_success(api.set_clock({"to_iso8601": "2026-09-01T23:59:59Z"}, admin))
    second = validate_success(
        api.create_connection(
            stack["institution"]["id"],
            {
                "consumer_ref": "cons_n",
                "consent_id": stack["consent"]["id"],
                "method": "CREDENTIALS",
            },
            consumer,
        ),
        expected_status=201,
    )

    validate_success(api.set_clock({"to_iso8601": "2026-09-02T00:00:00Z"}, admin))

    resp = api.create_connection(
        stack["institution"]["id"],
        {
            "consumer_ref": "cons_n",
            "consent_id": stack["consent"]["id"],
            "method": "CREDENTIALS",
        },
        consumer,
    )
    validate_error(resp, ApiErrorId.ERR_CONSENT_NOT_ACTIVE)

    consent = validate_success(api.get_consent(stack["consent"]["id"], consumer))
    assert consent["status"] == "EXPIRED", (
        f"at the exclusive expiry boundary the consent must be EXPIRED, got {consent['status']}"
    )
    for conn_id in (stack["connection"]["id"], second["id"]):
        connection = validate_success(api.get_connection(conn_id, consumer))
        assert connection["status"] == "DISCONNECTED", (
            "the expiry cascade must disconnect every non-terminal connection"
        )


def test_migrate_at_window_start_succeeds_closed_lower_bound(api):
    """PRD §3.8: "Migrating a connection requires it to be `ACTIVE`, requires
    its current `method` to differ from the institution's `target_method`,
    requires the clock to be inside the inclusive migration window, and
    requires `migration_state` to be `IN_PROGRESS`... Migration moves the
    connection to `MIGRATING` and rewrites its `method` to the target method."

    Design: Difficulty/resource_temporal_overlap/overlap_migration_window_closed_interval
    """
    stack = setup_active_stack(
        api,
        institution_name="Window Bank",
        recipient_name="WindowApp",
        consumer_ref="cons_o",
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-20T00:00:00Z",
        target_method="BANK_API",
        method="CREDENTIALS",
    )
    admin = stack["admin"]
    consumer = stack["consumer"]
    conn_id = stack["connection"]["id"]

    validate_success(api.set_clock({"to_iso8601": "2026-09-10T00:00:00Z"}, admin))
    validate_success(api.start_migration(stack["institution"]["id"], admin))

    migrating = validate_success(api.migrate_connection(conn_id, consumer))
    assert migrating["status"] == "MIGRATING", (
        "migrate at the exact window start must succeed (closed lower bound)"
    )
    assert migrating["method"] == "BANK_API"


def test_migrate_after_window_end_rejected_window_closed(api):
    """PRD §3.8: "requires the clock to be inside the inclusive migration
    window... failures of the temporal or state conditions surface as
    `ERR_MIGRATION_WINDOW_CLOSED` or `ERR_INVALID_STATE` respectively."

    Design: Difficulty/resource_temporal_overlap/overlap_migration_window_closed_interval
    """
    stack = setup_active_stack(
        api,
        institution_name="Window Bank",
        recipient_name="WindowApp",
        consumer_ref="cons_o",
        window_start="2026-09-10T00:00:00Z",
        window_end="2026-09-20T00:00:00Z",
        target_method="BANK_API",
        method="CREDENTIALS",
    )
    admin = stack["admin"]
    consumer = stack["consumer"]
    conn_id = stack["connection"]["id"]

    validate_success(api.set_clock({"to_iso8601": "2026-09-10T00:00:00Z"}, admin))
    validate_success(api.start_migration(stack["institution"]["id"], admin))

    # One second past the inclusive window end, migration still IN_PROGRESS.
    validate_success(api.set_clock({"to_iso8601": "2026-09-20T00:00:01Z"}, admin))
    resp = api.migrate_connection(conn_id, consumer)
    validate_error(resp, ApiErrorId.ERR_MIGRATION_WINDOW_CLOSED)

    connection = validate_success(api.get_connection(conn_id, consumer))
    assert connection["status"] == "ACTIVE"
    assert connection["method"] == "CREDENTIALS", (
        "a rejected migrate must leave the connection on its original method"
    )
