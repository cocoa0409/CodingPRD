"""State machines that loop, and two dimensions that advance independently.

A hold record can be sampled, come back indeterminate and be sampled again,
and only the submission consumes a round. A processing run's production status
and its quality disposition move on axes that do not gate each other.
"""

from prd_bench_local_runner.testing import validate_error

from test_helpers import assertions as a
from test_helpers import constants as c
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ApiErrorId
from test_helpers.test_users import (
    QA_TECHNICIAN_HEADERS,
    USER_QA_MANAGER_A,
    USER_QA_TECH_B,
    make_qa_manager_headers,
    make_qa_technician_headers,
)

JULIAN_LABEL_FINAL_LOW_APC = "2026228"
APC_WELL_BELOW_THRESHOLD = 400000


def test_two_indeterminate_results_leave_the_retest_budget_untouched(api):
    """Only a submitted sample advances test_round; a result never does.

    PRD: A successful submission increments `test_round` by 1, records the assay, clears `latest_test_result`, `latest_apc_cfu_g` and `resulted_by_user_id` from any earlier round, and moves the hold `HELD → UNDER_TEST` or `RETEST_REQUIRED → UNDER_TEST`.
    PRD: A result of `NEGATIVE` or `POSITIVE` leaves the hold in `UNDER_TEST` — a self-loop, so one round can be resulted and then acted on — while a result of `INDETERMINATE` moves the hold `UNDER_TEST → RETEST_REQUIRED` and leaves `test_round` unchanged, which means the next submission consumes one of the three rounds.

    Design: Difficulty/non_linear_state_machine/hold_record_retest_cycle_then_release
    """
    world = fx.closed_world(api)
    hold_id = world.hold_id
    assert world.hold["status"] == c.HOLD_HELD
    assert world.hold["test_round"] == 0

    tech = make_qa_technician_headers(USER_QA_TECH_B)

    first = fx.submit_sample(api, hold_id, c.TEST_LISTERIA, tech)
    assert (first["test_round"], first["status"]) == (1, c.HOLD_UNDER_TEST)

    first_result = fx.record_result(
        api, hold_id, c.RESULT_INDETERMINATE, resulted_by=USER_QA_TECH_B
    )
    assert (first_result["test_round"], first_result["status"]) == (
        1,
        c.HOLD_RETEST_REQUIRED,
    )

    second = fx.submit_sample(api, hold_id, c.TEST_LISTERIA, tech)
    assert (second["test_round"], second["status"]) == (2, c.HOLD_UNDER_TEST)

    second_result = fx.record_result(
        api, hold_id, c.RESULT_INDETERMINATE, resulted_by=USER_QA_TECH_B
    )
    assert (second_result["test_round"], second_result["status"]) == (
        2,
        c.HOLD_RETEST_REQUIRED,
    )

    third = fx.submit_sample(api, hold_id, c.TEST_APC, tech)
    assert (third["test_round"], third["status"]) == (3, c.HOLD_UNDER_TEST)

    cleared = fx.record_result(
        api,
        hold_id,
        c.RESULT_NEGATIVE,
        APC_WELL_BELOW_THRESHOLD,
        resulted_by=USER_QA_TECH_B,
    )
    # A negative result is the UNDER_TEST self-loop, not a state change.
    assert (cleared["test_round"], cleared["status"]) == (3, c.HOLD_UNDER_TEST)
    assert cleared["resulted_by_user_id"] == USER_QA_TECH_B
    assert cleared["latest_test_type"] == c.TEST_APC

    released = fx.release_hold(api, hold_id, released_by=USER_QA_MANAGER_A)
    assert released["status"] == c.HOLD_RELEASED
    assert released["test_round"] == c.MAX_RETEST_ROUNDS
    assert released["released_by_user_id"] == USER_QA_MANAGER_A

    run = fx.read_run(api, world.run_id)
    a.assert_shelf_life(
        run,
        final_days=c.FINAL_SHELF_LIFE_DAYS_LOW_APC,
        final_code_date=c.FINAL_CODE_DATE_LOW_APC,
    )
    assert run["disposition_status"] == c.DISPOSITION_RELEASED
    a.assert_case_counters(run, available=c.CLOSE_CASES_PRODUCED, on_hold=0,
                           shipped=0, destroyed=0)
    first_case = fx.list_cases(api, world.run_id, {"limit": c.MIN_LIMIT})[0]
    assert first_case["code_date_label"] == JULIAN_LABEL_FINAL_LOW_APC


