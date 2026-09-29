"""The five-link execution cascade and the four-link mandatory-recall cascade."""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLIENT_SUSPENDED,
    ERR_RECALLED_ITEM_NOT_REFURBISHABLE,
)
from test_helpers.assertions import (
    assert_conservation_flags,
    assert_line_states,
    assert_money,
    assert_pct_equals,
    assert_unit_buckets,
    entries_of_type,
    expected_destruction_write_off,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CLIENT_STATUS_ACTIVE,
    CLIENT_STATUS_SUSPENDED,
    DISPOSITION_DESTROY,
    DISPOSITION_LIQUIDATE,
    DISPOSITION_REFURBISH,
    DO_CANCELLED,
    DO_EXECUTED,
    DS_DISPOSITION_ASSIGNED,
    DS_DISPOSITIONED,
    DS_IN_REFURB,
    ENTRY_DESTRUCTION_WRITE_OFF,
    ENTRY_DONATION_WRITE_OFF,
    ENTRY_RECOVERY_CREDIT,
    ENTRY_REFURB_COST,
    FS_RELEASE_PENDING,
    GRADE_B,
    GRADE_C,
    GRADE_SCRAP,
    RECALL_MANDATORY,
    REASON_DEFECTIVE,
    RMA_CLOSED,
    TEST_WINDOW_1_END,
    TEST_WINDOW_1_START,
    TEST_WINDOW_2_END,
    TEST_WINDOW_2_START,
    TEST_WINDOW_3_END,
    TEST_WINDOW_3_START,
    USER_SUPERVISOR,
    USER_SUPERVISOR_2,
    WO_ABANDONED,
    WO_IN_TEST,
    WO_OPEN,
)
from test_helpers.test_users import ADMIN, SUPERVISOR_2, TECHNICIAN


def _destruction_client_kwargs(client_code):
    """A retailer whose exposure cap is small enough for one write-off to breach it."""
    return {
        "name": "Destruction Client",
        "client_code": client_code,
        "restock_grade_floor": GRADE_B,
        "refund_hold_hours": 48,
        "liquidation_floor_pct": 0.90,
        "fraud_tolerance_cents": 100000000,
        "donation_allowed": False,
        "destroy_requires_dual_signoff": False,
        "max_refund_exposure_cents": 20000,
    }


def _approved_destroy_world(api, client_code):
    """A scrapped line routed to destruction with its order already approved."""
    world = fx.graded_scenario(
        api,
        client_kwargs=_destruction_client_kwargs(client_code),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_SCRAP,
    )
    world["channel"] = fx.make_destruction_channel(api)
    world["order"] = fx.propose_and_approve(
        api, world["line"]["id"], channel_id=world["channel"]["id"]
    )
    return world


def _recall_item_world(api, client_code, bay_code="BAY-G1"):
    """A grade-C refurbishable line on its third test cycle, two rework cycles in."""
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(client_code),
        items=[fx.widget_item_kwargs(sku="RECALL-1", refurb_eligible=True)],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    world["bay"] = fx.make_general_bay(api, bay_code=bay_code, buffer_minutes=30)
    work_order = fx.open_work_order(api, world["line"]["id"])
    fx.run_failed_test_cycle(
        api,
        work_order["id"],
        world["bay"]["id"],
        TEST_WINDOW_1_START,
        TEST_WINDOW_1_END,
        labor_minutes=15,
    )
    fx.run_failed_test_cycle(
        api,
        work_order["id"],
        world["bay"]["id"],
        TEST_WINDOW_2_START,
        TEST_WINDOW_2_END,
        labor_minutes=15,
    )
    world["work_order"] = fx.start_test(
        api,
        work_order["id"],
        world["bay"]["id"],
        TEST_WINDOW_3_START,
        TEST_WINDOW_3_END,
    )
    return world


def _file_recall(api, catalog_item_id, recall_status=RECALL_MANDATORY):
    """File a recall notice against a catalogue item as a CenterAdmin."""
    return get_success_data(
        api.recall_catalog_item(
            catalog_item_id, {"recall_status": recall_status}, ADMIN
        )
    )


