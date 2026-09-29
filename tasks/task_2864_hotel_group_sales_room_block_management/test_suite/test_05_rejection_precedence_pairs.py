"""Rejection precedence: which of two live rules answers a doubly bad request.

PRD 2.8 fixes a single global order for every rejection, so a request that
breaks two rules at once must be answered by the earlier one; each test also
replays the request with the earlier rule satisfied, proving the later rule was
live all along.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    CONTRACT_ADMIN,
    RESERVATIONS_AGENT,
    ApiErrorId,
    BlockBillingStatus,
    BlockInventoryStatus,
    ContractStatus,
    assert_block_night,
    assert_group_contract,
    assert_rate_quote,
    assert_room_block,
    constants as C,
    contract_version,
    factories as F,
    night_on,
    read_block,
    read_contract,
    read_quote,
    seed_accepted_quote,
    seed_calendar_and_package,
    seed_cleared_lead,
    seed_draft_contract,
    seed_draft_quote,
    seed_open_master_block,
    seed_proposed_quote,
    seed_qualified_lead,
    seed_sent_contract,
    seed_signed_contract,
    seed_sub_block,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

_SINGLE_NIGHT = ["2026-11-09"]
_RESERVATION = {
    "guest_name": "Ada Lovelace",
    "arrival_date": "2026-11-09",
    "departure_date": "2026-11-10",
}


def _fully_carved_master(api):
    """A one-room programme whose only night is entirely carved into a
    sub-block while the master block is still SETUP, so a rooming-list write
    breaks the state rule and the capacity rule at the same time."""
    world = seed_calendar_and_package(
        api,
        stay_dates=_SINGLE_NIGHT,
        package=F.small_meetings_package_payload(),
        account={
            "name": "Vector Robotics",
            "billing_contact_email": "ap@vector.example",
        },
    )
    world = seed_qualified_lead(
        api,
        world,
        lead={
            "program_name": "Vector Board Retreat",
            "arrival_date": "2026-11-09",
            "departure_date": "2026-11-10",
            "peak_rooms": 1,
            "total_requested_room_nights": 1,
            "meeting_space_sqft_needed": 30,
        },
    )
    seed_cleared_lead(api, world)
    seed_draft_quote(
        api,
        world,
        quote={
            "base_rate_cents": 20000,
            "quoted_peak_rooms": 1,
            "quoted_room_nights": 1,
        },
    )
    seed_proposed_quote(api, world)
    seed_accepted_quote(api, world)
    seed_draft_contract(
        api,
        world,
        contract={
            "contracted_room_nights": 1,
            "contracted_peak_rooms": 1,
            "nightly_allotments": F.allotment_plan(("2026-11-09", 1)),
        },
    )
    seed_sent_contract(api, world)
    seed_signed_contract(api, world, signature_name="V. Chen")
    world["sub_block"] = seed_sub_block(
        api,
        world,
        name="S1 Directors",
        nightly_allotments=F.allotment_plan(("2026-11-09", 1)),
    )
    return world


def test_a_closed_block_is_refused_before_its_capacity_is_examined(api):
    """The block-state rule outranks the allotment-capacity rule.

    PRD 2.8 places ERR_BLOCK_NOT_OPEN at priority 12 and
    ERR_BLOCK_ALLOTMENT_EXCEEDED at priority 29, so a write into a block that is
    still SETUP and already has no open rooms must be answered by the state
    rule; an implementation that counts rooms first answers the wrong error.

    Design: Difficulty/priority_pair_validation_conflict/block_not_open_outranks_block_allotment_exceeded
    """
    world = _fully_carved_master(api)

    response = api.create_reservation(
        F.reservation_payload(world["master_block_id"], **_RESERVATION),
        RESERVATIONS_AGENT,
    )

    validate_error(response, ApiErrorId.BLOCK_NOT_OPEN, 409)
    assert (
        response.json()["data"]["error_id"] != ApiErrorId.BLOCK_ALLOTMENT_EXCEEDED
    ), "the capacity rule sits below the state rule in the order"

    _, meta = validate_paginated(
        api.list_block_reservations(world["master_block_id"], RESERVATIONS_AGENT)
    )
    assert meta["total_count"] == 0, "a rejected write must persist nothing"


def test_the_capacity_rule_answers_once_the_block_is_open(api):
    """With the earlier rule satisfied the later rule refuses the same payload.

    PRD 3.6 admits a rooming-list entry only while "rooms_open on every night of
    the stay is at least one"; the single contracted room is entirely
    sub-allocated, so the identical payload now fails on capacity and the night
    keeps its carved room.

    Design: Difficulty/priority_pair_validation_conflict/block_not_open_outranks_block_allotment_exceeded
    """
    world = _fully_carved_master(api)
    payload = F.reservation_payload(world["master_block_id"], **_RESERVATION)

    validate_error(
        api.create_reservation(payload, RESERVATIONS_AGENT),
        ApiErrorId.BLOCK_NOT_OPEN,
        409,
    )
    opened = validate_success(
        api.open_room_block(world["master_block_id"], RESERVATIONS_AGENT)
    )
    assert_room_block(opened, inventory_status=BlockInventoryStatus.OPEN)

    validate_error(
        api.create_reservation(payload, RESERVATIONS_AGENT),
        ApiErrorId.BLOCK_ALLOTMENT_EXCEEDED,
        409,
    )

    assert_block_night(
        night_on(api, world["master_block_id"], "2026-11-09"),
        rooms_sub_allocated=1,
        rooms_picked_up=0,
        rooms_open=0,
    )
    assert_rate_quote(read_quote(api, world["quote_id"]), effective_net_rate_cents=15167)


def test_a_settlement_opened_before_the_event_ends_is_refused_on_the_calendar(api):
    """The temporal rule outranks the referential block-state rule.

    PRD 2.8 places ERR_EVENT_NOT_CONCLUDED at priority 17 and
    ERR_BLOCKS_NOT_CUT_OFF at priority 22. Opening a settlement on 2026-08-01
    against a contract whose master block is still OPEN breaks both, and the
    order requires the 422 about the event still being in the future.

    Design: Difficulty/priority_pair_validation_conflict/event_not_concluded_outranks_blocks_not_cut_off
    """
    world = seed_open_master_block(api)
    payload = F.reconciliation_payload(contract_version(api, world["contract_id"]))

    response = api.create_reconciliation(world["contract_id"], payload, ACCOUNTING_CLERK)

    validate_error(response, ApiErrorId.EVENT_NOT_CONCLUDED, 422)
    assert (
        response.json()["data"]["error_id"] != ApiErrorId.BLOCKS_NOT_CUT_OFF
    ), "the block-state rule sits below the temporal rule in the order"


def test_the_block_state_rule_answers_once_the_event_is_over(api):
    """After the departure date the same payload fails on the open block.

    PRD 3.9 requires that "every RoomBlock of the contract is CUT_OFF or CLOSED"
    before a settlement may be opened; with the clock past 2026-11-12 the
    byte-identical payload is refused with the 409, no settlement row exists,
    and neither the contract nor the block has moved.

    Design: Difficulty/priority_pair_validation_conflict/event_not_concluded_outranks_blocks_not_cut_off
    """
    world = seed_open_master_block(api)
    version_before = contract_version(api, world["contract_id"])
    payload = F.reconciliation_payload(version_before)

    validate_error(
        api.create_reconciliation(world["contract_id"], payload, ACCOUNTING_CLERK),
        ApiErrorId.EVENT_NOT_CONCLUDED,
        422,
    )

    set_clock(api, C.POST_DEPARTURE_CLOCK)

    validate_error(
        api.create_reconciliation(world["contract_id"], payload, ACCOUNTING_CLERK),
        ApiErrorId.BLOCKS_NOT_CUT_OFF,
        409,
    )

    _, meta = validate_paginated(
        api.list_contract_reconciliations(world["contract_id"], ACCOUNTING_CLERK)
    )
    assert meta["total_count"] == 0, "neither rejection may leave a settlement behind"
    assert_group_contract(
        read_contract(api, world["contract_id"]),
        status=ContractStatus.SIGNED,
        version=version_before,
    )
    assert_room_block(
        read_block(api, world["master_block_id"]),
        inventory_status=BlockInventoryStatus.OPEN,
        billing_status=BlockBillingStatus.UNBILLED,
    )