def test_a_fourth_sample_against_the_same_hold_is_never_accepted(api):
    """The cycle is bounded at three submissions however often it laps.

    PRD: It is refused with `ERR_MAX_RETEST_ROUNDS_EXCEEDED` (HTTP 409) unless `test_round` is strictly below 3, so a fourth sample against the same hold is never accepted.
    PRD: Submitting a micro sample is legal from `HELD` or from `RETEST_REQUIRED` and carries the assay in `latest_test_type` as `APC`, `LISTERIA`, `ECOLI_O157` or `SALMONELLA`.

    Design: Difficulty/non_linear_state_machine/hold_record_retest_cycle_then_release
    """
    world = fx.closed_world(api)
    hold_id = world.hold_id
    tech = make_qa_technician_headers(USER_QA_TECH_B)

    for expected_round in (1, 2, 3):
        submitted = fx.submit_sample(api, hold_id, c.TEST_LISTERIA, tech)
        assert submitted["test_round"] == expected_round
        indeterminate = fx.record_result(
            api, hold_id, c.RESULT_INDETERMINATE, resulted_by=USER_QA_TECH_B
        )
        assert indeterminate["test_round"] == expected_round
        assert indeterminate["status"] == c.HOLD_RETEST_REQUIRED

    validate_error(
        api.submit_hold_sample(hold_id, f.hold_sample_payload(c.TEST_APC), tech),
        ApiErrorId.MAX_RETEST_ROUNDS_EXCEEDED,
    )

    unchanged = fx.list_holds(api, world.run_id)[0]
    assert unchanged["test_round"] == c.MAX_RETEST_ROUNDS
    assert unchanged["status"] == c.HOLD_RETEST_REQUIRED


def test_a_running_run_is_held_without_disturbing_its_production_axis(api):
    """The disposition axis moves while run_status stays RUNNING, then closes.

    PRD: A `QATechnician` may open one directly on any run whose `disposition_status` is not `REJECTED` and whose `run_status` is not `CANCELLED` — note that a run may be held while it is still `RUNNING`, since the two dimensions advance independently.
    PRD: The hold's `cases_held_count` records how many cases just moved, and its `shipped_case_count` records how many of the run's cases had already shipped at that moment — the customer notification list size.
    PRD: When the product's `hold_and_release_required` is true, the close opens a hold record with `reason` of `HOLD_AND_RELEASE_TESTING`, moves the run's disposition `UNRESTRICTED → HELD`, and moves every newly created case `IN_INVENTORY → ON_HOLD`.

    Design: Difficulty/non_linear_state_machine/process_run_parallel_run_and_disposition_dimensions
    """
    world = fx.build_world(api, stop_after=fx.STOP_TWO_READINGS)

    before = fx.read_run(api, world.run_id)
    assert before["run_status"] == c.RUN_RUNNING
    assert before["disposition_status"] == c.DISPOSITION_UNRESTRICTED
    assert fx.list_cases(api, world.run_id) == [], "nothing is packed until the close"

    hold_a = fx.open_hold(api, world.run_id, c.REASON_SANITATION_FAILURE)
    assert hold_a["status"] == c.HOLD_HELD
    assert hold_a["cases_held_count"] == 0
    assert hold_a["shipped_case_count"] == 0

    mid = fx.read_run(api, world.run_id)
    assert mid["run_status"] == c.RUN_RUNNING
    assert mid["disposition_status"] == c.DISPOSITION_HELD

    fx.set_clock(api, c.CLOCK_CLOSE)
    closed = fx.close_run(api, world.run_id)
    assert closed["run_status"] == c.RUN_CLOSED
    assert closed["disposition_status"] == c.DISPOSITION_HELD
    a.assert_case_counters(closed, available=0, on_hold=c.CLOSE_CASES_PRODUCED,
                           shipped=0, destroyed=0)

    hold_b = fx.list_holds(
        api, world.run_id, {"reason": c.REASON_HOLD_AND_RELEASE_TESTING}
    )[0]
    assert hold_b["id"] != hold_a["id"]
    assert hold_b["reason"] == c.REASON_HOLD_AND_RELEASE_TESTING
    assert hold_b["cases_held_count"] == c.CLOSE_CASES_PRODUCED

    # A capture taken at hold time is never back-filled by later packing.
    holds = {row["id"]: row for row in fx.list_holds(api, world.run_id)}
    assert holds[hold_a["id"]]["cases_held_count"] == 0
    assert holds[hold_a["id"]]["status"] == c.HOLD_HELD


