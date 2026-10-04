"""Corner queue B — cross_cutting_complexity_layers section instances."""

from test_helpers import (
    assert_connectivity_mode_tracks_migration,
    create_institution_payload,
    make_admin_headers,
    setup_active_stack,
    validate_paginated,
    validate_success,
)


def test_derived_connectivity_mode_recomputed_through_migration(api):
    """PRD §3.1: "The `connectivity_mode` is never written directly; it is
    derived from the migration journey. While `migration_state` is
    `NOT_STARTED` the institution runs in `LEGACY_MODE`; once migration is
    underway the mode reads `HYBRID`; once migration completes it reads
    `API_ONLY`."
    PRD §3.8: "Successful completion sets `migration_state` to `COMPLETE`,
    flips `connectivity_mode` to `API_ONLY`."

    Design: Corner/cross_cutting_complexity_layers/derived_connectivity_mode_recomputed_through_migration
    """
    admin = make_admin_headers()
    institution = validate_success(
        api.create_institution(
            create_institution_payload(
                name="DerivedMode Bank",
                supported_methods=["CREDENTIALS", "BANK_API"],
                target_method="BANK_API",
                migration_window_start="2026-09-01T00:00:00Z",
                migration_window_end="2026-09-30T00:00:00Z",
            ),
            admin,
        ),
        expected_status=201,
    )
    assert institution["connectivity_mode"] == "LEGACY_MODE"
    assert institution["migration_state"] == "NOT_STARTED"
    assert institution["version"] == 1

    started = validate_success(api.start_migration(institution["id"], admin))
    assert started["connectivity_mode"] == "HYBRID"
    assert started["migration_state"] == "IN_PROGRESS"

    # No connections exist, so the completion precondition holds vacuously.
    completed = validate_success(api.complete_migration(institution["id"], admin))
    assert completed["connectivity_mode"] == "API_ONLY"
    assert completed["migration_state"] == "COMPLETE"
    assert completed["version"] == 3, (
        "create + start + complete must step the version from 1 to 3"
    )
    assert_connectivity_mode_tracks_migration(completed)


def test_cascading_expiry_sweep_disconnects_and_notifies(api):
    """PRD §2.4: "Advancing the clock triggers two eager recomputations: any
    `ACTIVE` consent whose `expires_at` has been reached or passed transitions
    to `EXPIRED` with its full cascade... the response reports `now_iso8601`
    and the list `expired_consent_ids` of consents the sweep flipped."
    PRD §3.5: "When the clock reaches or passes a consent's `expires_at`...
    the consent moves to `EXPIRED`. The cascade mirrors revocation:
    connections are disconnected, and a `CONSENT_EXPIRED` webhook is emitted
    per affected connection."

    Design: Corner/cross_cutting_complexity_layers/cascading_expiry_sweep_disconnects_and_notifies
    """
    stack = setup_active_stack(
        api,
        institution_name="Sweep Bank",
        recipient_name="SweepApp",
        consumer_ref="cons_ai",
        expires_at="2026-09-02T00:00:00Z",
    )
    admin = stack["admin"]
    consumer = stack["consumer"]
    consent_id = stack["consent"]["id"]
    conn_id = stack["connection"]["id"]

    sweep = validate_success(api.set_clock({"to_iso8601": "2026-09-02T00:00:00Z"}, admin))
    assert consent_id in sweep["expired_consent_ids"], (
        "the sweep must report the consent it flipped to EXPIRED"
    )
    assert len(sweep["expired_consent_ids"]) == 1

    consent = validate_success(api.get_consent(consent_id, consumer))
    assert consent["status"] == "EXPIRED"
    connection = validate_success(api.get_connection(conn_id, consumer))
    assert connection["status"] == "DISCONNECTED"

    events, meta = validate_paginated(
        api.list_connection_webhook_events(conn_id, admin, params={"event_type": "CONSENT_EXPIRED"})
    )
    assert meta["total_count"] == 1, "the expiry cascade must emit one CONSENT_EXPIRED webhook"
