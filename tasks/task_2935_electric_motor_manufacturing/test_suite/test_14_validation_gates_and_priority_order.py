"""Validation gates: declared widths, inclusive band edges and rejection order."""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import test_users as U
from test_helpers.api_errors import (
    ERR_CURE_TEMP_EXCEEDS_OVEN_LIMIT,
    ERR_DUPLICATE_ACTIVE_SUBASSEMBLY,
    ERR_DUPLICATE_MODEL_CODE,
    ERR_EFFICIENCY_BELOW_REGULATORY_MINIMUM,
    ERR_INSULATION_SYSTEM_MISMATCH,
    ERR_INVALID_REQUEST,
    ERR_JURISDICTION_MISMATCH,
    ERR_LUBRICATION_FILL_OUT_OF_RANGE,
    ERR_NO_APPLICABLE_STANDARD,
    ERR_NOT_OWNER,
    ERR_OVEN_NOT_FOUND,
    ERR_RESOURCE_IN_MAINTENANCE,
    ERR_ROTOR_BAR_COUNT_MISMATCH,
    ERR_ROTOR_CONSTRUCTION_MISMATCH,
    ERR_SHAFT_FIT_OUT_OF_TOLERANCE,
    ERR_SHIP_DATE_UNACHIEVABLE,
    ERR_SLOT_FILL_OUT_OF_RANGE,
    ERR_STOCKING_PROGRAM_NOT_ENROLLED,
    ERR_SUBASSEMBLY_NOT_FOUND,
    ERR_SURGE_OVERSTRESS,
    ERR_TEST_WINDOW_NOT_STARTED,
    ERR_UNAUTHORIZED,
    ERR_UNBALANCE_EXCEEDS_GRADE_LIMIT,
    ERR_WORK_ORDER_NOT_FOUND,
)
from test_helpers.fixtures import Plant, build_plant

ONE_MILLISECOND_EARLY = "2026-08-05T08:59:59.999Z"
INVERTED_WINDOW = {
    "impregnation_window_start": F.IMPREGNATION_WINDOW_END,
    "impregnation_window_end": F.IMPREGNATION_WINDOW_START,
}


def _work_order_on_the_floor(api):
    """A distributor, a released design, a confirmed order and a RELEASED work order."""
    plant = Plant(api)
    plant.add_distributor()
    plant.released_design()
    plant.add_order()
    plant.confirm_order()
    work_order = plant.add_work_order()
    assert work_order["build_status"] == "RELEASED"
    return plant, work_order


def test_stator_creation_separates_the_width_the_band_and_the_insulation_faults(api):
    """Five refusals on one work order, then 78.00 exactly is accepted.

    PRD 3.6: "Slot fill must lie between 78.00 and 86.00 percent inclusive; outside
    that band the record is refused with `ERR_SLOT_FILL_OUT_OF_RANGE` (HTTP 422)."

    PRD 2.11: "Cross-entity referential rules are next, in this order: design release
    status (`ERR_DESIGN_NOT_RELEASED`), stocking enrolment
    (`ERR_STOCKING_PROGRAM_NOT_ENROLLED`), rotor construction match
    (`ERR_ROTOR_CONSTRUCTION_MISMATCH`), insulation-system match
    (`ERR_INSULATION_SYSTEM_MISMATCH`), rotor bar-count match
    (`ERR_ROTOR_BAR_COUNT_MISMATCH`) and jurisdiction match
    (`ERR_JURISDICTION_MISMATCH`)."

    Design: Corner/validations/stator_creation_checks_width_then_insulation_then_slot_fill_band
    """
    plant, work_order = _work_order_on_the_floor(api)
    assert plant.get_design()["insulation_class"] == "F"

    three_decimals = api.create_stator_build(
        F.stator_build_payload(work_order["id"], slot_fill_pct=82.005),
        U.BUILD_TECHNICIAN,
    )
    below_the_band = api.create_stator_build(
        F.stator_build_payload(work_order["id"], slot_fill_pct=77.99),
        U.BUILD_TECHNICIAN,
    )
    above_the_band = api.create_stator_build(
        F.stator_build_payload(work_order["id"], slot_fill_pct=86.01),
        U.BUILD_TECHNICIAN,
    )
    wrong_insulation = api.create_stator_build(
        F.stator_build_payload(
            work_order["id"],
            insulation_system="CLASS_B_POLYESTER",
            slot_fill_pct=82.00,
        ),
        U.BUILD_TECHNICIAN,
    )
    both_wrong = api.create_stator_build(
        F.stator_build_payload(
            work_order["id"],
            insulation_system="CLASS_B_POLYESTER",
            slot_fill_pct=77.99,
        ),
        U.BUILD_TECHNICIAN,
    )
    at_the_lower_edge = api.create_stator_build(
        F.stator_build_payload(work_order["id"], slot_fill_pct=78.00),
        U.BUILD_TECHNICIAN,
    )

    validate_error(three_decimals, ERR_INVALID_REQUEST, 400)
    validate_error(below_the_band, ERR_SLOT_FILL_OUT_OF_RANGE, 422)
    validate_error(above_the_band, ERR_SLOT_FILL_OUT_OF_RANGE, 422)
    validate_error(wrong_insulation, ERR_INSULATION_SYSTEM_MISMATCH, 409)
    validate_error(both_wrong, ERR_INSULATION_SYSTEM_MISMATCH, 409)
    accepted = validate_success(at_the_lower_edge, 201)
    A.assert_rounded_to(accepted["slot_fill_pct"], 78.00, 2, "slot_fill_pct")
    assert accepted["status"] == "WOUND"
    assert accepted["insulation_system"] == "CLASS_F_POLYESTERIMIDE"
    assert accepted["winder_user_id"] == U.USER_BUILD_TECHNICIAN
    _rows, meta = validate_paginated(
        api.list_stator_builds(U.PLANT_ADMIN, {"work_order_id": work_order["id"]})
    )
    assert meta["total_count"] == 1
    assert plant.get_work_order()["rework_reject_count"] == 0