def test_one_non_terminal_hold_blocks_the_release_of_every_other_hold(api):
    """Even a hold that captured no cases keeps the run's other hold shut.

    PRD: Release is a `QAManager` decision and it is guarded four ways, evaluated in this order: the hold must be in `UNDER_TEST` and every *other* hold record on the same run must already be in a terminal state of `RELEASED` or `REJECTED`, or the request is refused with `ERR_HOLD_INVALID_STATE` (HTTP 409); the releasing `X-User-ID` must differ from the hold's `resulted_by_user_id`, or the request is refused with `ERR_SEGREGATION_OF_DUTIES`; and the hold's `latest_test_result` must be `NEGATIVE`, since a `POSITIVE` or `INDETERMINATE` latest result cannot be released, or the request is refused with `ERR_TEST_RESULT_NOT_NEGATIVE` (HTTP 409).

    Design: Difficulty/non_linear_state_machine/process_run_parallel_run_and_disposition_dimensions
    """
    world = fx.build_world(api, stop_after=fx.STOP_TWO_READINGS)
    hold_a = fx.open_hold(api, world.run_id, c.REASON_SANITATION_FAILURE)
    fx.set_clock(api, c.CLOCK_CLOSE)
    fx.close_run(api, world.run_id)
    hold_b = fx.list_holds(
        api, world.run_id, {"reason": c.REASON_HOLD_AND_RELEASE_TESTING}
    )[0]

    # Take hold B all the way to a releasable negative result, so the only
    # remaining obstacle is hold A sitting in the non-terminal HELD state.
    fx.submit_sample(api, hold_b["id"], c.TEST_APC, QA_TECHNICIAN_HEADERS)
    under_test = fx.record_result(
        api, hold_b["id"], c.RESULT_NEGATIVE, c.APC_BELOW_MICRO_THRESHOLD
    )
    assert under_test["status"] == c.HOLD_UNDER_TEST

    validate_error(
        api.release_hold(hold_b["id"], make_qa_manager_headers(USER_QA_MANAGER_A)),
        ApiErrorId.HOLD_INVALID_STATE,
    )

    holds = {row["id"]: row for row in fx.list_holds(api, world.run_id)}
    assert holds[hold_a["id"]]["status"] == c.HOLD_HELD
    assert holds[hold_b["id"]]["status"] == c.HOLD_UNDER_TEST
    still_held = fx.read_run(api, world.run_id)
    assert still_held["disposition_status"] == c.DISPOSITION_HELD
    a.assert_case_counters(still_held, available=0, on_hold=c.CLOSE_CASES_PRODUCED,
                           shipped=0, destroyed=0)
