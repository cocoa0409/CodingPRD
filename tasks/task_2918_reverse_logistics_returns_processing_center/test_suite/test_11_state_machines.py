"""Declared transitions, refused transitions and one-shot side effects."""

from prd_bench_local_runner.testing import (
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_DISPOSITION_ORDER_INVALID_STATE,
    ERR_LINE_INVALID_DISPOSITION_STATE,
    ERR_QUARANTINE_NOT_APPLICABLE,
    ERR_RMA_EXPIRED,
    ERR_RMA_INVALID_STATE,
    ERR_RMA_NO_LINES,
    ERR_WORK_ORDER_INVALID_STATE,
)
from test_helpers.assertions import (
    assert_instant_equals,
    assert_line_states,
    assert_money,
    assert_pct_equals,
    entries_of_type,
    plus_days,
    sole_entry_of_type,
)
from test_helpers.constants import (
    BAY_TYPE_QUARANTINE,
    CHECK_EMPTY_BOX,
    CHECK_REPEAT_RETURNER,
    CHECK_SERIAL_MISMATCH,
    CHECK_VALUE_ANOMALY,
    CLOCK_STARTUP_INSTANT,
    DISPOSITION_LIQUIDATE,
    DISPOSITION_REFURBISH,
    DO_CANCELLED,
    DS_DISPOSITION_ASSIGNED,
    DS_IN_REFURB,
    DS_RECEIVED_UNGRADED,
    ENTRY_RECEIPT_VARIANCE,
    ENTRY_REFURB_COST,
    FS_HOLD_PENDING_DISPOSITION,
    GRADE_A,
    GRADE_B,
    GRADE_C,
    OUTCOME_FAIL,
    OUTCOME_PASS,
    REASON_DEFECTIVE,
    RMA_DRAFT,
    RMA_EXPIRED,
    RMA_ISSUED,
    RMA_VOID,
    STAGE_GRADING,
    STAGE_RECEIPT,
    TEST_WINDOW_1_END,
    TEST_WINDOW_1_START,
    USER_GRADER,
    WO_ABANDONED,
    WO_OPEN,
)
from test_helpers.test_users import ADMIN, CLERK, GRADER, SUPERVISOR, TECHNICIAN

ONE_DEFECTIVE_UNIT = [{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}]


def test_a_new_authorization_opens_in_draft_with_nothing_authorized_yet(api):
    """PRD §3.2: "A new authorization is `DRAFT`, its `issued_at` is null, its
    `supersedes_rma_id` is null, and the owning client's `open_rma_count` is
    recomputed."

    Design: Corner/state_machines/corner_rma_initial_state_is_draft_with_zero_totals
    """
    client = fx.make_client(api, name="SM One", client_code="SM1")
    rma = validate_success(
        api.create_rma(
            f.rma_payload(
                client["id"],
                order_reference="ORD-SM1",
                customer_reference="CUST-SM1",
            ),
            ADMIN,
        ),
        201,
    )
    assert rma["status"] == RMA_DRAFT
    assert rma["version"] == 1
    assert rma["authorized_unit_total"] == 0
    assert rma["received_unit_total"] == 0
    assert rma["supersedes_rma_id"] is None
    assert rma["issued_at"] is None
    assert fx.read_client(api, client["id"])["open_rma_count"] == 0, (
        "the count admits only ISSUED, PARTIALLY_RECEIVED and RECEIVED"
    )


def test_issuing_a_populated_draft_stamps_the_clock_and_opens_the_count(api):
    """PRD §3.2: "Issue stamps `issued_at` from the logical clock, advances the
    authorization's `version` by one, and recomputes the client's
    `open_rma_count`, which counts that client's authorizations in `ISSUED`,
    `PARTIALLY_RECEIVED` or `RECEIVED`."

    Design: Corner/state_machines/corner_rma_issue_draft_to_issued_valid_transition
    """
    client = fx.make_client(api, name="SM Two", client_code="SM2")
    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    draft = fx.make_draft_rma(
        api, client["id"], order_reference="ORD-SM2", customer_reference="CUST-SM2"
    )
    fx.add_rma_line(api, draft["id"], item["id"], authorized_quantity=2)

    issued = validate_success(api.issue_rma(draft["id"], ADMIN), 200)
    assert issued["status"] == RMA_ISSUED
    assert_instant_equals(issued["issued_at"], CLOCK_STARTUP_INSTANT, "issued_at")
    assert issued["authorized_unit_total"] == 2
    assert issued["received_unit_total"] == 0
    assert issued["version"] == 2, "the issue write advanced the version from 1"
    assert fx.read_client(api, client["id"])["open_rma_count"] == 1


