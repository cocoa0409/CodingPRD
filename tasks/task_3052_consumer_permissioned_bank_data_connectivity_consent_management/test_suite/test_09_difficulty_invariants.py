"""Difficulty queue A — compensating_invariant instances."""

from test_helpers import (
    assert_single_active_agreement,
    create_agreement_payload,
    setup_active_stack,
    validate_paginated,
    validate_success,
)


def test_agreement_supersede_keeps_single_active_agreement(api):
    """PRD §3.6: "Only one agreement governs an institution at a time. When a
    `PlatformAdmin` publishes a new agreement — supplying `rate_limit_per_hour`,
    the `permitted_fields_by_scope` map, and the OCC field
    `expected_institution_version` — the previously `ACTIVE` agreement's
    `active` flag flips to false, the institution's `version` increments, and
    the new row becomes the governing one."

    Design: Difficulty/compensating_invariant/invariant_active_agreement_count_conserved_across_supersede
    """
    from test_helpers import create_institution_with_agreement

    admin_stack = create_institution_with_agreement(
        api, name="Invariant Bank", rate_limit_per_hour=50
    )
    admin = admin_stack["admin"]
    institution = admin_stack["institution"]
    first = admin_stack["agreement"]
    assert first["active"] is True

    current = validate_success(api.get_institution(institution["id"], admin))
    second = validate_success(
        api.create_agreement(
            institution["id"],
            create_agreement_payload(
                rate_limit_per_hour=75,
                permitted_fields_by_scope={
                    "BALANCE": ["current_cents"],
                    "TRANSACTIONS": ["amount_cents"],
                },
                expected_institution_version=current["version"],
            ),
            admin,
        ),
        expected_status=201,
    )
    assert second["active"] is True

    agreements, meta = validate_paginated(api.list_agreements(institution["id"], admin))
    assert meta["total_count"] == 2, "agreement history must be retained"
    assert_single_active_agreement(agreements)
    by_id = {a["id"]: a for a in agreements}
    assert by_id[first["id"]]["active"] is False, (
        "the superseded agreement must flip to inactive (compensating flip)"
    )
    assert by_id[second["id"]]["active"] is True


def test_agreement_create_increments_institution_version(api):
    """PRD §3.6: "the previously `ACTIVE` agreement's `active` flag flips to
    false, the institution's `version` increments, and the new row becomes the
    governing one."
    PRD §2.5: "`version` is an integer starting at 1 that increments on every
    mutation."

    Design: Difficulty/compensating_invariant/invariant_active_agreement_count_conserved_across_supersede
    """
    from test_helpers import create_institution_with_agreement

    admin_stack = create_institution_with_agreement(
        api, name="Invariant Bank", rate_limit_per_hour=50
    )
    admin = admin_stack["admin"]
    institution = admin_stack["institution"]

    after_first = validate_success(api.get_institution(institution["id"], admin))
    assert after_first["version"] == institution["version"] + 1, (
        "the first agreement create must bump the institution version by 1"
    )

    validate_success(
        api.create_agreement(
            institution["id"],
            create_agreement_payload(
                rate_limit_per_hour=75,
                expected_institution_version=after_first["version"],
            ),
            admin,
        ),
        expected_status=201,
    )
    after_second = validate_success(api.get_institution(institution["id"], admin))
    assert after_second["version"] == after_first["version"] + 1


def test_reauth_restores_failure_counters_to_zero(api):
    """PRD §3.7: "A valid re-authentication moves the connection to `ACTIVE`,
    zeroes `consecutive_failures`, clears `reauth_not_before` to null, and
    writes a `connection.reauth` audit entry."

    Design: Difficulty/compensating_invariant/invariant_refresh_failure_counter_reset_on_reauth
    """
    stack = setup_active_stack(
        api,
        institution_name="Counter Bank",
        recipient_name="CounterApp",
        consumer_ref="cons_p",
        reauth_cooldown_seconds=0,
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    validate_success(
        api.refresh_connection(
            conn_id, {"kind": "FULL", "failure_reason": "CREDENTIALS_INVALID"}, consumer
        )
    )
    mid = validate_success(api.get_connection(conn_id, consumer))
    assert mid["consecutive_failures"] == 1, (
        "the forward action must increment consecutive_failures"
    )
    assert mid["status"] == "REAUTH_REQUIRED"

    restored = validate_success(api.reauth_connection(conn_id, {"valid": True}, consumer))
    assert restored["status"] == "ACTIVE"
    assert restored["consecutive_failures"] == 0, (
        "the compensating reauth must restore consecutive_failures to 0"
    )
    assert restored["reauth_not_before"] is None


def test_breakage_events_not_erased_by_compensating_reauth(api):
    """PRD §3.1: "Every refresh failure against any connection of the
    institution appends a `BreakageEvent`."
    PRD §3.1: "records the recovery instant so that past breakage events no
    longer count toward the window" — the events persist; only their weighting
    changes.

    Design: Difficulty/compensating_invariant/invariant_refresh_failure_counter_reset_on_reauth
    """
    stack = setup_active_stack(
        api,
        institution_name="Counter Bank",
        recipient_name="CounterApp",
        consumer_ref="cons_p",
        reauth_cooldown_seconds=0,
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    validate_success(
        api.refresh_connection(
            conn_id, {"kind": "FULL", "failure_reason": "CREDENTIALS_INVALID"}, consumer
        )
    )
    validate_success(api.reauth_connection(conn_id, {"valid": True}, consumer))

    events, meta = validate_paginated(
        api.list_institution_breakage_events(stack["institution"]["id"], stack["admin"])
    )
    assert meta["total_count"] == 1, (
        "the breakage ledger is append-only: a compensating reauth must not erase events"
    )