def test_executing_a_destroy_order_runs_all_five_links_in_order(api):
    """PRD §2.9: "Executing a disposition order runs a five-link cascade in a
    fixed order: link 1 moves the line's `disposition_state` to `DISPOSITIONED`
    and re-stamps its `recovery_value_cents`; link 2 appends exactly one
    shrink-ledger entry for the line; link 3 recomputes the owning client's unit
    buckets, `shrink_ledger_cents` and `settlement_balance_cents` from that
    appended entry; link 4 suspends the client when the recomputed settlement
    balance has fallen below the negated exposure cap; and link 5 closes the
    parent authorization once every one of its sibling lines has reached
    `DISPOSITIONED`."

    Design: Difficulty/transitive_cascade/execute_destroy_order_cascades_to_client_suspension_and_rma_close
    """
    world = _approved_destroy_world(api, "CLDES")
    assert world["order"]["approved_by_user_id"] == USER_SUPERVISOR

    executed = fx.execute_order(api, world["order"]["id"], headers=SUPERVISOR_2)
    assert executed["status"] == DO_EXECUTED
    assert executed["executed_by_user_id"] == USER_SUPERVISOR_2
    # A scrapped unit has no provisional recovery, so the lot grosses nothing.
    assert_money(executed["gross_lot_value_cents"], 0, "gross_lot_value_cents")
    assert_pct_equals(executed["effective_fee_pct"], 0.06, "effective_fee_pct")
    assert_money(executed["channel_fee_cents"], 0, "channel_fee_cents")
    assert_money(executed["net_recovery_cents"], 0, "net_recovery_cents")

    # Link 1.
    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITIONED,
        disposition=DISPOSITION_DESTROY,
    )
    assert_money(line["recovery_value_cents"], 0, "final recovery")

    # Link 2: the destruction fee rides in the ledger, not in net recovery.
    ledger = fx.list_ledger(api, world["client"]["id"])
    assert len(ledger) == 1, f"exactly one entry may exist, got {len(ledger)}"
    entry = sole_entry_of_type(ledger, ENTRY_DESTRUCTION_WRITE_OFF)
    assert_money(entry["amount_cents"], -20750, "DESTRUCTION_WRITE_OFF amount_cents")
    assert_money(
        entry["amount_cents"],
        expected_destruction_write_off(20000, 1),
        "DESTRUCTION_WRITE_OFF amount_cents",
    )
    assert entry["return_line_id"] == world["line"]["id"]

    # Links 3 and 4: -20750 sits below the negated 20000 exposure cap.
    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], -20750, "settlement_balance_cents")
    assert_money(client["shrink_ledger_cents"], -20750, "shrink_ledger_cents")
    assert client["status"] == CLIENT_STATUS_SUSPENDED, client["status"]
    assert_unit_buckets(client, received=1, in_process=0, reserved=0, dispositioned=1)

    # Link 5.
    rma = fx.read_rma(api, world["rma"]["id"])
    assert rma["status"] == RMA_CLOSED, rma["status"]


def test_the_audit_report_proves_conservation_across_the_whole_cascade(api):
    """PRD §3.8: "`unit_conservation_ok` is true when `units_received` equals
    `units_in_process` plus `units_reserved_for_disposition` plus
    `units_dispositioned`. `money_conservation_ok` is true when
    `settlement_balance_cents` equals the sum of all seven per-entry-type
    totals."

    Design: Difficulty/transitive_cascade/execute_destroy_order_cascades_to_client_suspension_and_rma_close
    """
    world = _approved_destroy_world(api, "CLDES2")
    fx.execute_order(api, world["order"]["id"], headers=SUPERVISOR_2)

    report = fx.read_audit(api, world["client"]["id"])
    assert report["destroy_count"] == 1, report["destroy_count"]
    assert report["pending_count"] == 0, report["pending_count"]
    assert report["restock_count"] == 0
    assert report["refurbish_count"] == 0
    assert report["liquidate_count"] == 0
    assert report["donate_count"] == 0
    assert_unit_buckets(report, received=1, in_process=0, reserved=0, dispositioned=1)
    assert_money(
        report["destruction_write_off_cents"], -20750, "destruction_write_off_cents"
    )
    assert_money(report["recovery_credit_cents"], 0, "recovery_credit_cents")
    assert_money(report["settlement_balance_cents"], -20750, "settlement_balance_cents")
    assert_conservation_flags(report)


