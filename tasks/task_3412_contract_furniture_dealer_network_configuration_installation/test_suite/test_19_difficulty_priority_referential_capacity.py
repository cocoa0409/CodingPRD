"""Difficulty rule: priority_pair_validation_conflict — the family-lifecycle
referential gate beats the plant-capacity constraint at reserve-slot
(PRD §3.6 check ordering)."""

from test_helpers import (
    ApiErrorId,
    acknowledge_order,
    advance_family,
    create_and_lock_configuration,
    create_order,
    create_phase,
    make_dealer_headers,
    make_module_entry,
    make_reserve_slot_payload,
    reserve_slot,
    setup_dealer_world,
    submit_order,
    validate_error,
)


def _full_plant_with_systems_order(api, discontinue):
    """Order A (4 chairs) acknowledged with phase A1 holding all 120 PLANT_GR
    units on 2026-11-02; order B (2 x WORKSTATION_6X6 A on the SYSTEMS
    family) acknowledged with phase B1 wanting 10 units on the same
    plant-day. When `discontinue` is true the SYSTEMS family is then driven
    CURRENT -> SUNSETTING -> DISCONTINUED."""
    ctx = setup_dealer_world(
        api,
        family_specs=(
            ("SEAT-2200", "SEATING", 28),
            ("SYS-7500", "SYSTEMS", 42),
        ),
    )
    dealer_id = ctx["dealer"]["id"]

    spec_a = create_and_lock_configuration(api, dealer_id)
    order_a = create_order(
        api, ctx["agreement"]["id"], spec_a["id"], dealer_id
    )
    order_a = submit_order(api, order_a, dealer_id)
    acknowledge_order(api, order_a["id"])
    phase_a = create_phase(api, order_a["id"], dealer_id, planned_units=120)
    reserve_slot(api, phase_a["id"], dealer_id, production_date="2026-11-02")

    spec_b = create_and_lock_configuration(
        api, dealer_id,
        modules=[make_module_entry("WORKSTATION_6X6", "A", 2)],
    )
    order_b = create_order(
        api, ctx["agreement"]["id"], spec_b["id"], dealer_id
    )
    order_b = submit_order(api, order_b, dealer_id)
    acknowledge_order(api, order_b["id"])
    phase_b = create_phase(
        api, order_b["id"], dealer_id, floor_number=2, planned_units=10
    )

    if discontinue:
        family = ctx["families"]["SYSTEMS"]
        advance_family(api, family["id"], lifecycle_status="SUNSETTING",
                       last_order_date="2026-12-31")
        advance_family(api, family["id"], lifecycle_status="DISCONTINUED",
                       parts_support_until="2033-09-01")
    return ctx, phase_b


def test_referential_error_beats_capacity_error_on_reserve_slot(api):
    """PRD §3.6: "The checks evaluate in this order: the phase must be
    `PLANNED` with `install_status` `NOT_STARTED` (else `ERR_INVALID_STATE`);
    the phase's order must be `ACKNOWLEDGED` (else
    `ERR_ORDER_NOT_ACKNOWLEDGED`); no module family of the order's
    configuration may be `DISCONTINUED` (else
    `ERR_PRODUCT_LINE_DISCONTINUED`)" and only later "the plant must have
    room on that date (else `ERR_PLANT_CAPACITY_EXCEEDED`)". With the
    SYSTEMS family discontinued AND the plant-day full, the referential
    check fires first.

    Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_capacity_error_on_reserve_slot
    """
    ctx, phase_b = _full_plant_with_systems_order(api, discontinue=True)
    resp = api.reserve_slot(
        phase_b["id"],
        make_reserve_slot_payload(production_date="2026-11-02"),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PRODUCT_LINE_DISCONTINUED)


def test_capacity_error_fires_when_family_still_current(api):
    """Control leg of the same design instance: before the family transition,
    the identical reserve on the full plant-day fails with
    `ERR_PLANT_CAPACITY_EXCEEDED` (PRD §3.6: "the plant must have room on
    that date (else `ERR_PLANT_CAPACITY_EXCEEDED`)") — proving both failure
    conditions are simultaneously present in the priority scenario.

    Design: Difficulty/priority_pair_validation_conflict/referential_error_beats_capacity_error_on_reserve_slot
    """
    ctx, phase_b = _full_plant_with_systems_order(api, discontinue=False)
    resp = api.reserve_slot(
        phase_b["id"],
        make_reserve_slot_payload(production_date="2026-11-02"),
        make_dealer_headers(ctx["dealer"]["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_PLANT_CAPACITY_EXCEEDED)
