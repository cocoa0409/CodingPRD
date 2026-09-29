"""Multi-hop cascades: the countersignature and the master-block cutoff.

PRD 3.5 makes one signature mint the master block and its nights, swap the soft
hold for a firm commitment on the calendar and confirm the programme's meeting
space; PRD 3.7 makes one cutoff walk the master, its sub-blocks, every night of
both and finally the calendar.
"""

from test_helpers import (
    CONTRACT_ADMIN,
    CONTRACT_ADMIN_ID,
    RESERVATIONS_AGENT,
    SALES_MANAGER,
    BlockBillingStatus,
    BlockInventoryStatus,
    ContractStatus,
    HoldStatus,
    QuoteStatus,
    ReservationStatus,
    assert_block_night,
    assert_function_space_hold,
    assert_group_contract,
    assert_instant_equals,
    assert_inventory_day,
    assert_nights_conserved,
    assert_reservation,
    assert_room_block,
    committed_rooms,
    constants as C,
    factories as F,
    held_rooms,
    master_block_of,
    night_on,
    read_block,
    read_nights,
    read_quote,
    seed_accepted_quote,
    seed_calendar_and_package,
    seed_cleared_lead,
    seed_draft_contract,
    seed_draft_quote,
    seed_function_space_hold,
    seed_lead,
    seed_proposed_quote,
    seed_reservation,
    seed_sent_contract,
    seed_signed_contract,
    seed_sub_block,
    set_clock,
    validate_success,
)


def _sent_world_with_space_hold(api):
    """A SENT 12-room-night contract whose lead still holds the ballroom.

    The meeting space is held while the lead is NEW so that the signature
    cascade of PRD 3.5 has a HELD booking to confirm; the accepted quote is
    holding 4 rooms on each of the three nights.
    """
    world = seed_calendar_and_package(api)
    lead = seed_lead(api, world["account_id"])
    world["lead_id"] = lead["id"]
    world["space_hold"] = seed_function_space_hold(api, lead["id"])
    world["lead"] = validate_success(api.qualify_lead(lead["id"], SALES_MANAGER))
    world["lead_version"] = world["lead"]["version"]
    seed_cleared_lead(api, world)
    seed_draft_quote(api, world)
    seed_proposed_quote(api, world)
    seed_accepted_quote(api, world)
    seed_draft_contract(api, world)
    seed_sent_contract(api, world)
    return world


def test_the_signature_mints_the_master_block_and_its_nights(api):
    """Countersigning stamps the contract and creates the block it implies.

    PRD 3.5: the signature "mints the master RoomBlock ... named MASTER with
    is_master true, inventory_status SETUP and billing_status UNBILLED, one
    BlockNight per nightly_allotments entry", and the block's cutoff_date is the
    arrival date less cutoff_days_before_arrival - 21 days before 2026-11-09.

    Design: Difficulty/transitive_cascade/contract_sign_cascade_four_hops_block_inventory_hold_and_function_space
    """
    world = _sent_world_with_space_hold(api)

    signed = validate_success(
        api.sign_contract(
            world["contract_id"], F.sign_payload(signature_name="R. Buyer"), CONTRACT_ADMIN
        )
    )

    assert_group_contract(
        signed,
        status=ContractStatus.SIGNED,
        signed_by_user_id=CONTRACT_ADMIN_ID,
        signature_name="R. Buyer",
        contracted_rate_cents=20880,
        nights_count=3,
    )
    assert_instant_equals(signed["signed_at"], C.CLOCK_DEFAULT, "signed_at")

    master = master_block_of(api, world["contract_id"])
    assert_room_block(
        master,
        is_master=True,
        name="MASTER",
        inventory_status=BlockInventoryStatus.SETUP,
        billing_status=BlockBillingStatus.UNBILLED,
        cutoff_date=C.CUTOFF_DATE,
        allotted_room_nights=12,
    )

    nights = read_nights(api, master["id"])
    assert len(nights) == 3, f"one BlockNight per allotment entry, got {nights}"
    assert_block_night(night_on(api, master["id"], "2026-11-09"), rooms_allotted=4, rooms_open=4)
    assert_block_night(night_on(api, master["id"], "2026-11-11"), rooms_allotted=4, rooms_open=4)
    assert_nights_conserved(nights)


