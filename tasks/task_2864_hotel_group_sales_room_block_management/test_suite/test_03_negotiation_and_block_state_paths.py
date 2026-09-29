"""Non-linear state paths: a lead that re-enters a state, a block with two axes.

PRD 3.4 sends a lead back for a fresh displacement study whenever a revise
grows the peak-room count, and PRD 3.6 gives RoomBlock two independent status
dimensions that advance at different rates.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    REVENUE_MANAGER,
    REVENUE_MANAGER_ID,
    SALES_MANAGER,
    AnalysisStatus,
    AnalysisVariant,
    BlockBillingStatus,
    BlockInventoryStatus,
    ContractStatus,
    LeadStatus,
    QuoteStatus,
    assert_displacement_analysis,
    assert_group_contract,
    assert_lead,
    assert_rate_quote,
    assert_receivable_identity,
    assert_reconciliation,
    assert_room_block,
    confirm_reservations,
    constants as C,
    decide_displacement_analysis,
    factories as F,
    held_rooms,
    read_block,
    read_contract,
    read_lead,
    read_quote,
    seed_ancillary_charge,
    seed_cut_off_master,
    seed_displacement_analysis,
    seed_draft_reconciliation,
    seed_finalized_reconciliation,
    seed_open_master_block,
    seed_proposed_quote,
    seed_reservations,
    validate_success,
)

_PICKUP_PATTERN = (
    {
        "guest_name": "Ada Lovelace",
        "arrival_date": "2026-11-09",
        "departure_date": "2026-11-12",
    },
    {
        "guest_name": "Grace Hopper",
        "arrival_date": "2026-11-09",
        "departure_date": "2026-11-10",
    },
    {
        "guest_name": "Alan Turing",
        "arrival_date": "2026-11-10",
        "departure_date": "2026-11-11",
    },
)


def _countered_then_grown(api):
    """A PROPOSED 4-room quote countered by the client and then revised upward
    to 5 peak rooms and 15 room nights (PRD 3.4)."""
    world = seed_proposed_quote(api)
    validate_success(
        api.counter_rate_quote(
            world["quote_id"],
            F.counter_payload(
                countered_base_rate_cents=22500,
                counter_note="Board wants a lower rate and one more suite",
            ),
            world["group_contact"],
        )
    )
    world["quote"] = validate_success(
        api.revise_rate_quote(
            world["quote_id"],
            F.revise_payload(
                base_rate_cents=23950, quoted_peak_rooms=5, quoted_room_nights=15
            ),
            SALES_MANAGER,
        )
    )
    return world


def test_growing_the_peak_rooms_sends_the_lead_back_for_a_new_study(api):
    """A revise that grows the peak night invalidates the clearance.

    PRD 3.4: "If quoted_peak_rooms strictly increases, the previous
    displacement clearance no longer covers the program: the quote falls back
    to DRAFT, the inventory hold is released, and the lead moves QUOTED to
    DISPLACEMENT_REVIEW." The lead therefore re-enters a state it had already
    left, and the rooms leave held_group_rooms on every occupied date.

    Design: Difficulty/non_linear_state_machine/lead_cycles_back_to_displacement_review_on_peak_increase
    """
    world = _countered_then_grown(api)

    assert_rate_quote(
        world["quote"], status=QuoteStatus.DRAFT, hold_placed=False
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.DISPLACEMENT_REVIEW)
    assert held_rooms(api, C.STAY_DATES) == [0, 0, 0], (
        "the released hold must leave the calendar on every occupied date"
    )


def test_the_second_clearance_re_proposes_the_larger_quote(api):
    """A second approved study lets the grown quote hold its new size.

    PRD 3.3 clears the lead again on approval and PRD 3.4 re-places the hold on
    propose, this time for the 5 quoted peak rooms; the re-priced quote values
    15 room nights at the unchanged 20880-cent effective rate, and the first
    approval is not undone by the loop.

    Design: Difficulty/non_linear_state_machine/lead_cycles_back_to_displacement_review_on_peak_increase
    """
    world = _countered_then_grown(api)
    first_analysis_id = world["analysis_id"]

    second = seed_displacement_analysis(
        api, world, analysis_variant=AnalysisVariant.FORECAST_BASED
    )
    decided = decide_displacement_analysis(api, world, second["id"])

    assert_displacement_analysis(decided, status=AnalysisStatus.APPROVED)
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.CLEARED)

    reproposed = validate_success(
        api.propose_rate_quote(world["quote_id"], SALES_MANAGER)
    )

    assert_rate_quote(
        reproposed,
        status=QuoteStatus.PROPOSED,
        hold_placed=True,
        quoted_peak_rooms=5,
        quoted_room_nights=15,
        effective_net_rate_cents=20880,
        total_quote_value_cents=313200,
    )
    assert_lead(read_lead(api, world["lead_id"]), status=LeadStatus.QUOTED)
    assert held_rooms(api, C.STAY_DATES) == [5, 5, 5]
    assert (
        validate_success(api.get_displacement_analysis(first_analysis_id, REVENUE_MANAGER))[
            "status"
        ]
        == AnalysisStatus.APPROVED
    ), "the earlier approval survives the loop"


_WAIVER_REASON = "Client rebooked 2027 in exchange for the shortfall"


def _post_event_block(api):
    """A cut-off master block with 5 actualized room nights and one POSTED
    banquet charge, the clock standing past departure (PRD 3.7, 3.8)."""
    world = seed_open_master_block(api)
    rows = seed_reservations(api, world["master_block_id"], _PICKUP_PATTERN)
    confirm_reservations(api, [row["id"] for row in rows])
    seed_ancillary_charge(
        api, world["contract_id"], gross_amount_cents=500000, post=True
    )
    seed_cut_off_master(api, world, at_clock=C.POST_DEPARTURE_CLOCK)
    return world


def test_cutoff_moves_only_the_inventory_axis_and_settlement_only_the_billing_axis(api):
    """The block's two status dimensions advance one at a time.

    PRD 3.6 gives RoomBlock an inventory_status and a billing_status that "move
    independently"; cutting off releases unsold rooms and moves
    OPEN to CUT_OFF while billing stays UNBILLED, and opening the settlement of
    PRD 3.9 moves UNBILLED to ATTRITION_ASSESSED with the inventory dimension
    untouched.

    Design: Difficulty/non_linear_state_machine/room_block_parallel_dimensions_advance_independently
    """
    world = _post_event_block(api)

    assert_room_block(
        world["master_block"],
        inventory_status=BlockInventoryStatus.CUT_OFF,
        billing_status=BlockBillingStatus.UNBILLED,
    )

    seed_draft_reconciliation(api, world, at_clock=None)

    assert_reconciliation(world["reconciliation"], attrition_damages_cents=70992)
    assert_room_block(
        read_block(api, world["master_block_id"]),
        inventory_status=BlockInventoryStatus.CUT_OFF,
        billing_status=BlockBillingStatus.ATTRITION_ASSESSED,
    )


def test_the_waiver_re_derives_the_draft_settlement_and_finalize_moves_both_axes(api):
    """Waiving attrition zeroes the damages; only finalize closes both axes.

    PRD 3.6: the waiver moves billing_status ATTRITION_ASSESSED to WAIVED and
    "the DRAFT settlement is re-derived with zero attrition damages", leaving
    the inventory dimension at CUT_OFF; PRD 3.9 then finalizes, and only that
    act advances the block to CLOSED and SETTLED together while the contract
    completes with no assessed damages.

    Design: Difficulty/non_linear_state_machine/room_block_parallel_dimensions_advance_independently
    """
    world = _post_event_block(api)
    seed_draft_reconciliation(api, world, at_clock=None)

    waived = validate_success(
        api.waive_attrition(
            world["master_block_id"],
            F.waive_attrition_payload(waiver_reason=_WAIVER_REASON),
            REVENUE_MANAGER,
        )
    )

    assert_room_block(
        waived,
        inventory_status=BlockInventoryStatus.CUT_OFF,
        billing_status=BlockBillingStatus.WAIVED,
        waiver_reason=_WAIVER_REASON,
        waived_by_user_id=REVENUE_MANAGER_ID,
    )

    redrawn = validate_success(
        api.get_reconciliation(world["reconciliation_id"], ACCOUNTING_CLERK)
    )
    assert_reconciliation(
        redrawn, attrition_damages_cents=0, total_settlement_cents=441787
    )

    seed_finalized_reconciliation(api, world)

    assert_room_block(
        read_block(api, world["master_block_id"]),
        inventory_status=BlockInventoryStatus.CLOSED,
        billing_status=BlockBillingStatus.SETTLED,
    )
    contract = read_contract(api, world["contract_id"])
    assert_group_contract(
        contract,
        status=ContractStatus.COMPLETED,
        assessed_damages_cents=0,
        rebate_paid_cents=3750,
        receivable_total_cents=446250,
    )
    assert_receivable_identity(contract)