def test_impregnation_and_surge_refuse_maintenance_overtemperature_and_overstress(api):
    """Four refusals, then a cure at exactly the ceiling and a surge inside capability.

    PRD 3.6: "The `cure_temp_c` must not exceed the oven's `max_temp_c`, or the
    booking is refused with `ERR_CURE_TEMP_EXCEEDS_OVEN_LIMIT` (HTTP 422); a requested
    temperature exactly equal to the ceiling is acceptable."

    PRD 3.6: "First, the applied level must not exceed `achieved_capability_kv`; a
    level beyond the impregnated capability would destroy the winding and is refused
    with `ERR_SURGE_OVERSTRESS` (HTTP 422)."

    Design: Corner/validations/impregnation_and_surge_gates_reject_maintenance_overtemperature_and_overstress
    """
    plant = Plant(api)
    plant.add_distributor()
    available = plant.add_oven(
        oven_code="OVEN-A", max_temp_c=180.0, cooldown_buffer_minutes=45
    )
    under_maintenance = plant.add_oven(
        oven_code="OVEN-M",
        max_temp_c=200.0,
        cooldown_buffer_minutes=30,
        status="MAINTENANCE",
    )
    plant.released_design()
    plant.add_order()
    plant.confirm_order()
    plant.add_work_order()
    stator = plant.add_stator()
    assert stator["status"] == "WOUND"

    inverted = api.impregnate_stator_build(
        stator["id"],
        F.impregnation_payload(available["id"], cure_temp_c=165.0, **INVERTED_WINDOW),
        U.BUILD_TECHNICIAN,
    )
    on_the_maintenance_oven = api.impregnate_stator_build(
        stator["id"],
        F.impregnation_payload(under_maintenance["id"], cure_temp_c=165.0),
        U.BUILD_TECHNICIAN,
    )
    over_the_ceiling = api.impregnate_stator_build(
        stator["id"],
        F.impregnation_payload(available["id"], cure_temp_c=180.1),
        U.BUILD_TECHNICIAN,
    )
    at_the_ceiling = api.impregnate_stator_build(
        stator["id"],
        F.impregnation_payload(available["id"], cure_temp_c=180.0),
        U.BUILD_TECHNICIAN,
    )

    validate_error(inverted, ERR_INVALID_REQUEST, 400)
    validate_error(on_the_maintenance_oven, ERR_RESOURCE_IN_MAINTENANCE, 409)
    validate_error(over_the_ceiling, ERR_CURE_TEMP_EXCEEDS_OVEN_LIMIT, 422)
    impregnated = validate_success(at_the_ceiling, 200)
    assert impregnated["status"] == "IMPREGNATED"
    A.assert_rounded_to(impregnated["cure_temp_c"], 180.0, 1, "cure_temp_c")
    A.assert_rounded_to(
        impregnated["achieved_capability_kv"],
        A.expected_achieved_capability_kv(400, "F", "VPI", 2),
        2,
        "achieved_capability_kv",
    )
    assert impregnated["achieved_capability_kv"] == 2.58
    assert impregnated["impregnation_minutes"] == 240
    assert plant.get_oven(available)["booked_minutes"] == 240
    assert plant.get_oven(under_maintenance)["booked_minutes"] == 0

    overstress = api.surge_test_stator_build(
        stator["id"], F.surge_test_payload(2.60), U.TEST_ENGINEER
    )

    validate_error(overstress, ERR_SURGE_OVERSTRESS, 422)
    refused = plant.get_stator(stator)
    assert refused["status"] == "IMPREGNATED"
    assert refused["surge_test_kv"] is None
    assert refused["surge_test_result"] is None

    passed = plant.surge_test_stator(stator=stator, surge_test_kv=2.40)

    assert passed["status"] == "SURGE_TESTED"
    A.assert_rounded_to(
        passed["insulation_margin_kv"],
        A.expected_insulation_margin_kv(2.40, 400, "F"),
        2,
        "insulation_margin_kv",
    )
    assert passed["insulation_margin_kv"] == 0.33
    assert passed["surge_test_result"] == "PASS"


