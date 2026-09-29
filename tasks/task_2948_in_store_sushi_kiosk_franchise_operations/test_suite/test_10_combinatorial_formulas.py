"""Multi-input formulas whose pinned evaluation order is observable in the answer."""

from test_helpers import (
    CAP_SOURCE_CASE_CAPACITY,
    CAP_SOURCE_DEMAND,
    CAP_SOURCE_STAFFING,
    FISH_QUARANTINED,
    FISH_RECEIVED,
    HARVEST_AQUACULTURE_EXEMPT,
    POSTURE_CLEAR,
    POSTURE_WATCH,
    QUARANTINE_REASON_COLD_CHAIN_BREACH,
    SEVERITY_MAJOR,
    SPACE_COMPLIANT,
    SPACE_DEFICIENT,
    SPECIES_SALMON_ATLANTIC,
    add_cold_chain_readings,
    add_draft_plan,
    add_draft_statement,
    add_pack_lot,
    add_received_fish_lot,
    add_reconciled_feed,
    add_submitted_audit,
    assert_close,
    attest_space,
    base_world,
    discard_pack_lot_as_auditor,
    shelf_ready_world,
    validate_list,
    validate_success,
)

WIDE_CASE_STORE = {
    "refrigerated_case_linear_ft": 30.0,
    "refrigerated_case_capacity_packs": 400,
}
WIDE_CASE_ATTESTATION = {
    "attested_sushi_space_sqft": 240,
    "attested_case_linear_ft": 30.0,
}


def test_a_watch_posture_shaves_the_demand_ceiling_after_the_minimum(api):
    """Two major findings attenuate the plan without changing which ceiling bound it.

    "`posture_factor_applied` is 1.00 when the kiosk is `CLEAR`, 0.85 when it is
    `WATCH` … `planned_pack_count` is the binding ceiling multiplied by that factor
    and rounded down to a whole pack. The order matters and is not interchangeable
    … `binding_cap_source` must reflect the unattenuated comparison."

    Design: Difficulty/combinatorial_formula/production_plan_min_of_three_caps_posture_conditional
    """
    world = base_world()
    add_submitted_audit(
        world,
        severities=(SEVERITY_MAJOR, SEVERITY_MAJOR),
        codes=["FS-HANDWASH-SIGNAGE", "FS-GLOVE-USE"],
    )

    watched = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert watched["risk_points"] == 8
    assert watched["sanitation_posture"] == POSTURE_WATCH
    assert watched["certified_chef_count"] == 1
    assert watched["daily_pack_cap"] == 180

    plan = add_draft_plan(world, traffic_forecast=9000)
    assert plan["binding_cap_source"] == CAP_SOURCE_DEMAND
    assert_close(plan["posture_factor_applied"], 0.85, places=2)
    assert plan["planned_pack_count"] == 137
    assert_close(plan["planned_rice_kg"], 16.44, places=2)


def test_the_case_capacity_ceiling_binds_when_forecast_demand_outruns_the_case(api):
    """A busier forecast hands the minimum to the refrigerated case.

    "The **case capacity** ceiling is the smaller of the host store's
    `refrigerated_case_capacity_packs` and the frontage-implied capacity of nine
    packs per linear foot of `refrigerated_case_linear_ft`, rounded down."

    Design: Difficulty/combinatorial_formula/production_plan_min_of_three_caps_posture_conditional
    """
    world = base_world()
    clear = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert clear["sanitation_posture"] == POSTURE_CLEAR

    plan = add_draft_plan(world, traffic_forecast=12000)
    assert plan["binding_cap_source"] == CAP_SOURCE_CASE_CAPACITY
    assert_close(plan["posture_factor_applied"], 1.00, places=2)
    assert plan["planned_pack_count"] == 180
    assert_close(plan["planned_rice_kg"], 21.60, places=2)


