"""The gates on a start, on a close, and on a release, in their declared order.

The six start gates fire one at a time on a single run as each is satisfied in
turn; the close gates put the dwell rule ahead of the atmosphere rule and refuse
to mint a single case until both are met; the release gates put state ahead of
segregation of duties ahead of the micro verdict; and shipping measures the
remaining code-date life in whole days.
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
    USER_QA_MANAGER_A,
    USER_QA_TECH_A,
    USER_QA_TECH_B,
    USER_SANITATION_TECH_B,
    make_qa_manager_headers,
    make_qa_technician_headers,
)

HTTP_CREATED = 201

# A dwell short of both the product minimum and the frozen requirement.
SHORT_DWELL_SECONDS = 60

# The window a rework run would occupy, two days clear of the standing run.
REWORK_START_AT = "2026-08-05T07:00:00Z"
REWORK_END_AT = "2026-08-05T12:00:00Z"
REWORK_CREW_SIZE = 4
GROSS_CONTAMINATION_APC_CFU_G = 5000000

# The three readings the start gates walk through, against a 20.0 ppm product.
EMPTY_INDEX = 0.000
STALE_READING_AT = "2026-08-03T05:59:00Z"
STALE_READING_PPM = 24.0
FRESH_READING_AT = "2026-08-03T06:00:00Z"
BELOW_MINIMUM_PPM = 19.9
TOPUP_TO_MINIMUM_PPM = 0.1
AT_MINIMUM_PPM = 20.0

# The reading taken at exactly the closing instant.
CLOSING_READING_PPM = 21.0
CLOSING_READING_PH = 6.7
CLOSING_READING_ORP_MV = 690
CLOSING_READING_TURBIDITY_NTU = 2.8
NO_EXCURSIONS = 0
ONE_HOLD = 1

# The celery run that follows the romaine run on the same line.
CELERY_CASE_NET_WEIGHT_LB = 25.0
CELERY_MIN_REMAINING_DAYS = 5
CELERY_MAX_SHELF_LIFE_DAYS = 14
CELERY_START_AT = "2026-08-04T07:00:00Z"
CELERY_END_AT = "2026-08-04T12:00:00Z"
CELERY_CREW_SIZE = 5
PLAIN_CLEAN_AT = "2026-08-04T05:00:00Z"
CHANGEOVER_CLEAN_AT = "2026-08-04T06:45:00Z"
CHANGEOVER_READING_AT = "2026-08-04T06:30:00Z"
CHANGEOVER_READING_PPM = 36.0
PLAIN_CLEAN_ATP_RLU = 110
CHANGEOVER_ATP_RLU = 90
LOADED_TARGET_PPM = 35.0

# The two cases the shipping boundary is measured on.
FIRST_TWO_CASES = 2
SHIP_AT_EXACT_BOUNDARY = "2026-08-06T08:00:00Z"
SHIP_ONE_DAY_LATE = "2026-08-07T08:00:00Z"
CASES_SHIPPED_ONCE = 1
FIRST_ROUND = 1


def test_the_dwell_gate_is_reported_before_the_atmosphere_gate(api):
    """A close wrong in both respects names the dwell, and mints nothing either way.

    PRD: The gates on a close are evaluated in this order.
    PRD: Then `actual_dwell_seconds` must be at least the greater of the product's `min_dwell_seconds` and the run's frozen `required_dwell_seconds_at_start`; exactly equal passes, and anything short is refused with `ERR_DWELL_TIME_INSUFFICIENT` (HTTP 422).
    PRD: Then `atmosphere_actual` must equal the specification's `atmosphere_required`, or the close is refused with `ERR_ATMOSPHERE_MISMATCH` (HTTP 422).

    Design: Corner/validations/corner_close_rejects_a_mismatched_packaging_atmosphere
    """
    world = fx.build_world(api, stop_after=fx.STOP_CLOCK_AT_CLOSE)
    assert world.spec["atmosphere_required"] == c.ATMOSPHERE_MAP_LOW_O2

    validate_error(
        api.close_process_run(
            world.run_id,
            f.close_payload(atmosphere_actual=c.ATMOSPHERE_AIR),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.ATMOSPHERE_MISMATCH,
    )
    # With the dwell wrong as well, the earlier gate is the one reported.
    validate_error(
        api.close_process_run(
            world.run_id,
            f.close_payload(
                actual_dwell_seconds=SHORT_DWELL_SECONDS,
                atmosphere_actual=c.ATMOSPHERE_AIR,
            ),
            LINE_OPERATOR_HEADERS,
        ),
        ApiErrorId.DWELL_TIME_INSUFFICIENT,
    )

    refused = fx.read_run(api, world.run_id)
    assert refused["run_status"] == c.RUN_RUNNING
    assert refused["cases_produced"] is None
    assert refused["closed_at"] is None
    a.assert_empty_page(api.list_finished_cases(world.run_id, QA_MANAGER_HEADERS))

    closed = fx.close_run(api, world.run_id)
    assert closed["run_status"] == c.RUN_CLOSED
    assert closed["atmosphere_actual"] == c.ATMOSPHERE_MAP_LOW_O2
    assert closed["cases_produced"] == c.CLOSE_CASES_PRODUCED


def test_only_a_rejected_run_may_be_named_as_a_rework_source(api):
    """A merely held run is refused; the rejection is what creates the eligibility.

    PRD: When `rework_source_run_id` is supplied, the run it names must have `disposition_status` of `REJECTED` — only rejected product may be reworked — or the request is refused with `ERR_REWORK_SOURCE_NOT_REJECTED` (HTTP 422).
    PRD: It stamps `closed_at` and `released_by_user_id`, moves the hold to `REJECTED`, moves the run's disposition to the terminal `REJECTED`, and moves every case of the run with `status` of `ON_HOLD` to `DESTROYED`, recomputing `cases_on_hold` and `cases_destroyed` so that the four counters still sum to `cases_produced`.
    PRD: A rejected run becomes eligible to be named as the `rework_source_run_id` of a later run, which is the only way rejected product legitimately re-enters production.

    Design: Corner/validations/corner_rework_source_must_be_a_rejected_run
    """
    world = fx.closed_world(api)
    assert world.run["disposition_status"] == c.DISPOSITION_HELD
    assert world.hold["status"] == c.HOLD_HELD

    rework_payload = f.process_run_payload(
        world.line_id,
        world.product_id,
        world.spec_id,
        world.wash_system_id,
        rework_source_run_id=world.run_id,
        planned_start_at=REWORK_START_AT,
        planned_end_at=REWORK_END_AT,
        crew_size=REWORK_CREW_SIZE,
    )
    validate_error(
        api.create_process_run(rework_payload, LINE_OPERATOR_HEADERS),
        ApiErrorId.REWORK_SOURCE_NOT_REJECTED,
    )

    fx.submit_sample(
        api, world.hold_id, c.TEST_APC, make_qa_technician_headers(USER_QA_TECH_B)
    )
    fx.record_result(
        api,
        world.hold_id,
        c.RESULT_POSITIVE,
        latest_apc_cfu_g=GROSS_CONTAMINATION_APC_CFU_G,
        resulted_by=USER_QA_TECH_B,
    )
    rejected = fx.reject_hold(api, world.hold_id, rejected_by=USER_QA_MANAGER_A)
    assert rejected["status"] == c.HOLD_REJECTED

    condemned = fx.read_run(api, world.run_id)
    assert condemned["disposition_status"] == c.DISPOSITION_REJECTED
    a.assert_case_counters(
        condemned, available=0, on_hold=0, shipped=0, destroyed=c.CLOSE_CASES_PRODUCED
    )
    a.assert_case_counters_conserved(condemned)

    reworked = validate_success(
        api.create_process_run(rework_payload, LINE_OPERATOR_HEADERS), HTTP_CREATED
    )
    assert reworked["rework_source_run_id"] == world.run_id
    assert reworked["run_status"] == c.RUN_SETUP


def test_the_three_wash_water_start_gates_fire_in_their_declared_order(api):
    """No reading, then a 61-minute-old one, then one a tenth of a ppm short.

    PRD: At least one wash-water reading must exist for that wash system, or the start is refused with `ERR_NO_ANTIMICROBIAL_READINGS` (HTTP 422).
    PRD: The latest reading must be fresh: its `reading_at` must be no earlier than the logical clock's current instant minus 60 minutes.
    PRD: A reading exactly 60 minutes old is still fresh; an older one is refused with `ERR_ANTIMICROBIAL_READING_STALE` (HTTP 422).
    PRD: Exactly equal passes; below the minimum is refused with `ERR_ANTIMICROBIAL_BELOW_MINIMUM` (HTTP 422).
    PRD: A successful start stamps `started_at` from the logical clock and freezes two figures onto the run by running the four-step wash-water chemistry of §3.4 in its pinned step order: `target_ppm_at_start` receives the tier target from step two and `required_dwell_seconds_at_start` receives the dwell requirement from step three.

    Design: Corner/validations/corner_run_start_antimicrobial_gates_in_priority_order
    """
    world = fx.build_world(api, stop_after=fx.STOP_RUN_PLANNED)
    assert world.product["min_antimicrobial_ppm"] == c.PRODUCT_MIN_ANTIMICROBIAL_PPM
    assert fx.read_line(api, world.line_id)["posture"] == c.POSTURE_OPEN
    a.assert_empty_page(
        api.list_antimicrobial_readings(world.wash_system_id, LINE_OPERATOR_HEADERS)
    )

    fx.set_clock(api, c.CLOCK_START)
    validate_error(
        api.start_process_run(world.run_id, LINE_OPERATOR_HEADERS),
        ApiErrorId.NO_ANTIMICROBIAL_READINGS,
    )

    # 05:59 is sixty-one minutes before 07:00, one minute past the freshness window.
    fx.create_reading(api, world.wash_system_id, STALE_READING_AT, STALE_READING_PPM)
    validate_error(
        api.start_process_run(world.run_id, LINE_OPERATOR_HEADERS),
        ApiErrorId.ANTIMICROBIAL_READING_STALE,
    )

    fresh_but_weak = fx.create_reading(
        api, world.wash_system_id, FRESH_READING_AT, BELOW_MINIMUM_PPM
    )
    a.assert_reading_derivations(
        fresh_but_weak,
        organic_load_index_at_reading=EMPTY_INDEX,
        target_free_chlorine_ppm_at_reading=c.TARGET_PPM_TIER_BASE,
        topup_ppm_required=TOPUP_TO_MINIMUM_PPM,
        below_target=True,
    )
    # Reaching the concentration gate proves the 06:00 reading counted as fresh.
    validate_error(
        api.start_process_run(world.run_id, LINE_OPERATOR_HEADERS),
        ApiErrorId.ANTIMICROBIAL_BELOW_MINIMUM,
    )

    fx.create_reading(api, world.wash_system_id, c.READING_PRE_START_AT, AT_MINIMUM_PPM)
    started = fx.start_run(api, world.run_id)
    assert started["run_status"] == c.RUN_RUNNING
    a.assert_instant_equals(started["started_at"], c.CLOCK_START, "started_at")
    assert started["target_ppm_at_start"] == c.BASE_TARGET_PPM_AT_START
    assert started["required_dwell_seconds_at_start"] == c.BASE_REQUIRED_DWELL_AT_START


def test_a_reading_at_exactly_the_closing_instant_is_inside_the_window(api):
    """The pre-start reading buys nothing; the 11:00 reading closes the run.

    PRD: At least one wash-water reading must fall inside the run's window, or the close is refused with `ERR_NO_ANTIMICROBIAL_READINGS` (HTTP 422).
    PRD: The run window is the closed interval running from `started_at` to `closed_at` with both ends inclusive: a reading taken at exactly `started_at`, or at exactly `closed_at`, is inside it.
    PRD: Only readings on the run's own wash system count, and readings taken before the run started or after it closed are excluded even when they belong to the same wash system and the same change-out window.
    PRD: The lowest `free_chlorine_ppm` among the in-window readings is stored as `min_ppm_observed`, compared at one decimal place with no rounding.
    PRD: `antimicrobial_excursion_count` is the number of in-window readings whose `free_chlorine_ppm` is strictly below the product's `min_antimicrobial_ppm`, so a reading exactly equal to the product minimum is compliant.

    Design: Corner/validations/corner_close_requires_a_reading_inside_the_inclusive_window
    """
    world = fx.build_world(api, stop_after=fx.STOP_RUN_CONSUMED)
    only_reading = a.assert_page(
        api.list_antimicrobial_readings(world.wash_system_id, LINE_OPERATOR_HEADERS),
        expected_total=1,
    )
    a.assert_instant_equals(
        only_reading[0]["reading_at"], c.READING_PRE_START_AT, "reading_at"
    )

    fx.set_clock(api, c.CLOCK_CLOSE)
    validate_error(
        api.close_process_run(world.run_id, f.close_payload(), LINE_OPERATOR_HEADERS),
        ApiErrorId.NO_ANTIMICROBIAL_READINGS,
    )

    fx.create_reading(
        api,
        world.wash_system_id,
        c.CLOCK_CLOSE,
        CLOSING_READING_PPM,
        ph=CLOSING_READING_PH,
        orp_mv=CLOSING_READING_ORP_MV,
        turbidity_ntu=CLOSING_READING_TURBIDITY_NTU,
    )
    closed = fx.close_run(api, world.run_id)
    assert closed["run_status"] == c.RUN_CLOSED
    a.assert_instant_equals(closed["closed_at"], c.CLOCK_CLOSE, "closed_at")
    assert closed["min_ppm_observed"] == CLOSING_READING_PPM
    a.assert_one_decimal(closed["min_ppm_observed"], "min_ppm_observed")
    assert closed["antimicrobial_excursion_count"] == NO_EXCURSIONS

    # A compliant window opens the hold-and-release hold and nothing else.
    holds = fx.list_holds(api, world.run_id)
    assert len(holds) == ONE_HOLD
    assert holds[0]["reason"] == c.REASON_HOLD_AND_RELEASE_TESTING


def test_only_a_documented_changeover_clean_unlocks_the_next_allergen_group(api):
    """An ordinary clean opens the line but does not satisfy the changeover gate.

    PRD: At planning time the server also computes `allergen_changeover_required`, which is true exactly when the line's `last_run_allergen_group` is non-null and differs from the `allergen_group` of the product this run will pack — that is, the line last ran a different allergen and has not been changed over.
    PRD: When the run's `allergen_changeover_required` is true, the newest `VALIDATED` sanitation event on the line must have `is_allergen_changeover` true, `allergen_swab_result` of `NEGATIVE`, and a `validated_at` at or after the line's `last_run_ended_at`.
    PRD: Any of those failing is refused with `ERR_ALLERGEN_CHANGEOVER_NOT_VALIDATED` (HTTP 422) — a changeover clean performed *before* the previous product finished does not count.
    PRD: The start also sets the line's `last_run_allergen_group` to the `allergen_group` of the product now running, recomputes the run's `allergen_changeover_required` to false, and increments the run's `version` by 1.

    Design: Corner/validations/corner_allergen_changeover_must_be_validated_before_the_next_group_runs
    """
    world = fx.closed_world(api)
    finished_line = fx.read_line(api, world.line_id)
    assert finished_line["last_run_allergen_group"] == c.ALLERGEN_NONE
    a.assert_instant_equals(
        finished_line["last_run_ended_at"], c.CLOCK_CLOSE, "last_run_ended_at"
    )

    celery = validate_success(
        api.create_product(f.celery_product_payload(), PLANT_ADMIN_HEADERS), HTTP_CREATED
    )
    assert celery["allergen_group"] == c.ALLERGEN_CELERY
    celery_spec = validate_success(
        api.create_customer_spec(
            celery["id"],
            f.customer_spec_payload(
                celery["version"],
                max_shelf_life_days_offered=CELERY_MAX_SHELF_LIFE_DAYS,
                min_remaining_shelf_life_days_at_ship=CELERY_MIN_REMAINING_DAYS,
                case_net_weight_lb=CELERY_CASE_NET_WEIGHT_LB,
            ),
            PLANT_ADMIN_HEADERS,
        ),
        HTTP_CREATED,
    )
    changeover_run = fx.plan_run(
        api,
        world.line_id,
        celery["id"],
        celery_spec["id"],
        world.wash_system_id,
        planned_start_at=CELERY_START_AT,
        planned_end_at=CELERY_END_AT,
        crew_size=CELERY_CREW_SIZE,
    )
    assert changeover_run["allergen_changeover_required"] is True

    fx.set_clock(api, PLAIN_CLEAN_AT)
    plain = fx.validated_sanitation(
        api,
        world.line_id,
        schedule_overrides={"scheduled_for": PLAIN_CLEAN_AT},
        submit_overrides={"atp_rlu": PLAIN_CLEAN_ATP_RLU},
    )
    assert plain["status"] == c.SANITATION_VALIDATED
    assert plain["is_allergen_changeover"] is False

    fx.set_clock(api, CHANGEOVER_READING_AT)
    fx.create_reading(
        api, world.wash_system_id, CHANGEOVER_READING_AT, CHANGEOVER_READING_PPM
    )
    fx.set_clock(api, CELERY_START_AT)
    assert fx.read_line(api, world.line_id)["posture"] == c.POSTURE_OPEN
    validate_error(
        api.start_process_run(changeover_run["id"], LINE_OPERATOR_HEADERS),
        ApiErrorId.ALLERGEN_CHANGEOVER_NOT_VALIDATED,
    )

    documented = fx.validated_sanitation(
        api,
        world.line_id,
        performed_by=USER_SANITATION_TECH_B,
        validated_by=USER_QA_TECH_A,
        schedule_overrides={"scheduled_for": CHANGEOVER_CLEAN_AT},
        submit_overrides={"atp_rlu": CHANGEOVER_ATP_RLU},
        is_allergen_changeover=True,
    )
    assert documented["status"] == c.SANITATION_VALIDATED
    assert documented["is_allergen_changeover"] is True
    assert documented["allergen_swab_result"] == c.SWAB_NEGATIVE
    a.assert_instant_equals(documented["validated_at"], CELERY_START_AT, "validated_at")

    started = fx.start_run(api, changeover_run["id"])
    assert started["run_status"] == c.RUN_RUNNING
    assert started["allergen_changeover_required"] is False
    assert started["target_ppm_at_start"] == LOADED_TARGET_PPM

    rewritten = fx.read_line(api, world.line_id)
    assert rewritten["last_run_allergen_group"] == c.ALLERGEN_CELERY
    assert rewritten["posture"] == c.POSTURE_OPEN


def test_the_release_gates_run_state_then_duties_then_the_micro_verdict(api):
    """One hold, four refusals, and a self-loop that overwrites a positive verdict.

    PRD: Recording the laboratory result is legal only from `UNDER_TEST` and carries `latest_test_result` as `NEGATIVE`, `POSITIVE` or `INDETERMINATE`, optionally with `latest_apc_cfu_g`, the aerobic plate count in colony-forming units per gram, which must be zero or greater.
    PRD: A result of `NEGATIVE` or `POSITIVE` leaves the hold in `UNDER_TEST` — a self-loop, so one round can be resulted and then acted on — while a result of `INDETERMINATE` moves the hold `UNDER_TEST → RETEST_REQUIRED` and leaves `test_round` unchanged, which means the next submission consumes one of the three rounds.
    PRD: Release is a `QAManager` decision and it is guarded four ways, evaluated in this order: the hold must be in `UNDER_TEST` and every *other* hold record on the same run must already be in a terminal state of `RELEASED` or `REJECTED`, or the request is refused with `ERR_HOLD_INVALID_STATE` (HTTP 409); the releasing `X-User-ID` must differ from the hold's `resulted_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`; and the hold's `latest_test_result` must be `NEGATIVE`, since a `POSITIVE` or `INDETERMINATE` latest result cannot be released, or the request is refused with `ERR_TEST_RESULT_NOT_NEGATIVE` (HTTP 409).
    PRD: A release stamps `closed_at` and `released_by_user_id`, moves the hold `UNDER_TEST → RELEASED`, and moves the run's disposition `HELD → RELEASED`.

    Design: Corner/validations/corner_hold_test_gates_and_release_segregation
    """
    world = fx.closed_world(api)
    assert world.hold["status"] == c.HOLD_HELD
    assert world.hold["test_round"] == 0

    validate_error(
        api.record_hold_result(
            world.hold_id,
            f.hold_result_payload(c.RESULT_NEGATIVE),
            make_qa_technician_headers(USER_QA_TECH_B),
        ),
        ApiErrorId.HOLD_INVALID_STATE,
    )
    validate_error(
        api.release_hold(world.hold_id, make_qa_manager_headers(USER_QA_MANAGER_A)),
        ApiErrorId.HOLD_INVALID_STATE,
    )

    under_test = fx.submit_sample(
        api, world.hold_id, c.TEST_LISTERIA, make_qa_technician_headers(USER_QA_TECH_B)
    )
    assert under_test["status"] == c.HOLD_UNDER_TEST
    assert under_test["test_round"] == FIRST_ROUND

    positive = fx.record_result(
        api, world.hold_id, c.RESULT_POSITIVE, resulted_by=USER_QA_TECH_B
    )
    assert positive["status"] == c.HOLD_UNDER_TEST
    assert positive["latest_test_result"] == c.RESULT_POSITIVE
    assert positive["resulted_by_user_id"] == USER_QA_TECH_B
    validate_error(
        api.release_hold(world.hold_id, make_qa_manager_headers(USER_QA_MANAGER_A)),
        ApiErrorId.TEST_RESULT_NOT_NEGATIVE,
    )

    negative = fx.record_result(
        api,
        world.hold_id,
        c.RESULT_NEGATIVE,
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
    )
    assert negative["status"] == c.HOLD_UNDER_TEST
    assert negative["latest_test_result"] == c.RESULT_NEGATIVE
    assert negative["test_round"] == FIRST_ROUND, "re-resulting a round consumes none"

    # The manager role does not exempt the operator who recorded the result.
    validate_error(
        api.release_hold(world.hold_id, make_qa_manager_headers(USER_QA_TECH_B)),
        ApiErrorId.SEGREGATION_OF_DUTIES,
    )

    released = fx.release_hold(api, world.hold_id, released_by=USER_QA_MANAGER_A)
    assert released["status"] == c.HOLD_RELEASED
    assert released["released_by_user_id"] == USER_QA_MANAGER_A
    a.assert_instant(released["closed_at"], "closed_at")

    cleared = fx.read_run(api, world.run_id)
    assert cleared["disposition_status"] == c.DISPOSITION_RELEASED
    a.assert_shelf_life(
        cleared,
        final_days=c.FINAL_SHELF_LIFE_DAYS_LOW_APC,
        final_code_date=c.FINAL_CODE_DATE_LOW_APC,
    )


def test_exactly_ten_remaining_days_ships_and_nine_does_not(api):
    """The same case code date is shippable on the sixth and refused on the seventh.

    PRD: The final code date is then stamped onto every case of the run that is neither `SHIPPED` nor `DESTROYED`, rewriting both `code_date` and `code_date_label`; product already in a customer's hands keeps the label it left with.
    PRD: Third, enough code-date life must remain: the number of whole days from the ship date — the UTC calendar date of the logical clock's current instant — to the case's `code_date` must be at least the specification's `min_remaining_shelf_life_days_at_ship`.
    PRD: Exactly equal passes; anything less is refused with `ERR_INSUFFICIENT_REMAINING_SHELF_LIFE` (HTTP 422).
    PRD: A successful shipment stamps `shipped_at` from the logical clock, decrements the run's `cases_available`, increments its `cases_shipped`, and increments the case's `version` by 1.

    Design: Corner/validations/corner_remaining_shelf_life_at_ship_boundary
    """
    world = fx.closed_world(api)
    assert world.spec["min_remaining_shelf_life_days_at_ship"] == (
        c.SPEC_MIN_REMAINING_SHELF_LIFE_DAYS
    )
    fx.clear_hold(
        api,
        world.hold_id,
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
        released_by=USER_QA_MANAGER_A,
    )
    dated = fx.read_run(api, world.run_id)
    a.assert_shelf_life(
        dated,
        final_days=c.FINAL_SHELF_LIFE_DAYS_LOW_APC,
        final_code_date=c.FINAL_CODE_DATE_LOW_APC,
    )

    first, second = fx.list_cases(
        api, world.run_id, {"limit": FIRST_TWO_CASES, "offset": 0}
    )
    for case in (first, second):
        assert case["status"] == c.CASE_IN_INVENTORY
        assert case["code_date"] == c.FINAL_CODE_DATE_LOW_APC

    fx.set_clock(api, SHIP_AT_EXACT_BOUNDARY)
    shipped = fx.ship_case(api, first["id"])
    assert shipped["status"] == c.CASE_SHIPPED
    a.assert_instant_equals(shipped["shipped_at"], SHIP_AT_EXACT_BOUNDARY, "shipped_at")

    fx.set_clock(api, SHIP_ONE_DAY_LATE)
    validate_error(
        api.ship_finished_case(second["id"], SHIPPING_CLERK_HEADERS),
        ApiErrorId.INSUFFICIENT_REMAINING_SHELF_LIFE,
    )
    assert fx.list_cases(api, world.run_id, {"limit": FIRST_TWO_CASES, "offset": 0})[1][
        "status"
    ] == c.CASE_IN_INVENTORY

    counted = fx.read_run(api, world.run_id)
    a.assert_case_counters(
        counted,
        available=c.CLOSE_CASES_PRODUCED - CASES_SHIPPED_ONCE,
        on_hold=0,
        shipped=CASES_SHIPPED_ONCE,
        destroyed=0,
    )
    a.assert_case_counters_conserved(counted)
