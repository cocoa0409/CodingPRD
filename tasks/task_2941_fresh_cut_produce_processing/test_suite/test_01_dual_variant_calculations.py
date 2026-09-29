"""Two calculations that each exist in two variants over one set of evidence.

A run's shelf life is computed twice - provisionally at close and finally at
release - and a grower lot carries two risk scores at once. Both pairs are
deliberately allowed to disagree, and these tests pin the disagreement.
"""

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    QA_MANAGER_HEADERS,
    USER_QA_MANAGER_A,
    USER_QA_TECH_B,
    make_qa_technician_headers,
)

# 2026-08-17 is the 229th day of 2026, 2026-08-16 the 228th, 2026-08-14 the 226th.
JULIAN_LABEL_PROVISIONAL = "2026229"
JULIAN_LABEL_FINAL_LOW_APC = "2026228"
JULIAN_LABEL_FINAL_HIGH_APC = "2026226"

# The lot whose field evidence scores 70: surface water and one prior rejection.
SURFACE_LOT_OVERRIDES = {
    "grower_code": "GRW-200",
    "ranch_block": "B12",
    "harvest_datetime": "2026-08-01T20:00:00Z",
    "water_source": c.WATER_SURFACE,
    "prior_rejected_receipt_count": 1,
}
SURFACE_LOT_PREHARVEST_SCORE = 70
SURFACE_LOT_TRAILING_AFTER_ONE_WARM_LOAD = 60
WARM_LOAD_JUSTIFICATION = (
    "QA manager override: product tempered to 3.2 C within 30 minutes, "
    "documented on CCP log 8842"
)


def test_close_stamps_the_provisional_shelf_life_anchored_on_the_start_instant(api):
    """The provisional variant reads its reference instant off started_at.

    PRD: In the provisional computation the reference instant is the run's `started_at`.
    PRD: A **micro penalty** completes the list and is zero in the provisional computation, because no micro result exists yet.
    PRD: The provisional code date is the UTC calendar date of the reference instant advanced by that many whole days, written to `provisional_code_date` as an ISO date in `YYYY-MM-DD` form.

    Design: Difficulty/dual_variant_calc/run_shelf_life_provisional_vs_final_diverges
    """
    world = fx.closed_world(api)
    run = world.run

    assert run["run_status"] == c.RUN_CLOSED
    a.assert_shelf_life(
        run,
        provisional_days=c.BASE_PROVISIONAL_SHELF_LIFE_DAYS,
        provisional_code_date=c.BASE_PROVISIONAL_CODE_DATE,
    )
    assert run["final_shelf_life_days"] is None, (
        "no final shelf life exists until a hold is released"
    )
    assert run["final_code_date"] is None

    # The close opened the hold-and-release hold by itself and put the pack on hold.
    assert world.hold["reason"] == c.REASON_HOLD_AND_RELEASE_TESTING
    assert world.hold["status"] == c.HOLD_HELD
    assert run["disposition_status"] == c.DISPOSITION_HELD
    a.assert_case_counters(run, available=0, on_hold=c.CLOSE_CASES_PRODUCED,
                           shipped=0, destroyed=0)

    # Every case left the packing line carrying the provisional date, JULIAN-rendered.
    first_case = fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]
    a.assert_calendar_date(first_case["code_date"], "code_date")
    assert first_case["code_date"] == c.BASE_PROVISIONAL_CODE_DATE
    assert first_case["code_date_label"] == JULIAN_LABEL_PROVISIONAL


