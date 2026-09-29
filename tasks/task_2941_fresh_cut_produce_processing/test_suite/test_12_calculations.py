"""The derived figures: organic load, tiers, dwell, shelf life and risk.

Each rule here is walked at the position where an implementation is most
likely to differ from the contract: on a breakpoint, at a cap, at a floor, or
just outside a window whose edge decides whether a measurement counts.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    LINE_OPERATOR_HEADERS,
    PLANT_ADMIN_HEADERS,
    QA_MANAGER_HEADERS,
    SHIPPING_CLERK_HEADERS,
)

HTTP_CREATED = 201
NO_TRIM_LB = 0.00
COOL_PULP_TEMP_C = 2.0

# A thousand-gallon flume, so thirty thousand leafy pounds land on the ceiling.
SMALL_FLUME_CODE = "W2"
SMALL_FLUME_GAL = 1000.00
SMALL_FLUME_MAX_RUNS = 1
CEILING_DRAW_LB = 30000.00
CEILING_WEIGHTED_LB = 30000.00
EXHAUSTED_READING_PPM = 26.0
RESET_WEIGHTED_LB = 0.00
RESET_INDEX = 0.000
FIRST_CHANGEOUT = 1

# The window of the second run on the same line, after the first one's.
SECOND_WINDOW_START_AT = "2026-08-03T13:00:00Z"
SECOND_WINDOW_END_AT = "2026-08-03T15:00:00Z"

# The three draws that walk the two tier breakpoints on a 4000-gallon flume.
BREAKPOINT_FLUME_CODE = "W3"
SECOND_LOAD_RECEIVED_AT = "2026-08-02T06:00:00Z"
SECOND_LOAD_GROSS_LB = 45000.00
SECOND_LOAD_TARE_LB = 1000.00
SECOND_LOAD_ACCEPTED_LB = 44000.00
BASE_TIER_DRAW_LB = 19960.00
BASE_TIER_INDEX = 0.499
MID_TIER_DRAW_LB = 40.00
MID_TIER_WEIGHTED_LB = 20000.00
MID_TIER_INDEX = 0.500
HIGH_TIER_DRAW_LB = 40000.00
HIGH_TIER_WEIGHTED_LB = 60000.00
HIGH_TIER_INDEX = 1.500

# A second line and a root-commodity product with its own foodservice spec.
SECOND_LINE_CODE = "L2"
SECOND_LINE_COMPONENT_COUNT = 10
CELERY_CASE_NET_WEIGHT_LB = 25.0
CELERY_MIN_REMAINING_DAYS = 5
CELERY_READING_PPM = 25.0
CELERY_CREW_SIZE = 5
FROZEN_DWELL_SECONDS = 90
ROOT_LOT_OVERRIDES = {
    "grower_code": "GRW-700",
    "ranch_block": "B7",
    "commodity_class": c.COMMODITY_ROOT,
    "harvest_datetime": "2026-08-01T08:00:00Z",
    "water_source": c.WATER_WELL,
}
ROOT_LOAD_OVERRIDES = {
    "received_at": "2026-08-02T05:30:00Z",
    "pulp_temp_c": COOL_PULP_TEMP_C,
    "gross_weight_lb": 21000.00,
    "tare_weight_lb": 1000.00,
}
ROOT_DRAW_LB = 12000.00
ROOT_WEIGHTED_LB = 21600.00
ROOT_INDEX = 0.540
MISMATCHED_DRAW_LB = 100.00

# A fortnight-old root lot whose warm load costs two more days of life.
OLD_LOT_OVERRIDES = {
    "grower_code": "GRW-800",
    "ranch_block": "B8",
    "commodity_class": c.COMMODITY_ROOT,
    "harvest_datetime": "2026-07-20T08:00:00Z",
    "water_source": c.WATER_WELL,
}
WARM_LOAD_OVERRIDES = {
    "received_at": "2026-08-02T05:30:00Z",
    "pulp_temp_c": 5.0,
    "gross_weight_lb": 7000.00,
    "tare_weight_lb": 1000.00,
}
WARM_LOAD_NET_LB = 6000.00
WARM_LOAD_JUSTIFICATION = (
    "Chilled to 2.1 C within 40 minutes of receipt and re-verified by QA"
)
FLOOR_DRAW_LB = 5000.00
FLOOR_READING_AT = "2026-08-03T08:00:00Z"
CLOCK_FLOOR_READING = "2026-08-03T08:00:00Z"
CLOCK_FLOOR_CLOSE = "2026-08-03T09:00:00Z"
FLOOR_CLOSE_OVERRIDES = {
    "actual_dwell_seconds": 130,
    "spin_rpm": 700,
    "spin_seconds": 40,
    "atmosphere_actual": c.ATMOSPHERE_MAP_LOW_O2,
    "water_gal_used": 5000.00,
    "cases_produced": 120,
}
FLOOR_CASES_PRODUCED = 120
FLOOR_OUTPUT_LB = 3000.00
FLOOR_YIELD_PCT = 60.00
FLOOR_SHELF_LIFE_DAYS = 3
FLOOR_CODE_DATE = "2026-08-06"
FLOOR_JULIAN_LABEL = "2026218"
NO_EXCURSIONS = 0

# The one in-window reading that falls below the product's own minimum.
LOW_READING_PPM = 19.5
LOADED_INDEX = 0.750
LOADED_TARGET_PPM = 35.0
LOW_READING_TOPUP_PPM = 15.5
ONE_EXCURSION = 1
EXPECTED_HOLD_COUNT = 2

# Two graded lots differing only in the length of their rejection history.
FOUR_PRIOR_REJECTS = 4
FORTY_PRIOR_REJECTS = 40
CAPPED_SCORE = 80
CAP_LOT_A_OVERRIDES = {
    "grower_code": "GRW-A04",
    "ranch_block": "B1",
    "harvest_datetime": "2026-08-01T08:00:00Z",
    "water_source": c.WATER_WELL,
    "prior_rejected_receipt_count": FOUR_PRIOR_REJECTS,
}
CAP_LOT_B_OVERRIDES = dict(
    CAP_LOT_A_OVERRIDES,
    grower_code="GRW-A40",
    prior_rejected_receipt_count=FORTY_PRIOR_REJECTS,
)

# The retail revision whose generous offer cannot lift the product's window.
RETAIL_CASE_NET_WEIGHT_LB = 12.5
RETAIL_MIN_REMAINING_DAYS = 8
FIRST_SPEC_REVISION = 1
SPECS_BEFORE_RETAIL = 1
SPECS_AFTER_RETAIL = 2
RETAIL_READING_PPM = 36.0
RETAIL_CASES_PRODUCED = 1440
RETAIL_OUTPUT_LB = 18000.00
RETAIL_YIELD_PCT = 60.00
RETAIL_SHELF_LIFE_DAYS = 16
RETAIL_CODE_DATE = "2026-08-19"
RETAIL_WATER_GAL_USED = 12000.00
SECOND_CASE_CODE = "L1-20260803-0002"
FIRST_TWO_CASES = 2


def test_an_index_of_exactly_three_exhausts_the_water_and_a_changeout_resets_it(api):
    """Thirty thousand pounds in a thousand-gallon flume hit the ceiling exactly.

    PRD: An index of 3.000 or greater exhausts the water: the system moves `IN_SERVICE → DUMP_REQUIRED` and `target_free_chlorine_ppm` is set to null, because no chlorine tier is defined above the change-out ceiling.
    PRD: The run's wash system must have `status` of `IN_SERVICE`; a system awaiting a dump is refused with `ERR_WASH_SYSTEM_DUMP_REQUIRED` (HTTP 422).
    PRD: The change-out sets `last_changeout_at` to the logical clock's current instant, increments `changeout_count` by 1 and sets `status` to `IN_SERVICE`.
    PRD: Because the load window now begins at the new change-out instant, no consumption falls inside it, so the recomputation resets `weighted_load_lb` to 0, `organic_load_index` to 0.000 and `target_free_chlorine_ppm` to 20.0.

    Design: Corner/calculations/corner_load_index_at_exact_ceiling_forces_changeout_and_reset
    """
    world = fx.build_world(api, stop_after=fx.STOP_SANITATION_VALIDATED)
    small = fx.create_wash_system(
        api,
        system_code=SMALL_FLUME_CODE,
        water_volume_gal=SMALL_FLUME_GAL,
        max_concurrent_runs=SMALL_FLUME_MAX_RUNS,
    )
    first = fx.plan_run(
        api, world.line_id, world.product_id, world.spec_id, small["id"]
    )
    fx.set_clock(api, c.CLOCK_PRE_START)
    fx.create_reading(
        api, small["id"], c.READING_PRE_START_AT, c.READING_PRE_START_PPM
    )
    fx.set_clock(api, c.CLOCK_START)
    started = fx.start_run(api, first["id"])
    assert started["target_ppm_at_start"] == c.TARGET_PPM_TIER_BASE, (
        "the run froze its target before its own pounds existed"
    )

    fx.consume(
        api, first["id"], world.receipt_id, started["version"], CEILING_DRAW_LB
    )
    exhausted = fx.read_wash_system(api, small["id"])
    a.assert_wash_chemistry(
        exhausted,
        weighted_load_lb=CEILING_WEIGHTED_LB,
        organic_load_index=c.LOAD_INDEX_CHANGEOUT_CEILING,
        status=c.WASH_DUMP_REQUIRED,
    )
    assert exhausted["target_free_chlorine_ppm"] is None, (
        "the ceiling comparison is inclusive, so exactly 3.000 leaves no tier"
    )

    fx.set_clock(api, c.CLOCK_MID_RUN)
    reading = fx.create_reading(
        api, small["id"], c.READING_MID_RUN_AT, EXHAUSTED_READING_PPM
    )
    assert reading["organic_load_index_at_reading"] == (
        c.LOAD_INDEX_CHANGEOUT_CEILING
    )
    assert reading["target_free_chlorine_ppm_at_reading"] is None

    second = fx.plan_run(
        api,
        world.line_id,
        world.product_id,
        world.spec_id,
        small["id"],
        planned_start_at=SECOND_WINDOW_START_AT,
        planned_end_at=SECOND_WINDOW_END_AT,
    )
    fx.set_clock(api, SECOND_WINDOW_START_AT)
    validate_error(
        api.start_process_run(second["id"], LINE_OPERATOR_HEADERS),
        ApiErrorId.WASH_SYSTEM_DUMP_REQUIRED,
    )

    recharged = fx.changeout_wash_system(api, small["id"])
    a.assert_wash_chemistry(
        recharged,
        weighted_load_lb=RESET_WEIGHTED_LB,
        organic_load_index=RESET_INDEX,
        target_free_chlorine_ppm=c.TARGET_PPM_TIER_BASE,
        status=c.WASH_IN_SERVICE,
    )
    assert recharged["changeout_count"] == FIRST_CHANGEOUT
    a.assert_instant_equals(
        recharged["last_changeout_at"], SECOND_WINDOW_START_AT, "last_changeout_at"
    )
    # The reset moved the window, so the pounds themselves are still on the run.
    assert fx.read_run(api, first["id"])["input_lb"] == CEILING_DRAW_LB


def test_both_tier_breakpoints_are_inclusive_on_the_lower_side(api):
    """0.499 stays at 20.0, exactly 0.500 buys 35.0, and exactly 1.500 buys 55.0.

    PRD: `organic_load_index` is the weighted load divided by the product of the system's `water_volume_gal` and a normalising constant of 10, rounded half-up to exactly three decimal places.
    PRD: Otherwise, an index of 1.500 or greater sets `target_free_chlorine_ppm` to 55.0; an index of 0.500 or greater sets it to 35.0; and anything below that sets it to 20.0.
    PRD: An index of exactly 0.500 therefore targets 35.0, exactly 1.500 targets 55.0, and exactly 3.000 forces a change-out.

    Design: Corner/calculations/corner_tier_breakpoints_are_inclusive_lower
    """
    world = fx.build_world(api, stop_after=fx.STOP_SANITATION_VALIDATED)
    flume = fx.create_wash_system(api, system_code=BREAKPOINT_FLUME_CODE)
    bulk_load = fx.create_receipt(
        api,
        world.grower_lot_id,
        received_at=SECOND_LOAD_RECEIVED_AT,
        pulp_temp_c=COOL_PULP_TEMP_C,
        gross_weight_lb=SECOND_LOAD_GROSS_LB,
        tare_weight_lb=SECOND_LOAD_TARE_LB,
    )
    bulk_load = fx.disposition_receipt(
        api, bulk_load["id"], c.DECISION_ACCEPT, trim_loss_lb=NO_TRIM_LB
    )
    assert bulk_load["accepted_lb"] == SECOND_LOAD_ACCEPTED_LB

    run = fx.plan_run(
        api, world.line_id, world.product_id, world.spec_id, flume["id"]
    )
    fx.set_clock(api, c.CLOCK_PRE_START)
    fx.create_reading(
        api, flume["id"], c.READING_PRE_START_AT, c.READING_PRE_START_PPM
    )
    fx.set_clock(api, c.CLOCK_START)
    running = fx.start_run(api, run["id"])

    fx.consume(
        api, run["id"], world.receipt_id, running["version"], BASE_TIER_DRAW_LB
    )
    a.assert_wash_chemistry(
        fx.read_wash_system(api, flume["id"]),
        weighted_load_lb=BASE_TIER_DRAW_LB,
        organic_load_index=BASE_TIER_INDEX,
        target_free_chlorine_ppm=c.TARGET_PPM_TIER_BASE,
        status=c.WASH_IN_SERVICE,
    )

    fx.consume(
        api,
        run["id"],
        world.receipt_id,
        fx.read_run(api, run["id"])["version"],
        MID_TIER_DRAW_LB,
    )
    a.assert_wash_chemistry(
        fx.read_wash_system(api, flume["id"]),
        weighted_load_lb=MID_TIER_WEIGHTED_LB,
        organic_load_index=MID_TIER_INDEX,
        target_free_chlorine_ppm=c.TARGET_PPM_TIER_MID,
        status=c.WASH_IN_SERVICE,
    )

    fx.consume(
        api,
        run["id"],
        bulk_load["id"],
        fx.read_run(api, run["id"])["version"],
        HIGH_TIER_DRAW_LB,
    )
    a.assert_wash_chemistry(
        fx.read_wash_system(api, flume["id"]),
        weighted_load_lb=HIGH_TIER_WEIGHTED_LB,
        organic_load_index=HIGH_TIER_INDEX,
        target_free_chlorine_ppm=c.TARGET_PPM_TIER_HIGH,
        status=c.WASH_IN_SERVICE,
    )


def test_root_pounds_weigh_one_and_four_fifths_against_the_flume(api):
    """Twelve thousand root pounds load the water like twenty-one thousand six hundred.

    PRD: Each surviving consumption contributes its `consumed_lb` multiplied by the load factor of the commodity class of the product its run was packing: 1.0 for `LEAFY`, 1.8 for `ROOT`, and 0.5 for `FRUIT`.
    PRD: Those contributions are added together and the sum, rounded half-up to two decimal places, becomes `weighted_load_lb`.
    PRD: On a line that has never run anything, `last_run_allergen_group` is null and no changeover is required.
    PRD: The grower lot's `commodity_class` must equal the `commodity_class` of the product the run is packing; a mismatch is refused with `ERR_COMMODITY_CLASS_MISMATCH` (HTTP 422).

    Design: Corner/calculations/corner_root_commodity_load_factor_scales_the_index
    """
    world = fx.build_world(api, stop_after=fx.STOP_RECEIPT_ACCEPTED)
    celery = validate_success(
        api.create_product(f.celery_product_payload(), PLANT_ADMIN_HEADERS),
        HTTP_CREATED,
    )
    celery_spec = validate_success(
        api.create_customer_spec(
            celery["id"],
            f.customer_spec_payload(
                celery["version"],
                case_net_weight_lb=CELERY_CASE_NET_WEIGHT_LB,
                min_remaining_shelf_life_days_at_ship=CELERY_MIN_REMAINING_DAYS,
            ),
            PLANT_ADMIN_HEADERS,
        ),
        HTTP_CREATED,
    )
    second_line = fx.create_line(
        api,
        line_code=SECOND_LINE_CODE,
        required_disassembly_component_count=SECOND_LINE_COMPONENT_COUNT,
    )
    root_lot = fx.approved_grower_lot(api, **ROOT_LOT_OVERRIDES)
    root_load = fx.create_receipt(api, root_lot["id"], **ROOT_LOAD_OVERRIDES)
    root_load = fx.disposition_receipt(
        api, root_load["id"], c.DECISION_ACCEPT, trim_loss_lb=NO_TRIM_LB
    )
    fx.validated_sanitation(api, second_line["id"])

    run = fx.plan_run(
        api,
        second_line["id"],
        celery["id"],
        celery_spec["id"],
        world.wash_system_id,
        crew_size=CELERY_CREW_SIZE,
    )
    assert run["allergen_changeover_required"] is False, (
        "the second line has never packed anything, so the celery group needs no clean"
    )
    fx.set_clock(api, c.CLOCK_PRE_START)
    fx.create_reading(
        api, world.wash_system_id, c.READING_PRE_START_AT, CELERY_READING_PPM
    )
    fx.set_clock(api, c.CLOCK_START)
    running = fx.start_run(api, run["id"])
    assert running["target_ppm_at_start"] == c.TARGET_PPM_TIER_BASE
    assert running["required_dwell_seconds_at_start"] == FROZEN_DWELL_SECONDS

    drawn = fx.consume(
        api, run["id"], root_load["id"], running["version"], ROOT_DRAW_LB
    )
    assert drawn["consumed_lb"] == ROOT_DRAW_LB
    a.assert_wash_chemistry(
        fx.read_wash_system(api, world.wash_system_id),
        weighted_load_lb=ROOT_WEIGHTED_LB,
        organic_load_index=ROOT_INDEX,
        target_free_chlorine_ppm=c.TARGET_PPM_TIER_MID,
        status=c.WASH_IN_SERVICE,
    )

    # A leafy load cannot be fed to a root run, so one run's pounds never mix factors.
    validate_error(
        api.create_lot_consumption(
            run["id"],
            f.lot_consumption_payload(
                world.receipt_id,
                fx.read_run(api, run["id"])["version"],
                MISMATCHED_DRAW_LB,
            ),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.COMMODITY_CLASS_MISMATCH,
    )


def test_the_three_day_floor_is_applied_to_the_total_and_not_to_each_penalty(api):
    """Penalties of two, twelve and one against a base of twelve still leave three days.

    PRD: The shelf life in days is then the base window less all four penalties, floored at three days — and the floor is applied last, to the total, not to each term: a base of 12 with penalties totalling 11 yields 3, not 1.
    PRD: The grace day is subtracted *after* the lag has been reduced to whole days, so 47 elapsed hours give one lag day and no penalty, while 51 elapsed hours give two lag days and a one-day penalty.
    PRD: A **spin penalty** of one day is taken when the reported `spin_rpm` is strictly below the product's `min_spin_rpm`, and zero otherwise.
    PRD: The provisional code date is the UTC calendar date of the reference instant advanced by that many whole days, written to `provisional_code_date` as an ISO date in `YYYY-MM-DD` form.
    PRD: Third, enough code-date life must remain: the number of whole days from the ship date — the UTC calendar date of the logical clock's current instant — to the case's `code_date` must be at least the specification's `min_remaining_shelf_life_days_at_ship`.

    Design: Corner/calculations/corner_shelf_life_floor_is_a_max_not_a_per_term_clamp
    """
    world = fx.master_data_world(api)
    celery = validate_success(
        api.create_product(f.celery_product_payload(), PLANT_ADMIN_HEADERS),
        HTTP_CREATED,
    )
    celery_spec = validate_success(
        api.create_customer_spec(
            celery["id"],
            f.customer_spec_payload(
                celery["version"],
                case_net_weight_lb=CELERY_CASE_NET_WEIGHT_LB,
                min_remaining_shelf_life_days_at_ship=CELERY_MIN_REMAINING_DAYS,
            ),
            PLANT_ADMIN_HEADERS,
        ),
        HTTP_CREATED,
    )
    second_line = fx.create_line(
        api,
        line_code=SECOND_LINE_CODE,
        required_disassembly_component_count=SECOND_LINE_COMPONENT_COUNT,
    )
    old_lot = fx.approved_grower_lot(api, **OLD_LOT_OVERRIDES)
    warm_load = fx.create_receipt(api, old_lot["id"], **WARM_LOAD_OVERRIDES)
    assert warm_load["net_weight_lb"] == WARM_LOAD_NET_LB
    assert warm_load["temp_grade"] == c.TEMP_OUT_OF_SPEC
    assert warm_load["shelf_life_deduction_days"] == c.SHELF_LIFE_DEDUCTION_OUT_OF_SPEC
    warm_load = fx.disposition_receipt(
        api,
        warm_load["id"],
        c.DECISION_ACCEPT,
        trim_loss_lb=NO_TRIM_LB,
        override_justification=WARM_LOAD_JUSTIFICATION,
        headers=QA_MANAGER_HEADERS,
    )
    assert warm_load["accepted_lb"] == WARM_LOAD_NET_LB
    fx.validated_sanitation(api, second_line["id"])

    run = fx.plan_run(
        api,
        second_line["id"],
        celery["id"],
        celery_spec["id"],
        world.wash_system_id,
        crew_size=CELERY_CREW_SIZE,
    )
    fx.set_clock(api, c.CLOCK_PRE_START)
    fx.create_reading(
        api, world.wash_system_id, c.READING_PRE_START_AT, CELERY_READING_PPM
    )
    fx.set_clock(api, c.CLOCK_START)
    running = fx.start_run(api, run["id"])
    assert running["required_dwell_seconds_at_start"] == FROZEN_DWELL_SECONDS
    fx.consume(
        api, run["id"], warm_load["id"], running["version"], FLOOR_DRAW_LB
    )
    fx.set_clock(api, CLOCK_FLOOR_READING)
    fx.create_reading(
        api, world.wash_system_id, FLOOR_READING_AT, CELERY_READING_PPM
    )
    fx.set_clock(api, CLOCK_FLOOR_CLOSE)

    closed = fx.close_run(api, run["id"], **FLOOR_CLOSE_OVERRIDES)
    assert closed["input_lb"] == FLOOR_DRAW_LB
    assert closed["output_lb"] == FLOOR_OUTPUT_LB
    assert closed["yield_pct"] == FLOOR_YIELD_PCT
    assert closed["antimicrobial_excursion_count"] == NO_EXCURSIONS
    assert closed["disposition_status"] == c.DISPOSITION_UNRESTRICTED
    a.assert_shelf_life(
        closed,
        provisional_days=FLOOR_SHELF_LIFE_DAYS,
        provisional_code_date=FLOOR_CODE_DATE,
    )

    rows = a.assert_page(
        api.list_finished_cases(
            run["id"], QA_MANAGER_HEADERS, {"limit": c.MIN_LIMIT, "offset": 0}
        ),
        expected_total=FLOOR_CASES_PRODUCED,
    )
    first_case = rows[0]
    assert first_case["status"] == c.CASE_IN_INVENTORY
    assert first_case["code_date"] == FLOOR_CODE_DATE
    assert first_case["code_date_label"] == FLOOR_JULIAN_LABEL

    # Three days of life is less than the five this customer demands at shipment.
    validate_error(
        api.ship_finished_case(first_case["id"], SHIPPING_CLERK_HEADERS),
        ApiErrorId.INSUFFICIENT_REMAINING_SHELF_LIFE,
    )


def test_a_reading_taken_before_the_start_is_outside_the_compliance_window(api):
    """The 06:30 reading of 24.0 is ignored and the in-window 19.5 is the excursion.

    PRD: Only readings on the run's own wash system count, and readings taken before the run started or after it closed are excluded even when they belong to the same wash system and the same change-out window.
    PRD: The lowest `free_chlorine_ppm` among the in-window readings is stored as `min_ppm_observed`, compared at one decimal place with no rounding.
    PRD: `antimicrobial_excursion_count` is the number of in-window readings whose `free_chlorine_ppm` is strictly below the product's `min_antimicrobial_ppm`, so a reading exactly equal to the product minimum is compliant.
    PRD: When `antimicrobial_excursion_count` is greater than zero, the close opens a hold record with `reason` of `ANTIMICROBIAL_EXCURSION` and additionally opens a corrective action on the line with `source_type` of `ANTIMICROBIAL_EXCURSION`, `severity` of `MAJOR`, and `source_ref_id` pointing at the in-window reading with the lowest `free_chlorine_ppm`, tie-broken by the lowest `sequence_no`; the line's posture is then recomputed, which will restrict the line.

    Design: Corner/calculations/corner_excursion_uses_only_readings_inside_the_run_window
    """
    world = fx.build_world(api, stop_after=fx.STOP_RUN_CONSUMED)
    fx.set_clock(api, c.CLOCK_MID_RUN)
    low = fx.create_reading(
        api, world.wash_system_id, c.READING_MID_RUN_AT, LOW_READING_PPM
    )
    a.assert_reading_derivations(
        low,
        organic_load_index_at_reading=LOADED_INDEX,
        target_free_chlorine_ppm_at_reading=LOADED_TARGET_PPM,
        topup_ppm_required=LOW_READING_TOPUP_PPM,
        below_target=True,
    )

    fx.set_clock(api, c.CLOCK_CLOSE)
    closed = fx.close_run(api, world.run_id)
    assert closed["min_ppm_observed"] == LOW_READING_PPM, (
        "the pre-start reading of 24.0 sits outside the window and cannot be the minimum"
    )
    assert closed["antimicrobial_excursion_count"] == ONE_EXCURSION
    assert closed["disposition_status"] == c.DISPOSITION_HELD
    a.assert_case_counters(
        closed, available=0, on_hold=c.CLOSE_CASES_PRODUCED, shipped=0, destroyed=0
    )
    a.assert_case_counters_conserved(closed)

    holds = fx.list_holds(api, world.run_id)
    assert len(holds) == EXPECTED_HOLD_COUNT
    assert {hold["reason"] for hold in holds} == {
        c.REASON_HOLD_AND_RELEASE_TESTING,
        c.REASON_ANTIMICROBIAL_EXCURSION,
    }
    assert sorted(hold["cases_held_count"] for hold in holds) == [
        0,
        c.CLOSE_CASES_PRODUCED,
    ], "only the first hold moved cases; the second found them already on hold"

    actions = fx.list_line_corrective_actions(api, world.line_id)
    assert len(actions) == 1
    assert actions[0]["source_type"] == c.SOURCE_ANTIMICROBIAL_EXCURSION
    assert actions[0]["severity"] == c.SEVERITY_MAJOR
    assert actions[0]["status"] == c.CA_OPEN
    assert actions[0]["source_ref_id"] == low["id"]

    restricted = fx.read_line(api, world.line_id)
    assert restricted["posture"] == c.POSTURE_RESTRICTED
    assert restricted["open_corrective_action_count"] == 1


def test_four_prior_rejections_and_forty_cost_the_same_twenty_points(api):
    """The prior-rejection term saturates before it is ever subtracted.

    PRD: A prior-rejection deduction is then taken: five points for each load counted in `prior_rejected_receipt_count`, but the whole term is capped at twenty points *before* it is subtracted, so a grower with four prior rejected loads and a grower with forty prior rejected loads both lose exactly twenty points.
    PRD: The server writes the computed value into `preharvest_risk_score` and copies the identical value into `trailing_risk_score`, because no operating evidence exists yet, and refreshes `out_of_spec_receipt_count` and `env_positive_run_count` to their current counts.

    Design: Corner/calculations/corner_prior_reject_penalty_is_capped_before_subtraction
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    four_rejects = fx.create_grower_lot(api, **CAP_LOT_A_OVERRIDES)
    forty_rejects = fx.create_grower_lot(api, **CAP_LOT_B_OVERRIDES)
    assert four_rejects["prior_rejected_receipt_count"] == FOUR_PRIOR_REJECTS
    assert forty_rejects["prior_rejected_receipt_count"] == FORTY_PRIOR_REJECTS

    modest = fx.approve_grower_lot(api, four_rejects["id"])
    a.assert_risk_scores(
        modest,
        preharvest=CAPPED_SCORE,
        trailing=CAPPED_SCORE,
        status=c.LOT_APPROVED,
    )

    heavy = fx.approve_grower_lot(api, forty_rejects["id"])
    a.assert_risk_scores(
        heavy,
        preharvest=CAPPED_SCORE,
        trailing=CAPPED_SCORE,
        status=c.LOT_APPROVED,
    )
    assert modest["preharvest_risk_score"] == heavy["preharvest_risk_score"], (
        "an uncapped five-point-per-load penalty would have driven the second lot to 0"
    )


