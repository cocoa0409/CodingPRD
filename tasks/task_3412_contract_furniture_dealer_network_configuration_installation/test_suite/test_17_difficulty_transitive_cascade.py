"""Difficulty rule: transitive_cascade — order cancel runs a depth-3 cascade
(phase -> window/punch -> plant-day release) and phase completion bubbles the
order to CLOSED (PRD §3.5, §3.6)."""

from test_helpers import (
    ApiErrorId,
    acknowledge_order,
    cancel_order,
    complete_phase,
    create_order,
    create_phase,
    create_window,
    get_agreement,
    get_order,
    make_dealer_headers,
    make_reserve_slot_payload,
    reserve_slot,
    setup_locked_world,
    setup_phase_in_progress,
    submit_order,
    validate_error,
    validate_paginated,
)


def _two_orders_plant_full(api):
    """Orders A and B acknowledged on one locked 4-chair configuration
    (500000c pre-discount each). Phase A1 holds all 120 PLANT_GR units on
    2026-11-02 and carries one RESERVED window; phase B1 wants 60 more."""
    ctx = setup_locked_world(api)
    dealer_id = ctx["dealer"]["id"]

    order_a = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"], dealer_id
    )
    order_a = submit_order(api, order_a, dealer_id)
    order_a = acknowledge_order(api, order_a["id"])
    phase_a = create_phase(api, order_a["id"], dealer_id, planned_units=120)
    reserve_slot(api, phase_a["id"], dealer_id, production_date="2026-11-02")
    window_a = create_window(api, phase_a["id"], dealer_id)

    order_b = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"], dealer_id
    )
    order_b = submit_order(api, order_b, dealer_id)
    order_b = acknowledge_order(api, order_b["id"])
    phase_b = create_phase(
        api, order_b["id"], dealer_id, floor_number=2, planned_units=60
    )
    return ctx, order_a, phase_a, window_a, order_b, phase_b


def test_cancel_cascades_to_phase_window_and_ledger(api):
    """PRD §3.6: "A phase in `PLANNED`, `SCHEDULED`, or `DELIVERED` logistics
    whose `install_status` is not `COMPLETE` has both dimensions set to
    `CANCELLED`" and "every `RESERVED` install window of the phase moves to
    `CANCELLED`"; §3.5: "From `ACKNOWLEDGED`, the ledger is compensated first
    — the agreement's `cumulative_volume_cents` decreases by the order's
    `pre_discount_total_cents`".

    Design: Difficulty/transitive_cascade/order_cancel_cascades_phase_window_and_frees_plant_capacity
    """
    ctx, order_a, phase_a, window_a, _order_b, _phase_b = (
        _two_orders_plant_full(api)
    )
    dealer_h = make_dealer_headers(ctx["dealer"]["id"])

    cancelled = cancel_order(api, order_a["id"], dealer_h, reason="scope cut")
    assert cancelled["status"] == "CANCELLED"

    phases, meta = validate_paginated(
        api.list_phases(order_a["id"], dealer_h)
    )
    assert meta["total_count"] == 1
    assert phases[0]["id"] == phase_a["id"]
    assert phases[0]["logistics_status"] == "CANCELLED"
    assert phases[0]["install_status"] == "CANCELLED"

    windows, wmeta = validate_paginated(
        api.list_install_windows(
            dealer_h, params={"installation_phase_id": phase_a["id"]}
        )
    )
    assert wmeta["total_count"] == 1
    assert windows[0]["id"] == window_a["id"]
    assert windows[0]["status"] == "CANCELLED"

    agreement = get_agreement(api, ctx["agreement"]["id"])
    assert agreement["cumulative_volume_cents"] == 500000


def test_capacity_release_lets_rejected_reserve_succeed(api):
    """PRD §3.6: "a phase that was `SCHEDULED` or `DELIVERED` releases its
    plant-day reservation, raising the plant's available capacity on that
    date by the phase's `planned_units` — so a slot reservation previously
    rejected for that plant and day may now succeed."

    Design: Difficulty/transitive_cascade/order_cancel_cascades_phase_window_and_frees_plant_capacity
    """
    ctx, order_a, _phase_a, _window_a, _order_b, phase_b = (
        _two_orders_plant_full(api)
    )
    dealer_h = make_dealer_headers(ctx["dealer"]["id"])

    # Plant-day is full (120/120 at PLANT_GR on 2026-11-02).
    resp = api.reserve_slot(
        phase_b["id"],
        make_reserve_slot_payload(production_date="2026-11-02"),
        dealer_h,
    )
    validate_error(resp, ApiErrorId.ERR_PLANT_CAPACITY_EXCEEDED)

    cancel_order(api, order_a["id"], dealer_h, reason="scope cut")

    rescheduled = reserve_slot(
        api, phase_b["id"], ctx["dealer"]["id"], production_date="2026-11-02"
    )
    assert rescheduled["logistics_status"] == "SCHEDULED"


def test_complete_stamps_actual_install_complete_date(api):
    """PRD §3.6: "On success `actual_install_complete_date` is set to the
    clock date — this date becomes the basis of the phase's warranty
    windows". Completing at clock 2026-11-02 records 2026-11-02.

    Design: Difficulty/transitive_cascade/phase_complete_bubble_up_closes_order
    """
    ctx = setup_phase_in_progress(api, production_date="2026-11-02")
    done = complete_phase(api, ctx["phase"]["id"], ctx["dealer"]["id"])
    assert done["install_status"] == "COMPLETE"
    assert done["actual_install_complete_date"] == "2026-11-02"


def test_last_phase_completion_bubbles_order_to_closed(api):
    """PRD §3.6: "Completion bubbles up: after any phase completes, if the
    order is `ACKNOWLEDGED`, has at least one phase, and every phase of the
    order is `COMPLETE`, the order itself moves `ACKNOWLEDGED → CLOSED` with
    its `version` incremented."

    Design: Difficulty/transitive_cascade/phase_complete_bubble_up_closes_order
    """
    ctx = setup_phase_in_progress(api, production_date="2026-11-02")
    order_before = get_order(
        api, ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
    )
    assert order_before["status"] == "ACKNOWLEDGED"

    complete_phase(api, ctx["phase"]["id"], ctx["dealer"]["id"])

    order_after = get_order(
        api, ctx["order"]["id"], make_dealer_headers(ctx["dealer"]["id"])
    )
    assert order_after["status"] == "CLOSED"
    assert order_after["version"] == order_before["version"] + 1
