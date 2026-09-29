"""Priority pairs where two rules break at once and the earlier one must answer."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_FRAUD_HOLD_ACTIVE,
    ERR_LINE_INVALID_FINANCIAL_STATE,
    ERR_RECALL_DISPOSITION_LOCKED,
    ERR_REFUND_HOLD_ACTIVE,
    ERR_SEGREGATION_OF_DUTIES,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_money,
    entries_of_type,
    plus_hours,
)
from test_helpers.constants import (
    CLOCK_STARTUP_INSTANT,
    DISPOSITION_DESTROY,
    DISPOSITION_LIQUIDATE,
    DO_PROPOSED,
    ENTRY_REFUND_DEBIT,
    FS_FRAUD_HOLD,
    FS_HOLD_PENDING_DISPOSITION,
    FS_RELEASE_PENDING,
    GRADE_C,
    GRADE_D,
    GRADE_SCRAP,
    RECALL_MANDATORY,
    REASON_DEFECTIVE,
    USER_DUAL,
)
from test_helpers.test_users import (
    ANALYST,
    DUAL_ANALYST,
    DUAL_GRADER,
    SUPERVISOR,
)


# §3.6: "`channel_window_start_at` and `channel_window_end_at` bound the lot
# window at the channel, and for every non-restock order they are mandatory with
# the start no later than the end".
LOT_WINDOW_START = "2026-08-03T08:00:00Z"
LOT_WINDOW_END = "2026-08-03T12:00:00Z"


def _held_line_world(api, client_code):
    """A graded-C line whose money axis is still on the pre-disposition hold."""
    return fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )


def test_pre_disposition_hold_answers_with_the_state_error_not_the_hold_error(api):
    """PRD §2.6: "Priority 24 requires the line's `financial_state` to admit the
    requested transition: release only from `RELEASE_PENDING` or `FRAUD_HOLD`,
    denial only from `HOLD_PENDING_DISPOSITION`, `FRAUD_HOLD` or
    `RELEASE_PENDING`, hold clearing only from `FRAUD_HOLD`, and reversal only
    from `REFUNDED`. The code is `ERR_LINE_INVALID_FINANCIAL_STATE`. A line still
    in `HOLD_PENDING_DISPOSITION` is rejected here even when other refund
    preconditions also fail."

    Design: Difficulty/priority_pair_validation_conflict/release_refund_state_error_beats_temporal_hold_error
    """
    world = _held_line_world(api, "CLPAIR1")
    line = world["line"]
    assert line["financial_state"] == FS_HOLD_PENDING_DISPOSITION
    # No order has executed, so the hold instant does not exist yet either.
    assert world["refund_release"]["release_eligible_at"] is None

    response = api.release_refund(line["id"], ANALYST)
    validate_error(response, ERR_LINE_INVALID_FINANCIAL_STATE, 409)


def test_the_rejected_release_leaves_the_money_axis_and_the_ledger_untouched(api):
    """PRD §3.7: "A successful release moves `financial_state` from
    `RELEASE_PENDING` to `REFUNDED`, stamps `released_at` from the logical clock
    and `released_by_user_id` from the caller, appends a `ShrinkLedgerEntry` of
    type `REFUND_DEBIT` whose `amount_cents` is the negative of
    `net_refund_cents`, recomputes the client's `settlement_balance_cents` from
    that entry, suspends the client when the recomputed balance falls below the
    negation of `max_refund_exposure_cents`, and advances the line's `version`."

    Design: Difficulty/priority_pair_validation_conflict/release_refund_state_error_beats_temporal_hold_error
    """
    world = _held_line_world(api, "CLPAIR1B")
    line = world["line"]

    response = api.release_refund(line["id"], ANALYST)
    validate_error(response, ERR_LINE_INVALID_FINANCIAL_STATE, 409)

    after = fx.read_return_line(api, line["id"])
    assert after["financial_state"] == FS_HOLD_PENDING_DISPOSITION
    assert after["version"] == line["version"]

    refund = fx.refund_release_for_line(api, line["id"])
    assert refund["released_by_user_id"] is None
    assert refund["released_at"] is None

    ledger = fx.list_ledger(api, world["client"]["id"])
    assert entries_of_type(ledger, ENTRY_REFUND_DEBIT) == []
    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], 0, "settlement_balance_cents")


def test_a_fraud_hold_passes_the_state_rung_and_is_caught_by_the_fraud_rung(api):
    """PRD §2.6: "a release attempt on a line in `FRAUD_HOLD`, by contrast,
    deliberately passes priority 24 and is caught later at priority 38, so the
    caller is told the fraud hold is the reason rather than receiving a generic
    state error."

    Design: Difficulty/priority_pair_validation_conflict/release_refund_state_error_beats_temporal_hold_error
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("CLPAIR1C", fraud_tolerance_cents=4000),
        items=[fx.widget_item_kwargs(sku="SERIAL-1", serialized=True)],
        lines=[
            {
                "authorized_quantity": 1,
                "reason_code": REASON_DEFECTIVE,
                "declared_serial": "SER-AAA",
                "scanned_serial": "SER-BBB",
            }
        ],
        condition_grade=GRADE_C,
    )
    line = world["line"]
    assert line["financial_state"] == FS_FRAUD_HOLD

    response = api.release_refund(line["id"], ANALYST)
    validate_error(response, ERR_FRAUD_HOLD_ACTIVE, 409)

    after = fx.read_return_line(api, line["id"])
    assert after["financial_state"] == FS_FRAUD_HOLD