def test_the_automatic_suspension_latches_and_blocks_the_next_authorization(api):
    """PRD §2.10: "Suspension halts everything that would increase the center's
    exposure to that retailer: no new return authorizations, no new authorization
    lines, no issuing, no new receipts, no new scanned unit lines, no new
    disposition orders and no refund releases. Any of those attempted against a
    suspended client is rejected with `ERR_CLIENT_SUSPENDED`."

    Design: Difficulty/transitive_cascade/execute_destroy_order_cascades_to_client_suspension_and_rma_close
    """
    world = _approved_destroy_world(api, "CLDES3")
    before = fx.read_client(api, world["client"]["id"])
    assert before["status"] == CLIENT_STATUS_ACTIVE

    fx.execute_order(api, world["order"]["id"], headers=SUPERVISOR_2)

    response = api.create_rma(
        f.rma_payload(
            world["client"]["id"],
            order_reference="ORD-1008",
            customer_reference="CUST-8",
        ),
        ADMIN,
    )
    validate_error(response, ERR_CLIENT_SUSPENDED, 409)

    # Reads remain fully available to prove the posture rather than the failure.
    after = fx.read_client(api, world["client"]["id"])
    assert after["status"] == CLIENT_STATUS_SUSPENDED


def test_execution_couples_the_money_axis_and_prices_the_scrap_restocking_fee(api):
    """PRD §3.4: "A grade adjustment is added: 0.00 for `A`, 0.05 for `B`, 0.10
    for `C`, 0.15 for `D` and 0.25 for `SCRAP`."

    Design: Difficulty/transitive_cascade/execute_destroy_order_cascades_to_client_suspension_and_rma_close
    """
    world = _approved_destroy_world(api, "CLDES4")
    fx.execute_order(api, world["order"]["id"], headers=SUPERVISOR_2)

    refund = fx.refund_release_for_line(api, world["line"]["id"])
    assert_money(refund["gross_refund_cents"], 20000, "gross_refund_cents")
    # DEFECTIVE 0.00 + SL_STANDARD 0.00 + SCRAP 0.25 + no lateness band.
    assert_pct_equals(refund["restocking_fee_pct"], 0.25, "restocking_fee_pct")
    assert_money(refund["restocking_fee_cents"], 5000, "restocking_fee_cents")
    assert_money(refund["net_refund_cents"], 15000, "net_refund_cents")

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITIONED,
        financial_state=FS_RELEASE_PENDING,
    )


def test_mandatory_recall_forces_destroy_and_abandons_the_live_work_order(api):
    """PRD §3.8: "Link one forces `disposition` to `DESTROY` on every affected
    `ReturnLine` whose `disposition_state` is `RECEIVED_UNGRADED`,
    `QUARANTINED`, `DISPOSITION_ASSIGNED` or `IN_REFURB`, advancing each line's
    `version`; a line already in `DISPOSITION_ASSIGNED` self-loops there with a
    new disposition."

    Design: Difficulty/transitive_cascade/mandatory_recall_cascades_through_refurb_abandon_to_shrink_ledger
    """
    world = _recall_item_world(api, "CLRECALL")
    work_order = world["work_order"]
    assert work_order["status"] == WO_IN_TEST
    assert work_order["rework_cycles"] == 2
    assert work_order["labor_minutes_total"] == 30

    before_line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        before_line,
        disposition_state=DS_IN_REFURB,
        disposition=DISPOSITION_REFURBISH,
    )

    recalled = _file_recall(api, world["item"]["id"])
    assert recalled["recall_status"] == RECALL_MANDATORY

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        disposition=DISPOSITION_DESTROY,
    )
    assert line["version"] > before_line["version"]

    swept = fx.read_work_order(api, work_order["id"])
    assert swept["status"] == WO_ABANDONED, swept["status"]
    assert swept["packaging_cost_cents"] == 0
    # 30 minutes at 95 cents loaded once by 15 percent: 2850 x 1.15 is 3277.5.
    assert_money(swept["total_cost_cents"], 3278, "total_cost_cents")

    entry = sole_entry_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_REFURB_COST
    )
    assert_money(entry["amount_cents"], -3278, "REFURB_COST amount_cents")

    client = fx.read_client(api, world["client"]["id"])
    assert_money(client["settlement_balance_cents"], -3278, "settlement_balance_cents")
    assert_money(client["shrink_ledger_cents"], -3278, "shrink_ledger_cents")