def test_release_at_an_elevated_plate_count_shortens_shelf_life_by_three_days(api):
    """The final variant re-anchors on closed_at and adds the micro penalty.

    PRD: The reference instant becomes the run's `closed_at` rather than its `started_at`, which is later and can therefore make the harvest-lag penalty a full day larger.
    PRD: And the micro penalty becomes two days when the releasing hold's `latest_apc_cfu_g` is at least 1,000,000 colony-forming units per gram, and zero otherwise.
    PRD: The final code date is then stamped onto every case of the run that is neither `SHIPPED` nor `DESTROYED`, rewriting both `code_date` and `code_date_label`; product already in a customer's hands keeps the label it left with.

    Design: Difficulty/dual_variant_calc/run_shelf_life_provisional_vs_final_diverges
    """
    world = fx.closed_world(api)
    provisional_days = world.run["provisional_shelf_life_days"]

    fx.submit_sample(
        api, world.hold_id, c.TEST_APC, make_qa_technician_headers(USER_QA_TECH_B)
    )
    fx.record_result(
        api,
        world.hold_id,
        c.RESULT_NEGATIVE,
        c.APC_ABOVE_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
    )
    hold = fx.release_hold(api, world.hold_id, released_by=USER_QA_MANAGER_A)
    assert hold["status"] == c.HOLD_RELEASED

    run = fx.read_run(api, world.run_id)
    a.assert_shelf_life(
        run,
        provisional_days=c.BASE_PROVISIONAL_SHELF_LIFE_DAYS,
        provisional_code_date=c.BASE_PROVISIONAL_CODE_DATE,
        final_days=c.FINAL_SHELF_LIFE_DAYS_HIGH_APC,
        final_code_date=c.FINAL_CODE_DATE_HIGH_APC,
    )
    # One harvest-lag day, because 07:00 and 11:00 sit either side of 48 hours
    # after the 2026-08-01T08:00:00Z harvest, plus two micro-penalty days.
    assert provisional_days - run["final_shelf_life_days"] == 3

    assert run["run_status"] == c.RUN_CLOSED
    assert run["disposition_status"] == c.DISPOSITION_RELEASED
    a.assert_case_counters(run, available=c.CLOSE_CASES_PRODUCED, on_hold=0,
                           shipped=0, destroyed=0)

    first_case = fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]
    assert first_case["code_date"] == c.FINAL_CODE_DATE_HIGH_APC
    assert first_case["code_date_label"] == JULIAN_LABEL_FINAL_HIGH_APC
    assert first_case["status"] == c.CASE_IN_INVENTORY


def test_release_below_the_plate_count_threshold_loses_only_the_harvest_lag_day(api):
    """With no micro penalty the two variants still diverge, by exactly one day.

    PRD: And the micro penalty becomes two days when the releasing hold's `latest_apc_cfu_g` is at least 1,000,000 colony-forming units per gram, and zero otherwise.
    PRD: Every other term is computed exactly as it was provisionally — including the spin penalty, which is evaluated in both forms from the same reported `spin_rpm` and so is never itself the source of a divergence between them.

    Design: Difficulty/dual_variant_calc/run_shelf_life_provisional_vs_final_diverges
    """
    world = fx.closed_world(api)

    fx.clear_hold(
        api,
        world.hold_id,
        latest_apc_cfu_g=c.APC_BELOW_MICRO_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
        released_by=USER_QA_MANAGER_A,
    )

    run = fx.read_run(api, world.run_id)
    a.assert_shelf_life(
        run,
        provisional_days=c.BASE_PROVISIONAL_SHELF_LIFE_DAYS,
        provisional_code_date=c.BASE_PROVISIONAL_CODE_DATE,
        final_days=c.FINAL_SHELF_LIFE_DAYS_LOW_APC,
        final_code_date=c.FINAL_CODE_DATE_LOW_APC,
    )
    assert (
        run["provisional_shelf_life_days"] - run["final_shelf_life_days"] == 1
    ), "the later reference instant alone costs one harvest-lag day"

    last_case = fx.list_cases(
        api, world.run_id, {"limit": c.MIN_LIMIT, "offset": c.CLOSE_CASES_PRODUCED - 1}
    )[0]
    assert last_case["case_sequence"] == c.CLOSE_CASES_PRODUCED
    assert last_case["code_date"] == c.FINAL_CODE_DATE_LOW_APC
    assert last_case["code_date_label"] == JULIAN_LABEL_FINAL_LOW_APC