def test_model_codes_are_case_sensitive_and_a_rejected_build_frees_its_slot(api):
    """Two uniqueness scopes: every design ever, and the live build per work order.

    PRD 3.1: "a `model_code` of 1 to 40 characters that must not already be used by
    any other design — the comparison is case-sensitive and includes designs that have
    already been retired, and a collision is refused with `ERR_DUPLICATE_MODEL_CODE`
    (HTTP 409)"

    PRD 3.6: "A work order may hold at most one live stator build at a time: if it
    already has a stator build that is neither `REJECTED` nor `SCRAPPED`, a second is
    refused with `ERR_DUPLICATE_ACTIVE_SUBASSEMBLY` (HTTP 409) — a rejected or
    scrapped predecessor, by contrast, may freely be replaced."

    Design: Corner/validations/model_codes_and_live_subassemblies_are_unique_within_their_scopes
    """
    plant = Plant(api)
    plant.add_distributor()
    released = plant.released_design()
    assert released["status"] == "RELEASED"
    assert released["model_code"] == "WM-132M-7K5-IE3"
    retired = plant.add_design(F.economy_motor_design_payload())
    plant.submit_design(design=retired)
    retired = plant.decide_design("OBSOLETE", design=retired)
    assert retired["status"] == "OBSOLETE"
    assert retired["model_code"] == "WM-132S-7K5-IE3B"

    against_the_released_code = api.create_motor_design(
        F.premium_motor_design_payload(model_code="WM-132M-7K5-IE3"),
        U.DESIGN_ENGINEER,
    )
    against_the_retired_code = api.create_motor_design(
        F.premium_motor_design_payload(model_code="WM-132S-7K5-IE3B"),
        U.DESIGN_ENGINEER,
    )
    lowercase = api.create_motor_design(
        F.motor_design_payload(model_code="wm-132m-7k5-ie3"), U.DESIGN_ENGINEER
    )

    validate_error(against_the_released_code, ERR_DUPLICATE_MODEL_CODE, 409)
    validate_error(against_the_retired_code, ERR_DUPLICATE_MODEL_CODE, 409)
    distinct_by_case = validate_success(lowercase, 201)
    assert distinct_by_case["model_code"] == "wm-132m-7k5-ie3"
    assert distinct_by_case["id"] != released["id"]

    plant.add_order()
    plant.confirm_order()
    work_order = plant.add_work_order()
    first_stator = plant.add_stator()
    second_stator = api.create_stator_build(
        F.stator_build_payload(work_order["id"], slot_fill_pct=83.00),
        U.BUILD_TECHNICIAN,
    )
    plant.add_rotor()
    second_rotor = api.create_rotor_build(
        F.rotor_build_payload(work_order["id"]), U.BUILD_TECHNICIAN
    )
    validate_error(second_stator, ERR_DUPLICATE_ACTIVE_SUBASSEMBLY, 409)
    validate_error(second_rotor, ERR_DUPLICATE_ACTIVE_SUBASSEMBLY, 409)

    rejected = plant.disposition_stator(
        "REJECTED",
        stator=first_stator,
        disposition_notes="Turn-to-turn short found before impregnation.",
    )
    replacement = api.create_stator_build(
        F.stator_build_payload(work_order["id"], slot_fill_pct=83.00),
        U.BUILD_TECHNICIAN,
    )

    assert rejected["status"] == "REJECTED"
    accepted_replacement = validate_success(replacement, 201)
    assert accepted_replacement["status"] == "WOUND"
    A.assert_rounded_to(
        accepted_replacement["slot_fill_pct"], 83.00, 2, "slot_fill_pct"
    )
    _stators, stator_meta = validate_paginated(
        api.list_stator_builds(U.PLANT_ADMIN, {"work_order_id": work_order["id"]})
    )
    assert stator_meta["total_count"] == 2
    costed = plant.get_work_order()
    assert costed["rework_reject_count"] == 1
    assert costed["actual_cost_cents"] == 2414212
    A.assert_cost_rollup(costed, F.motor_design_payload(), 12, 1)
    _designs, design_meta = validate_paginated(api.list_motor_designs(U.PLANT_ADMIN))
    assert design_meta["total_count"] == 3


