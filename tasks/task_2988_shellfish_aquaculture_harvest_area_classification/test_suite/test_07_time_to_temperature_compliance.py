"""Time-to-temperature compliance at landing (PRD §3.8).

`allowed_ttt_minutes` is derived from an active vibrio control plan in four
ordered steps over three inputs outside the payload, both elapsed bases are
always persisted, the governing basis is chosen by the growing area's
`classification` rather than by the request, and the inclusive comparison against
the allowance is what the tag step later refuses on.
"""
from test_helpers import (
    ApiErrorId,
    api_client,
    assert_compliance_consistent,
    assert_governing_basis_consistent,
    create_listed_dealer,
    create_vessel,
    design_world,
    DW_AREA_CODE,
    DW_DEALER_CERT_NO,
    dw_dealer_payload,
    dw_deploy_unit,
    dw_land_lot,
    DW_LEASE_CODE,
    dw_vessel_payload,
    DW_WINDOW_END,
    DW_WINDOW_START,
    get_success_data,
    harvest_authorization_payload,
    iso,
    set_clock,
    tag_payload,
    TEST_USERS,
    validate_error,
    validate_success,
)

AUTHORITY = TEST_USERS["authority_headers"]
OPERATOR = TEST_USERS["operator_headers"]

PLACED_AT_TEN_FORTY = iso(2026, 8, 10, 10, 40)
PLACED_AT_TEN_THIRTY = iso(2026, 8, 10, 10, 30)
PLACED_AT_TEN_THIRTY_ONE = iso(2026, 8, 10, 10, 31)


# --------------------------------------------------------------------------
# The basis variant is read from another entity's state field
# --------------------------------------------------------------------------
def _conditionally_approved_world_with_one_lot():
    """The area carries a conditional management plan and was decided
    CONDITIONALLY_APPROVED before any harvest, which selects
    LAST_HARVEST_BASIS at landing. The lot is out of the water from 06:00 to
    08:00 and placed in temperature control at 10:40."""
    world = design_world(
        stage="active",
        area_overrides={"conditional_management_plan_on_file": True},
        sample_mpns=[2, 2, 2, 2, 2],
        classification="CONDITIONALLY_APPROVED",
        classification_overrides={
            "decision_note": "conditional management plan in force"},
    )
    # The lot is placed in temperature control at 10:40, so the clock must be at
    # or after that instant or the landing is future-dated (PRD §2.5).
    set_clock(iso(2026, 8, 10, 11))
    world["lot"] = dw_land_lot(
        world, lot_code="LOT-001",
        placed_in_temperature_control_at=PLACED_AT_TEN_FORTY)
    return world


def test_both_elapsed_bases_are_persisted_and_the_area_selects_the_last():
    """Both bases are always computed and always persisted: 06:00 to 10:40 is
    280 minutes on the first basis and 08:00 to 10:40 is 160 on the last. The
    variant selector is not in the landing payload at all -- it is the growing
    area's CONDITIONALLY_APPROVED `classification`, which makes
    `ttt_basis_variant` LAST_HARVEST_BASIS and `governing_ttt_minutes` 160.

    Design: Difficulty/dual_variant_calc/ttt_minutes_diverge_between_first_and_last_out_of_water_basis
    """
    world = _conditionally_approved_world_with_one_lot()
    lot = world["lot"]

    assert lot["ttt_minutes_first_basis"] == 280
    assert lot["ttt_minutes_last_basis"] == 160
    assert lot["ttt_basis_variant"] == "LAST_HARVEST_BASIS"
    assert lot["governing_ttt_minutes"] == 160
    assert_governing_basis_consistent(lot)

    area = get_success_data(
        api_client.get_growing_area(world["area"]["id"], AUTHORITY))
    assert area["classification"] == "CONDITIONALLY_APPROVED"


def test_the_selected_basis_flips_the_compliance_verdict():
    """The two bases diverge by 120 minutes and the allowance is 270, so the
    choice of basis decides the verdict: the first-basis 280 would have exceeded
    it while the selected last-basis 160 is comfortably inside, and the lot is
    COMPLIANT. The lot also records which plan priced it -- `vibrio_plan_month` 8
    and `vibrio_control_plan_id` naming the published August plan.

    Design: Difficulty/dual_variant_calc/ttt_minutes_diverge_between_first_and_last_out_of_water_basis
    """
    world = _conditionally_approved_world_with_one_lot()
    lot = world["lot"]

    assert lot["allowed_ttt_minutes"] == 270
    assert lot["ttt_minutes_first_basis"] - lot["ttt_minutes_last_basis"] == 120
    assert lot["ttt_minutes_first_basis"] > lot["allowed_ttt_minutes"]
    assert lot["governing_ttt_minutes"] <= lot["allowed_ttt_minutes"]
    assert lot["compliance_status"] == "COMPLIANT"
    assert_compliance_consistent(lot)
    assert lot["vibrio_plan_month"] == 8
    assert lot["vibrio_control_plan_id"] == world["plan"]["id"]