def test_a_wider_case_leaves_the_single_chef_as_the_binding_ceiling(api):
    """With demand and frontage both out of the way, one chef caps the day at 200.

    "The **staffing** ceiling is the kiosk's `certified_chef_count` multiplied by
    200 packs per certified chef; only chefs whose `status` is `CERTIFIED` count."

    Design: Difficulty/combinatorial_formula/production_plan_min_of_three_caps_posture_conditional
    """
    world = base_world(
        store_overrides=WIDE_CASE_STORE, attestation_overrides=WIDE_CASE_ATTESTATION
    )
    roomy = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert roomy["sanitation_posture"] == POSTURE_CLEAR
    assert roomy["certified_chef_count"] == 1
    assert roomy["daily_pack_cap"] == 270

    plan = add_draft_plan(world, traffic_forecast=20000)
    assert plan["binding_cap_source"] == CAP_SOURCE_STAFFING
    assert_close(plan["posture_factor_applied"], 1.00, places=2)
    assert plan["planned_pack_count"] == 200
    assert_close(plan["planned_rice_kg"], 24.00, places=2)


def test_four_alternating_readings_each_attribute_eight_whole_minutes(api):
    """Rounding every fifteen-minute half-breach up to 8 pushes the total past thirty.

    "if exactly *one* end is above 4.4 the midpoint rule attributes half the gap,
    rounded half up to a whole minute … The rounding order here is load-bearing:
    each interval is rounded to a whole minute *before* the intervals are summed,
    and summing the raw halves to round once at the end gives a different answer."

    Design: Difficulty/combinatorial_formula/cold_chain_per_interval_round_then_sum
    """
    world = base_world()
    lot = add_received_fish_lot(
        world,
        species=SPECIES_SALMON_ATLANTIC,
        supplier_code="SUP-4410",
        harvest_method=HARVEST_AQUACULTURE_EXEMPT,
        net_weight_kg=10.0,
        received_at="2026-08-03T06:00:00Z",
        receiving_temp_c=2.8,
    )
    assert lot["status"] == FISH_RECEIVED
    assert lot["cold_chain_breach_minutes"] == 0

    readings = add_cold_chain_readings(
        world,
        lot["id"],
        [
            ("2026-08-03T06:15:00Z", 5.0),
            ("2026-08-03T06:30:00Z", 3.0),
            ("2026-08-03T06:45:00Z", 5.0),
            ("2026-08-03T07:00:00Z", 3.0),
        ],
    )
    assert [reading["breach_minutes_attributed"] for reading in readings] == [8, 8, 8, 8]
    assert [reading["lot_breach_minutes_after"] for reading in readings] == [
        8,
        16,
        24,
        32,
    ]
    assert readings[0]["interval_minutes_from_previous"] is None
    assert readings[3]["interval_minutes_from_previous"] == 15

    breached = validate_success(api.get_fish_lot(lot["id"], world["ops_headers"]))
    assert breached["cold_chain_breach_minutes"] == 32
    assert breached["cold_chain_breach_minutes"] > 30
    assert breached["status"] == FISH_QUARANTINED
    assert breached["quarantine_reason"] == QUARANTINE_REASON_COLD_CHAIN_BREACH

    charged = validate_success(api.get_kiosk(world["kiosk_id"], world["ops_headers"]))
    assert charged["risk_points"] == 6
    assert charged["sanitation_posture"] == POSTURE_CLEAR


def test_a_wholly_warm_interval_attributes_its_entire_gap(api):
    """Both ends above the limit attribute fifteen minutes, not seven and a half.

    "if the temperature at *both* ends of the interval is above 4.4 the whole gap
    is attributed, since the product was out of temperature throughout … the lot's
    `cold_chain_breach_minutes` becomes the sum of the per-interval attributions,
    echoed onto the reading as `lot_breach_minutes_after`."

    Design: Difficulty/combinatorial_formula/cold_chain_per_interval_round_then_sum
    """
    world = base_world()
    lot = add_received_fish_lot(
        world,
        species=SPECIES_SALMON_ATLANTIC,
        supplier_code="SUP-4410",
        harvest_method=HARVEST_AQUACULTURE_EXEMPT,
        net_weight_kg=10.0,
        received_at="2026-08-03T06:00:00Z",
        receiving_temp_c=2.8,
    )

    warming = add_cold_chain_readings(
        world,
        lot["id"],
        [("2026-08-03T06:15:00Z", 5.0), ("2026-08-03T06:30:00Z", 5.5)],
    )
    assert warming[0]["breach_minutes_attributed"] == 8
    assert warming[1]["breach_minutes_attributed"] == 15
    assert warming[1]["lot_breach_minutes_after"] == 23
    assert warming[1]["interval_minutes_from_previous"] == 15

    still_received = validate_success(api.get_fish_lot(lot["id"], world["ops_headers"]))
    assert still_received["status"] == FISH_RECEIVED
    assert still_received["cold_chain_breach_minutes"] == 23

    cooling = add_cold_chain_readings(
        world, lot["id"], [("2026-08-03T06:45:00Z", 3.0)]
    )
    assert cooling[0]["breach_minutes_attributed"] == 8
    assert cooling[0]["lot_breach_minutes_after"] == 31

    quarantined = validate_success(api.get_fish_lot(lot["id"], world["ops_headers"]))
    assert quarantined["status"] == FISH_QUARANTINED
    assert quarantined["cold_chain_breach_minutes"] == 31
    validate_list(
        api.list_cold_chain_readings(lot["id"], world["ops_headers"]), expected_total=3
    )