def test_the_cage_fork_is_checked_before_the_bar_count_is_ever_compared(api):
    """Five 409s on two opposite rotor routes, then each fork writes its own triple.

    PRD 3.7: "A method that contradicts the construction, or a payload missing its own
    fork's fields or carrying the other fork's fields, is refused with
    `ERR_ROTOR_CONSTRUCTION_MISMATCH` (HTTP 409)."

    PRD 3.7: "This branch performs one extra cross-check the die-cast branch does not:
    `bar_count` must equal the pinned design's `rotor_bar_count`, and a mismatch is
    refused with `ERR_ROTOR_BAR_COUNT_MISMATCH` (HTTP 409)."

    Design: Corner/validations/cage_method_must_match_the_pinned_construction_before_bar_count_is_even_read
    """
    plant = Plant(api)
    plant.add_distributor()
    aluminium_design = plant.released_design()
    copper_design = plant.add_design(F.premium_motor_design_payload())
    copper_design = plant.release_design(design=copper_design)
    assert aluminium_design["rotor_construction"] == "DIE_CAST_ALUMINUM"
    assert aluminium_design["rotor_bar_count"] == 34
    assert copper_design["rotor_construction"] == "FABRICATED_COPPER"
    assert copper_design["rotor_bar_count"] == 40
    plant.add_order()
    plant.confirm_order()
    aluminium_wo = plant.add_work_order()
    copper_order = plant.add_order(design=copper_design)
    plant.confirm_order(order=copper_order)
    copper_wo = plant.add_work_order(order=copper_order, design=copper_design)
    aluminium_rotor = plant.add_rotor()
    copper_rotor = plant.add_rotor(work_order=copper_wo)
    assert aluminium_rotor["construction"] == "DIE_CAST_ALUMINUM"
    assert copper_rotor["construction"] == "FABRICATED_COPPER"

    wrong_fork = api.form_rotor_cage(
        aluminium_rotor["id"],
        F.brazed_bar_cage_payload(bar_count=34, braze_alloy="AgCu-56"),
        U.BUILD_TECHNICIAN,
    )
    missing_melt_temp = api.form_rotor_cage(
        aluminium_rotor["id"],
        {"cage_method": "DIE_CAST", "die_preheat_c": 250.0},
        U.BUILD_TECHNICIAN,
    )
    foreign_field = api.form_rotor_cage(
        aluminium_rotor["id"],
        F.die_cast_cage_payload(
            melt_temp_c=700.0, die_preheat_c=250.0, braze_alloy="AgCu-56"
        ),
        U.BUILD_TECHNICIAN,
    )
    die_cast_on_copper = api.form_rotor_cage(
        copper_rotor["id"],
        F.die_cast_cage_payload(melt_temp_c=700.0, die_preheat_c=250.0),
        U.BUILD_TECHNICIAN,
    )
    wrong_bar_count = api.form_rotor_cage(
        copper_rotor["id"],
        F.brazed_bar_cage_payload(bar_count=38, braze_alloy="AgCu-56"),
        U.BUILD_TECHNICIAN,
    )

    validate_error(wrong_fork, ERR_ROTOR_CONSTRUCTION_MISMATCH, 409)
    validate_error(missing_melt_temp, ERR_ROTOR_CONSTRUCTION_MISMATCH, 409)
    validate_error(foreign_field, ERR_ROTOR_CONSTRUCTION_MISMATCH, 409)
    validate_error(die_cast_on_copper, ERR_ROTOR_CONSTRUCTION_MISMATCH, 409)
    validate_error(wrong_bar_count, ERR_ROTOR_BAR_COUNT_MISMATCH, 409)
    for untouched in (aluminium_rotor, copper_rotor):
        stored = plant.get_rotor(untouched)
        assert stored["status"] == "PLANNED"
        assert stored["cage_conductivity_ratio"] is None

    cast = plant.form_cage(
        rotor=aluminium_rotor,
        payload=F.die_cast_cage_payload(melt_temp_c=700.0, die_preheat_c=250.0),
    )
    brazed = plant.form_cage(
        rotor=copper_rotor,
        payload=F.brazed_bar_cage_payload(bar_count=40, braze_alloy="AgCu-56"),
    )

    assert cast["status"] == "CAST_POURED"
    A.assert_rounded_to(cast["melt_temp_c"], 700.0, 1, "melt_temp_c")
    A.assert_rounded_to(cast["die_preheat_c"], 250.0, 1, "die_preheat_c")
    assert cast["braze_alloy"] is None
    assert cast["bar_count"] is None
    A.assert_rounded_to(
        cast["cage_conductivity_ratio"], 0.62, 2, "cage_conductivity_ratio"
    )
    A.assert_rounded_to(cast["slip_penalty_pct"], 1.8, 1, "slip_penalty_pct")
    assert cast["rotor_process_cost_cents"] == 18000
    assert brazed["status"] == "BARS_BRAZED"
    assert brazed["braze_alloy"] == "AgCu-56"
    assert brazed["bar_count"] == 40
    assert brazed["melt_temp_c"] is None
    assert brazed["die_preheat_c"] is None
    A.assert_rounded_to(
        brazed["cage_conductivity_ratio"], 1.00, 2, "cage_conductivity_ratio"
    )
    A.assert_rounded_to(brazed["slip_penalty_pct"], 0.6, 1, "slip_penalty_pct")
    assert brazed["rotor_process_cost_cents"] == 47500
    assert plant.get_work_order(aluminium_wo)["rework_reject_count"] == 0
    assert plant.get_work_order(copper_wo)["rework_reject_count"] == 0


