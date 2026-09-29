"""Six-step lot settlement and its reversal (PRD §3.8).

Three properties of the settlement arithmetic are pinned here: the surcharge is
rounded half-up exactly once per lot, before the lot total enters the lease
ledger; the royalty tier is keyed on the season total *including* the lot being
landed, on a whole-total basis; and voiding a lot subtracts exactly that lot's
own settlement without re-tiering any surviving sibling.
"""
from test_helpers import (
    api_client,
    assert_lot_settlement_consistent,
    design_world,
    dw_land_lot,
    DW_HARVEST_CLOCK,
    get_success_data,
    INSPECTION_FEE_CENTS,
    INSPECTION_FEE_WAIVER_CENTS,
    set_clock,
    TEST_USERS,
    TIER1_RATE_CENTS,
    TIER2_RATE_CENTS,
    validate_success,
    void_payload,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]


def _lease(world):
    return get_success_data(api_client.get_lease(world["lease"]["id"], AUTHORITY))


def _authorization(world):
    return get_success_data(api_client.get_harvest_authorization(
        world["authorization"]["id"], OPERATOR))


def _lot(lot_id):
    return get_success_data(api_client.get_harvest_lot(lot_id, OPERATOR))


# --------------------------------------------------------------------------
# The surcharge is rounded once per lot, not once over the sum
# --------------------------------------------------------------------------
def _two_identical_ten_bushel_lots():
    world = design_world(stage="active")
    # The reference harvest instants run to 10:30; the clock must stand at the
    # reference harvest clock (11:00) or the landing is future-dated (PRD §2.5).
    set_clock(DW_HARVEST_CLOCK)
    world["lot1"] = dw_land_lot(world, lot_code="LOT-001")
    world["lot2"] = dw_land_lot(world, lot_code="LOT-002")
    return world


def test_each_ten_bushel_lot_settles_at_three_thousand_seven_hundred_sixty_cents():
    """Both lots reach a season total inside `TIER1_MAX_BUSHELS` 500, so both are
    rated at 115 cents per bushel: royalty 1150, an inspection fee of 2500
    because 1150 is below the 50 000-cent waiver, a surcharge of half-up
    (0.03 x 3650) = 110, and a settlement of 3760. Only
    `season_total_bushels_at_creation` distinguishes them -- 10 for the first
    lot and 20 for the second, because the total includes the lot being landed.

    Design: Difficulty/combinatorial_formula/surcharge_rounds_per_lot_before_accrual_sum
    """
    world = _two_identical_ten_bushel_lots()

    for lot, season_total in ((world["lot1"], 10), (world["lot2"], 20)):
        assert lot["season_total_bushels_at_creation"] == season_total
        assert lot["royalty_rate_cents_per_bushel"] == TIER1_RATE_CENTS
        assert lot["royalty_cents"] == 1150
        assert lot["inspection_fee_cents"] == INSPECTION_FEE_CENTS
        assert lot["conservation_surcharge_cents"] == 110
        assert lot["lot_settlement_cents"] == 3760
        assert_lot_settlement_consistent(lot)


def test_the_lease_ledger_sums_two_rounded_surcharges_not_one_rounded_sum():
    """Rounding order is observable to the cent. Two 110-cent surcharges accrue
    to 7520; rounding a single summed 7300-cent base instead would give a
    219-cent surcharge and a lease total of 7519. The authorization's
    `harvested_bushels` reaches 20.

    Design: Difficulty/combinatorial_formula/surcharge_rounds_per_lot_before_accrual_sum
    """
    world = _two_identical_ten_bushel_lots()

    lease = _lease(world)

    assert lease["royalty_accrued_cents"] == 7520
    assert lease["royalty_accrued_cents"] != 7519
    assert _authorization(world)["harvested_bushels"] == 20


# --------------------------------------------------------------------------
# The tier is keyed on the season total including the current lot
# --------------------------------------------------------------------------
def _five_hundred_bushels_then_one_more():
    world = design_world(stage="active")
    # The reference harvest instants run to 10:30; the clock must stand at the
    # reference harvest clock (11:00) or the landing is future-dated (PRD §2.5).
    set_clock(DW_HARVEST_CLOCK)
    world["lot_big"] = dw_land_lot(world, lot_code="LOT-BIG", bushels=500)
    world["lot_edge"] = dw_land_lot(world, lot_code="LOT-EDGE", bushels=1)
    return world