def test_issuing_the_same_authorization_twice_is_refused(api):
    """PRD §2.6: "Priority 20 requires the `ReturnAuthorization` to be in a
    status admitting the requested transition — lines may only be declared while
    `DRAFT`, issue only from `DRAFT`, void only from `ISSUED` or
    `PARTIALLY_RECEIVED`, reissue only from `ISSUED`, and receipts may only be
    created against an authorization in `ISSUED` or `PARTIALLY_RECEIVED` —
    failing with `ERR_RMA_INVALID_STATE`."

    Design: Corner/state_machines/corner_rma_issue_twice_second_attempt_rejected
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "SM Three", "client_code": "SM3"},
        items=[fx.widget_item_kwargs()],
        lines=ONE_DEFECTIVE_UNIT,
        rma_kwargs={"order_reference": "ORD-SM3", "customer_reference": "CUST-SM3"},
        scan=False,
    )
    validate_error(
        api.issue_rma(world["rma"]["id"], ADMIN), ERR_RMA_INVALID_STATE, 409
    )

    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["status"] == RMA_ISSUED
    assert rma["version"] == 2, "the refused call wrote nothing"
    assert fx.read_client(api, world["client"]["id"])["open_rma_count"] == 1


def test_voiding_an_already_voided_authorization_writes_off_nothing_further(api):
    """PRD §3.2: "Voiding writes off the unreceived remainder as shrink: for each
    authorization line whose `authorized_quantity` exceeds its
    `received_quantity`, one `ShrinkLedgerEntry` of type `RECEIPT_VARIANCE` is
    appended whose `amount_cents` is the negative of the shortfall multiplied by
    that item's `declared_value_cents`; lines with no shortfall are skipped and
    produce no entry."

    Design: Corner/state_machines/corner_rma_void_from_terminal_void_state_rejected
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "SM Four", "client_code": "SM4"},
        items=[fx.widget_item_kwargs()],
        lines=ONE_DEFECTIVE_UNIT,
        rma_kwargs={"order_reference": "ORD-SM4", "customer_reference": "CUST-SM4"},
        scan=False,
    )
    first = get_success_data(
        api.void_rma(world["rma"]["id"], ADMIN, {"void_reason": "First void"})
    )
    assert first["status"] == RMA_VOID

    validate_error(
        api.void_rma(world["rma"]["id"], ADMIN, {"void_reason": "Second void"}),
        ERR_RMA_INVALID_STATE,
        409,
    )

    entries = fx.list_ledger(api, world["client"]["id"])
    assert len(entries) == 1, "a terminal state appends no second write-off"
    variance = sole_entry_of_type(entries, ENTRY_RECEIPT_VARIANCE)
    assert_money(variance["amount_cents"], -20000, "RECEIPT_VARIANCE amount_cents")

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["shrink_ledger_cents"], -20000, "shrink_ledger_cents")
    assert_money(client["settlement_balance_cents"], -20000, "settlement_balance_cents")


def test_an_authorization_with_no_lines_cannot_be_issued(api):
    """PRD §3.2: "Issue advances `status` from `DRAFT` to `ISSUED` and requires
    four things: the authorization is still `DRAFT`, it has at least one declared
    line — an authorization with `declared_line_count` of zero is refused with
    `ERR_RMA_NO_LINES` — the owning client is `ACTIVE`, and `expires_at` is still
    strictly later than the current logical clock, failing with
    `ERR_RMA_EXPIRES_IN_PAST` otherwise."

    Design: Corner/state_machines/corner_rma_issue_with_zero_lines_precondition_rejected
    """
    client = fx.make_client(api, name="SM Five", client_code="SM5")
    draft = fx.make_draft_rma(
        api, client["id"], order_reference="ORD-SM5", customer_reference="CUST-SM5"
    )

    validate_error(api.issue_rma(draft["id"], ADMIN), ERR_RMA_NO_LINES, 409)

    unchanged = fx.read_rma(api, draft["id"])
    assert unchanged["status"] == RMA_DRAFT
    assert unchanged["version"] == 1
    assert unchanged["issued_at"] is None
    assert fx.read_client(api, client["id"])["open_rma_count"] == 0