def test_assembly_reports_the_shaft_fault_before_the_grease_fault(api):
    """A residual one tenth over the limit, then a body that breaks both metrology bands.

    PRD 3.7: "An `ACCEPTED` disposition additionally requires
    `residual_unbalance_g_mm` to be no greater than that permissible limit — a residual
    exactly equal to the limit is accepted, anything above it is refused with
    `ERR_UNBALANCE_EXCEEDS_GRADE_LIMIT` (HTTP 422) — and moves the build `MACHINED →
    ACCEPTED`."

    PRD 2.11: "The safety, metrology and compliance limits are evaluated after all of
    the above, in this order: `ERR_SLOT_FILL_OUT_OF_RANGE`,
    `ERR_CURE_TEMP_EXCEEDS_OVEN_LIMIT`, `ERR_SURGE_OVERSTRESS`,
    `ERR_SURGE_MARGIN_NEGATIVE`, `ERR_AIR_GAP_OUT_OF_TOLERANCE`,
    `ERR_UNBALANCE_EXCEEDS_GRADE_LIMIT`, `ERR_SHAFT_FIT_OUT_OF_TOLERANCE`,
    `ERR_LUBRICATION_FILL_OUT_OF_RANGE`, `ERR_DESIGN_CLASS_SHORTFALL`,
    `ERR_NO_APPLICABLE_STANDARD`, `ERR_EFFICIENCY_BELOW_REGULATORY_MINIMUM` and
    `ERR_NAMEPLATE_NOT_CERTIFIED`."

    PRD 3.8: "It must fall inside the ISO band for the design's
    `shaft_tolerance_class`, both bounds inclusive: 2 to 18 micrometres for `k6`, 7 to
    25 for `m6`, and -5 to 11 for `j6`."

    Design: Corner/validations/assembly_checks_shaft_fit_before_lubrication_fill_and_accepts_both_inclusive_edges
    """
    plant = build_plant(api, "rotor_machined")
    machined = plant.get_rotor()
    A.assert_rounded_to(machined["measured_air_gap_mm"], 0.450, 3, "measured_air_gap_mm")
    A.assert_rounded_to(
        machined["air_gap_deviation_mm"], 0.000, 3, "air_gap_deviation_mm"
    )
    assert machined["status"] == "MACHINED"
    design = plant.get_design()
    assert design["shaft_diameter_mm"] == 38.000
    assert design["shaft_tolerance_class"] == "k6"
    assert design["lubrication_spec"] == "GREASE_REGREASABLE"

    over_the_limit = api.balance_disposition_rotor_build(
        machined["id"],
        F.balance_disposition_payload(
            initial_unbalance_g_mm=1200.0, residual_unbalance_g_mm=296.1
        ),
        U.TEST_ENGINEER,
    )

    validate_error(over_the_limit, ERR_UNBALANCE_EXCEEDS_GRADE_LIMIT, 422)
    assert plant.get_rotor()["status"] == "MACHINED"

    at_the_limit = plant.balance_rotor(
        "ACCEPTED", initial_unbalance_g_mm=1200.0, residual_unbalance_g_mm=296.0
    )

    A.assert_rounded_to(
        at_the_limit["permissible_unbalance_g_mm"],
        A.expected_permissible_unbalance_g_mm("G2_5", 18.6, 4),
        1,
        "permissible_unbalance_g_mm",
    )
    assert at_the_limit["permissible_unbalance_g_mm"] == 296.0
    assert at_the_limit["status"] == "ACCEPTED"
    work_order = plant.get_work_order()
    assert work_order["build_status"] == "SUBASSEMBLIES_DONE"

    both_bands_broken = api.create_assembly_record(
        F.assembly_record_payload(
            work_order["id"],
            plant.stator["id"],
            machined["id"],
            shaft_measured_diameter_mm=38.001,
            grease_fill_pct=35.00,
        ),
        U.BUILD_TECHNICIAN,
    )
    only_the_grease_broken = api.create_assembly_record(
        F.assembly_record_payload(
            work_order["id"],
            plant.stator["id"],
            machined["id"],
            shaft_measured_diameter_mm=38.010,
            grease_fill_pct=35.00,
        ),
        U.BUILD_TECHNICIAN,
    )
    at_both_upper_edges = api.create_assembly_record(
        F.assembly_record_payload(
            work_order["id"],
            plant.stator["id"],
            machined["id"],
            shaft_measured_diameter_mm=38.018,
            grease_fill_pct=60.00,
        ),
        U.BUILD_TECHNICIAN,
    )

    validate_error(both_bands_broken, ERR_SHAFT_FIT_OUT_OF_TOLERANCE, 422)
    validate_error(only_the_grease_broken, ERR_LUBRICATION_FILL_OUT_OF_RANGE, 422)
    built = validate_success(at_both_upper_edges, 201)
    assert built["status"] == "BUILT"
    assert built["shaft_fit_deviation_um"] == A.expected_shaft_fit_deviation_um(
        38.018, 38.000
    )
    assert built["shaft_fit_deviation_um"] == 18
    A.assert_rounded_to(built["grease_fill_pct"], 60.00, 2, "grease_fill_pct")
    assert built["lubrication_spec_applied"] == "GREASE_REGREASABLE"
    assert built["assembler_user_id"] == U.USER_BUILD_TECHNICIAN
    assembled = plant.get_work_order()
    assert assembled["build_status"] == "ASSEMBLED"
    assert assembled["rework_reject_count"] == 0
    _records, meta = validate_paginated(
        api.list_assembly_records(U.PLANT_ADMIN, {"work_order_id": work_order["id"]})
    )
    assert meta["total_count"] == 1


def test_only_a_stock_replenish_order_from_an_unenrolled_partner_is_refused(api):
    """The same confirm succeeds for another order type and for an enrolled partner.

    PRD 3.4: "A `STOCK_REPLENISH` order additionally requires the distributor's
    `stocking_program_enrolled` flag to be true, or the confirmation is refused with
    `ERR_STOCKING_PROGRAM_NOT_ENROLLED` (HTTP 409); other order types are indifferent
    to enrolment."

    Design: Corner/validations/stock_replenish_confirm_applies_only_to_enrolled_distributors
    """
    plant = Plant(api)
    unenrolled = plant.add_distributor(
        name="Eastgate Motor Supply", stocking_program_enrolled=False
    )
    enrolled = plant.add_extra_distributor(
        name="Westgate Motor Supply", stocking_program_enrolled=True
    )
    assert unenrolled["stocking_program_enrolled"] is False
    assert enrolled["stocking_program_enrolled"] is True
    plant.released_design()
    replenish_unenrolled = plant.add_order(order_type="STOCK_REPLENISH", quantity=10)
    made_to_order = plant.add_order(order_type="MADE_TO_ORDER", quantity=12)
    replenish_enrolled = plant.add_order(
        distributor=enrolled, order_type="STOCK_REPLENISH", quantity=10
    )

    refused = api.confirm_customer_order(
        replenish_unenrolled["id"], F.confirm_order_payload(), U.PRODUCTION_PLANNER
    )

    validate_error(refused, ERR_STOCKING_PROGRAM_NOT_ENROLLED, 409)
    still_draft = plant.get_order(replenish_unenrolled)
    assert still_draft["status"] == "DRAFT"
    assert still_draft["confirmed_at"] is None
    assert plant.get_distributor(unenrolled)["units_outstanding"] == 0

    confirmed_made_to_order = plant.confirm_order(order=made_to_order)
    confirmed_replenish = plant.confirm_order(order=replenish_enrolled)

    assert confirmed_made_to_order["status"] == "CONFIRMED"
    assert confirmed_made_to_order["promised_lead_time_days"] == 29
    assert confirmed_made_to_order["promised_ship_date"] == "2026-08-30"
    unenrolled_ledger = plant.get_distributor(unenrolled)
    assert unenrolled_ledger["units_outstanding"] == 12
    assert unenrolled_ledger["stock_allowance_remaining_units"] == 488
    assert confirmed_replenish["status"] == "CONFIRMED"
    assert confirmed_replenish["promised_lead_time_days"] == 6
    assert confirmed_replenish["promised_lead_time_days"] == A.expected_lead_time_days(
        "STOCK_REPLENISH", "EU", "GOLD", 10, 10
    )
    assert confirmed_replenish["promised_ship_date"] == "2026-08-07"
    enrolled_ledger = plant.get_distributor(enrolled)
    assert enrolled_ledger["units_outstanding"] == 10
    assert enrolled_ledger["stock_allowance_remaining_units"] == 490