# --------------------------------------------------------------------------
# The four-input allowance chain
# --------------------------------------------------------------------------
def _three_lots_across_gear_vessel_and_temperature():
    """One August plan of 300 minutes prices three lots that share their harvest
    instants but differ in water temperature, gear type and vessel
    refrigeration."""
    world = design_world(
        stage="seed",
        lease_overrides={
            "gear_types_permitted": ["BOTTOM", "RACK_AND_BAG", "FLOATING_BAG"]},
    )
    world["dealer"] = create_listed_dealer(dw_dealer_payload())
    mechanical = create_vessel(OPERATOR, dw_vessel_payload())
    unrefrigerated = create_vessel(OPERATOR, dw_vessel_payload(
        name="Sound Runner", registration_no="NC-5520",
        refrigeration_type="NONE"))
    bottom_unit = dw_deploy_unit(
        world["lease"], world["seed_lot"], OPERATOR,
        {"plot_code": "P1", "gear_type": "BOTTOM"})
    floating_unit = dw_deploy_unit(
        world["lease"], world["seed_lot"], OPERATOR,
        {"plot_code": "P2", "gear_type": "FLOATING_BAG",
         "deployed_on": "2026-05-06", "planned_retrieval_on": "2026-10-16"},
        predator_control_at=None)

    authorizations = {}
    for key, unit, vessel in (("bottom", bottom_unit, mechanical),
                              ("floating", floating_unit, unrefrigerated)):
        authorizations[key] = validate_success(
            api_client.create_harvest_authorization(
                harvest_authorization_payload(
                    world["lease"]["id"], unit["id"], vessel["id"],
                    world["dealer"]["id"], DW_WINDOW_START, DW_WINDOW_END,
                    projected_bushels=600),
                OPERATOR), 201)
    set_clock(DW_WINDOW_START)
    for authorization in authorizations.values():
        validate_success(api_client.activate_harvest_authorization(
            authorization["id"], OPERATOR))
    set_clock(iso(2026, 8, 10, 11))

    world["lot_hot"] = dw_land_lot(
        world, authorization=authorizations["bottom"], lot_code="LOT-HOT",
        placed_in_temperature_control_at=PLACED_AT_TEN_THIRTY, water_temp_c=24.0)
    world["lot_cool"] = dw_land_lot(
        world, authorization=authorizations["bottom"], lot_code="LOT-COOL",
        placed_in_temperature_control_at=PLACED_AT_TEN_THIRTY, water_temp_c=22.0)
    world["lot_float"] = dw_land_lot(
        world, authorization=authorizations["floating"], lot_code="LOT-FLOAT",
        placed_in_temperature_control_at=PLACED_AT_TEN_THIRTY, water_temp_c=24.0)
    return world


def test_one_plan_yields_three_different_allowances():
    """From a single 300-minute plan the four ordered steps give 270 for BOTTOM
    gear on a MECHANICAL vessel at 24.0 C (300 - 60 for the inclusive high-temp
    test - 30 intertidal + 60 refrigeration credit), 330 for the same gear and
    vessel at 22.0 C (no high-temp reduction, since 22.0 is below the plan's
    23.0), and 240 for FLOATING_BAG gear on an unrefrigerated vessel at 24.0 C
    (no intertidal penalty and no credit). The 60-minute floor never binds.

    Design: Difficulty/combinatorial_formula/vibrio_allowed_minutes_nonlinear_across_four_inputs
    """
    world = _three_lots_across_gear_vessel_and_temperature()

    assert world["lot_hot"]["allowed_ttt_minutes"] == 270
    assert world["lot_cool"]["allowed_ttt_minutes"] == 330
    assert world["lot_float"]["allowed_ttt_minutes"] == 240


def test_the_three_allowances_are_not_a_product_of_independent_factors():
    """Changing one input at a time moves the allowance by different amounts --
    330 - 270 = 60 for the temperature step and 270 - 240 = 30 for the gear and
    refrigeration pair -- so no single multiplicative factor reproduces the
    three. All three were priced by the same August plan.

    Design: Difficulty/combinatorial_formula/vibrio_allowed_minutes_nonlinear_across_four_inputs
    """
    world = _three_lots_across_gear_vessel_and_temperature()
    hot = world["lot_hot"]
    cool = world["lot_cool"]
    floating = world["lot_float"]

    assert cool["allowed_ttt_minutes"] - hot["allowed_ttt_minutes"] == 60
    assert hot["allowed_ttt_minutes"] - floating["allowed_ttt_minutes"] == 30
    for lot in (hot, cool, floating):
        assert lot["vibrio_plan_month"] == 8
        assert lot["vibrio_control_plan_id"] == world["plan"]["id"]


