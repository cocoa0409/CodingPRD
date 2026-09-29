"""The two independent state dimensions, and the rework cycle cap at two."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_REWORK_LIMIT_EXCEEDED
from test_helpers.assertions import (
    assert_line_states,
    assert_money,
    expected_refurb_total_cost,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CHECK_EMPTY_BOX,
    CHECK_REPEAT_RETURNER,
    CHECK_SERIAL_MISMATCH,
    CHECK_VALUE_ANOMALY,
    CLIENT_STATUS_ACTIVE,
    DISPOSITION_LIQUIDATE,
    DISPOSITION_REFURBISH,
    DS_DISPOSITION_ASSIGNED,
    DS_DISPOSITIONED,
    DS_IN_REFURB,
    ENTRY_RECOVERY_CREDIT,
    ENTRY_REFURB_COST,
    FS_FRAUD_HOLD,
    FS_HOLD_PENDING_DISPOSITION,
    FS_RELEASE_PENDING,
    GRADE_C,
    OUTCOME_FAIL,
    OUTCOME_PASS,
    REASON_DEFECTIVE,
    STAGE_GRADING,
    STAGE_RECEIPT,
    TEST_RESULT_FAIL,
    TEST_WINDOW_1_END,
    TEST_WINDOW_1_START,
    TEST_WINDOW_2_END,
    TEST_WINDOW_2_START,
    TEST_WINDOW_3_END,
    TEST_WINDOW_3_START,
    TEST_WINDOW_4_END,
    TEST_WINDOW_4_START,
    USER_QA,
    USER_TECH,
    WO_ABANDONED,
    WO_IN_TEST,
    WO_OPEN,
    WO_TEST_FAILED,
)
from test_helpers.test_users import ANALYST, TECHNICIAN


def _serial_mismatch_world(api, client_code):
    """A serialized line scanned with the wrong serial, on a tight tolerance.

    The carton weighs exactly what the authorization expects, so the empty-box
    check passes, while the declared and scanned serials disagree.
    """
    world = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            client_code, fraud_tolerance_cents=4000
        ),
        items=[fx.widget_item_kwargs(sku="SERIAL-1", serialized=True)],
        lines=[
            {
                "authorized_quantity": 1,
                "reason_code": REASON_DEFECTIVE,
                "declared_serial": "SER-AAA",
                "scanned_serial": "SER-BBB",
            }
        ],
    )
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    return world


def _order_and_execute(api, world):
    """Propose, approve and execute the line's liquidation order at its frozen price."""
    order = fx.propose_order(
        api,
        world["line"]["id"],
        channel_id=world["channel"]["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    fx.approve_order(api, order["id"])
    return fx.execute_order(api, order["id"])


def _clear_hold(api, return_line_id):
    """Clear a fraud hold as a RefundAnalyst and return the updated line."""
    return get_success_data(
        api.clear_fraud_hold(
            return_line_id,
            f.clear_fraud_hold_payload(
                resolution_note="Serial re-verified against carrier photo evidence"
            ),
            ANALYST,
        )
    )


def test_receipt_and_release_fraud_score_variants_over_four_check_rows(api):
    """PRD §3.4: "The line's `fraud_score_release` is then the sum of
    `weight_points` across all four rows — the two dock rows plus the two grading
    rows. For identical physical inputs this release-time variant returns a
    strictly larger number than `fraud_score_receipt` whenever either
    grading-stage check fails, and it alone decides whether money is held."

    Design: Difficulty/non_linear_state_machine/return_line_parallel_dimensions_evolve_independently
    """
    world = _serial_mismatch_world(api, "CLFRAUD")
    scanned = world["line"]

    # Only SERIAL_MISMATCH fails at the dock: 1400 grams is the full expectation.
    assert scanned["fraud_score_receipt"] == 40, scanned["fraud_score_receipt"]
    assert scanned["fraud_score_release"] == 0, scanned["fraud_score_release"]

    graded = fx.grade_line(api, scanned["id"], GRADE_C)
    assert graded["fraud_score_receipt"] == 40, "the dock variant never revises"
    # 40 SERIAL_MISMATCH + 20 VALUE_ANOMALY (20000 - 7200 > 4000).
    assert graded["fraud_score_release"] == 60, graded["fraud_score_release"]
    assert graded["fraud_score_release"] > graded["fraud_score_receipt"]

    rows = fx.fraud_checks_for_line(api, scanned["id"])
    assert len(rows) == 4, f"a graded line carries four rows, got {len(rows)}"
    by_type = {row["check_type"]: row for row in rows}
    assert set(by_type) == {
        CHECK_SERIAL_MISMATCH,
        CHECK_EMPTY_BOX,
        CHECK_VALUE_ANOMALY,
        CHECK_REPEAT_RETURNER,
    }

    serial = by_type[CHECK_SERIAL_MISMATCH]
    assert serial["outcome"] == OUTCOME_FAIL
    assert serial["weight_points"] == 40
    assert serial["evaluated_stage"] == STAGE_RECEIPT

    empty_box = by_type[CHECK_EMPTY_BOX]
    assert empty_box["outcome"] == OUTCOME_PASS
    assert empty_box["weight_points"] == 0
    assert empty_box["evaluated_stage"] == STAGE_RECEIPT

    anomaly = by_type[CHECK_VALUE_ANOMALY]
    assert anomaly["outcome"] == OUTCOME_FAIL
    assert anomaly["weight_points"] == 20
    assert anomaly["evaluated_stage"] == STAGE_GRADING

    repeat = by_type[CHECK_REPEAT_RETURNER]
    assert repeat["outcome"] == OUTCOME_PASS
    assert repeat["weight_points"] == 0
    assert repeat["evaluated_stage"] == STAGE_GRADING


def test_physical_axis_reaches_terminal_while_the_money_axis_stays_frozen(api):
    """PRD §2.9: "The two dimensions advance independently and neither one gates
    the other except at a single coupling point: executing a disposition order
    both drives `disposition_state` to `DISPOSITIONED` and moves
    `financial_state` from `HOLD_PENDING_DISPOSITION` to `RELEASE_PENDING`. A
    line can therefore be physically terminal while its money is still frozen,
    and a line can be denied a refund while its units are still in a
    refurbishment bay."

    Design: Difficulty/non_linear_state_machine/return_line_parallel_dimensions_evolve_independently
    """
    world = _serial_mismatch_world(api, "CLFRAUD2")
    graded = fx.grade_line(api, world["line"]["id"], GRADE_C)
    assert_line_states(
        graded,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        financial_state=FS_FRAUD_HOLD,
        disposition=DISPOSITION_LIQUIDATE,
    )

    _order_and_execute(api, world)
    executed_line = fx.read_return_line(api, world["line"]["id"])
    # The physical axis is terminal; the money axis never left FRAUD_HOLD,
    # because the coupling point only promotes HOLD_PENDING_DISPOSITION.
    assert_line_states(
        executed_line,
        disposition_state=DS_DISPOSITIONED,
        financial_state=FS_FRAUD_HOLD,
    )

    cleared = _clear_hold(api, world["line"]["id"])
    assert_line_states(
        cleared,
        disposition_state=DS_DISPOSITIONED,
        financial_state=FS_RELEASE_PENDING,
    )
    assert cleared["version"] == executed_line["version"] + 1


def test_cleared_hold_leaves_the_release_score_standing_as_evidence(api):
    """PRD §3.7: "Crucially, `fraud_score_release` is **not** recomputed
    downward: the score is permanent evidence and the state is the gate. A line
    whose hold was cleared may be released even though its score remains at or
    above 50 forever."

    Design: Difficulty/non_linear_state_machine/return_line_parallel_dimensions_evolve_independently
    """
    world = _serial_mismatch_world(api, "CLFRAUD3")
    fx.grade_line(api, world["line"]["id"], GRADE_C)
    _order_and_execute(api, world)

    cleared = _clear_hold(api, world["line"]["id"])
    assert cleared["fraud_score_release"] == 60, cleared["fraud_score_release"]
    assert cleared["fraud_score_receipt"] == 40, cleared["fraud_score_receipt"]
    assert cleared["financial_state"] == FS_RELEASE_PENDING

    rows = fx.fraud_checks_for_line(api, world["line"]["id"])
    assert len(rows) == 4, "clearing a hold appends and removes no evidence row"


def test_execution_books_the_recovery_credit_even_under_a_fraud_hold(api):
    """PRD §3.8: "A `RECOVERY_CREDIT` is appended when a `RESTOCK` or
    `LIQUIDATE` order executes, and its amount is the order's
    `net_recovery_cents` less the center's handling share of 7.5 percent of that
    net recovery, rounded half up."

    Design: Difficulty/non_linear_state_machine/return_line_parallel_dimensions_evolve_independently
    """
    world = _serial_mismatch_world(api, "CLFRAUD4")
    fx.grade_line(api, world["line"]["id"], GRADE_C)
    executed = _order_and_execute(api, world)

    # 7200 frozen price, a small lot at 0.12 + 0.06, so 1296 in commission.
    assert_money(executed["gross_lot_value_cents"], 7200, "gross_lot_value_cents")
    assert_money(executed["channel_fee_cents"], 1296, "channel_fee_cents")
    assert_money(executed["net_recovery_cents"], 5904, "net_recovery_cents")

    credit = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_RECOVERY_CREDIT
    )
    assert_money(credit["amount_cents"], 5461, "RECOVERY_CREDIT amount_cents")

    line = fx.read_return_line(api, world["line"]["id"])
    assert line["financial_state"] == FS_FRAUD_HOLD, "money is still frozen"
    assert_money(line["recovery_value_cents"], 5904, "final recovery")


def test_hold_cleared_before_execution_returns_the_line_to_the_pre_disposition_hold(api):
    """PRD §3.7: "Where the line lands depends entirely on the *other*
    dimension: if the line's disposition order has not executed yet, the line
    returns from `FRAUD_HOLD` to `HOLD_PENDING_DISPOSITION` and waits for
    execution as normal; if it has already executed — so `disposition_state` is
    already `DISPOSITIONED` — the line moves straight from `FRAUD_HOLD` to
    `RELEASE_PENDING`."

    Design: Difficulty/non_linear_state_machine/return_line_parallel_dimensions_evolve_independently
    """
    world = _serial_mismatch_world(api, "CLFRAUD5")
    graded = fx.grade_line(api, world["line"]["id"], GRADE_C)
    assert graded["financial_state"] == FS_FRAUD_HOLD

    cleared = _clear_hold(api, world["line"]["id"])
    assert_line_states(
        cleared,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        financial_state=FS_HOLD_PENDING_DISPOSITION,
    )

    # The physical axis then advances on its own and couples the money axis.
    _order_and_execute(api, world)
    after = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        after,
        disposition_state=DS_DISPOSITIONED,
        financial_state=FS_RELEASE_PENDING,
    )