def test_a_draft_authorization_refuses_reissue_even_on_a_current_version(api):
    """PRD §3.2: "A `ClientRep` or `CenterAdmin` may **reissue** an authorization
    that is `ISSUED` and against which absolutely nothing has been received,
    supplying a fresh `expires_at` and the `expected_rma_version` guard of §2.8."

    Design: Corner/state_machines/corner_rma_reissue_from_draft_is_not_a_declared_transition
    """
    client = fx.make_client(api, name="SM Six", client_code="SM6")
    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    draft = fx.make_draft_rma(
        api, client["id"], order_reference="ORD-SM6", customer_reference="CUST-SM6"
    )
    fx.add_rma_line(api, draft["id"], item["id"])

    # The version guard is deliberately correct, so only the status can refuse.
    current = fx.read_rma(api, draft["id"])
    response = api.reissue_rma(
        draft["id"],
        f.reissue_payload(
            current["version"], expires_at=plus_days(CLOCK_STARTUP_INSTANT, 61)
        ),
        ADMIN,
    )
    validate_error(response, ERR_RMA_INVALID_STATE, 409)

    _, meta = validate_paginated(
        api.list_rmas(ADMIN, {"supersedes_rma_id": draft["id"], "limit": 100})
    )
    assert meta["total_count"] == 0, "no replacement authorization was minted"
    assert fx.read_rma(api, draft["id"])["status"] == RMA_DRAFT