def test_a_generous_customer_offer_cannot_lengthen_the_products_own_window(api):
    """Seventeen offered days yield sixteen, printed as a calendar date on the case.

    PRD: The server computes `spec_revision` as 1 plus the number of specification rows that already existed for the same `product_id` and `channel`, sets the new row's `status` to `ACTIVE` with `superseded_at` left null, and moves the previously `ACTIVE` row for that same `product_id` and `channel` to `SUPERSEDED`, stamping its `superseded_at` with the logical clock.
    PRD: The server maintains `active_spec_count` on the product, starting at 0, as the number of that product's specification revisions whose `status` is `ACTIVE`.
    PRD: The base window is the smaller of the product's `base_shelf_life_days` and the specification's `max_shelf_life_days_offered` — the customer's cap can shorten the validated life but never extend it.
    PRD: Each case carries `process_run_id`, a `case_code` composed of the line's `line_code`, a hyphen, the pack date rendered as eight digits in year-month-day order, another hyphen, and the case's `case_sequence` zero-padded to four digits — where the pack date is the UTC calendar date of the run's `started_at`.
    PRD: Each case copies the specification's `case_net_weight_lb` into its own `net_weight_lb`, receives the run's `provisional_code_date` as its `code_date`, and receives a `code_date_label` rendering that code date in the format the specification's `code_date_format` demands: for `CALENDAR`, the ISO form `YYYY-MM-DD`; for `JULIAN`, a seven-character string of the four-digit year followed by the zero-padded three-digit day of the year.

    Design: Corner/calculations/corner_spec_cap_and_calendar_label_and_case_code_format
    """
    world = fx.build_world(api, stop_after=fx.STOP_SANITATION_VALIDATED)
    before = validate_success(api.get_product(world.product_id, PLANT_ADMIN_HEADERS))
    assert before["active_spec_count"] == SPECS_BEFORE_RETAIL

    retail = validate_success(
        api.create_customer_spec(
            world.product_id,
            f.retail_spec_payload(
                before["version"],
                case_net_weight_lb=RETAIL_CASE_NET_WEIGHT_LB,
                min_remaining_shelf_life_days_at_ship=RETAIL_MIN_REMAINING_DAYS,
            ),
            PLANT_ADMIN_HEADERS,
        ),
        HTTP_CREATED,
    )
    assert retail["spec_revision"] == FIRST_SPEC_REVISION, (
        "revisions count prior rows for the same product and channel only"
    )
    assert retail["status"] == c.SPEC_ACTIVE
    assert retail["superseded_at"] is None
    after = validate_success(api.get_product(world.product_id, PLANT_ADMIN_HEADERS))
    assert after["active_spec_count"] == SPECS_AFTER_RETAIL

    run = fx.plan_run(
        api, world.line_id, world.product_id, retail["id"], world.wash_system_id
    )
    fx.set_clock(api, c.CLOCK_PRE_START)
    fx.create_reading(
        api, world.wash_system_id, c.READING_PRE_START_AT, c.READING_PRE_START_PPM
    )
    fx.set_clock(api, c.CLOCK_START)
    running = fx.start_run(api, run["id"])
    fx.consume(api, run["id"], world.receipt_id, running["version"], c.CONSUMED_LB)
    fx.set_clock(api, c.CLOCK_MID_RUN)
    fx.create_reading(
        api, world.wash_system_id, c.READING_MID_RUN_AT, RETAIL_READING_PPM
    )
    fx.set_clock(api, c.CLOCK_CLOSE)

    closed = fx.close_run(
        api,
        run["id"],
        atmosphere_actual=c.ATMOSPHERE_AIR,
        water_gal_used=RETAIL_WATER_GAL_USED,
        cases_produced=RETAIL_CASES_PRODUCED,
    )
    assert closed["output_lb"] == RETAIL_OUTPUT_LB
    assert closed["yield_pct"] == RETAIL_YIELD_PCT
    a.assert_shelf_life(
        closed,
        provisional_days=RETAIL_SHELF_LIFE_DAYS,
        provisional_code_date=RETAIL_CODE_DATE,
    )

    rows = a.assert_page(
        api.list_finished_cases(
            run["id"], QA_MANAGER_HEADERS, {"limit": FIRST_TWO_CASES, "offset": 0}
        ),
        expected_total=RETAIL_CASES_PRODUCED,
    )
    first_case, second_case = rows
    assert first_case["case_sequence"] == 1
    assert first_case["case_code"] == c.BASE_FIRST_CASE_CODE
    assert first_case["code_date"] == RETAIL_CODE_DATE
    assert first_case["code_date_label"] == RETAIL_CODE_DATE
    assert first_case["net_weight_lb"] == RETAIL_CASE_NET_WEIGHT_LB
    assert second_case["case_code"] == SECOND_CASE_CODE