def test_the_recall_orders_destruction_without_writing_the_destruction_off(api):
    """PRD §3.8: "A `DESTRUCTION_WRITE_OFF` is appended when a `DESTROY` order
    executes, and its amount is the negative of the item's
    `declared_value_cents` plus the 750-cent certified-destruction fee, that sum
    multiplied by the order's `quantity`."

    Design: Difficulty/transitive_cascade/mandatory_recall_cascades_through_refurb_abandon_to_shrink_ledger
    """
    world = _recall_item_world(api, "CLREC2", bay_code="BAY-G2")
    _file_recall(api, world["item"]["id"])

    ledger = fx.list_ledger(api, world["client"]["id"])
    assert len(ledger) == 1, f"only the refurbishment write-off may exist, got {ledger}"
    assert entries_of_type(ledger, ENTRY_DESTRUCTION_WRITE_OFF) == []
    assert entries_of_type(ledger, ENTRY_DONATION_WRITE_OFF) == []
    assert entries_of_type(ledger, ENTRY_RECOVERY_CREDIT) == []

    client = fx.read_client(api, world["client"]["id"])
    assert client["status"] == CLIENT_STATUS_ACTIVE, client["status"]
    assert_unit_buckets(client, received=1, in_process=1, reserved=0, dispositioned=0)


def test_a_work_order_still_open_is_not_swept_but_is_barred_from_starting(api):
    """PRD §3.8: "A work order still in `OPEN` is deliberately **not** swept: it
    has consumed no bay time and no labour, so there is nothing to write off — it
    stays `OPEN` and is instead permanently barred from ever starting by the
    recall rule, which refuses it with `ERR_RECALLED_ITEM_NOT_REFURBISHABLE`."

    Design: Difficulty/transitive_cascade/mandatory_recall_cascades_through_refurb_abandon_to_shrink_ledger
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("CLREC3"),
        items=[fx.widget_item_kwargs(sku="RECALL-3", refurb_eligible=True)],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    bay = fx.make_general_bay(api, bay_code="BAY-G3", buffer_minutes=30)
    work_order = fx.open_work_order(api, world["line"]["id"])
    assert work_order["status"] == WO_OPEN
    assert work_order["labor_minutes_total"] == 0

    _file_recall(api, world["item"]["id"])

    untouched = fx.read_work_order(api, work_order["id"])
    assert untouched["status"] == WO_OPEN, untouched["status"]
    assert_money(untouched["total_cost_cents"], 0, "total_cost_cents")
    assert entries_of_type(
        fx.list_ledger(api, world["client"]["id"]), ENTRY_REFURB_COST
    ) == []

    line = fx.read_return_line(api, world["line"]["id"])
    assert line["disposition"] == DISPOSITION_DESTROY

    response = api.start_test(
        work_order["id"],
        f.start_test_payload(bay["id"], TEST_WINDOW_1_START, TEST_WINDOW_1_END),
        TECHNICIAN,
    )
    validate_error(response, ERR_RECALLED_ITEM_NOT_REFURBISHABLE, 409)


def test_the_recall_cancels_an_in_flight_order_and_returns_its_units(api):
    """PRD §3.8: "Link two moves every `DispositionOrder` of those lines in
    `PROPOSED` or `APPROVED` to `CANCELLED`, returning its units from
    `units_reserved_for_disposition` to `units_in_process`."

    Design: Difficulty/transitive_cascade/mandatory_recall_cascades_through_refurb_abandon_to_shrink_ledger
    """
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("CLREC4"),
        items=[fx.widget_item_kwargs(sku="RECALL-4")],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
    )
    channel = fx.make_channel(api, **fx.auction_channel_kwargs("AUC1"))
    order = fx.propose_order(
        api,
        world["line"]["id"],
        channel_id=channel["id"],
        disposition=DISPOSITION_LIQUIDATE,
        quantity=1,
    )
    reserved = fx.read_client(api, world["client"]["id"])
    assert_unit_buckets(reserved, received=1, in_process=0, reserved=1, dispositioned=0)

    _file_recall(api, world["item"]["id"])

    cancelled = fx.read_order(api, order["id"])
    assert cancelled["status"] == DO_CANCELLED, cancelled["status"]
    assert cancelled["version"] > order["version"]

    line = fx.read_return_line(api, world["line"]["id"])
    assert_line_states(
        line,
        disposition_state=DS_DISPOSITION_ASSIGNED,
        disposition=DISPOSITION_DESTROY,
    )

    client = fx.read_client(api, world["client"]["id"])
    assert_unit_buckets(client, received=1, in_process=1, reserved=0, dispositioned=0)
    assert fx.list_ledger(api, world["client"]["id"]) == []
