"""Constant tables, thresholds, half-up precision and waterfall allocation."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.fixtures import Plant, build_plant

# A second design point: M235_35A steel, a 200 mm stack, 14.5 kg of copper and a
# fabricated copper cage, none of which the baseline design exercises.
PREMIUM_VARIANT = F.motor_design_payload(
    model_code="WM-132M-7K5-IE4C",
    target_efficiency_class="IE4",
    lamination_grade="M235_35A",
    lamination_stack_length_mm=200,
    winding_copper_kg=14.5,
    rotor_construction="FABRICATED_COPPER",
    rotor_bar_count=40,
)

VPI_WINDOW_START = F.instant("2026-08-02", 8, 0)
VPI_WINDOW_END = F.instant("2026-08-02", 12, 0)
DIP_WINDOW_START = F.instant("2026-08-02", 13, 0)
DIP_WINDOW_END = F.instant("2026-08-02", 15, 0)
TRICKLE_WINDOW_START = F.instant("2026-08-03", 8, 0)
TRICKLE_WINDOW_END = F.instant("2026-08-03", 10, 0)

SIX_MONTH_CLOCK = F.instant("2027-02-05", 9, 30)
SIXTY_MONTH_CLOCK = F.instant("2031-08-05", 9, 30)
FIELD_APPLICATION = {
    "measured_load_pct": 118.0,
    "measured_ambient_c": 52.0,
    "measured_voltage_unbalance_pct": 2.4,
    "measured_starts_per_hour": 9,
    "claimed_parts_cents": 140000,
    "claimed_labor_cents": 60000,
    "claimed_freight_cents": 20000,
}


def test_a_second_design_point_reproduces_every_loss_component_and_both_verdicts(api):
    """M235_35A steel on a 200 mm stack with a copper cage lands 388.8 W.

    PRD 3.2: "`total_predicted_loss_w` is then the sum of those five *already
    rounded* components, in that order. The rounding happens before the summation,
    never after; adding the raw products and rounding the total once produces a
    different, wrong figure."

    Design: Corner/calculations/premium_design_variant_reproduces_every_loss_component_and_both_classes
    """
    components = A.expected_loss_components(PREMIUM_VARIANT)

    created = validate_success(
        api.create_motor_design(PREMIUM_VARIANT, U.DESIGN_ENGINEER), 201
    )

    # The five individual loss components are named only inside the loss-model
    # prose of PRD 3.2, never as response-visible design attributes, so only the
    # declared outputs are asserted. 111.8 + 130.3 + 79.2 + 45.0 + 22.5 = 388.8
    # is reachable only by rounding each component before the summation.
    A.assert_rounded_to(
        created["total_predicted_loss_w"],
        components["total_predicted_loss_w"],
        1,
        "total_predicted_loss_w",
    )
    assert created["total_predicted_loss_w"] == 388.8
    assert created["predicted_efficiency_pct"] == 95.07
    assert created["guaranteed_efficiency_pct"] == 94.33
    assert created["design_estimate_class"] == "IE5"
    assert created["predicted_class"] == "IE4"
    assert created["status"] == "DRAFT"
    assert created["version"] == 1


def test_four_orders_differ_only_in_the_lead_time_constants_they_select(api):
    """29, 36, 96 and 36 days, and an unrecognised flag that adds nothing.

    PRD 3.4: "Start with the channel base: 5 days for `STOCK_REPLENISH`, 28 days
    for `MADE_TO_ORDER`, 56 days for `ENGINEERED_SPECIAL`." "An unrecognised key
    contributes nothing at all, and a recognised key that is simply absent is
    treated as false."

    Design: Corner/calculations/order_lead_time_sums_base_tier_jurisdiction_and_special_requirement_constants
    """
    plant = Plant(api)
    gold = plant.add_distributor()
    platinum = plant.add_extra_distributor(
        name="Southwind Motor Distribution", tier="PLATINUM", jurisdiction="CN"
    )
    plant.released_design()

    plain = plant.add_order()
    mounted = plant.add_order(special_requirements={"non_standard_mounting": True})
    special = plant.add_order(
        distributor=platinum,
        order_type="ENGINEERED_SPECIAL",
        quantity=4,
        jurisdiction="CN",
        special_requirements={"hazardous_environment": True, "marine_certification": True},
    )
    unknown_flag = plant.add_order(
        special_requirements={
            "non_standard_mounting": True,
            "gold_plated_terminal_box": True,
        }
    )

    assert plain["promised_lead_time_days"] == 29
    assert plain["promised_lead_time_days"] == A.expected_lead_time_days(
        "MADE_TO_ORDER", "EU", "GOLD", 12, 10
    )
    assert plain["promised_ship_date"] == "2026-08-30"
    assert mounted["promised_lead_time_days"] == 36
    assert mounted["promised_ship_date"] == "2026-09-06"
    assert special["promised_lead_time_days"] == 96
    assert special["promised_lead_time_days"] == A.expected_lead_time_days(
        "ENGINEERED_SPECIAL",
        "CN",
        "PLATINUM",
        4,
        10,
        {"hazardous_environment": True, "marine_certification": True},
    )
    assert special["promised_ship_date"] == "2026-11-05"
    assert unknown_flag["promised_lead_time_days"] == 36
    assert unknown_flag["promised_ship_date"] == "2026-09-06"
    assert unknown_flag["promised_ship_date"] == A.add_days(F.CLOCK_DAY, 36)
    for order in (plain, mounted, special, unknown_flag):
        assert order["status"] == "DRAFT"
        assert order["confirmed_at"] is None
    assert plant.get_distributor(gold)["units_outstanding"] == 0
    assert plant.get_distributor(platinum)["units_outstanding"] == 0


def test_the_shortfall_adder_needs_both_a_strict_excess_and_the_right_order_type(api):
    """Ten units draw nothing, eleven draw eleven days, and a MADE_TO_ORDER eleven draws nothing.

    PRD 3.4: "Add a stocking shortfall penalty of 11 days, but only for a
    `STOCK_REPLENISH` order whose `quantity` is **strictly greater** than the
    distributor's `stock_buffer_units`; a quantity exactly equal to the buffer draws
    no penalty, and no other order type ever draws it."

    Design: Corner/calculations/stock_buffer_shortfall_adder_fires_only_strictly_above_the_buffer
    """
    plant = Plant(api)
    distributor = plant.add_distributor()
    assert distributor["stock_buffer_units"] == 10
    plant.released_design()

    at_the_buffer = plant.add_order(order_type="STOCK_REPLENISH", quantity=10)
    over_the_buffer = plant.add_order(order_type="STOCK_REPLENISH", quantity=11)
    made_to_order = plant.add_order(order_type="MADE_TO_ORDER", quantity=11)

    assert at_the_buffer["promised_lead_time_days"] == 6
    assert at_the_buffer["promised_lead_time_days"] == A.expected_lead_time_days(
        "STOCK_REPLENISH", "EU", "GOLD", 10, 10
    )
    assert at_the_buffer["promised_ship_date"] == "2026-08-07"
    assert over_the_buffer["promised_lead_time_days"] == 17
    assert over_the_buffer["promised_lead_time_days"] == A.expected_lead_time_days(
        "STOCK_REPLENISH", "EU", "GOLD", 11, 10
    )
    assert over_the_buffer["promised_ship_date"] == "2026-08-18"
    assert over_the_buffer["promised_lead_time_days"] - at_the_buffer[
        "promised_lead_time_days"
    ] == 11
    assert made_to_order["promised_lead_time_days"] == 29
    assert made_to_order["promised_ship_date"] == "2026-08-30"


def test_a_tied_third_decimal_on_the_air_gap_rounds_away_from_zero(api):
    """A 134.503 mm rotor makes the raw half-difference exactly 0.4485 mm.

    PRD 2.7: "Every rounding operation in this specification uses the **round half
    up** rule: a value exactly halfway between two representable results rounds away
    from zero to the larger magnitude."

    PRD 3.7: "From the outer diameter the server derives the air gap:
    `measured_air_gap_mm` is the pinned design's `stator_bore_id_mm` minus
    `measured_rotor_od_mm`, halved, rounded to three decimal places — the gap is
    radial, which is why the diametral difference is halved."

    Design: Corner/calculations/rotor_air_gap_rounds_half_up_at_the_third_decimal
    """
    plant = build_plant(api, "rotor_caged")
    design = plant.get_design()
    assert design["stator_bore_id_mm"] == 135.4
    assert design["design_air_gap_mm"] == 0.45
    assert design["air_gap_tolerance_mm"] == 0.05
    assert plant.get_rotor()["status"] == "CAST_POURED"

    machined = plant.machine_rotor(measured_rotor_od_mm=134.503)

    A.assert_rounded_to(
        machined["measured_air_gap_mm"],
        A.expected_air_gap_mm(135.400, 134.503),
        3,
        "measured_air_gap_mm",
    )
    assert machined["measured_air_gap_mm"] == 0.449
    A.assert_rounded_to(
        machined["air_gap_deviation_mm"],
        A.expected_air_gap_deviation_mm(135.400, 134.503, 0.450),
        3,
        "air_gap_deviation_mm",
    )
    assert machined["air_gap_deviation_mm"] == -0.001
    assert machined["measured_rotor_od_mm"] == 134.503
    assert machined["status"] == "MACHINED"
    assert plant.get_work_order()["build_status"] == "RELEASED"


def test_three_impregnations_walk_the_varnish_table_and_the_cycle_bonus_cap(api):
    """VPI at five cycles is capped, DIP_BAKE at one earns nothing, TRICKLE at three earns 0.08.

    PRD 3.6: "The cycle bonus is 0.04 for each impregnation cycle beyond the first,
    capped at 0.12 — so two cycles give 0.04, three give 0.08, four give 0.12, and
    five or six give no more than four does."

    Design: Corner/calculations/surge_capability_applies_the_varnish_multiplier_and_caps_the_cycle_bonus
    """
    plant = Plant(api)
    plant.add_distributor()
    oven = plant.add_oven(
        oven_code="OVEN-A", max_temp_c=180.0, cooldown_buffer_minutes=45
    )
    plant.released_design()
    plant.add_order()
    plant.confirm_order()
    plant.add_work_order()

    vpi = plant.add_stator()
    vpi = plant.impregnate_stator(
        stator=vpi,
        impregnation_window_start=VPI_WINDOW_START,
        impregnation_window_end=VPI_WINDOW_END,
        varnish_process="VPI",
        varnish_cycles=5,
        cure_temp_c=165.0,
    )
    plant.disposition_stator(
        "REJECTED", stator=vpi, disposition_notes="Slot liner displaced during VPI."
    )
    dip = plant.add_stator()
    dip = plant.impregnate_stator(
        stator=dip,
        impregnation_window_start=DIP_WINDOW_START,
        impregnation_window_end=DIP_WINDOW_END,
        varnish_process="DIP_BAKE",
        varnish_cycles=1,
        cure_temp_c=165.0,
    )
    plant.disposition_stator(
        "REJECTED", stator=dip, disposition_notes="Insufficient varnish penetration."
    )
    trickle = plant.add_stator()
    trickle = plant.impregnate_stator(
        stator=trickle,
        impregnation_window_start=TRICKLE_WINDOW_START,
        impregnation_window_end=TRICKLE_WINDOW_END,
        varnish_process="TRICKLE",
        varnish_cycles=3,
        cure_temp_c=165.0,
    )

    required = A.expected_required_surge_kv(400, "F")
    assert required == A.dec("2.07")
    for build in (vpi, dip, trickle):
        A.assert_rounded_to(build["required_surge_kv"], 2.07, 2, "required_surge_kv")
    A.assert_rounded_to(
        vpi["achieved_capability_kv"],
        A.expected_achieved_capability_kv(400, "F", "VPI", 5),
        2,
        "achieved_capability_kv",
    )
    assert vpi["achieved_capability_kv"] == 2.78
    assert dip["achieved_capability_kv"] == 2.07
    assert trickle["achieved_capability_kv"] == 2.35
    assert trickle["impregnation_minutes"] == 120
    assert trickle["status"] == "IMPREGNATED"
    work_order = plant.get_work_order()
    assert work_order["rework_reject_count"] == 2
    assert work_order["actual_cost_cents"] == 2476712
    assert work_order["cost_variance_cents"] == 125000
    A.assert_cost_rollup(work_order, F.motor_design_payload(), 12, 2)
    assert plant.get_oven(oven)["booked_minutes"] == 120


def test_the_governing_standard_is_the_latest_effective_row_registered_earliest(api):
    """Seven scrambled standards, four ineligible reasons, and a created_at tie-break.

    PRD 3.9: "Rank the survivors by `effective_from` descending, because the most
    recently effective standard governs; where two rows share an effective date, the
    earliest-registered row wins, comparing `created_at` ascending. The row's `id` is
    never consulted as a tiebreaker."

    Design: Corner/calculations/regulatory_standard_selector_ranks_by_effective_date_and_ignores_ineligible_rows
    """
    plant = build_plant(
        api,
        "tested",
        standard={
            "standard_code": "IEC_60034_30_1_EU_IE5_4P_2027",
            "efficiency_class": "IE5",
            "minimum_efficiency_pct": 94.80,
            "effective_from": "2027-01-01",
        },
    )
    future = plant.standard
    old = plant.add_standard()
    united_states = plant.add_standard(
        standard_code="IEC_60034_30_1_US_IE3_4P",
        jurisdiction="US",
        minimum_efficiency_pct=91.70,
        effective_from="2023-01-01",
    )
    two_pole = plant.add_standard(
        standard_code="IEC_60034_30_1_EU_IE3_2P",
        poles=2,
        minimum_efficiency_pct=91.40,
        effective_from="2023-01-01",
    )
    wrong_band = plant.add_standard(
        standard_code="IEC_60034_30_1_EU_IE3_4P_LARGE",
        rated_output_kw_min=11.1,
        rated_output_kw_max=20.0,
        minimum_efficiency_pct=92.50,
        effective_from="2023-01-01",
    )
    winner = plant.add_standard(
        standard_code="IEC_60034_30_1_EU_IE2_4P_2023",
        efficiency_class="IE2",
        minimum_efficiency_pct=90.50,
        effective_from="2023-01-01",
    )
    # PRD 2.4 mints created_at from the logical clock, so the clock is advanced
    # one minute to make the two rows sharing 2023-01-01 genuinely differ in
    # registration instant — the tiebreak PRD 3.9 names is created_at ascending.
    plant.set_clock(F.instant(F.TEST_DAY, 9, 31))
    tie = plant.add_standard(
        standard_code="IEC_60034_30_1_EU_IE3_4P_2023",
        efficiency_class="IE3",
        minimum_efficiency_pct=92.10,
        effective_from="2023-01-01",
    )
    assert plant.get_test()["measured_efficiency_pct"] == 93.42
    assert plant.get_work_order()["build_status"] == "TESTED"
    assert winner["created_at"] < tie["created_at"]

    nameplate = plant.issue_nameplate()

    assert nameplate["standard_id"] == winner["id"]
    assert nameplate["standard_id"] != tie["id"]
    assert nameplate["standard_id"] != future["id"]
    assert nameplate["standard_id"] != united_states["id"]
    assert nameplate["standard_id"] != two_pole["id"]
    assert nameplate["standard_id"] != wrong_band["id"]
    assert nameplate["standard_id"] != old["id"]
    A.assert_rounded_to(
        nameplate["minimum_efficiency_pct_applied"],
        90.50,
        2,
        "minimum_efficiency_pct_applied",
    )
    assert nameplate["stamped_efficiency_pct"] == 93.42
    assert nameplate["stamped_class"] == "IE3"
    assert nameplate["status"] == "ISSUED"
    assert plant.get_work_order()["certification_status"] == "CERTIFIED"


def test_the_credit_waterfall_forfeits_freight_and_settles_to_zero_at_sixty_months(api):
    """One shipped motor, two claims, and two service ages either side of the window.

    PRD 3.10: "The three buckets are then filled in a fixed order — parts, then
    labour, then freight — each capped independently *and* by whatever remains of the
    ceiling." "A claim at or beyond 60 months of service therefore settles at exactly
    0."

    Design: Corner/calculations/warranty_credit_waterfall_fills_parts_then_labor_and_forfeits_the_remainder
    """
    plant = build_plant(api, "shipped")
    assert plant.get_work_order()["shipped_at"] == F.RECORD_CLOCK
    assert plant.get_work_order()["standard_cost_cents"] == 2351712
    assert A.service_age_months(F.TEST_DAY, "2027-02-05") == 6
    assert A.service_age_months(F.TEST_DAY, "2031-08-05") == 60
    waterfall = A.expected_warranty_credit_cents(195976, 140000, 60000, 20000, 6)

    plant.set_clock(SIX_MONTH_CLOCK)
    in_warranty = plant.file_claim(
        headers=plant.distributor_headers,
        failure_mode="WINDING_SHORT",
        operating_hours=3100,
        **FIELD_APPLICATION
    )
    settled = plant.analyze_claim(F.analyze_field_data_payload(), claim=in_warranty)
    plant.set_clock(SIXTY_MONTH_CLOCK)
    out_of_warranty = plant.file_claim(
        headers=plant.distributor_headers,
        failure_mode="INSULATION_BREAKDOWN",
        operating_hours=41000,
        **FIELD_APPLICATION
    )
    forfeited = plant.analyze_claim(
        F.analyze_field_data_payload(), claim=out_of_warranty
    )

    assert settled["adjudication"] == "DEFECT_CONFIRMED"
    assert settled["misuse_index"] == 0.4705
    assert settled["claim_unit_standard_cost_cents"] == 195976
    assert waterfall["ceiling_cents"] == 149922
    assert waterfall["parts_cents"] == 117586
    assert waterfall["labor_cents"] == 32336
    assert waterfall["freight_cents"] == 0
    assert settled["warranty_credit_cents"] == 149922
    assert settled["warranty_credit_cents"] == waterfall["warranty_credit_cents"]
    assert settled["credit_posted"] is True
    assert forfeited["adjudication"] == "DEFECT_CONFIRMED"
    assert forfeited["misuse_index"] == 0.4705
    assert forfeited["warranty_credit_cents"] == 0
    assert forfeited["claim_unit_standard_cost_cents"] == 195976
    assert plant.get_distributor()["warranty_credit_balance_cents"] == 149922