def test_a_one_bushel_lot_is_priced_by_the_season_total_it_pushes_over_the_tier():
    """`TIER1_MAX_BUSHELS` 500 is inclusive, so the 500-bushel lot is rated at
    115 with the inspection fee waived because its 57 500-cent royalty clears the
    50 000-cent waiver. The following one-bushel lot brings the season total to
    501 and is therefore rated at `TIER2_RATE_CENTS` 95 -- not the 115 its own
    volume would suggest -- and its own 95-cent royalty does not clear the
    waiver, so it pays the flat 2500 fee.

    Design: Difficulty/combinatorial_formula/royalty_tier_keyed_on_season_total_including_current_lot
    """
    world = _five_hundred_bushels_then_one_more()
    big, edge = world["lot_big"], world["lot_edge"]

    assert big["season_total_bushels_at_creation"] == 500
    assert big["royalty_rate_cents_per_bushel"] == TIER1_RATE_CENTS
    assert big["royalty_cents"] == 57500
    assert big["royalty_cents"] >= INSPECTION_FEE_WAIVER_CENTS
    assert big["inspection_fee_cents"] == 0
    assert big["conservation_surcharge_cents"] == 1725
    assert big["lot_settlement_cents"] == 59225

    assert edge["season_total_bushels_at_creation"] == 501
    assert edge["royalty_rate_cents_per_bushel"] == TIER2_RATE_CENTS
    assert edge["royalty_rate_cents_per_bushel"] != TIER1_RATE_CENTS
    assert edge["royalty_cents"] == 95
    assert edge["inspection_fee_cents"] == INSPECTION_FEE_CENTS
    assert edge["conservation_surcharge_cents"] == 78
    assert edge["lot_settlement_cents"] == 2673
    assert_lot_settlement_consistent(edge)


def test_crossing_the_tier_boundary_never_re_rates_the_earlier_lot():
    """The rate is stamped per lot at landing and never recomputed, so the
    500-bushel lot still reads 115 after the second landing has moved the season
    total past the tier boundary, and the lease ledger holds the plain sum
    59225 + 2673 = 61898.

    Design: Difficulty/combinatorial_formula/royalty_tier_keyed_on_season_total_including_current_lot
    """
    world = _five_hundred_bushels_then_one_more()

    big_after = _lot(world["lot_big"]["id"])

    assert big_after["royalty_rate_cents_per_bushel"] == TIER1_RATE_CENTS
    assert big_after["season_total_bushels_at_creation"] == 500
    assert _lease(world)["royalty_accrued_cents"] == 61898
    assert _authorization(world)["harvested_bushels"] == 501


# --------------------------------------------------------------------------
# Voiding a lot is an exact monetary reversal
# --------------------------------------------------------------------------
def test_voiding_the_one_bushel_lot_restores_the_pre_landing_ledger():
    """The void subtracts exactly the voided lot's `lot_settlement_cents`:
    61898 - 2673 = 59225, the value the lease held before that landing, and rolls
    the authorization's `harvested_bushels` back to 500. Every settlement field
    is retained on the voided row for the audit trail.

    Design: Difficulty/compensating_invariant/harvest_lot_void_restores_lease_royalty_accrued_cents
    """
    world = _five_hundred_bushels_then_one_more()

    voided = validate_success(api_client.void_harvest_lot(
        world["lot_edge"]["id"],
        void_payload(void_note="double-counted tote"), OPERATOR))

    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == "OPERATOR_CORRECTION"
    assert voided["royalty_rate_cents_per_bushel"] == TIER2_RATE_CENTS
    assert voided["conservation_surcharge_cents"] == 78
    assert voided["lot_settlement_cents"] == 2673
    assert _lease(world)["royalty_accrued_cents"] == 59225
    assert _authorization(world)["harvested_bushels"] == 500


def test_the_void_reverses_one_lot_without_recomputing_the_season():
    """No re-tiering occurs: the surviving 500-bushel lot keeps its stamped 115
    rate and its 59225-cent settlement even though the season total that selected
    that rate has now fallen, and it stays HARVESTED with `shipment_id` null.
    Because VOIDED lots are excluded from the season total, a fresh one-bushel
    landing is priced at 95 again with `season_total_bushels_at_creation` 501.

    Design: Difficulty/compensating_invariant/harvest_lot_void_restores_lease_royalty_accrued_cents
    """
    world = _five_hundred_bushels_then_one_more()
    validate_success(api_client.void_harvest_lot(
        world["lot_edge"]["id"],
        void_payload(void_note="double-counted tote"), OPERATOR))

    big_after = _lot(world["lot_big"]["id"])
    replacement = dw_land_lot(world, lot_code="LOT-EDGE-2", bushels=1)

    assert big_after["royalty_rate_cents_per_bushel"] == TIER1_RATE_CENTS
    assert big_after["lot_settlement_cents"] == 59225
    assert big_after["status"] == "HARVESTED"
    assert big_after["shipment_id"] is None
    assert replacement["season_total_bushels_at_creation"] == 501
    assert replacement["royalty_rate_cents_per_bushel"] == TIER2_RATE_CENTS
