"""Pinned arithmetic: the rate components and the settlement waterfall.

PRD 3.4 fixes the order in which the effective net rate's components are
rounded, and PRD 3.9 fixes the six steps of the settlement and the step whose
result the rebooking incentive is keyed on.
"""

from test_helpers import (
    ACCOUNTING_CLERK,
    SALES_MANAGER,
    BlockBillingStatus,
    ChargeCategory,
    ChargeStatus,
    QuoteStatus,
    ReconciliationStatus,
    assert_ancillary_charge,
    assert_concession_package,
    assert_rate_quote,
    assert_reconciliation,
    assert_room_block,
    assert_waterfall_identities,
    confirm_reservations,
    constants as C,
    factories as F,
    read_block,
    seed_ancillary_charge,
    seed_cleared_lead,
    seed_cut_off_master,
    seed_draft_reconciliation,
    seed_open_master_block,
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


def _quote_on_cleared_lead(api):
    """A cleared lead priced at 23950 cents off the 0.0725 / 40-room package."""
    world = seed_cleared_lead(api)
    world["quote"] = validate_success(
        api.create_rate_quote(
            F.rate_quote_payload(
                world["lead_id"],
                world["package_id"],
                world["lead_version"],
                base_rate_cents=23950,
                quoted_peak_rooms=4,
                quoted_room_nights=12,
            ),
            SALES_MANAGER,
        ),
        201,
    )
    world["quote_id"] = world["quote"]["id"]
    return world


def test_each_rate_component_is_rounded_before_it_is_subtracted(api):
    """The discount and the comp credit are each rounded, then subtracted.

    PRD 3.4: "Each component is computed and rounded to whole cents
    independently, and only then subtracted." 23950 x 0.0725 is 1736.375 cents
    and rounds to 1736, while 23950 / (40 + 1) is 584.146 cents and rounds to
    584, leaving 20880 - one cent above the 20879 that a single rounding at the
    end would produce, and 12 cents of divergence on the 12-night total.

    Design: Difficulty/combinatorial_formula/effective_net_rate_component_rounding_order
    """
    world = _quote_on_cleared_lead(api)

    assert_rate_quote(
        world["quote"],
        effective_net_rate_cents=20880,
        total_quote_value_cents=250560,
    )
    assert world["quote"]["effective_net_rate_cents"] != 20879, (
        "rounding the whole expression once at the end would lose a cent"
    )


def test_the_quote_snapshots_the_package_components_it_priced_with(api):
    """The quote freezes the concession terms and opens in DRAFT without a hold.

    PRD 3.4: "The quote starts in DRAFT with negotiation_round at 1,
    hold_placed false"; the package's four discounts sum to the
    discount_stack_pct that the eligibility ceiling is checked against, and the
    comp ratio and rebate are copied onto the quote so later re-pricing reads
    the same components.

    Design: Difficulty/combinatorial_formula/effective_net_rate_component_rounding_order
    """
    world = _quote_on_cleared_lead(api)

    assert_concession_package(world["package"], discount_stack_pct=0.3725)
    assert_rate_quote(
        world["quote"],
        comp_room_ratio=40,
        rebate_per_room_night_cents=750,
        status=QuoteStatus.DRAFT,
        negotiation_round=1,
        hold_placed=False,
    )


def _settlement_world(api):
    """The full post-event position: 5 actualized room nights against a 12-room
    -night commitment, one POSTED banquet charge, one still-QUOTED audiovisual
    charge, the block cut off and the clock past departure (PRD 3.7, 3.8)."""
    world = seed_open_master_block(api)
    rows = seed_reservations(api, world["master_block_id"], _PICKUP_PATTERN)
    confirm_reservations(api, [row["id"] for row in rows])
    world["banquet"] = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.BANQUET,
        gross_amount_cents=500000,
        post=True,
    )
    world["audiovisual"] = seed_ancillary_charge(
        api,
        world["contract_id"],
        category=ChargeCategory.AUDIOVISUAL,
        gross_amount_cents=200000,
    )
    seed_cut_off_master(api, world, at_clock=C.POST_DEPARTURE_CLOCK)
    return seed_draft_reconciliation(api, world, at_clock=None)


def test_the_incentive_rate_is_keyed_on_the_net_before_the_incentive(api):
    """The six settlement steps run in order and step 4 reads step 3's result.

    PRD 3.9 nets the earned rebate off the gross settlement in step 3 and then
    applies the rebooking incentive to that net_before_incentive_cents: damages
    70992 plus posted ancillary 450000 give a gross of 520992, the 3750-cent
    earned rebate leaves 517242, and the brand-new account's base 0.01 tier
    yields a 5172-cent incentive for a 512070-cent total. Keying the rate on
    the total, or netting the rebate after the incentive, lands elsewhere.

    Design: Difficulty/combinatorial_formula/settlement_waterfall_six_step_order_with_incentive_keyed_on_step_three
    """
    world = _settlement_world(api)

    assert_reconciliation(
        world["reconciliation"],
        actualized_room_nights=5,
        billable_room_nights=5,
        attrition_shortfall_room_nights=4,
        attrition_damages_cents=70992,
        ancillary_net_cents=450000,
        gross_settlement_cents=520992,
        rebate_payable_cents=3750,
        net_before_incentive_cents=517242,
        incentive_rate_snapshot=0.01,
        rebooking_incentive_cents=5172,
        total_settlement_cents=512070,
        status=ReconciliationStatus.DRAFT,
    )
    assert_waterfall_identities(world["reconciliation"])


def test_only_posted_ancillary_revenue_enters_the_waterfall(api):
    """A charge that was never posted stays out of the settlement.

    PRD 3.9 sums "the net_amount_cents of the contract's POSTED ancillary
    charges", so the 170000-cent audiovisual charge left QUOTED is excluded
    while the discounted banquet charge is included, and opening the settlement
    moves the block's billing dimension to ATTRITION_ASSESSED (PRD 3.6).

    Design: Difficulty/combinatorial_formula/settlement_waterfall_six_step_order_with_incentive_keyed_on_step_three
    """
    world = _settlement_world(api)

    assert_ancillary_charge(
        world["banquet"], discount_pct=0.10, net_amount_cents=450000
    )
    assert_ancillary_charge(
        world["audiovisual"],
        net_amount_cents=170000,
        status=ChargeStatus.QUOTED,
    )
    assert world["reconciliation"]["ancillary_net_cents"] == 450000, (
        "a QUOTED charge must not reach the settlement"
    )
    assert_room_block(
        read_block(api, world["master_block_id"]),
        billing_status=BlockBillingStatus.ATTRITION_ASSESSED,
    )