def test_one_grade_call_fires_every_declared_side_effect(api):
    """PRD §3.4: "Grading also creates the line's single `RefundRelease`, stamped
    with its amounts and with `release_eligible_at` left null until a disposition
    order executes."

    Design: Corner/state_machines/corner_grade_side_effects_stamp_disposition_recovery_refund_and_fraud_rows
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "SM Seven", "client_code": "SM7"},
        items=[fx.widget_item_kwargs()],
        lines=ONE_DEFECTIVE_UNIT,
        rma_kwargs={"order_reference": "ORD-SM7", "customer_reference": "CUST-SM7"},
        tracking_reference="TRK-SM7",
    )
    graded = validate_success(
        api.grade_line(world["line"]["id"], f.grade_payload(GRADE_C), GRADER), 200
    )

    assert_line_states(
        graded,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        financial_state=FS_HOLD_PENDING_DISPOSITION,
        condition_grade=GRADE_C,
        disposition=DISPOSITION_LIQUIDATE,
    )
    assert graded["graded_by_user_id"] == USER_GRADER
    # 20000 x 0.40 x (1 - 0.10), rounded per unit, times one unit.
    assert_money(graded["recovery_value_cents"], 7200, "recovery_value_cents")
    # Only VALUE_ANOMALY failed: 20000 - 7200 == 12800 exceeds the 5000 tolerance.
    assert graded["fraud_score_release"] == 20
    assert graded["fraud_score_receipt"] == 0, (
        "the receipt-time variant never sees the grading-stage rows"
    )

    release = fx.refund_release_for_line(api, graded["id"])
    assert_money(release["gross_refund_cents"], 20000, "gross_refund_cents")
    # 0.00 DEFECTIVE + 0.00 SL_STANDARD + 0.10 grade C + 0.00 lateness.
    assert_pct_equals(release["restocking_fee_pct"], 0.10, "restocking_fee_pct")
    assert_money(release["restocking_fee_cents"], 2000, "restocking_fee_cents")
    assert_money(release["net_refund_cents"], 18000, "net_refund_cents")
    assert release["release_eligible_at"] is None

    checks = fx.fraud_checks_for_line(api, graded["id"])
    assert len(checks) == 4, "two dock rows plus two grading rows"
    by_type = {c["check_type"]: c for c in checks}
    assert by_type[CHECK_EMPTY_BOX]["evaluated_stage"] == STAGE_RECEIPT
    assert by_type[CHECK_EMPTY_BOX]["outcome"] == OUTCOME_PASS
    assert by_type[CHECK_SERIAL_MISMATCH]["evaluated_stage"] == STAGE_RECEIPT
    assert by_type[CHECK_SERIAL_MISMATCH]["outcome"] == OUTCOME_PASS
    assert by_type[CHECK_VALUE_ANOMALY]["evaluated_stage"] == STAGE_GRADING
    assert by_type[CHECK_VALUE_ANOMALY]["outcome"] == OUTCOME_FAIL
    assert by_type[CHECK_REPEAT_RETURNER]["evaluated_stage"] == STAGE_GRADING
    assert by_type[CHECK_REPEAT_RETURNER]["outcome"] == OUTCOME_PASS


def test_grading_a_line_a_second_time_is_refused(api):
    """PRD §2.6: "Priority 23 requires the return line's `disposition_state` to
    admit the requested transition: quarantine only from `RECEIVED_UNGRADED`,
    grading only from `RECEIVED_UNGRADED` or `QUARANTINED`, disposition override
    only from `DISPOSITION_ASSIGNED`, work-order creation only from
    `DISPOSITION_ASSIGNED` with `disposition` equal to `REFURBISH`, and
    disposition-order creation only from `DISPOSITION_ASSIGNED`."

    Design: Corner/state_machines/corner_grade_twice_second_call_rejected_invalid_disposition_state
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "SM Eight", "client_code": "SM8"},
        items=[fx.widget_item_kwargs()],
        lines=ONE_DEFECTIVE_UNIT,
        rma_kwargs={"order_reference": "ORD-SM8", "customer_reference": "CUST-SM8"},
        tracking_reference="TRK-SM8",
    )
    fx.grade_line(api, world["line"]["id"], GRADE_C)

    response = api.grade_line(
        world["line"]["id"], f.grade_payload(GRADE_A), GRADER
    )
    validate_error(response, ERR_LINE_INVALID_DISPOSITION_STATE, 409)

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line, condition_grade=GRADE_C, disposition=DISPOSITION_LIQUIDATE
    )
    assert_money(line["recovery_value_cents"], 7200, "recovery_value_cents")
    releases = get_success_data(
        api.list_refund_releases(
            ADMIN, {"return_line_id": world["line"]["id"], "limit": 100}
        )
    )
    assert len(releases) == 1, "the refused grade created no additional release"