def test_confirm_compares_the_request_against_the_recomputed_promise(api):
    """One day short is refused, the promise date exactly passes, seven added days refuse again.

    PRD 3.4: "The lead time is then recomputed from the *current* logical clock date,
    and the resulting `promised_ship_date` must fall on or before
    `requested_ship_date`; a date that slips past the request is refused with
    `ERR_SHIP_DATE_UNACHIEVABLE` (HTTP 422)."

    Design: Corner/validations/confirm_rejects_a_requested_date_the_recomputed_promise_cannot_reach
    """
    plant = Plant(api)
    distributor = plant.add_distributor()
    plant.released_design()
    one_day_short = plant.add_order(requested_ship_date="2026-08-29")
    exactly_on_the_promise = plant.add_order(requested_ship_date="2026-08-30")
    pushed_out_by_the_mounting = plant.add_order(
        requested_ship_date="2026-08-30",
        special_requirements={"non_standard_mounting": True},
    )
    assert one_day_short["promised_ship_date"] == "2026-08-30"
    assert pushed_out_by_the_mounting["promised_lead_time_days"] == 36

    short = api.confirm_customer_order(
        one_day_short["id"], F.confirm_order_payload(), U.PRODUCTION_PLANNER
    )

    validate_error(short, ERR_SHIP_DATE_UNACHIEVABLE, 422)
    assert plant.get_order(one_day_short)["status"] == "DRAFT"
    assert plant.get_distributor(distributor)["units_outstanding"] == 0

    confirmed = plant.confirm_order(order=exactly_on_the_promise)
    special = api.confirm_customer_order(
        pushed_out_by_the_mounting["id"],
        F.confirm_order_payload(),
        U.PRODUCTION_PLANNER,
    )

    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["promised_lead_time_days"] == 29
    assert confirmed["promised_ship_date"] == "2026-08-30"
    validate_error(special, ERR_SHIP_DATE_UNACHIEVABLE, 422)
    unconfirmed = plant.get_order(pushed_out_by_the_mounting)
    assert unconfirmed["status"] == "DRAFT"
    assert unconfirmed["special_requirements"] == {"non_standard_mounting": True}
    assert unconfirmed["promised_ship_date"] == "2026-09-06"
    ledger = plant.get_distributor(distributor)
    assert ledger["units_outstanding"] == 12
    assert ledger["stock_allowance_remaining_units"] == 488


def test_ownership_is_keyed_on_the_row_not_on_the_caller_role(api):
    """Four 403s across two ownership keys, then the same call from its owner succeeds.

    PRD 2.1: "A `Distributor` caller may therefore only create, read or act on a
    customer order or a warranty claim whose `distributor_id` equals its own
    `X-User-ID`, and any attempt to reach another distributor's order or claim —
    including supplying a foreign `distributor_id` in a creation payload — is rejected
    with `ERR_NOT_OWNER` (HTTP 403)."

    PRD 2.1: "Two of those recorded values are compared to a later caller's
    `X-User-ID` for ownership rather than separation: only the authoring engineer,
    identified by `created_by_user_id`, may submit their own design for review or
    reopen it for revision, and a different `DesignEngineer` attempting either is
    rejected with `ERR_NOT_OWNER`."

    Design: Corner/validations/only_the_owning_distributor_and_the_authoring_engineer_may_act_on_a_row
    """
    plant = Plant(api)
    owner = plant.add_distributor(name="Northwind Motor Distribution")
    outsider = plant.add_extra_distributor(name="Southwind Motor Distribution")
    released = plant.released_design()
    still_draft = plant.add_design(F.economy_motor_design_payload())
    owners_order = plant.add_order()
    assert released["created_by_user_id"] == U.USER_DESIGN_ENGINEER
    assert still_draft["created_by_user_id"] == U.USER_DESIGN_ENGINEER
    assert owners_order["distributor_id"] == owner["id"]
    outsider_headers = U.make_distributor_headers(outsider["id"])

    creating_for_another_owner = api.create_customer_order(
        F.customer_order_payload(owner["id"], released["id"]), outsider_headers
    )
    reading_another_owners_row = api.get_customer_order(
        owners_order["id"], outsider_headers
    )
    submitting_another_engineers_draft = api.submit_design_review(
        still_draft["id"], F.submit_review_payload(), U.DESIGN_ENGINEER_OTHER
    )
    reopening_another_engineers_release = api.open_design_revision(
        released["id"], F.open_revision_payload(), U.DESIGN_ENGINEER_OTHER
    )

    validate_error(creating_for_another_owner, ERR_NOT_OWNER, 403)
    _orders, meta = validate_paginated(api.list_customer_orders(U.PLANT_ADMIN))
    assert meta["total_count"] == 1
    validate_error(reading_another_owners_row, ERR_NOT_OWNER, 403)
    validate_error(submitting_another_engineers_draft, ERR_NOT_OWNER, 403)
    assert plant.get_design(still_draft)["status"] == "DRAFT"
    validate_error(reopening_another_engineers_release, ERR_NOT_OWNER, 403)
    untouched = plant.get_design(released)
    assert untouched["status"] == "RELEASED"
    assert untouched["revision_index"] == 0

    by_its_author = plant.submit_design(design=still_draft)

    assert by_its_author["status"] == "IN_REVIEW"
    assert by_its_author["review_round"] == 0
    assert by_its_author["created_by_user_id"] == U.USER_DESIGN_ENGINEER