def _recall_locked_world(api, client_code):
    """A graded-C line whose SKU is recalled after grading, plus two channels.

    `AUCX` accepts grade A only, so a liquidation order names a channel that
    cannot take the line's grade at the same time as it breaks the recall lock.
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs(sku="RECALL-2")],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    world["grade_a_channel"] = fx.make_channel(
        api,
        name="Grade A Only Auction",
        channel_code="AUCX",
        accepted_grades=["A"],
        fee_pct=0.12,
        hazard_certified=True,
        recall_certified=True,
        min_lot_value_cents=0,
        concurrent_lot_capacity=5,
    )
    world["destruction_channel"] = fx.make_destruction_channel(
        api,
        accepted_grades=[GRADE_C, GRADE_D, GRADE_SCRAP],
        hazard_certified=True,
        recall_certified=True,
    )
    world["recalled_item"] = fx.file_recall(api, world["item"]["id"])
    return world


def test_the_recall_lock_answers_before_any_channel_suitability_rule(api):
    """PRD §2.6: "Priority 30 locks a mandatory recall: a line whose catalogue
    item has `recall_status` `MANDATORY` has been force-dispositioned to
    `DESTROY` and that outcome cannot be overridden, nor may any disposition
    order be created for it with any disposition other than `DESTROY`. Because
    this lock is evaluated before any channel-suitability or fiscal check, a
    request that both violates the recall lock and names a channel that does not
    accept the line's grade returns `ERR_RECALL_DISPOSITION_LOCKED` and never a
    channel error."

    Design: Difficulty/priority_pair_validation_conflict/recall_safety_lock_beats_channel_grade_constraint
    """
    world = _recall_locked_world(api, "CLPAIR2")
    assert world["recalled_item"]["recall_status"] == RECALL_MANDATORY

    line = fx.read_return_line(api, world["line"]["id"])
    assert line["disposition"] == DISPOSITION_DESTROY
    assert line["condition_grade"] == GRADE_C

    response = api.create_disposition_order(
        f.disposition_order_payload(
            line["id"],
            line["version"],
            channel_id=world["grade_a_channel"]["id"],
            disposition=DISPOSITION_LIQUIDATE,
            quantity=1,
            channel_window_start_at=LOT_WINDOW_START,
            channel_window_end_at=LOT_WINDOW_END,
        ),
        SUPERVISOR,
    )
    # Priority 30 answers, so neither the grade rule at 48 nor the drift rule
    # at 49 is ever consulted.
    validate_error(response, ERR_RECALL_DISPOSITION_LOCKED, 409)

    # Nothing later in the ladder ran, so no order exists for the line.
    rows = fx.orders_for_line(api, line["id"])
    assert rows == [], f"the rejected proposal created {len(rows)} order(s)"

    after = fx.read_return_line(api, line["id"])
    assert after["version"] == line["version"]


def test_a_destroy_order_is_still_permitted_for_a_recall_locked_line(api):
    """PRD §2.6: "nor may any disposition order be created for it with any
    disposition other than `DESTROY`."

    Design: Difficulty/priority_pair_validation_conflict/recall_safety_lock_beats_channel_grade_constraint
    """
    world = _recall_locked_world(api, "CLPAIR2B")
    line = fx.read_return_line(api, world["line"]["id"])

    response = api.create_disposition_order(
        f.disposition_order_payload(
            line["id"],
            line["version"],
            channel_id=world["destruction_channel"]["id"],
            disposition=DISPOSITION_DESTROY,
            quantity=1,
            channel_window_start_at=LOT_WINDOW_START,
            channel_window_end_at=LOT_WINDOW_END,
        ),
        SUPERVISOR,
    )
    order = validate_success(response, 201)
    assert order["status"] == DO_PROPOSED
    assert order["disposition"] == DISPOSITION_DESTROY
    assert order["channel_id"] == world["destruction_channel"]["id"]
    assert_money(order["unit_price_cents"], 0, "unit_price_cents")


def _grader_is_also_analyst_world(api, client_code):
    """A line graded by the same person who later attempts its refund release.

    The order executes at the startup instant and the clock is never advanced,
    so the client's 48-hour hold is still running when the release is attempted.
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        grader=DUAL_GRADER,
    )
    world["channel"] = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    order = fx.propose_and_approve(
        api, world["line"]["id"], channel_id=world["channel"]["id"]
    )
    world["order"] = fx.execute_order(api, order["id"])
    world["refund_release"] = fx.refund_release_for_line(api, world["line"]["id"])
    return world