def test_identical_elapsed_time_is_compliant_twice_and_noncompliant_once():
    """All three lots share their harvest instants, so all three read
    `ttt_minutes_first_basis` 270 and `ttt_minutes_last_basis` 150, and the
    APPROVED area gives all three FIRST_HARVEST_BASIS with
    `governing_ttt_minutes` 270. The same 270 minutes is COMPLIANT against the
    270 and 330 allowances and NONCOMPLIANT against the 240.

    Design: Difficulty/combinatorial_formula/vibrio_allowed_minutes_nonlinear_across_four_inputs
    """
    world = _three_lots_across_gear_vessel_and_temperature()

    for lot in (world["lot_hot"], world["lot_cool"], world["lot_float"]):
        assert lot["ttt_minutes_first_basis"] == 270
        assert lot["ttt_minutes_last_basis"] == 150
        assert lot["ttt_basis_variant"] == "FIRST_HARVEST_BASIS"
        assert lot["governing_ttt_minutes"] == 270
        assert_governing_basis_consistent(lot)
        assert_compliance_consistent(lot)

    assert world["lot_hot"]["compliance_status"] == "COMPLIANT"
    assert world["lot_cool"]["compliance_status"] == "COMPLIANT"
    assert world["lot_float"]["compliance_status"] == "NONCOMPLIANT"


# --------------------------------------------------------------------------
# The inclusive equality boundary on the derived minute count
# --------------------------------------------------------------------------
def test_governing_minutes_exactly_at_the_allowance_is_compliant_and_taggable():
    """`governing_ttt_minutes` 270 equals `allowed_ttt_minutes` 270, and the
    comparison is at-or-below, so the lot is COMPLIANT and the tag is accepted at
    HTTP 200, stamping the four shellstock-tag fields from the payload, the
    area's `code`, the lease's `lease_code` and the dealer's `certification_no`.

    Design: Difficulty/boundary_precision_check/time_to_temperature_exactly_at_allowed_limit_is_compliant
    """
    world = design_world(
        stage="landed",
        placed_in_temperature_control_at=PLACED_AT_TEN_THIRTY,
        lot_overrides={"lot_code": "LOT-001"},
    )
    lot = world["lot"]

    assert lot["allowed_ttt_minutes"] == 270
    assert lot["ttt_minutes_first_basis"] == 270
    assert lot["ttt_basis_variant"] == "FIRST_HARVEST_BASIS"
    assert lot["governing_ttt_minutes"] == 270
    assert lot["compliance_status"] == "COMPLIANT"

    tagged = validate_success(api_client.tag_harvest_lot(
        lot["id"], tag_payload("2026-08-10", DW_DEALER_CERT_NO), OPERATOR))

    assert tagged["status"] == "TAGGED"
    assert tagged["tag_harvest_date"] == "2026-08-10"
    assert tagged["tag_area_code"] == DW_AREA_CODE
    assert tagged["tag_lease_code"] == DW_LEASE_CODE
    assert tagged["tag_dealer_certification_no"] == DW_DEALER_CERT_NO


def test_one_minute_past_the_allowance_lands_but_cannot_be_tagged():
    """A single extra minute in temperature control makes
    `governing_ttt_minutes` 271 against the same 270 allowance, so the lot is
    NONCOMPLIANT. Nothing about the landing is refused on compliance grounds --
    it is still recorded at HTTP 201 with all its computed fields -- and it is
    the tag step that answers ERR_TIME_TEMPERATURE_EXCEEDED, leaving the lot in
    HARVESTED with its tag fields null.

    Design: Difficulty/boundary_precision_check/time_to_temperature_exactly_at_allowed_limit_is_compliant
    """
    world = design_world(stage="active")
    # The lot is placed in temperature control at 10:31, so the clock must be at
    # or after that instant or the landing is future-dated (PRD §2.5).
    set_clock(iso(2026, 8, 10, 11))
    lot = validate_success(api_client.create_harvest_lot(
        world["authorization"]["id"],
        {"lot_code": "LOT-001", "bushels": 10,
         "first_out_of_water_at": iso(2026, 8, 10, 6),
         "last_out_of_water_at": iso(2026, 8, 10, 8),
         "placed_in_temperature_control_at": PLACED_AT_TEN_THIRTY_ONE,
         "water_temp_c": 24.0},
        OPERATOR), 201)

    assert lot["governing_ttt_minutes"] == 271
    assert lot["allowed_ttt_minutes"] == 270
    assert lot["compliance_status"] == "NONCOMPLIANT"

    response = api_client.tag_harvest_lot(
        lot["id"], tag_payload("2026-08-10", DW_DEALER_CERT_NO), OPERATOR)

    validate_error(response, ApiErrorId.ERR_TIME_TEMPERATURE_EXCEEDED, 409)
    unchanged = get_success_data(
        api_client.get_harvest_lot(lot["id"], OPERATOR))
    assert unchanged["status"] == "HARVESTED"
    assert unchanged["tag_harvest_date"] is None
    assert unchanged["tag_area_code"] is None