def test_the_jurisdiction_gate_answers_before_the_standard_selector_runs(api):
    """Four refusals around one tested motor while the standards table fills in.

    PRD 3.9: "The `jurisdiction` on the request must equal the `jurisdiction` of the
    `CustomerOrder` that owns the work order — a motor built for a European order
    cannot be certified to a Chinese standard — and a mismatch is refused with
    `ERR_JURISDICTION_MISMATCH` (HTTP 409)."

    PRD 3.9: "If the eligible set is empty, no fallback standard is invented and the
    request is refused with `ERR_NO_APPLICABLE_STANDARD` (HTTP 422)."

    PRD 3.9: "The cited test's `measured_efficiency_pct` must be greater than or equal
    to that minimum; exactly equal passes, and anything below is refused with
    `ERR_EFFICIENCY_BELOW_REGULATORY_MINIMUM` (HTTP 422)."

    Design: Corner/validations/nameplate_jurisdiction_outranks_the_standard_and_efficiency_gates
    """
    plant = Plant(api)
    plant.add_distributor()
    plant.add_oven()
    plant.add_cell()
    plant.released_design()
    plant.add_order()
    plant.confirm_order()
    work_order = plant.add_work_order()
    plant.accepted_stator()
    plant.accepted_rotor()
    plant.add_assembly()
    plant.schedule_test()
    recorded = plant.record_test()
    A.assert_performance_test_figures(
        recorded, F.record_results_payload(), "IEC_60034_2_1_SUMMATION", 4
    )
    assert recorded["measured_efficiency_pct"] == 93.42
    assert recorded["achieved_class"] == "IE3"
    assert recorded["status"] == "COMPLETED"
    assert plant.get_work_order()["build_status"] == "TESTED"
    _empty, standard_meta = validate_paginated(
        api.list_regulatory_standards(U.PLANT_ADMIN)
    )
    assert standard_meta["total_count"] == 0

    with_no_rows_at_all = api.create_nameplate(
        F.nameplate_payload(work_order["id"], recorded["id"], jurisdiction="EU"),
        U.QUALITY_CERTIFIER,
    )
    united_states = plant.add_standard(
        standard_code="US-DOE-2016-IE3-4P",
        jurisdiction="US",
        minimum_efficiency_pct=89.60,
        effective_from="2016-06-01",
    )
    with_only_a_us_row = api.create_nameplate(
        F.nameplate_payload(work_order["id"], recorded["id"], jurisdiction="EU"),
        U.QUALITY_CERTIFIER,
    )
    for_the_wrong_jurisdiction = api.create_nameplate(
        F.nameplate_payload(work_order["id"], recorded["id"], jurisdiction="CN"),
        U.QUALITY_CERTIFIER,
    )
    strict = plant.add_standard(
        standard_code="EU-2019-1781-IE3-4P-STRICT",
        minimum_efficiency_pct=95.00,
        effective_from="2024-01-01",
    )
    below_the_strict_minimum = api.create_nameplate(
        F.nameplate_payload(work_order["id"], recorded["id"], jurisdiction="EU"),
        U.QUALITY_CERTIFIER,
    )

    validate_error(with_no_rows_at_all, ERR_NO_APPLICABLE_STANDARD, 422)
    validate_error(with_only_a_us_row, ERR_NO_APPLICABLE_STANDARD, 422)
    validate_error(for_the_wrong_jurisdiction, ERR_JURISDICTION_MISMATCH, 409)
    validate_error(below_the_strict_minimum, ERR_EFFICIENCY_BELOW_REGULATORY_MINIMUM, 422)
    assert plant.get_work_order()["certification_status"] == "PENDING"
    _nameplates, nameplate_meta = validate_paginated(api.list_nameplates(U.PLANT_ADMIN))
    assert nameplate_meta["total_count"] == 0

    governing = plant.add_standard(
        standard_code="EU-2019-1781-IE3-4P",
        minimum_efficiency_pct=89.60,
        effective_from="2025-06-01",
    )
    issued = plant.issue_nameplate()

    assert issued["status"] == "ISSUED"
    assert issued["standard_id"] == governing["id"]
    assert issued["standard_id"] != strict["id"]
    assert issued["standard_id"] != united_states["id"]
    A.assert_rounded_to(
        issued["minimum_efficiency_pct_applied"],
        89.60,
        2,
        "minimum_efficiency_pct_applied",
    )
    assert issued["stamped_efficiency_pct"] == 93.42
    assert issued["stamped_class"] == "IE3"
    assert issued["certifier_user_id"] == U.USER_QUALITY_CERTIFIER
    assert plant.get_work_order()["certification_status"] == "CERTIFIED"


