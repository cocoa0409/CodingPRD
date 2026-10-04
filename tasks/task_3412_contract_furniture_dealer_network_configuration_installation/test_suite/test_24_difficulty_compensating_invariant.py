"""Difficulty rule: compensating_invariant — agreement volume and plant
capacity are conserved across acknowledge/cancel pairs (PRD §3.2, §3.5,
§3.6)."""

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    acknowledge_order,
    assert_agreement_volume_invariant,
    cancel_order,
    create_order,
    create_phase,
    get_agreement,
    get_order,
    make_dealer_headers,
    make_reserve_slot_payload,
    reserve_slot,
    setup_locked_world,
    submit_order,
    validate_error,
)

ADMIN = TEST_USERS["admin_headers"]


def _two_acknowledged_orders(api):
    """One locked 4-chair configuration (pre-discount 500000c per order) and
    two ACKNOWLEDGED orders against it."""
    ctx = setup_locked_world(api)
    dealer_id = ctx["dealer"]["id"]
    order1 = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"], dealer_id
    )
    order1 = submit_order(api, order1, dealer_id)
    order1 = acknowledge_order(api, order1["id"])
    order2 = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"], dealer_id
    )
    order2 = submit_order(api, order2, dealer_id)
    order2 = acknowledge_order(api, order2["id"])
    return ctx, order1, order2


def test_acknowledge_debits_agreement_ledger(api):
    """PRD §3.5: "Acknowledgment then debits the agreement ledger:
    `cumulative_volume_cents` increases by the order's
    `pre_discount_total_cents`" — two 500000-cent acknowledges accumulate to
    500000 then 1000000.

    Design: Difficulty/compensating_invariant/agreement_volume_conserved_across_acknowledge_and_cancel
    """
    ctx, order1, order2 = _two_acknowledged_orders(api)
    assert order1["pre_discount_total_cents"] == 500000
    assert order2["pre_discount_total_cents"] == 500000
    agreement = get_agreement(api, ctx["agreement"]["id"])
    assert agreement["cumulative_volume_cents"] == 1000000
    assert_agreement_volume_invariant(agreement, [order1, order2])


def test_cancel_from_acknowledged_compensates_ledger(api):
    """PRD §3.5: "From `ACKNOWLEDGED`, the ledger is compensated first — the
    agreement's `cumulative_volume_cents` decreases by the order's
    `pre_discount_total_cents` and `current_tier` is recomputed" — the
    compensating cancel exactly reverses the earlier debit, leaving 500000.

    Design: Difficulty/compensating_invariant/agreement_volume_conserved_across_acknowledge_and_cancel
    """
    ctx, order1, order2 = _two_acknowledged_orders(api)
    dealer_h = make_dealer_headers(ctx["dealer"]["id"])

    cancel_order(api, order1["id"], dealer_h, reason="downsized")

    agreement = get_agreement(api, ctx["agreement"]["id"])
    assert agreement["cumulative_volume_cents"] == 500000
    order1_now = get_order(api, order1["id"], dealer_h)
    order2_now = get_order(api, order2["id"], dealer_h)
    assert order1_now["status"] == "CANCELLED"
    assert_agreement_volume_invariant(agreement, [order1_now, order2_now])


def _plant_day_full(api):
    """Order A acknowledged with a phase holding all 120 PLANT_GR units on
    2026-11-02; order B acknowledged with a 1-unit phase for the same
    plant-day."""
    ctx = setup_locked_world(api)
    dealer_id = ctx["dealer"]["id"]

    order_a = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"], dealer_id
    )
    order_a = submit_order(api, order_a, dealer_id)
    order_a = acknowledge_order(api, order_a["id"])
    phase_a = create_phase(api, order_a["id"], dealer_id, planned_units=120)
    reserve_slot(api, phase_a["id"], dealer_id, production_date="2026-11-02")

    order_b = create_order(
        api, ctx["agreement"]["id"], ctx["configuration"]["id"], dealer_id
    )
    order_b = submit_order(api, order_b, dealer_id)
    order_b = acknowledge_order(api, order_b["id"])
    phase_b = create_phase(
        api, order_b["id"], dealer_id, floor_number=2, planned_units=1
    )
    return ctx, order_a, phase_b


def test_full_plant_day_rejects_additional_reserve(api):
    """PRD §3.6: "the available capacity is the plant's daily capacity (120
    for `PLANT_GR`, 80 for `PLANT_DAL`) minus the reserved units; reserved
    plus available always equals the plant's daily capacity" — with 120 of
    120 reserved, a further 1-unit reservation is rejected
    `ERR_PLANT_CAPACITY_EXCEEDED`.

    Design: Difficulty/compensating_invariant/plant_capacity_conserved_across_reserve_and_cancel
    """
    ctx, _order_a, phase_b = _plant_day_full(api)
    resp = api.reserve_slot(
        phase_b["id"],
        make_reserve_slot_payload(production_date="2026-11-02"),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLANT_CAPACITY_EXCEEDED)


def test_order_cancel_restores_plant_capacity_exactly(api):
    """PRD §3.6: "a phase that was `SCHEDULED` or `DELIVERED` releases its
    plant-day reservation, raising the plant's available capacity on that
    date by the phase's `planned_units` — so a slot reservation previously
    rejected for that plant and day may now succeed."

    Design: Difficulty/compensating_invariant/plant_capacity_conserved_across_reserve_and_cancel
    """
    ctx, order_a, phase_b = _plant_day_full(api)
    resp = api.reserve_slot(
        phase_b["id"],
        make_reserve_slot_payload(production_date="2026-11-02"),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLANT_CAPACITY_EXCEEDED)

    # The manufacturer cancels order A (shared operation, PRD §4).
    cancel_order(api, order_a["id"], ADMIN, reason="project shelved")

    rescheduled = reserve_slot(
        api, phase_b["id"], ctx["dealer"]["id"], production_date="2026-11-02"
    )
    assert rescheduled["logistics_status"] == "SCHEDULED"