def test_both_credits_are_capped_against_the_share_before_either_is_applied(api):
    """A fifteen-foot shortfall and a 180000 cent discard net down to 247650.

    "Its cap is 25 percent of `binding_share_cents`, rounded half up to whole
    cents … 40 percent of the total `discard_value_cents` of events whose
    `settlement_credit_eligible` is true, rounded half up, capped at 10 percent of
    `binding_share_cents` … Both caps are keyed on `binding_share_cents`, the share
    *before* any credit is applied."

    Design: Difficulty/combinatorial_formula/settlement_credit_caps_pinned_evaluation_order
    """
    world = shelf_ready_world(
        store_overrides=WIDE_CASE_STORE,
        attestation_overrides=WIDE_CASE_ATTESTATION,
        plan_overrides={"traffic_forecast": 20000},
        batch_overrides={"rice_kg": 24.0},
    )
    assert world["plan"]["planned_pack_count"] == 200
    assert world["plan"]["binding_cap_source"] == CAP_SOURCE_STAFFING
    assert world["rice_batch"]["max_pack_yield"] == 200

    lot = add_pack_lot(
        world, world["rice_batch_id"], world["fish_lot_id"], pack_count=200
    )
    spoiled = discard_pack_lot_as_auditor(world, lot["id"])
    assert spoiled["unit_value_cents"] == 900
    assert spoiled["discard_value_cents"] == 180000
    assert spoiled["settlement_credit_eligible"] is True

    shrunk = attest_space(
        world["host_store_id"],
        attested_sushi_space_sqft=205,
        attested_case_linear_ft=30.0,
        attested_on="2026-08-03",
    )
    assert shrunk["space_compliance_state"] == SPACE_DEFICIENT
    priced = validate_success(
        api.get_license_agreement(world["agreement_id"], world["ops_headers"])
    )
    assert priced["space_shortfall_sqft"] == 15

    add_reconciled_feed(world)
    statement = add_draft_statement(world)

    assert statement["binding_share_cents"] == 296000
    assert statement["space_shortfall_credit_cents"] == 18750
    assert statement["period_discard_value_cents"] == 180000
    assert statement["discard_credit_cents"] == 29600
    assert statement["net_due_cents"] == 247650


def test_a_full_attestation_leaves_the_discard_cap_exactly_where_it_was(api):
    """Removing the space credit does not move the discard credit by a single cent.

    "`net_due_cents` is `binding_share_cents` less both credits, floored at zero …
    keying the discard cap on the already-reduced amount produces a different figure
    and is wrong."

    Design: Difficulty/combinatorial_formula/settlement_credit_caps_pinned_evaluation_order
    """
    world = shelf_ready_world(
        store_overrides=WIDE_CASE_STORE,
        attestation_overrides=WIDE_CASE_ATTESTATION,
        plan_overrides={"traffic_forecast": 20000},
        batch_overrides={"rice_kg": 24.0},
    )
    compliant = validate_success(
        api.get_host_store(world["host_store_id"], world["ops_headers"])
    )
    assert compliant["space_compliance_state"] == SPACE_COMPLIANT

    lot = add_pack_lot(
        world, world["rice_batch_id"], world["fish_lot_id"], pack_count=200
    )
    discard_pack_lot_as_auditor(world, lot["id"])

    add_reconciled_feed(world)
    statement = add_draft_statement(world)

    assert statement["binding_share_cents"] == 296000
    assert statement["space_shortfall_credit_cents"] == 0
    assert statement["period_discard_value_cents"] == 180000
    assert statement["discard_credit_cents"] == 29600
    assert statement["net_due_cents"] == 266400
