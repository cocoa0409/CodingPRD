"""Difficulty queue A — dual_variant_calc instances."""

from test_helpers import (
    ApiErrorId,
    assert_instants_equal,
    drive_consecutive_failures,
    get_success_data,
    make_admin_headers,
    make_consumer_headers,
    setup_active_stack,
    validate_paginated,
    validate_success,
)


def test_institution_health_broken_at_five_events_inclusive_window(api):
    """PRD §3.1: "Health evaluation counts the breakage events for the
    institution whose `occurred_at` falls within the trailing 86400 seconds —
    one full day... If the count is 5 or more, the institution is `BROKEN`;
    if it is 3 or 4, the institution is `DEGRADED`; below 3 it is `ACTIVE`."

    Design: Difficulty/dual_variant_calc/dual_variant_institution_health_inclusive_vs_post_recover
    """
    stack = setup_active_stack(
        api,
        institution_name="First Mutual Bank",
        recipient_name="BudgetWise App",
        consumer_ref="cons_a",
        reauth_cooldown_seconds=600,
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    drive_consecutive_failures(api, conn_id, "cons_a", 5)

    institution = validate_success(api.get_institution(stack["institution"]["id"], stack["admin"]))
    assert institution["status"] == "BROKEN", (
        f"5 breakage events inside the window must yield BROKEN, got {institution['status']}"
    )
    # The connection was ACTIVE when the 5th event landed, so the institution
    # breakage cascade parked it in REAUTH_REQUIRED.
    connection = validate_success(api.get_connection(conn_id, consumer))
    assert connection["status"] == "REAUTH_REQUIRED", (
        f"institution breakage cascade must push ACTIVE connections to REAUTH_REQUIRED, "
        f"got {connection['status']}"
    )


def test_institution_health_resets_to_active_after_recover(api):
    """PRD §3.1: "A `PlatformAdmin` recovers the institution after the
    underlying fault is fixed; recovery flips the `status` back to `ACTIVE`,
    records the recovery instant so that past breakage events no longer count
    toward the window, and increments the institution's `version`. Connections
    parked in `REAUTH_REQUIRED` by the outage stay there — each consumer must
    re-authenticate individually."

    Design: Difficulty/dual_variant_calc/dual_variant_institution_health_inclusive_vs_post_recover
    """
    stack = setup_active_stack(
        api,
        institution_name="First Mutual Bank",
        recipient_name="BudgetWise App",
        consumer_ref="cons_a",
        reauth_cooldown_seconds=600,
    )
    conn_id = stack["connection"]["id"]
    inst_id = stack["institution"]["id"]
    admin = stack["admin"]
    version_before = validate_success(api.get_institution(inst_id, admin))["version"]

    drive_consecutive_failures(api, conn_id, "cons_a", 5)
    assert validate_success(api.get_institution(inst_id, admin))["status"] == "BROKEN"

    recovered = validate_success(api.recover_institution(inst_id, admin))
    assert recovered["status"] == "ACTIVE", (
        f"post_recover_reset: status must recompute to ACTIVE, got {recovered['status']}"
    )
    assert recovered["version"] == version_before + 1, (
        "recovery must increment the institution version by 1"
    )

    reread = validate_success(api.get_institution(inst_id, admin))
    assert reread["status"] == "ACTIVE"

    connection = validate_success(api.get_connection(conn_id, stack["consumer"]))
    assert connection["status"] == "REAUTH_REQUIRED", (
        "connections parked in REAUTH_REQUIRED by the outage must stay there after recovery"
    )


def test_cost_summary_finalized_variant_below_free_allowance(api):
    """PRD §3.9: "under `LOW`, a `FULL` refresh costs 2 units and an
    `INCREMENTAL` costs 1... The summed units are then offset by a free
    allowance per rate class — 10 units for `LOW`, 20 for `MEDIUM`, 40 for
    `HIGH`. Billable units are the excess of total units over the allowance,
    floored at zero, and the cost in cents is exactly 100 per billable unit."

    Design: Difficulty/dual_variant_calc/dual_variant_connection_cost_final_vs_provisional
    """
    stack = setup_active_stack(
        api,
        institution_name="Harbor Savings",
        recipient_name="CashTrack",
        consumer_ref="cons_b",
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]

    # complete_auth already ran one FULL refresh; add one more explicit FULL.
    job = validate_success(api.refresh_connection(conn_id, {"kind": "FULL"}, consumer))
    assert job["status"] == "SUCCEEDED"

    summary = validate_success(api.get_cost_summary(conn_id, consumer))
    assert summary["rate_class"] == "LOW"
    assert summary["units"] == 4, (
        f"two SUCCEEDED FULL refreshes at LOW cost 2 must total 4 units, got {summary['units']}"
    )
    assert summary["billable_units"] == 0, (
        f"4 units against the LOW free allowance of 10 must bill 0, got {summary['billable_units']}"
    )
    assert summary["cost_cents"] == 0


def test_cost_summary_provisional_variant_exceeds_final(api):
    """PRD §3.9: "the projected units equal the month-to-date units plus the
    `rate_class`'s `FULL`-refresh unit cost multiplied by the number of
    remaining weeks in the month rounded up — that is, the gap from the clock
    to the first instant of the next UTC calendar month, divided by 604800
    seconds, with any partial week counting as a full one. Billable units and
    cents are then recomputed from the projected figure against the same free
    allowance, so the provisional total strictly exceeds the finalized figure
    whenever the month has remaining days."

    Design: Difficulty/dual_variant_calc/dual_variant_connection_cost_final_vs_provisional
    """
    stack = setup_active_stack(
        api,
        institution_name="Harbor Savings",
        recipient_name="CashTrack",
        consumer_ref="cons_b",
    )
    conn_id = stack["connection"]["id"]
    consumer = stack["consumer"]
    validate_success(api.refresh_connection(conn_id, {"kind": "FULL"}, consumer))

    # Clock at 2026-09-01T00:00:00Z: 2592000s remain in September 2026,
    # ceil(2592000/604800) = 5 projected remaining weekly FULL refreshes.
    provisional = validate_success(
        api.get_cost_summary(conn_id, consumer, params={"include_pending": "true"})
    )
    assert provisional["units"] == 14, (
        f"provisional units must be 4 + 2 * 5 = 14, got {provisional['units']}"
    )
    assert provisional["billable_units"] == 4
    assert provisional["cost_cents"] == 400

    finalized = validate_success(api.get_cost_summary(conn_id, consumer))
    assert finalized["cost_cents"] == 0
    assert provisional["cost_cents"] > finalized["cost_cents"], (
        "the provisional figure must strictly exceed the finalized figure"
    )