def test_the_signature_swaps_the_soft_hold_for_a_firm_commitment(api):
    """The same signature moves the calendar and confirms the meeting space.

    PRD 3.5 commits the block's rooms - "committed_group_rooms rises by the
    allotment on each occupied date" - and releases the accepted quote's soft
    hold on those same dates, while the lead's HELD function space booking
    becomes CONFIRMED. The two calendar counters move in opposite directions on
    the same rows, so a half-run cascade shows up as a double count.

    Design: Difficulty/transitive_cascade/contract_sign_cascade_four_hops_block_inventory_hold_and_function_space
    """
    world = _sent_world_with_space_hold(api)
    assert held_rooms(api, C.STAY_DATES) == [4, 4, 4], "the accepted quote holds the rooms"

    validate_success(
        api.sign_contract(
            world["contract_id"], F.sign_payload(signature_name="R. Buyer"), CONTRACT_ADMIN
        )
    )

    assert committed_rooms(api, C.STAY_DATES) == [4, 4, 4]
    assert held_rooms(api, C.STAY_DATES) == [0, 0, 0]

    quote = read_quote(api, world["quote_id"])
    assert quote["status"] == QuoteStatus.ACCEPTED
    assert quote["hold_placed"] is False, "the firm commitment replaces the soft hold"

    assert_function_space_hold(
        validate_success(
            api.get_function_space_hold(world["space_hold"]["id"], SALES_MANAGER)
        ),
        status=HoldStatus.CONFIRMED,
    )


def _open_master_and_sub(api):
    """A master block of 4/4/4 with a 2+2 sub-block carved out, both OPEN, one
    PENDING rooming-list entry in each, and the clock standing exactly on the
    2026-10-19 cutoff date (PRD 3.6, PRD 3.7)."""
    world = seed_signed_contract(api)
    sub = seed_sub_block(
        api,
        world,
        name="S1 Executive Team",
        nightly_allotments=F.allotment_plan(("2026-11-09", 2), ("2026-11-10", 2)),
    )
    world["sub_block_id"] = sub["id"]
    validate_success(api.open_room_block(world["master_block_id"], RESERVATIONS_AGENT))
    validate_success(api.open_room_block(sub["id"], RESERVATIONS_AGENT))
    world["sub_reservation"] = seed_reservation(
        api,
        sub["id"],
        guest_name="Kay Antonelli",
        arrival_date="2026-11-09",
        departure_date="2026-11-10",
    )
    world["master_reservation"] = seed_reservation(
        api,
        world["master_block_id"],
        guest_name="Ada Lovelace",
        arrival_date="2026-11-09",
        departure_date="2026-11-12",
    )
    set_clock(api, C.CUTOFF_CLOCK)
    return world


def test_cutting_off_the_master_releases_the_sub_block_nights_too(api):
    """The cutoff walks the master, its sub-block and every night of both.

    PRD 3.7: cutting off the master "cuts off every OPEN sub-block of that
    master as well" and on each night sets "rooms_released to rooms_allotted
    less rooms_sub_allocated less rooms_picked_up, and rooms_open to zero".
    Rooms that were written onto a rooming list are never released, so the
    PENDING entries survive the cutoff untouched.

    Design: Difficulty/transitive_cascade/block_cutoff_cascade_four_hops_through_sub_block_to_inventory
    """
    world = _open_master_and_sub(api)

    cut = validate_success(api.cutoff_room_block(world["master_block_id"], RESERVATIONS_AGENT))

    assert_room_block(cut, inventory_status=BlockInventoryStatus.CUT_OFF)
    assert_room_block(
        read_block(api, world["sub_block_id"]),
        inventory_status=BlockInventoryStatus.CUT_OFF,
    )

    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-09"),
        rooms_sub_allocated=2,
        rooms_picked_up=1,
        rooms_released=1,
        rooms_open=0,
    )
    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-11"),
        rooms_released=3,
        rooms_open=0,
    )
    assert_block_night(
        night_on(api, world["sub_block_id"], "2026-11-09"),
        rooms_released=1,
        rooms_open=0,
    )
    assert_block_night(
        night_on(api, world["sub_block_id"], "2026-11-10"),
        rooms_released=2,
        rooms_open=0,
    )
    assert_nights_conserved(read_nights(api, world["master_block_id"]))
    assert_nights_conserved(read_nights(api, world["sub_block_id"]))

    for key in ("sub_reservation", "master_reservation"):
        assert_reservation(
            validate_success(
                api.get_reservation(world[key]["id"], RESERVATIONS_AGENT)
            ),
            status=ReservationStatus.PENDING,
        )


def test_only_the_masters_released_rooms_come_off_the_calendar(api):
    """Sub-block releases must not decrement the calendar a second time.

    PRD 3.7 decrements committed_group_rooms by the master's released rooms
    alone, because a sub-block's rooms were already carved out of the master's
    allotment: 2026-11-09 and 2026-11-10 keep 3 committed rooms and 2026-11-11
    keeps 1, and the block rollups report the release and pickup totals of each
    block separately.

    Design: Difficulty/transitive_cascade/block_cutoff_cascade_four_hops_through_sub_block_to_inventory
    """
    world = _open_master_and_sub(api)

    cut = validate_success(api.cutoff_room_block(world["master_block_id"], RESERVATIONS_AGENT))

    assert_room_block(
        cut, released_room_nights=5, picked_up_room_nights=4, peak_night_rooms=1
    )
    assert_room_block(
        read_block(api, world["sub_block_id"]),
        released_room_nights=3,
        picked_up_room_nights=1,
    )
    assert committed_rooms(api, C.STAY_DATES) == [3, 3, 1], (
        "only the master's released rooms return to the house"
    )
