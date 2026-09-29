"""Inclusive thresholds: the qualification floor and the attrition commitment.

PRD 3.2 qualifies a lead whose score reaches the floor, and PRD 3.7 bills
attrition only when the actualized pickup falls short of the commitment, both
comparisons inclusive at the boundary.
"""

from test_helpers import (
    RESERVATIONS_AGENT,
    REVENUE_MANAGER,
    SALES_MANAGER,
    HoldStatus,
    LeadStatus,
    MarketSegment,
    ReconciliationStatus,
    SpaceCode,
    assert_function_space_hold,
    assert_lead,
    assert_pickup_summary,
    assert_reconciliation,
    confirm_reservations,
    constants as C,
    factories as F,
    pickup_summary,
    read_lead,
    seed_calendar_and_package,
    seed_cut_off_master,
    seed_draft_reconciliation,
    seed_function_space_hold,
    seed_lead,
    seed_open_master_block,
    seed_reservation,
    seed_reservations,
    validate_success,
)

_ASSOCIATION_ACCOUNT = {
    "name": "Pacific Educators Association",
    "market_segment": MarketSegment.ASSOCIATION,
    "billing_contact_email": "ap@pea.example",
}


def _two_association_leads(api):
    """Two ASSOCIATION leads differing only in requested room nights, 90 versus
    80, so the segment multiplier of 1.00 leaves the additive score visible; the
    smaller lead also holds meeting space (PRD 3.2)."""
    world = seed_calendar_and_package(api, account=_ASSOCIATION_ACCOUNT)
    world["lead_a"] = seed_lead(
        api,
        world["account_id"],
        program_name="PEA Annual Congress",
        total_requested_room_nights=90,
        meeting_space_sqft_needed=200,
    )
    world["lead_b"] = seed_lead(
        api,
        world["account_id"],
        program_name="PEA Regional Forum",
        total_requested_room_nights=80,
        meeting_space_sqft_needed=200,
    )
    world["hold_b"] = seed_function_space_hold(
        api,
        world["lead_b"]["id"],
        space_code=SpaceCode.SALON_A,
        start_at="2026-11-09T13:00:00Z",
        end_at="2026-11-09T15:00:00Z",
        attendee_count=40,
    )
    return world


def test_a_score_exactly_at_the_floor_qualifies(api):
    """The qualification floor is inclusive.

    PRD 3.2 qualifies the lead when the score "is greater than or equal to 30";
    12 lead-time points, 1 peak-room point, 8 space-ratio points and 9
    room-night points give exactly 30 for this ASSOCIATION programme, whose
    1.00 multiplier leaves the raw total untouched.

    Design: Difficulty/boundary_precision_check/qualification_score_exactly_at_floor_qualifies_one_below_turns_down
    """
    world = _two_association_leads(api)

    qualified = validate_success(api.qualify_lead(world["lead_a"]["id"], SALES_MANAGER))

    assert_lead(
        qualified,
        qualification_score=30,
        status=LeadStatus.QUALIFIED,
        estimated_room_night_value_cents=1549800,
        nights_count=3,
    )


def test_one_point_below_the_floor_turns_the_lead_down_and_frees_its_space(api):
    """A single point below the floor takes the other branch of the fork.

    PRD 3.2 turns the lead down below the floor and "releases every HELD
    FunctionSpaceHold of that lead"; ten fewer requested room nights cost one
    point, so the sibling lead scores 29 and loses its salon.

    Design: Difficulty/boundary_precision_check/qualification_score_exactly_at_floor_qualifies_one_below_turns_down
    """
    world = _two_association_leads(api)

    qualified = validate_success(api.qualify_lead(world["lead_a"]["id"], SALES_MANAGER))
    turned_down = validate_success(api.qualify_lead(world["lead_b"]["id"], SALES_MANAGER))

    assert_lead(
        turned_down,
        qualification_score=29,
        status=LeadStatus.TURNED_DOWN,
        estimated_room_night_value_cents=1377600,
        nights_count=3,
    )
    assert (
        qualified["qualification_score"] - turned_down["qualification_score"] == 1
    ), "the two leads must sit one point apart across the floor"
    assert_function_space_hold(
        validate_success(
            api.get_function_space_hold(world["hold_b"]["id"], SALES_MANAGER)
        ),
        status=HoldStatus.RELEASED,
    )


_EIGHT_ROOM_NIGHTS = (
    {
        "guest_name": "Ada Lovelace",
        "arrival_date": "2026-11-09",
        "departure_date": "2026-11-12",
    },
    {
        "guest_name": "Grace Hopper",
        "arrival_date": "2026-11-09",
        "departure_date": "2026-11-12",
    },
    {
        "guest_name": "Alan Turing",
        "arrival_date": "2026-11-09",
        "departure_date": "2026-11-11",
    },
)


def _block_at_eight_room_nights(api):
    """An OPEN master block of 4/4/4 carrying 8 CONFIRMED room nights against a
    12-room-night commitment, one short of the 0.75 threshold (PRD 3.7)."""
    world = seed_open_master_block(api)
    rows = seed_reservations(api, world["master_block_id"], _EIGHT_ROOM_NIGHTS)
    confirm_reservations(api, [row["id"] for row in rows])
    return world


def test_one_room_night_short_of_the_commitment_is_billed(api):
    """A shortfall of one room night is priced, proving the threshold is live.

    PRD 3.7 sets the commitment at the ceiling of the commitment base times
    attrition_threshold_pct - ceil(12 x 0.75) is 9 - and prices each missing
    room night at the contracted rate times the 0.85 damage factor, so 8
    actualized room nights owe 17748 cents.

    Design: Difficulty/boundary_precision_check/attrition_actualized_exactly_at_commitment_yields_zero_damages
    """
    world = _block_at_eight_room_nights(api)

    summary = pickup_summary(api, world["master_block_id"])

    assert_pickup_summary(
        summary,
        commitment_base_room_nights=12,
        picked_up_room_nights=8,
        room_nights_basis_shortfall=1,
        room_nights_basis_damages_cents=17748,
    )


def test_pickup_exactly_at_the_commitment_owes_nothing(api):
    """Reaching the commitment exactly leaves no damages anywhere.

    PRD 3.7 bills only the room nights by which the actualized pickup falls
    below the commitment, so the ninth room night takes the shortfall to zero;
    the settlement of PRD 3.9 then reports no damages, no earned rebate against
    a zero gross, and a zero total.

    Design: Difficulty/boundary_precision_check/attrition_actualized_exactly_at_commitment_yields_zero_damages
    """
    world = _block_at_eight_room_nights(api)

    ninth = seed_reservation(
        api,
        world["master_block_id"],
        guest_name="Katherine Johnson",
        arrival_date="2026-11-11",
        departure_date="2026-11-12",
    )
    confirm_reservations(api, [ninth["id"]])

    summary = pickup_summary(api, world["master_block_id"])
    assert_pickup_summary(
        summary,
        picked_up_room_nights=9,
        room_nights_basis_shortfall=0,
        room_nights_basis_damages_cents=0,
    )

    seed_cut_off_master(api, world, at_clock=C.POST_DEPARTURE_CLOCK)
    seed_draft_reconciliation(api, world, at_clock=None)

    assert_reconciliation(
        world["reconciliation"],
        actualized_room_nights=9,
        billable_room_nights=9,
        attrition_shortfall_room_nights=0,
        attrition_damages_cents=0,
        gross_settlement_cents=0,
        rebate_payable_cents=0,
        total_settlement_cents=0,
        status=ReconciliationStatus.DRAFT,
    )