def test_results_are_refused_until_the_logical_clock_reaches_the_window(api):
    """Four days early, one millisecond early, then accepted on the boundary instant.

    PRD 3.8: "The test must be in `SCHEDULED`
    (`ERR_INVALID_PERFORMANCE_TEST_STATE`), must not carry `requires_requalification`
    (`ERR_REQUALIFICATION_REQUIRED`, HTTP 409 — a test flagged by a design revision
    must be superseded by a freshly scheduled test rather than recorded), and the
    logical clock must have reached or passed `window_start`, or the request is refused
    with `ERR_TEST_WINDOW_NOT_STARTED` (HTTP 409)."

    Design: Corner/validations/results_cannot_be_recorded_before_the_test_window_opens
    """
    plant = build_plant(api, "test_scheduled")
    scheduled = plant.get_test()
    assert scheduled["status"] == "SCHEDULED"
    assert scheduled["window_start"] == F.TEST_WINDOW_START
    assert plant.get_work_order()["build_status"] == "ASSEMBLED"

    four_days_early = api.record_performance_test(
        scheduled["id"], F.record_results_payload(), U.TEST_ENGINEER
    )
    plant.set_clock(ONE_MILLISECOND_EARLY)
    one_millisecond_early = api.record_performance_test(
        scheduled["id"], F.record_results_payload(), U.TEST_ENGINEER
    )

    validate_error(four_days_early, ERR_TEST_WINDOW_NOT_STARTED, 409)
    validate_error(one_millisecond_early, ERR_TEST_WINDOW_NOT_STARTED, 409)
    refused = plant.get_test()
    assert refused["status"] == "SCHEDULED"
    assert refused["recorded_at"] is None
    assert refused["measured_efficiency_pct"] is None
    assert plant.get_work_order()["build_status"] == "ASSEMBLED"

    plant.set_clock(F.TEST_WINDOW_START)
    completed = plant.record_test(advance_clock=False)

    assert completed["status"] == "COMPLETED"
    A.assert_performance_test_figures(
        completed, F.record_results_payload(), "IEC_60034_2_1_SUMMATION", 4
    )
    assert completed["measured_efficiency_pct"] == 93.42
    assert completed["stator_loss_corrected_w"] == 221.0
    assert completed["stray_load_loss_w"] == 40.1
    assert completed["total_loss_w"] == 528.1
    assert completed["achieved_class"] == "IE3"
    assert completed["recorded_at"] == F.TEST_WINDOW_START
    assert completed["test_engineer_user_id"] == U.USER_TEST_ENGINEER
    assert plant.get_work_order()["build_status"] == "TESTED"


def test_the_path_identifier_is_reported_before_the_body_foreign_key(api):
    """One endpoint carrying both kinds of identifier, six ways of getting it wrong.

    PRD 2.11: "Existence checks follow: path identifiers first, then body foreign keys,
    as described in §2.6."

    PRD 2.11: "Authentication comes first (`ERR_UNAUTHENTICATED`), then endpoint role
    authorisation (`ERR_UNAUTHORIZED`), then row ownership (`ERR_NOT_OWNER`), then
    segregation of duties (`ERR_SEGREGATION_OF_DUTIES`)."

    Design: Corner/validations/path_existence_is_reported_before_body_foreign_keys_but_after_role_and_schema
    """
    plant = Plant(api)
    plant.add_distributor()
    oven = plant.add_oven(oven_code="OVEN-A")
    plant.released_design()
    plant.add_order()
    plant.confirm_order()
    plant.add_work_order()
    stator = plant.add_stator()
    assert stator["status"] == "WOUND"

    unknown_body_work_order = api.create_stator_build(
        F.stator_build_payload(NON_EXISTENT_UUID), U.BUILD_TECHNICIAN
    )
    unknown_path_only = api.impregnate_stator_build(
        NON_EXISTENT_UUID, F.impregnation_payload(oven["id"]), U.BUILD_TECHNICIAN
    )
    both_unknown = api.impregnate_stator_build(
        NON_EXISTENT_UUID,
        F.impregnation_payload(NON_EXISTENT_UUID),
        U.BUILD_TECHNICIAN,
    )
    unknown_body_oven = api.impregnate_stator_build(
        stator["id"], F.impregnation_payload(NON_EXISTENT_UUID), U.BUILD_TECHNICIAN
    )
    both_unknown_as_the_wrong_role = api.impregnate_stator_build(
        NON_EXISTENT_UUID, F.impregnation_payload(NON_EXISTENT_UUID), U.TEST_ENGINEER
    )
    both_unknown_with_an_inverted_window = api.impregnate_stator_build(
        NON_EXISTENT_UUID,
        F.impregnation_payload(NON_EXISTENT_UUID, **INVERTED_WINDOW),
        U.BUILD_TECHNICIAN,
    )

    validate_error(unknown_body_work_order, ERR_WORK_ORDER_NOT_FOUND, 404)
    validate_error(unknown_path_only, ERR_SUBASSEMBLY_NOT_FOUND, 404)
    validate_error(both_unknown, ERR_SUBASSEMBLY_NOT_FOUND, 404)
    validate_error(unknown_body_oven, ERR_OVEN_NOT_FOUND, 404)
    validate_error(both_unknown_as_the_wrong_role, ERR_UNAUTHORIZED, 403)
    validate_error(both_unknown_with_an_inverted_window, ERR_INVALID_REQUEST, 400)
    untouched = plant.get_stator(stator)
    assert untouched["status"] == "WOUND"
    assert untouched["oven_id"] is None
    assert plant.get_oven(oven)["booked_minutes"] == 0
