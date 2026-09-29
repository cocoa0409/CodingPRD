"""Endpoint behaviour: computed reads, cross-resource links and action verbs."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import ERR_NO_ELIGIBLE_CHANNEL
from test_helpers.assertions import (
    assert_conservation_flags,
    assert_index_pct_equals,
    assert_line_states,
    assert_money,
    assert_page_meta,
    assert_pct_equals,
    assert_unit_buckets,
    expected_recovery_credit,
)
from test_helpers.constants import (
    CHANNEL_STATUS_ACTIVE,
    CHANNEL_STATUS_PAUSED,
    CHANNEL_TYPE_BULK_LIQUIDATOR,
    CLIENT_STATUS_ACTIVE,
    CLIENT_STATUS_SUSPENDED,
    DISPOSITION_LIQUIDATE,
    DS_DISPOSITIONED,
    ENTRY_RECOVERY_CREDIT,
    ENTRY_REFUND_DEBIT,
    ENTRY_REVERSAL,
    FS_CLAWED_BACK,
    FS_REFUNDED,
    GRADE_C,
    REASON_DEFECTIVE,
    RMA_ISSUED,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    SUPERVISOR,
    SUPERVISOR_2,
)

# The single lot window every order in this file books.
LOT_WINDOW_START = "2026-08-01T08:00:00Z"
LOT_WINDOW_END = "2026-08-01T12:00:00Z"
LATER_WINDOW_START = "2026-08-03T08:00:00Z"
LATER_WINDOW_END = "2026-08-03T12:00:00Z"


def _liquidation_channel(api, channel_code, name):
    """One BULK_LIQUIDATOR taking grade C at a 12 percent base commission."""
    return fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            channel_code=channel_code,
            name=name,
            channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
            accepted_grades=[GRADE_C],
        ),
    )


def test_the_audit_report_reconciles_every_aggregate_it_publishes(api):
    """PRD §3.9: "`money_conservation_ok` is true when
    `settlement_balance_cents` equals the sum of all seven per-entry-type
    totals."

    Design: Corner/endpoints/corner_ep_disposition_audit_report_reconciles_every_aggregate
    """
    channel = _liquidation_channel(api, "AL-VD1", "Audit Liquidator")
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            "VD1", name="Audit Client", refund_hold_hours=0
        ),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VD1",
    )
    line = world["line"]
    order = fx.propose_and_approve(
        api,
        line["id"],
        channel_id=channel["id"],
        window_start_at=LOT_WINDOW_START,
        window_end_at=LOT_WINDOW_END,
        approver=SUPERVISOR,
    )
    fx.execute_order(api, order["id"], headers=SUPERVISOR_2)
    validate_success(api.release_refund(line["id"], ANALYST), 200)

    report = fx.read_audit(api, world["client"]["id"])

    assert report["pending_count"] == 0
    assert report["restock_count"] == 0
    assert report["refurbish_count"] == 0
    assert report["liquidate_count"] == 1
    assert report["donate_count"] == 0
    assert report["destroy_count"] == 0

    # Gross 7200 at a 0.18 small-lot effective fee nets 5904; the center keeps
    # 7.5 percent of that, leaving a 5461-cent credit.
    credit = expected_recovery_credit(5904)
    assert_money(report["recovery_credit_cents"], credit, "recovery_credit_cents")
    assert_money(report["refund_debit_cents"], -18000, "refund_debit_cents")
    assert_money(report["reversal_cents"], 0, "reversal_cents")
    assert_money(report["refurb_cost_cents"], 0, "refurb_cost_cents")
    assert_money(
        report["donation_write_off_cents"], 0, "donation_write_off_cents"
    )
    assert_money(
        report["destruction_write_off_cents"], 0, "destruction_write_off_cents"
    )
    assert_money(report["receipt_variance_cents"], 0, "receipt_variance_cents")

    # The realized 5904 measured against the provisional 7200 estimate.
    assert_money(report["recovery_variance_cents"], -1296, "recovery_variance_cents")
    assert_money(
        report["settlement_balance_cents"], credit - 18000, "settlement_balance_cents"
    )
    assert_money(
        report["projected_settlement_balance_cents"],
        credit - 18000,
        "projected balance with nothing in flight",
    )
    assert_money(report["shrink_ledger_cents"], 0, "shrink_ledger_cents")

    assert_unit_buckets(
        report, received=1, in_process=0, reserved=0, dispositioned=1
    )
    assert_conservation_flags(report)


def test_pricing_feedback_reindexes_the_channel_it_names(api):
    """PRD §3.6: "The system copies `expected_price_cents` from the order's
    `unit_price_cents` at the moment of the report, computes `variance_pct` as the
    realized price minus the expected price divided by the expected price, rounded
    half up to four fractional digits, or exactly 0.0000 when the expected price is
    zero, and assigns `sequence_no` as that channel's next value in a monotonic
    counter starting at 1."

    Design: Corner/endpoints/corner_ep_pricing_feedback_links_order_to_channel_and_reindexes_it
    """
    channel = _liquidation_channel(api, "FB-VD2", "Feedback Liquidator")
    assert_index_pct_equals(channel["price_index_pct"], 1.0)
    world = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            "VD2", name="Feedback Client", refund_hold_hours=0
        ),
        items=[fx.widget_item_kwargs()],
        lines=[
            {
                "authorized_quantity": 2,
                "reason_code": REASON_DEFECTIVE,
                "scan_quantity": 1,
            }
        ],
        tracking_reference="TRK-VD2",
    )
    first_line = fx.grade_line(api, world["line"]["id"], GRADE_C)
    first_order = fx.propose_and_approve(
        api,
        first_line["id"],
        channel_id=channel["id"],
        window_start_at=LOT_WINDOW_START,
        window_end_at=LOT_WINDOW_END,
        approver=SUPERVISOR,
    )
    assert_money(first_order["unit_price_cents"], 7200, "frozen unit_price_cents")
    fx.execute_order(api, first_order["id"], realized_unit_price_cents=5760,
                     headers=SUPERVISOR_2)

    feedback = validate_success(
        api.create_pricing_feedback(
            f.pricing_feedback_payload(first_order["id"], channel["id"], 5760),
            SUPERVISOR,
        ),
        201,
    )
    assert feedback["disposition_order_id"] == first_order["id"]
    assert feedback["channel_id"] == channel["id"]
    assert_money(feedback["expected_price_cents"], 7200, "expected_price_cents")
    assert_money(feedback["realized_price_cents"], 5760, "realized_price_cents")
    assert_pct_equals(feedback["variance_pct"], -0.2000, "variance_pct")
    assert feedback["sequence_no"] == 1

    reindexed = validate_success(api.get_channel(channel["id"], SUPERVISOR), 200)
    assert_index_pct_equals(reindexed["price_index_pct"], 0.8000)

    rows, meta = validate_paginated(
        api.list_pricing_feedback(SUPERVISOR, {"channel_id": channel["id"]})
    )
    assert meta["total_count"] == 1
    assert [row["id"] for row in rows] == [feedback["id"]]

    # The loop closes: the next lot on that channel is priced at the new index.
    second_unit = fx.scan_line(
        api, world["receipt"]["id"], world["rma_line"]["id"], quantity=1
    )
    second_line = fx.grade_line(api, second_unit["id"], GRADE_C)
    second_order = fx.propose_order(
        api,
        second_line["id"],
        channel_id=channel["id"],
        window_start_at=LATER_WINDOW_START,
        window_end_at=LATER_WINDOW_END,
    )
    assert_money(
        second_order["unit_price_cents"], 5760, "re-indexed unit_price_cents"
    )


def test_suspending_and_reinstating_a_client_touches_nothing_else(api):
    """PRD §2.10: "A `CenterAdmin` may suspend a client explicitly, optionally
    recording a `suspension_reason`, and may later reinstate it to `ACTIVE`."

    Design: Corner/endpoints/corner_ep_client_suspend_and_reinstate_flip_status_without_touching_history
    """
    client = fx.make_client(api, name="Posture Client", client_code="VD3")
    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    issued = fx.make_issued_rma(
        api,
        client["id"],
        [
            {
                "catalog_item_id": item["id"],
                "authorized_quantity": 1,
                "reason_code": REASON_DEFECTIVE,
            }
        ],
        order_reference="ORD-VD3",
        customer_reference="CUST-VD3",
    )
    assert client["version"] == 1

    suspended = validate_success(
        api.suspend_client(
            client["id"], ADMIN, {"suspension_reason": "unpaid settlement statement"}
        ),
        200,
    )
    assert suspended["status"] == CLIENT_STATUS_SUSPENDED
    assert suspended["version"] == 2

    read_back = fx.read_client(api, client["id"])
    assert read_back["open_rma_count"] == 1, "suspension recomputes nothing"
    assert_unit_buckets(read_back, received=0, in_process=0, reserved=0,
                        dispositioned=0)
    assert_money(read_back["settlement_balance_cents"], 0, "settlement_balance_cents")
    assert fx.read_rma(api, issued["rma"]["id"])["status"] == RMA_ISSUED, (
        "no cascade reached the authorization"
    )

    reinstated = validate_success(api.reinstate_client(client["id"], ADMIN), 200)
    assert reinstated["status"] == CLIENT_STATUS_ACTIVE
    assert reinstated["version"] == 3

    rows, _ = validate_paginated(
        api.list_clients(ADMIN, {"status": CLIENT_STATUS_SUSPENDED, "limit": 100})
    )
    assert client["id"] not in [row["id"] for row in rows]


def test_a_paused_channel_leaves_the_selector_candidate_set(api):
    """PRD §3.1: "A `CenterAdmin` or `DispositionSupervisor` may pause a channel,
    optionally recording a `pause_reason`, which moves its `status` to `PAUSED`,
    removes it from the selector's candidate set and blocks execution of orders
    already routed to it; resuming returns it to `ACTIVE`."

    Design: Corner/endpoints/corner_ep_pausing_a_channel_removes_it_from_the_selector_candidate_set
    """
    channel = _liquidation_channel(api, "PB-VD4", "Pausable Liquidator")
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("VD4", name="Pause Client"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VD4",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_LIQUIDATE)

    paused = validate_success(
        api.pause_channel(
            channel["id"], SUPERVISOR,
            {"pause_reason": "settlement dispute with the buyer"},
        ),
        200,
    )
    assert paused["status"] == CHANNEL_STATUS_PAUSED

    selector_body = f.disposition_order_payload(
        line["id"],
        line["version"],
        channel_window_start_at=LATER_WINDOW_START,
        channel_window_end_at=LATER_WINDOW_END,
    )
    validate_error(
        api.create_disposition_order(selector_body, SUPERVISOR),
        ERR_NO_ELIGIBLE_CHANNEL,
        409,
    )

    resumed = validate_success(api.resume_channel(channel["id"], SUPERVISOR), 200)
    assert resumed["status"] == CHANNEL_STATUS_ACTIVE

    order = validate_success(
        api.create_disposition_order(selector_body, SUPERVISOR), 201
    )
    assert order["channel_id"] == channel["id"]
    assert order["selected_by_policy"] is True
    assert_money(order["unit_price_cents"], 7200, "unit_price_cents")


def test_the_ledger_listing_filters_and_pages_over_its_sequence_order(api):
    """PRD §2.3: "The shrink-ledger listing is the one place where the domain gives
    that ordering a second name: because each client's entries are numbered by a
    monotonic `sequence_no` in append order, ordering by `created_at` ascending and
    ordering by `sequence_no` ascending describe the same sequence for a single
    client."

    Design: Corner/endpoints/corner_ep_shrink_ledger_list_filters_and_paginates_in_sequence_order
    """
    channel = _liquidation_channel(api, "LL-VD5", "Ledger Liquidator")
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs(
            "VD5", name="Ledger Client", refund_hold_hours=0
        ),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-VD5",
    )
    line = world["line"]
    client_id = world["client"]["id"]
    order = fx.propose_and_approve(
        api,
        line["id"],
        channel_id=channel["id"],
        window_start_at=LOT_WINDOW_START,
        window_end_at=LOT_WINDOW_END,
        approver=SUPERVISOR,
    )
    fx.execute_order(api, order["id"], headers=SUPERVISOR_2)
    released = validate_success(api.release_refund(line["id"], ANALYST), 200)
    assert_line_states(released, financial_state=FS_REFUNDED)
    validate_success(
        api.reverse_refund(
            line["id"],
            f.reverse_refund_payload("customer never shipped the unit back"),
            ANALYST,
        ),
        200,
    )

    credit = expected_recovery_credit(5904)
    rows, meta = validate_paginated(
        api.list_shrink_ledger_entries(ADMIN, {"client_id": client_id, "limit": 100})
    )
    assert_page_meta(meta, limit=100, offset=0, total_count=3, has_more=False)
    assert [row["sequence_no"] for row in rows] == [1, 2, 3]
    assert [row["entry_type"] for row in rows] == [
        ENTRY_RECOVERY_CREDIT,
        ENTRY_REFUND_DEBIT,
        ENTRY_REVERSAL,
    ]
    assert [row["amount_cents"] for row in rows] == [credit, -18000, 18000]
    assert rows[0]["return_line_id"] == line["id"]

    filtered_rows, filtered_meta = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN, {"client_id": client_id, "entry_type": ENTRY_REVERSAL, "limit": 100}
        )
    )
    assert filtered_meta["total_count"] == 1
    assert_money(filtered_rows[0]["amount_cents"], 18000, "REVERSAL amount_cents")
    assert filtered_rows[0]["sequence_no"] == 3

    paged_rows, paged_meta = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN, {"client_id": client_id, "limit": 2, "offset": 2}
        )
    )
    assert [row["sequence_no"] for row in paged_rows] == [3]
    assert_page_meta(paged_meta, limit=2, offset=2, total_count=3, has_more=False)

    settled = fx.read_client(api, client_id)
    assert_money(
        settled["settlement_balance_cents"], credit, "settlement after the reversal"
    )
    assert_money(settled["shrink_ledger_cents"], 0, "shrink_ledger_cents")
    final_line = fx.read_return_line(api, line["id"])
    assert_line_states(
        final_line, financial_state=FS_CLAWED_BACK, disposition_state=DS_DISPOSITIONED
    )