def _refurb_world(api, client_code, bay_code="BAY-G1"):
    """A grade-C refurbishable line with an OPEN work order and a GENERAL bay."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs(sku="REFURB-1", refurb_eligible=True)],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    world["bay"] = fx.make_general_bay(api, bay_code=bay_code, buffer_minutes=30)
    world["work_order"] = fx.open_work_order(api, world["line"]["id"])
    return world


def test_rework_counter_only_advances_on_a_re_entry_from_test_failed(api):
    """PRD §3.5: "When the start is a re-entry from `TEST_FAILED`,
    `rework_cycles` increases by one first, and a re-entry is refused once
    `rework_cycles` has already reached the cap of two rework cycles, with
    `ERR_REWORK_LIMIT_EXCEEDED`; at that point the only remaining exit is
    abandonment."

    Design: Difficulty/non_linear_state_machine/refurb_work_order_rework_cycle_terminates_at_two
    """
    world = _refurb_world(api, "CLREF")
    work_order = world["work_order"]
    bay_id = world["bay"]["id"]
    assert work_order["status"] == WO_OPEN
    assert work_order["rework_cycles"] == 0
    assert work_order["labor_minutes_total"] == 0

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_IN_REFURB,
        disposition=DISPOSITION_REFURBISH,
    )

    # First start comes out of OPEN, so it is an entry and not a re-entry.
    first = fx.start_test(
        api, work_order["id"], bay_id, TEST_WINDOW_1_START, TEST_WINDOW_1_END
    )
    assert first["status"] == WO_IN_TEST
    assert first["rework_cycles"] == 0, first["rework_cycles"]

    failed_once = fx.record_test_result(
        api, work_order["id"], TEST_RESULT_FAIL, labor_minutes=10
    )
    assert failed_once["status"] == WO_TEST_FAILED
    assert failed_once["labor_minutes_total"] == 10

    second = fx.start_test(
        api, work_order["id"], bay_id, TEST_WINDOW_2_START, TEST_WINDOW_2_END
    )
    assert second["rework_cycles"] == 1, second["rework_cycles"]
    fx.record_test_result(api, work_order["id"], TEST_RESULT_FAIL, labor_minutes=10)

    third = fx.start_test(
        api, work_order["id"], bay_id, TEST_WINDOW_3_START, TEST_WINDOW_3_END
    )
    assert third["rework_cycles"] == 2, third["rework_cycles"]
    failed_thrice = fx.record_test_result(
        api, work_order["id"], TEST_RESULT_FAIL, labor_minutes=10
    )
    assert failed_thrice["status"] == WO_TEST_FAILED
    assert failed_thrice["labor_minutes_total"] == 30


def test_fourth_start_is_refused_and_leaves_the_work_order_exactly_as_it_was(api):
    """PRD §3.5: "a re-entry is refused once `rework_cycles` has already reached
    the cap of two rework cycles, with `ERR_REWORK_LIMIT_EXCEEDED`; at that point
    the only remaining exit is abandonment."

    Design: Difficulty/non_linear_state_machine/refurb_work_order_rework_cycle_terminates_at_two
    """
    world = _refurb_world(api, "CLREF2", bay_code="BAY-G2")
    work_order_id = world["work_order"]["id"]
    bay_id = world["bay"]["id"]
    for start_at, end_at in (
        (TEST_WINDOW_1_START, TEST_WINDOW_1_END),
        (TEST_WINDOW_2_START, TEST_WINDOW_2_END),
        (TEST_WINDOW_3_START, TEST_WINDOW_3_END),
    ):
        fx.run_failed_test_cycle(
            api, work_order_id, bay_id, start_at, end_at, labor_minutes=10
        )

    before = fx.read_work_order(api, work_order_id)
    assert before["rework_cycles"] == 2
    assert before["status"] == WO_TEST_FAILED

    response = api.start_test(
        work_order_id,
        f.start_test_payload(bay_id, TEST_WINDOW_4_START, TEST_WINDOW_4_END),
        TECHNICIAN,
    )
    validate_error(response, ERR_REWORK_LIMIT_EXCEEDED, 409)

    after = fx.read_work_order(api, work_order_id)
    assert after["status"] == WO_TEST_FAILED
    assert after["rework_cycles"] == 2
    assert after["version"] == before["version"]
    assert after["labor_minutes_total"] == 30


def test_qa_signoff_is_stamped_apart_from_the_assigned_technician(api):
    """PRD §3.5: "Whichever way the result goes, the reported labour is added to
    the running `labor_minutes_total` and the reported parts spend is added to
    the running `parts_cost_cents`, the acting user's `X-User-ID` is stamped as
    `qa_user_id`, and the work order's `version` advances."

    Design: Difficulty/non_linear_state_machine/refurb_work_order_rework_cycle_terminates_at_two
    """
    world = _refurb_world(api, "CLREF3", bay_code="BAY-G3")
    work_order = world["work_order"]
    assert work_order["assigned_technician_user_id"] == USER_TECH
    assert work_order["qa_user_id"] is None

    fx.start_test(
        api,
        work_order["id"],
        world["bay"]["id"],
        TEST_WINDOW_1_START,
        TEST_WINDOW_1_END,
    )
    recorded = fx.record_test_result(
        api, work_order["id"], TEST_RESULT_FAIL, labor_minutes=10, parts_cost_cents=0
    )
    assert recorded["qa_user_id"] == USER_QA
    assert recorded["assigned_technician_user_id"] == USER_TECH
    assert recorded["qa_user_id"] != recorded["assigned_technician_user_id"]
    assert recorded["labor_minutes_total"] == 10


def test_abandonment_writes_off_the_loaded_cost_and_re_runs_the_matrix(api):
    """PRD §3.5: "It moves the work order to `ABANDONED` and stamps
    `total_cost_cents` by the same formula with `packaging_cost_cents` treated as
    zero, then appends a `REFURB_COST` entry for the negative of that cost and
    recomputes the client's `shrink_ledger_cents` and
    `settlement_balance_cents`."

    Design: Difficulty/non_linear_state_machine/refurb_work_order_rework_cycle_terminates_at_two
    """
    world = _refurb_world(api, "CLREF4", bay_code="BAY-G4")
    work_order_id = world["work_order"]["id"]
    bay_id = world["bay"]["id"]
    for start_at, end_at in (
        (TEST_WINDOW_1_START, TEST_WINDOW_1_END),
        (TEST_WINDOW_2_START, TEST_WINDOW_2_END),
        (TEST_WINDOW_3_START, TEST_WINDOW_3_END),
    ):
        fx.run_failed_test_cycle(
            api, work_order_id, bay_id, start_at, end_at, labor_minutes=10
        )

    abandoned = fx.abandon_work_order(api, work_order_id)
    assert abandoned["status"] == WO_ABANDONED
    assert abandoned["packaging_cost_cents"] == 0
    # 30 minutes at 95 cents, loaded once by 15 percent: 2850 x 1.15 is 3277.5.
    assert_money(abandoned["total_cost_cents"], 3278, "total_cost_cents")
    assert_money(
        abandoned["total_cost_cents"],
        expected_refurb_total_cost(30, 0, 0),
        "total_cost_cents",
    )

    entry = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_REFURB_COST
    )
    assert_money(entry["amount_cents"], -3278, "REFURB_COST amount_cents")

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], -3278, "settlement_balance_cents")
    assert_money(client["shrink_ledger_cents"], -3278, "shrink_ledger_cents")
    assert client["status"] == CLIENT_STATUS_ACTIVE

    # The matrix re-runs with refurbishment forced unavailable, so rule six wins.
    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        disposition=DISPOSITION_LIQUIDATE,
        condition_grade=GRADE_C,
    )