def test_duty_separation_answers_before_the_unexpired_hold_window(api):
    """PRD §2.6: "Because this separation outranks every temporal and fiscal
    check, a release attempted by the grader inside an unexpired hold window
    returns `ERR_SEGREGATION_OF_DUTIES` (HTTP 403) rather than a hold error."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_refund_hold_window
    """
    world = _grader_is_also_analyst_world(api, "CLPAIR3")
    line = fx.read_return_line(api, world["line"]["id"])
    assert line["graded_by_user_id"] == USER_DUAL
    assert line["financial_state"] == FS_RELEASE_PENDING

    response = api.release_refund(line["id"], DUAL_ANALYST)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    after = fx.read_return_line(api, line["id"])
    assert after["financial_state"] == FS_RELEASE_PENDING
    assert after["version"] == line["version"]


def test_the_hold_window_really_had_not_elapsed_for_a_different_analyst(api):
    """PRD §3.7: "A release is permitted when the current logical clock is at or
    after `release_eligible_at`; the comparison is inclusive at millisecond
    resolution, so an attempt at exactly `release_eligible_at` succeeds and one
    millisecond earlier is refused with `ERR_REFUND_HOLD_ACTIVE`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_refund_hold_window
    """
    world = _grader_is_also_analyst_world(api, "CLPAIR3B")
    refund = world["refund_release"]
    # Executed at the startup instant, plus the client's 48-hour hold.
    assert_instant_equals(
        refund["release_eligible_at"],
        plus_hours(CLOCK_STARTUP_INSTANT, 48),
        "release_eligible_at",
    )

    # An analyst who did not grade the line clears priority 36 and is stopped
    # by the temporal rule instead, proving both conditions genuinely held.
    response = api.release_refund(world["line"]["id"], ANALYST)
    validate_error(response, ERR_REFUND_HOLD_ACTIVE, 409)


def test_the_refused_release_leaves_only_the_recovery_credit_on_the_ledger(api):
    """PRD §3.8: "A client's `settlement_balance_cents` is the sum of
    `amount_cents` across **all** of that client's entries regardless of type,
    traversed in `sequence_no` ascending order; nothing is ever filtered out,
    because the ledger is append-only."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_beats_refund_hold_window
    """
    world = _grader_is_also_analyst_world(api, "CLPAIR3C")
    response = api.release_refund(world["line"]["id"], DUAL_ANALYST)
    validate_error(response, ERR_SEGREGATION_OF_DUTIES, 403)

    ledger = fx.list_ledger(api, world["client"]["id"])
    assert len(ledger) == 1, f"only the recovery credit may exist, got {ledger}"
    assert entries_of_type(ledger, ENTRY_REFUND_DEBIT) == []

    client = fx.read_client(api, world["client"]["id"])
    # Net recovery 5904 less the 443-cent handling share.
    assert_money(client["settlement_balance_cents"], 5461, "settlement_balance_cents")

    refund = fx.refund_release_for_line(api, world["line"]["id"])
    assert refund["released_at"] is None
    assert refund["released_by_user_id"] is None