def test_an_ordinary_line_has_nothing_to_quarantine_for(api):
    """PRD §3.3: "Quarantine is only meaningful for a line whose item has a
    `hazard_class` other than `NONE` or a `recall_status` other than `NONE`;
    requesting it for an ordinary line is refused with
    `ERR_QUARANTINE_NOT_APPLICABLE`."

    Design: Corner/state_machines/corner_quarantine_not_applicable_for_clean_non_recalled_sku
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "SM Nine", "client_code": "SM9"},
        items=[fx.widget_item_kwargs()],
        lines=ONE_DEFECTIVE_UNIT,
        rma_kwargs={"order_reference": "ORD-SM9", "customer_reference": "CUST-SM9"},
        tracking_reference="TRK-SM9",
    )
    bay = fx.make_bay(
        api, bay_code="QB-SM9", bay_type=BAY_TYPE_QUARANTINE, buffer_minutes=0
    )

    response = api.quarantine_line(
        world["line"]["id"],
        f.quarantine_payload(bay["id"], TEST_WINDOW_1_START, TEST_WINDOW_1_END),
        CLERK,
    )
    validate_error(response, ERR_QUARANTINE_NOT_APPLICABLE, 409)

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(line, disposition_state=DS_RECEIVED_UNGRADED)
    assert line["bay_id"] is None
    assert line["quarantine_start_at"] is None

    # Grading still succeeds, so no occupation was consumed.
    graded = fx.grade_line(api, world["line"]["id"], GRADE_C)
    assert_line_states(graded, disposition_state=DS_DISPOSITION_ASSIGNED)


def _refurbishing_line(api, client_code, name, order_reference, tracking_reference):
    """A grade-B refurbishable line sitting in IN_REFURB with an open work order."""
    world = fx.received_scenario(
        api,
        client_kwargs={
            "name": name,
            "client_code": client_code,
            "restock_grade_floor": GRADE_A,
        },
        items=[
            fx.widget_item_kwargs(
                sku="REFURB-1",
                description="Refurbishable widget",
                refurb_eligible=True,
            )
        ],
        lines=ONE_DEFECTIVE_UNIT,
        rma_kwargs={
            "order_reference": order_reference,
            "customer_reference": "CUST-" + client_code,
        },
        tracking_reference=tracking_reference,
    )
    graded = fx.grade_line(api, world["line"]["id"], GRADE_B)
    assert_line_states(graded, disposition=DISPOSITION_REFURBISH)
    # 20000 x 0.65 x (1 - 0.10) for one unit.
    assert_money(graded["recovery_value_cents"], 11700, "recovery_value_cents")
    world["work_order"] = fx.open_work_order(api, world["line"]["id"])
    return world


def test_abandoning_a_failed_work_order_sinks_its_cost_and_reroutes_the_line(api):
    """PRD §3.5: "It moves the work order to `ABANDONED` and stamps
    `total_cost_cents` by the same formula with `packaging_cost_cents` treated as
    zero, then appends a `REFURB_COST` entry for the negative of that cost and
    recomputes the client's `shrink_ledger_cents` and `settlement_balance_cents`."

    Design: Corner/state_machines/corner_work_order_abandon_writes_off_cost_and_returns_line_to_disposition
    """
    world = _refurbishing_line(api, "SM10", "SM Ten", "ORD-SM10", "TRK-SM10")
    bay = fx.make_general_bay(api, bay_code="GB-SM10", buffer_minutes=0)
    fx.run_failed_test_cycle(
        api,
        world["work_order"]["id"],
        bay["id"],
        TEST_WINDOW_1_START,
        TEST_WINDOW_1_END,
        labor_minutes=30,
    )

    abandoned = validate_success(
        api.abandon_work_order(
            world["work_order"]["id"],
            f.abandon_payload("Board fault not economically repairable"),
            TECHNICIAN,
        ),
        200,
    )
    assert abandoned["status"] == WO_ABANDONED
    assert abandoned["labor_minutes_total"] == 30
    assert_money(abandoned["parts_cost_cents"], 0, "parts_cost_cents")
    assert_money(abandoned["packaging_cost_cents"], 0, "packaging_cost_cents")
    # 30 x 95 == 2850 direct, x 1.15 overhead == 3277.5, rounded half up once.
    assert_money(abandoned["total_cost_cents"], 3278, "total_cost_cents")

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        disposition=DISPOSITION_LIQUIDATE,
    )
    assert_money(line["recovery_value_cents"], 11700, "recovery is not recomputed")

    entries = fx.list_ledger(api, world["client"]["id"])
    assert len(entries) == 1
    cost = sole_entry_of_type(entries, ENTRY_REFURB_COST)
    assert_money(cost["amount_cents"], -3278, "REFURB_COST amount_cents")
    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["shrink_ledger_cents"], -3278, "shrink_ledger_cents")
    assert_money(client["settlement_balance_cents"], -3278, "settlement_balance_cents")


def test_an_untested_work_order_cannot_be_repackaged(api):
    """PRD §2.6: "Priority 25 requires the work order's `status` to admit the
    requested transition: test start only from `OPEN` or `TEST_FAILED`,
    test-result recording only from `IN_TEST`, repackage only from `PASSED_QA`,
    and abandonment only from `OPEN`, `IN_TEST`, `TEST_FAILED` or `PASSED_QA`."

    Design: Corner/state_machines/corner_work_order_repackage_from_open_is_not_a_declared_transition
    """
    world = _refurbishing_line(api, "SM11", "SM Eleven", "ORD-SM11", "TRK-SM11")

    response = api.repackage_work_order(
        world["work_order"]["id"],
        f.repackage_payload(packaging_cost_cents=500, resulting_grade=GRADE_B),
        TECHNICIAN,
    )
    validate_error(response, ERR_WORK_ORDER_INVALID_STATE, 409)

    work_order = fx.read_work_order(api, world["work_order"]["id"])
    assert work_order["status"] == WO_OPEN
    assert_money(work_order["packaging_cost_cents"], 0, "packaging_cost_cents")
    assert_money(work_order["total_cost_cents"], 0, "total_cost_cents")

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(line, disposition_state=DS_IN_REFURB)
    assert fx.list_ledger(api, world["client"]["id"]) == []


def test_a_cancelled_disposition_order_can_never_be_approved(api):
    """PRD §2.6: "Priority 26 requires the disposition order's `status` to admit
    the requested transition: approval only from `PROPOSED`, execution only from
    `APPROVED`, cancellation only from `PROPOSED` or `APPROVED`."

    Design: Corner/state_machines/corner_disposition_order_approve_after_cancel_terminal_lockdown
    """
    world = fx.graded_scenario(
        api,
        client_kwargs={"name": "SM Twelve", "client_code": "SM12"},
        items=[fx.widget_item_kwargs()],
        lines=ONE_DEFECTIVE_UNIT,
        condition_grade=GRADE_C,
        rma_kwargs={"order_reference": "ORD-SM12", "customer_reference": "CUST-SM12"},
        tracking_reference="TRK-SM12",
    )
    channel = fx.make_channel(
        api, **fx.auction_channel_kwargs("AU12", name="Auction Twelve")
    )
    order = fx.propose_order(api, world["line"]["id"], channel_id=channel["id"])
    cancelled = get_success_data(
        api.cancel_disposition_order(order["id"], f.cancel_payload(), SUPERVISOR)
    )
    assert cancelled["status"] == DO_CANCELLED

    response = api.approve_disposition_order(order["id"], SUPERVISOR)
    validate_error(response, ERR_DISPOSITION_ORDER_INVALID_STATE, 409)

    unchanged = fx.read_order(api, order["id"])
    assert unchanged["status"] == DO_CANCELLED
    assert unchanged["executed_at"] is None

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        financial_state=FS_HOLD_PENDING_DISPOSITION,
    )
    assert fx.list_ledger(api, world["client"]["id"]) == [], (
        "no recovery credit was ever appended"
    )


def test_moving_the_clock_past_expiry_expires_the_authorization(api):
    """PRD §3.2: "Whenever a `CenterAdmin` moves the logical clock, the system
    sweeps every authorization in `ISSUED` or `PARTIALLY_RECEIVED` whose
    `expires_at` is at or before the new clock value and moves it to `EXPIRED`."

    Design: Corner/state_machines/corner_clock_advance_expires_issued_rma_and_books_receipt_variance
    """
    world = fx.received_scenario(
        api,
        client_kwargs={"name": "SM Thirteen", "client_code": "SM13"},
        items=[fx.widget_item_kwargs()],
        lines=ONE_DEFECTIVE_UNIT,
        rma_kwargs={
            "order_reference": "ORD-SM13",
            "customer_reference": "CUST-SM13",
            "expires_at": plus_days(CLOCK_STARTUP_INSTANT, 4),
        },
        scan=False,
    )
    assert world["rma"]["status"] == RMA_ISSUED

    fx.set_clock(api, plus_days(CLOCK_STARTUP_INSTANT, 5))

    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["status"] == RMA_EXPIRED

    entries = fx.list_ledger(api, world["client"]["id"])
    assert len(entries) == 1
    variance = entries_of_type(entries, ENTRY_RECEIPT_VARIANCE)[0]
    assert_money(variance["amount_cents"], -20000, "RECEIPT_VARIANCE amount_cents")
    assert variance["sequence_no"] == 1

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["shrink_ledger_cents"], -20000, "shrink_ledger_cents")
    assert_money(client["settlement_balance_cents"], -20000, "settlement_balance_cents")
    assert client["open_rma_count"] == 0

    response = api.create_receipt(
        f.receipt_payload(
            world["rma"]["id"],
            tracking_reference="TRK-SM13",
            gross_weight_grams=world["expected_weight_grams"],
        ),
        CLERK,
    )
    validate_error(response, ERR_RMA_EXPIRED, 409)
