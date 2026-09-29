"""Compensating actions that must leave a conserved quantity exactly as it was.

PRD 3.6 conserves every master night as rooms_allotted equals sub-allocated plus
picked up plus released plus open, and PRD 3.8 conserves the contract's
receivable; a cancellation and a force-majeure termination are the compensating
moves that have to hand back precisely what they took.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    CONTRACT_ADMIN,
    RESERVATIONS_AGENT,
    BlockInventoryStatus,
    CancellationReason,
    ChargeCategory,
    ChargeStatus,
    ContractStatus,
    ReservationStatus,
    advance_reservation,
    assert_block_night,
    assert_group_contract,
    assert_nights_conserved,
    assert_pickup_summary,
    assert_receivable_identity,
    assert_reservation,
    assert_room_block,
    committed_rooms,
    constants as C,
    factories as F,
    night_on,
    pickup_summary,
    read_block,
    read_contract,
    read_nights,
    seed_ancillary_charge,
    seed_open_master_block,
    seed_reservation,
    seed_sub_block,
    set_clock,
    validate_paginated,
    validate_success,
)

_SUB_PLAN = (("2026-11-09", 2), ("2026-11-10", 2))
_SPEAKER = {
    "guest_name": "Keynote Speaker",
    "arrival_date": "2026-11-09",
    "departure_date": "2026-11-10",
}
_DELEGATE = {
    "guest_name": "Delegate One",
    "arrival_date": "2026-11-09",
    "departure_date": "2026-11-12",
}


def _master_and_sub_with_two_entries(api):
    """An OPEN 4/4/4 master with a 2+2 sub-block carved out of it, one PENDING
    rooming-list entry in each (PRD 3.6)."""
    world = seed_open_master_block(api)
    sub = seed_sub_block(
        api, world, name="Speakers", nightly_allotments=F.allotment_plan(*_SUB_PLAN)
    )
    world["sub_block_id"] = sub["id"]
    validate_success(api.open_room_block(sub["id"], RESERVATIONS_AGENT))
    world["sub_reservation"] = seed_reservation(api, sub["id"], **_SPEAKER)
    world["master_reservation"] = seed_reservation(
        api, world["master_block_id"], **_DELEGATE
    )
    return world


def _cancel_the_master_entry(api, world):
    return validate_success(
        api.cancel_reservation(
            world["master_reservation"]["id"],
            F.cancel_reservation_payload(disposition_reason="Traveller withdrew"),
            RESERVATIONS_AGENT,
        )
    )


def test_cancelling_a_reservation_returns_its_rooms_to_open_not_to_released(api):
    """The compensating cancel puts the rooms back in the bucket they came from.

    PRD 3.6 counts a rooming-list entry against every night of its half-open
    stay - three room nights for a 2026-11-09 to -12 stay - and a cancellation
    "decrements rooms_picked_up and increments rooms_open on each of those
    nights". The rooms must not appear as released, and the per-night identity
    rooms_allotted equals sub-allocated plus picked up plus released plus open has
    to survive on both blocks.

    Design: Difficulty/compensating_invariant/block_night_room_conservation_survives_cancel_then_cutoff
    """
    world = _master_and_sub_with_two_entries(api)
    assert world["sub_reservation"]["room_nights"] == 1
    assert world["master_reservation"]["room_nights"] == 3
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-09"),
        rooms_picked_up=1,
        rooms_open=1,
    )
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-11"), rooms_open=3
    )

    cancelled = _cancel_the_master_entry(api, world)

    assert_reservation(cancelled, status=ReservationStatus.CANCELLED)
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-09"),
        rooms_sub_allocated=2,
        rooms_picked_up=0,
        rooms_released=0,
        rooms_open=2,
    )
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-11"),
        rooms_picked_up=0,
        rooms_open=4,
    )
    assert_nights_conserved(read_nights(api, world["master_block_id"]))
    assert_nights_conserved(read_nights(api, world["sub_block_id"]))


def test_the_cutoff_converts_the_returned_rooms_into_releases_exactly_once(api):
    """The cascade releases the handed-back rooms without double counting them.

    PRD 3.7 sets each night's rooms_released to rooms_allotted less
    rooms_sub_allocated less rooms_picked_up and drives rooms_open to zero, so the
    two rooms the cancellation returned on 2026-11-09 are released once, and
    2026-11-11 releases all four. The master's rollups see only its own nights -
    8 released room nights, and a peak of 0 because every master night is empty -
    while the sub-block's single occupied room night still rolls up as pickup, and
    only the master's releases return to the house calendar.

    Design: Difficulty/compensating_invariant/block_night_room_conservation_survives_cancel_then_cutoff
    """
    world = _master_and_sub_with_two_entries(api)
    _cancel_the_master_entry(api, world)
    set_clock(api, C.CUTOFF_CLOCK)

    cut = validate_success(
        api.cutoff_room_block(world["master_block_id"], RESERVATIONS_AGENT)
    )

    assert_room_block(cut, inventory_status=BlockInventoryStatus.CUT_OFF)
    assert_room_block(
        read_block(api, world["sub_block_id"]),
        inventory_status=BlockInventoryStatus.CUT_OFF,
    )
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-09"),
        rooms_released=2,
        rooms_open=0,
    )
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-10"), rooms_released=2
    )
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-11"),
        rooms_released=4,
        rooms_open=0,
    )
    assert_block_night(
        night_on(api, world["sub_block_id"], "2026-11-09"),
        rooms_picked_up=1,
        rooms_released=1,
        rooms_open=0,
    )
    assert_block_night(
        night_on(api, world["sub_block_id"], "2026-11-10"), rooms_released=2
    )
    assert_nights_conserved(read_nights(api, world["master_block_id"]))
    assert_nights_conserved(read_nights(api, world["sub_block_id"]))

    assert_pickup_summary(
        pickup_summary(api, world["master_block_id"]),
        released_room_nights=8,
        picked_up_room_nights=1,
        peak_night_rooms=0,
        commitment_base_room_nights=12,
    )
    assert committed_rooms(api, C.STAY_DATES) == [2, 2, 0], (
        "only the master's own releases move the house calendar"
    )
    assert_reservation(
        validate_success(
            api.get_reservation(world["sub_reservation"]["id"], RESERVATIONS_AGENT)
        ),
        status=ReservationStatus.PENDING,
    )


def _contract_carrying_two_posted_charges(api):
    """A signed 4/4/4 contract with an OPEN master block, one CONFIRMED guest and
    620000 cents of posted ancillary revenue (PRD 3.6, PRD 3.8)."""
    world = seed_open_master_block(api)
    reservation = seed_reservation(api, world["master_block_id"], **_DELEGATE)
    world["reservation_id"] = reservation["id"]
    advance_reservation(api, reservation["id"], "CONFIRMED")
    world["banquet"] = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
        post=True,
    )
    world["av"] = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.AUDIOVISUAL,
        gross_amount_cents=200000,
        post=True,
    )
    return world


def _terminate_for_force_majeure(api, world):
    return validate_success(
        api.cancel_contract(
            world["contract_id"],
            F.cancel_contract_payload(
                cancellation_reason=CancellationReason.FORCE_MAJEURE,
                note="Airport closed by hurricane",
            ),
            CONTRACT_ADMIN,
        )
    )


def test_force_majeure_returns_the_receivable_to_its_pre_charge_value(api):
    """Every posted cent comes back off the ledger, with no residue.

    PRD 3.8 states the purpose of the void asymmetry outright: terminating for
    force majeure under a STANDARD clause "voids every charge and zeroes the
    damages, so receivable_total_cents returns to exactly its pre-charge value of
    0 with no drift". The clause is what makes the damages zero - the same
    termination for a client cancellation would have priced the mitigated
    commitment - so a non-zero receivable or a surviving POSTED charge is a
    conservation failure.

    Design: Difficulty/compensating_invariant/force_majeure_termination_returns_receivable_to_zero
    """
    world = _contract_carrying_two_posted_charges(api)
    before = read_contract(api, world["contract_id"])
    assert_group_contract(
        before,
        contracted_rate_cents=20880,
        ancillary_posted_cents=620000,
        receivable_total_cents=620000,
        assessed_damages_cents=0,
    )
    assert_receivable_identity(before)

    terminated = _terminate_for_force_majeure(api, world)

    assert_group_contract(
        terminated,
        status=ContractStatus.TERMINATED_FORCE_MAJEURE,
        assessed_damages_cents=0,
        ancillary_posted_cents=0,
        receivable_total_cents=0,
    )
    assert_receivable_identity(terminated)

    charges, _ = validate_paginated(
        api.list_contract_ancillary_charges(world["contract_id"], ACCOUNTING_CLERK)
    )
    assert [row["status"] for row in charges] == [
        ChargeStatus.VOIDED,
        ChargeStatus.VOIDED,
    ], f"both charges must be voided by the termination: {charges}"
    assert [row["net_amount_cents"] for row in charges] == [450000, 170000], (
        "voiding leaves each charge's own net amount on the row"
    )


def test_the_termination_also_releases_the_rooms_and_the_confirmed_guest(api):
    """The termination cascade empties the block and the house calendar.

    PRD 3.6 moves the block to RELEASED on termination and cancels its
    reservations, and the release "absorbs picked-up and unpicked rooms alike":
    all four rooms of every night become released, none remain picked up or open,
    and committed_group_rooms falls to zero on all three dates even though one
    guest had been CONFIRMED.

    Design: Difficulty/compensating_invariant/force_majeure_termination_returns_receivable_to_zero
    """
    world = _contract_carrying_two_posted_charges(api)

    _terminate_for_force_majeure(api, world)

    assert_reservation(
        validate_success(
            api.get_reservation(world["reservation_id"], RESERVATIONS_AGENT)
        ),
        status=ReservationStatus.CANCELLED,
    )
    assert_room_block(
        read_block(api, world["master_block_id"]),
        inventory_status=BlockInventoryStatus.RELEASED,
    )
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-09"),
        rooms_released=4,
        rooms_picked_up=0,
        rooms_open=0,
    )
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-11"), rooms_released=4
    )
    assert_nights_conserved(read_nights(api, world["master_block_id"]))
    assert committed_rooms(api, C.STAY_DATES) == [0, 0, 0]
