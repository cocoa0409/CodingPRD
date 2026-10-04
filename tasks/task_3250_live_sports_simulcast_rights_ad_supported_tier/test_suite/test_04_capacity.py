"""Capacity pools and reservations: conservation, holds, expiry (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    SO,
    assert_pool_conservation,
    confirm_reservation,
    create_active_property,
    create_pool,
    create_window,
    get_success_data,
    hold_and_confirm,
    hold_reservation,
    set_clock,
    validate_error,
    validate_error_is_one_of,
    validate_success,
)


def _pool_and_window(total_units=20, oversubscribe_pct=0, capacity_required=7):
    prop = create_active_property()
    window = create_window(
        prop["id"],
        scheduled_start="2026-09-20T18:00:00Z",
        scheduled_end="2026-09-20T21:00:00Z",
        capacity_required_units=capacity_required,
    )
    pool = create_pool(total_units=total_units, oversubscribe_pct=oversubscribe_pct)
    return prop, window, pool


def test_pool_committed_units_conserved_across_hold_confirm_release(api):
    """PRD §3.5: "The **capacity conservation invariant** is that
    `committed_units` on a pool always equals the sum of `units` over its
    reservations currently in `HELD` or `CONFIRMED`."

    Hold 7 (0 -> 7), confirm (7, unchanged), release (7 -> 0).

    Design: Difficulty/compensating_invariant/pool_committed_units_conserved_across_hold_release_cycle
    """
    _, window, pool = _pool_and_window()
    res = hold_reservation(pool["id"], window["id"], units=7)
    mid = get_success_data(api.get_capacity_pool(pool["id"], SO))
    assert mid["committed_units"] == 7
    confirm_reservation(res["id"])
    confirmed = get_success_data(api.get_capacity_pool(pool["id"], SO))
    assert confirmed["committed_units"] == 7
    resp = api.release_capacity_reservation(res["id"], SO)
    validate_success(resp)
    final = get_success_data(api.get_capacity_pool(pool["id"], SO))
    assert final["committed_units"] == 0, (
        f"hold+confirm+release must restore committed_units to 0, got {final['committed_units']}"
    )


def test_pool_committed_units_conserved_across_two_cycles(api):
    """PRD §3.5: "The **capacity conservation invariant** is that
    `committed_units` on a pool always equals the sum of `units` over its
    reservations currently in `HELD` or `CONFIRMED`. Every transition into
    or out of those states adjusts the counter in the same atomic step as
    the reservation's own state change."

    Two independent hold/release cycles return the counter to zero each time.

    Design: Difficulty/compensating_invariant/pool_committed_units_conserved_across_hold_release_cycle
    """
    _, window, pool = _pool_and_window()
    for _ in range(2):
        res = hold_and_confirm(pool["id"], window["id"], units=7)
        pool_now = get_success_data(api.get_capacity_pool(pool["id"], SO))
        assert_pool_conservation(pool_now, [res])
        validate_success(api.release_capacity_reservation(res["id"], SO))
        pool_now = get_success_data(api.get_capacity_pool(pool["id"], SO))
        assert pool_now["committed_units"] == 0


def test_capacity_hold_equality_passes_one_more_fails(api):
    """PRD §3.5: "The creation of a reservation can also surface
    `ERR_CAPACITY_INSUFFICIENT` when the pool cannot satisfy the requested
    units." and "oversubscription does **not** apply at hold time — a hold
    is bounded by the pool's raw `total_units`."

    Pool of 10: a hold of exactly 10 succeeds; one further unit is rejected.

    Design: Difficulty/resource_temporal_overlap/capacity_window_aggregate_overlap_across_reservations
    """
    _, window, pool = _pool_and_window(total_units=10, capacity_required=10)
    res = hold_reservation(pool["id"], window["id"], units=10)
    assert res["status"] == "HELD"
    resp = api.create_capacity_reservation(
        {"pool_id": pool["id"], "window_id": window["id"], "units": 1}, SO
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_INSUFFICIENT)


def test_capacity_aggregate_shared_across_windows(api):
    """PRD §3.5: "The pool's `committed_units` counter is computed as the sum
    of units over all non-terminal reservations (those in `HELD` or
    `CONFIRMED`)."

    Reservations for two different windows share the same pool's units:
    holds of 6 and 4 fill a pool of 10; a third hold of 1 is rejected.

    Design: Difficulty/resource_temporal_overlap/capacity_window_aggregate_overlap_across_reservations
    """
    prop = create_active_property()
    w1 = create_window(prop["id"], scheduled_start="2026-09-19T18:00:00Z",
                       scheduled_end="2026-09-19T21:00:00Z", capacity_required_units=6)
    w2 = create_window(prop["id"], scheduled_start="2026-09-20T18:00:00Z",
                       scheduled_end="2026-09-20T21:00:00Z", capacity_required_units=4)
    pool = create_pool(total_units=10)
    hold_reservation(pool["id"], w1["id"], units=6)
    hold_reservation(pool["id"], w2["id"], units=4)
    pool_now = get_success_data(api.get_capacity_pool(pool["id"], SO))
    assert pool_now["committed_units"] == 10
    resp = api.create_capacity_reservation(
        {"pool_id": pool["id"], "window_id": w1["id"], "units": 1}, SO
    )
    validate_error(resp, ApiErrorId.ERR_CAPACITY_INSUFFICIENT)


def test_reservation_confirm_after_hold_expiry_rejected(api):
    """PRD §3.5: "The reservation is created in `HELD` with `hold_expires_at`
    set to the current logical time plus 900 seconds" and "Confirming a
    `HELD` reservation is permitted only when the current logical time is
    strictly less than `hold_expires_at`; a confirm attempted at or after
    that instant is rejected with `ERR_HOLD_EXPIRED` (HTTP 409)."

    Design: Corner/state_machines/reservation_confirm_after_hold_expiry_rejected
    """
    _, window, pool = _pool_and_window()
    set_clock("2026-09-24T17:00:00Z")
    res = hold_reservation(pool["id"], window["id"], units=1)
    set_clock("2026-09-24T17:15:01Z")  # 901 seconds later
    resp = api.confirm_capacity_reservation(res["id"], SO)
    # PRD pins both "ERR_HOLD_EXPIRED on confirm at/after hold_expires_at"
    # (§3.5) and "a HELD reservation transitions to EXPIRED automatically when
    # the clock reaches hold_expires_at" (§3.5/§2.8) without stating whether
    # the automatic transition materializes at clock-set time (making the row
    # EXPIRED, so the confirm hits the priority-6 state check) or is evaluated
    # lazily at confirm time (yielding ERR_HOLD_EXPIRED). Both orderings are
    # faithful readings; accept either.
    validate_error_is_one_of(resp, [ApiErrorId.ERR_HOLD_EXPIRED, ApiErrorId.ERR_INVALID_STATE])