def test_adjudication_freezes_the_preharvest_score_and_copies_it_into_the_trailing_score(api):
    """The preharvest variant scores field evidence only, once, at approval.

    PRD: Twenty-five points are deducted when `water_source` is `SURFACE`.
    PRD: A prior-rejection deduction is then taken: five points for each load counted in `prior_rejected_receipt_count`, but the whole term is capped at twenty points *before* it is subtracted, so a grower with four prior rejected loads and a grower with forty prior rejected loads both lose exactly twenty points.
    PRD: The server writes the computed value into `preharvest_risk_score` and copies the identical value into `trailing_risk_score`, because no operating evidence exists yet, and refreshes `out_of_spec_receipt_count` and `env_positive_run_count` to their current counts.

    Design: Difficulty/dual_variant_calc/grower_lot_preharvest_vs_trailing_risk_diverges
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)

    pending = fx.create_grower_lot(api, **SURFACE_LOT_OVERRIDES)
    assert pending["status"] == c.LOT_PENDING_APPROVAL
    a.assert_risk_scores(pending, status=c.LOT_PENDING_APPROVAL)
    assert pending["preharvest_risk_score"] is None
    assert pending["trailing_risk_score"] is None

    adjudicated = fx.approve_grower_lot(api, pending["id"])
    a.assert_risk_scores(
        adjudicated,
        preharvest=SURFACE_LOT_PREHARVEST_SCORE,
        trailing=SURFACE_LOT_PREHARVEST_SCORE,
        status=c.LOT_APPROVED,
    )
    assert adjudicated["out_of_spec_receipt_count"] == 0
    assert adjudicated["env_positive_run_count"] == 0
    a.assert_version_is(adjudicated, 2, "grower lot")


def test_accepting_one_warm_load_moves_the_trailing_score_and_not_the_preharvest_one(api):
    """One GET returns two different scores over one set of evidence.

    PRD: The trailing computation begins from the *frozen* `preharvest_risk_score` — never from a freshly re-derived preharvest figure — and subtracts ten points for each receipt counted in `out_of_spec_receipt_count` and twelve points for each run counted in `env_positive_run_count`, constraining the result to the range 0 through 100 inclusive.
    PRD: A pulp temperature greater than 4.4 degrees Celsius grades the load `OUT_OF_SPEC`.
    PRD: The comparison is strict: a trailing score of exactly 50 keeps the lot `APPROVED`.

    Design: Difficulty/dual_variant_calc/grower_lot_preharvest_vs_trailing_risk_diverges
    """
    fx.set_clock(api, c.CLOCK_MASTER_DATA)
    lot = fx.approved_grower_lot(api, **SURFACE_LOT_OVERRIDES)

    warm_load = fx.create_receipt(
        api,
        lot["id"],
        received_at="2026-08-02T05:20:00Z",
        pulp_temp_c=4.6,
        gross_weight_lb=18000.00,
        tare_weight_lb=1000.00,
    )
    assert warm_load["temp_grade"] == c.TEMP_OUT_OF_SPEC
    assert warm_load["shelf_life_deduction_days"] == c.SHELF_LIFE_DEDUCTION_OUT_OF_SPEC

    accepted = fx.disposition_receipt(
        api,
        warm_load["id"],
        c.DECISION_ACCEPT,
        trim_loss_lb=2000.00,
        override_justification=WARM_LOAD_JUSTIFICATION,
        headers=QA_MANAGER_HEADERS,
    )
    assert accepted["status"] == c.RECEIPT_ACCEPTED

    scored = fx.read_grower_lot(api, lot["id"])
    assert scored["out_of_spec_receipt_count"] == 1
    a.assert_risk_scores(
        scored,
        preharvest=SURFACE_LOT_PREHARVEST_SCORE,
        trailing=SURFACE_LOT_TRAILING_AFTER_ONE_WARM_LOAD,
        status=c.LOT_APPROVED,
    )
