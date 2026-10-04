"""Trade work-order commercial loop: quotes, permits, coverage, inspection
rework, strikes, and payment (PRD §3.7)."""

from test_helpers import (
    ApiErrorId,
    approve_work_order,
    api_client,
    create_contractor,
    create_work_order,
    create_work_order_payload,
    drive_work_order_to,
    get_contractor,
    get_cycle,
    get_project,
    get_work_order,
    inspect_work_order,
    invoice_work_order,
    make_trade_partner_headers,
    pay_work_order,
    schedule_work_order,
    set_clock,
    setup_project_with_work_order,
    setup_selected_project,
    trade_scope_item_payload,
    validate_error,
    validate_ok,
    validate_paginated,
    DEFAULT_VISIT_CLOCK_ISO,
    STAFF,
)


def test_work_order_inspection_rework_loop_reaches_passed():
    """PRD §3.7: "A failing outcome moves the order to `INSPECTION_FAILED`,
    stamps `inspected_on`, and adds one to the contractor's `strike_count`;
    when the count reaches 3 the contractor auto-suspends (`ACTIVE` →
    `SUSPENDED`) and the full suspension cascade below fires."
    PRD §3.7: "Rework loops the order `INSPECTION_FAILED` → `IN_PROGRESS`,
    permitted only while the contractor is `ACTIVE` (else
    `ERR_CONTRACTOR_NOT_QUALIFIED`)."

    The order loops IN_PROGRESS -> PENDING_INSPECTION -> INSPECTION_FAILED ->
    IN_PROGRESS -> PENDING_INSPECTION -> INSPECTED; a single FAILED inspection
    leaves strike_count at 1 and the contractor ACTIVE.

    Design: Difficulty/non_linear_state_machine/work_order_inspection_rework_loop
    """
    ctx = setup_project_with_work_order(
        item_est=(100_000, 300_000),
        requires_permit=True,
        wo_target_status="PENDING_INSPECTION",
        quote_cents=180_000,
        budget_cents=2_000_000,
    )
    wo_id = ctx["work_order"]["id"]
    contractor_id = ctx["contractor"]["id"]
    failed = inspect_work_order(wo_id, outcome="FAILED", notes="grounding fault")
    assert failed["status"] == "INSPECTION_FAILED", (
        "the loop's failure vertex is a real, observable state"
    )
    validate_ok(
        api_client.patch_trade_work_order(wo_id, {"status": "IN_PROGRESS"}, STAFF)
    )
    validate_ok(
        api_client.patch_trade_work_order(
            wo_id, {"status": "PENDING_INSPECTION"}, STAFF
        )
    )
    passed = inspect_work_order(wo_id, outcome="PASSED")
    assert passed["status"] == "INSPECTED"
    contractor = get_contractor(contractor_id)
    assert contractor["strike_count"] == 1, "suspension requires 3 strikes"
    assert contractor["status"] == "ACTIVE"


def test_work_order_rework_then_paid_moves_money():
    """PRD §3.7: "Payment moves money through the ledger of §2.6: the cycle's
    `spent_cents` rises by `invoice_cents`, the project's
    `reserved_balance_cents` falls by the same amount, the cycle's
    `reserved_cents` falls with it, and the project's reconciled cost
    recomputes."

    After one rework loop the order reaches PAID at invoice 155000 against the
    230000 envelope: project reserved 75000, reconciled 155000; cycle spent
    155000, available 1770000 (2000000 - 75000 - 155000).

    Design: Difficulty/non_linear_state_machine/work_order_inspection_rework_loop
    """
    ctx = setup_project_with_work_order(
        item_est=(100_000, 300_000),
        requires_permit=True,
        wo_target_status="PENDING_INSPECTION",
        quote_cents=180_000,
        budget_cents=2_000_000,
    )
    wo_id = ctx["work_order"]["id"]
    contractor_id = ctx["contractor"]["id"]
    inspect_work_order(wo_id, outcome="FAILED", notes="grounding fault")
    validate_ok(
        api_client.patch_trade_work_order(wo_id, {"status": "IN_PROGRESS"}, STAFF)
    )
    validate_ok(
        api_client.patch_trade_work_order(
            wo_id, {"status": "PENDING_INSPECTION"}, STAFF
        )
    )
    inspect_work_order(wo_id, outcome="PASSED")
    invoiced = invoice_work_order(wo_id, contractor_id, 155_000)
    assert invoiced["status"] == "INVOICED"
    paid = pay_work_order(wo_id)
    assert paid["status"] == "PAID"
    project = get_project(ctx["project"]["id"])
    assert project["reconciled_cost_cents"] == 155_000
    assert project["reserved_balance_cents"] == 75_000, "230000 - 155000"
    cycle = get_cycle(ctx["cycle"]["id"])
    assert cycle["spent_cents"] == 155_000
    assert cycle["reserved_cents"] == 75_000
    assert cycle["available_cents"] == 1_770_000


def _setup_four_order_project():
    """One selected project with four ELECTRICAL items (100000 each) and one
    contractor (max_concurrent_jobs 5); four work orders approved and scheduled
    back-to-back on 2026-10-05, promoting the project to READY."""
    ctx = setup_selected_project(
        budget_cents=5_000_000,
        scope_items=[
            trade_scope_item_payload(
                est_low_cents=100_000, est_high_cents=100_000, description=f"e{i}"
            )
            for i in range(1, 5)
        ],
    )
    contractor = create_contractor(
        legal_name="Quad Electric", max_concurrent_jobs=5
    )
    items = sorted(ctx["scope_items"], key=lambda i: i["description"])
    windows = [
        ("2026-10-05T08:00:00Z", "2026-10-05T10:00:00Z"),
        ("2026-10-05T10:00:00Z", "2026-10-05T12:00:00Z"),
        ("2026-10-05T12:00:00Z", "2026-10-05T14:00:00Z"),
        ("2026-10-05T14:00:00Z", "2026-10-05T16:00:00Z"),
    ]
    work_orders = []
    for item, (visit_start, visit_end) in zip(items, windows):
        wo = create_work_order(
            ctx["project"]["id"], contractor["id"], [item["id"]]
        )
        drive_work_order_to(
            wo["id"], contractor["id"], "APPROVED", quote_cents=100_000
        )
        schedule_work_order(wo["id"], visit_start, visit_end)
        work_orders.append(wo)
    project = get_project(ctx["project"]["id"])
    assert project["status"] == "READY", (
        "all four items covered by SCHEDULED orders"
    )
    set_clock(DEFAULT_VISIT_CLOCK_ISO)
    for wo in work_orders[:3]:
        validate_ok(
            api_client.patch_trade_work_order(
                wo["id"], {"status": "IN_PROGRESS"}, STAFF
            )
        )
        validate_ok(
            api_client.patch_trade_work_order(
                wo["id"], {"status": "PENDING_INSPECTION"}, STAFF
            )
        )
    inspect_work_order(work_orders[0]["id"], outcome="FAILED")
    inspect_work_order(work_orders[1]["id"], outcome="FAILED")
    return ctx, contractor, work_orders


def test_third_inspection_failure_suspends_contractor_and_cancels_orders():
    """PRD §3.7: "A failing outcome moves the order to `INSPECTION_FAILED`,
    stamps `inspected_on`, and adds one to the contractor's `strike_count`;
    when the count reaches 3 the contractor auto-suspends (`ACTIVE` →
    `SUSPENDED`) and the full suspension cascade below fires."
    PRD §3.7: "First, every work order of the contractor in `QUOTE_REQUESTED`,
    `QUOTED`, `APPROVED`, or `SCHEDULED` is cancelled with
    `cancellation_reason` set to the literal `CONTRACTOR_SUSPENDED`."

    The third FAILED inspection auto-suspends the contractor; the still-
    SCHEDULED fourth order is cascade-cancelled while the failed orders
    themselves remain INSPECTION_FAILED.

    Design: Difficulty/transitive_cascade/third_inspection_failure_suspends_contractor_and_cancels_orders
    """
    _, contractor, work_orders = _setup_four_order_project()
    inspect_work_order(work_orders[2]["id"], outcome="FAILED")
    contractor_after = get_contractor(contractor["id"])
    assert contractor_after["strike_count"] == 3
    assert contractor_after["status"] == "SUSPENDED", (
        "the third FAILED inspection auto-suspends"
    )
    wo4 = get_work_order(work_orders[3]["id"])
    assert wo4["status"] == "CANCELLED"
    assert wo4["cancellation_reason"] == "CONTRACTOR_SUSPENDED"
    assert get_work_order(work_orders[0]["id"])["status"] == "INSPECTION_FAILED"
    assert get_work_order(work_orders[2]["id"])["status"] == "INSPECTION_FAILED", (
        "failed orders themselves are not cascade-cancelled"
    )


def test_third_failure_demotes_ready_project_to_planning():
    """PRD §3.7: "Second, each affected project's `readiness_posture` is
    recomputed, and a `READY` project whose posture drops to `BLOCKED` demotes
    to `PLANNING`."

    Once the third failure suspends the contractor and cancels the last live
    order, no INCLUDED licensed item retains coverage: the project's posture
    drops to BLOCKED and the project demotes READY -> PLANNING.

    Design: Difficulty/transitive_cascade/third_inspection_failure_suspends_contractor_and_cancels_orders
    """
    ctx, _, work_orders = _setup_four_order_project()
    inspect_work_order(work_orders[2]["id"], outcome="FAILED")
    project = get_project(ctx["project"]["id"])
    assert project["readiness_posture"] == "BLOCKED"
    assert project["status"] == "PLANNING"


def test_work_order_second_quote_returns_invalid_state():
    """PRD §3.7: "The `TradePartner` whose `X-User-ID` equals the order's
    `contractor_id` quotes by moving `QUOTE_REQUESTED` → `QUOTED` carrying a
    strictly positive `quote_cents`; a foreign contractor is
    `ERR_NOT_RESOURCE_OWNER` and a non-positive quote is `ERR_INVALID_REQUEST`."

    The QUOTED transition is single-shot: re-quoting from QUOTED is a
    from-state violation and the original quote_cents is not overwritten.

    Design: Corner/state_machines/work_order_second_quote_returns_invalid_state
    """
    ctx = setup_project_with_work_order(
        wo_target_status="QUOTED", quote_cents=50_000
    )
    wo_id = ctx["work_order"]["id"]
    contractor_id = ctx["contractor"]["id"]
    resp = api_client.patch_trade_work_order(
        wo_id,
        {"status": "QUOTED", "quote_cents": 99_999},
        make_trade_partner_headers(contractor_id),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    assert get_work_order(wo_id)["quote_cents"] == 50_000, (
        "the rejected re-quote did not overwrite"
    )


def test_approve_without_permit_number_returns_permit_required():
    """PRD §3.7: "Staff approve `QUOTED` → `APPROVED`, and when any covered
    scope item has `requires_permit` true the approval must carry a
    `permit_number`, otherwise `ERR_PERMIT_REQUIRED`."

    Approval fails without permit_number and succeeds once it is supplied.

    Design: Corner/validations/approve_without_permit_number_returns_permit_required
    """
    ctx = setup_project_with_work_order(
        requires_permit=True, wo_target_status="QUOTED", quote_cents=50_000
    )
    wo_id = ctx["work_order"]["id"]
    resp = api_client.patch_trade_work_order(wo_id, {"status": "APPROVED"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_PERMIT_REQUIRED)
    approved = approve_work_order(wo_id, permit_number="P-100")
    assert approved["status"] == "APPROVED"
    assert get_work_order(wo_id)["permit_number"] == "P-100"


def test_work_order_mixed_trades_returns_trade_mismatch():
    """PRD §3.7: "every covered item must have `volunteer_performable` false
    and a `required_trade` equal to the contractor's trade
    (`ERR_TRADE_MISMATCH`); and no covered item may already sit under another
    work order that is not `CANCELLED` (`ERR_SCOPE_ITEM_ALREADY_COVERED`)."

    A single order may cover only one licensed trade: mixing an ELECTRICAL and
    a PLUMBING item under an ELECTRICAL contractor is rejected at creation.

    Design: Corner/validations/work_order_mixed_trades_returns_trade_mismatch
    """
    ctx = setup_selected_project(
        scope_items=[
            trade_scope_item_payload(description="e"),
            trade_scope_item_payload(trade="PLUMBING", description="p"),
        ],
    )
    contractor = create_contractor(legal_name="Mix Electric", trade="ELECTRICAL")
    si_e = next(i for i in ctx["scope_items"] if i["description"] == "e")
    si_p = next(i for i in ctx["scope_items"] if i["description"] == "p")
    resp = api_client.create_trade_work_order(
        create_work_order_payload(
            ctx["project"]["id"], contractor["id"], [si_e["id"], si_p["id"]]
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_TRADE_MISMATCH)
    rows, _ = validate_paginated(
        api_client.list_trade_work_orders(
            STAFF, params={"project_id": ctx["project"]["id"]}
        )
    )
    assert rows == [], "no work-order row persists for the failed create"


def test_work_order_double_coverage_returns_already_covered():
    """PRD §3.7: "every covered item must have `volunteer_performable` false
    and a `required_trade` equal to the contractor's trade
    (`ERR_TRADE_MISMATCH`); and no covered item may already sit under another
    work order that is not `CANCELLED` (`ERR_SCOPE_ITEM_ALREADY_COVERED`)."

    A scope item covered by a QUOTE_REQUESTED (non-terminal) order cannot be
    added to a second contractor's order.

    Design: Corner/validations/work_order_double_coverage_returns_already_covered
    """
    ctx = setup_project_with_work_order()
    contractor2 = create_contractor(legal_name="Second Electric")
    resp = api_client.create_trade_work_order(
        create_work_order_payload(
            ctx["project"]["id"], contractor2["id"], [ctx["trade_item"]["id"]]
        ),
        STAFF,
    )
    validate_error(resp, ApiErrorId.ERR_SCOPE_ITEM_ALREADY_COVERED)


def test_work_orders_list_filters_by_contractor_and_status():
    """PRD §4: "List work orders; filters by project and/or contractor".
    PRD §3.7: "The order is born `QUOTE_REQUESTED` with its `trade` copied from
    the contractor's record, and the project's posture is recomputed."

    The contractor filter returns exactly the one plumbing order; the project
    filter returns both orders, each born QUOTE_REQUESTED with its contractor's
    trade copied on.

    Design: Corner/entities/work_orders_list_filters_by_contractor_and_status
    """
    ctx = setup_selected_project(
        budget_cents=2_000_000,
        scope_items=[
            trade_scope_item_payload(description="e1"),
            trade_scope_item_payload(description="e2"),
            trade_scope_item_payload(trade="PLUMBING", description="p1"),
        ],
    )
    contractor_e = create_contractor(legal_name="E Co", trade="ELECTRICAL")
    contractor_p = create_contractor(legal_name="P Co", trade="PLUMBING")
    items = {i["description"]: i for i in ctx["scope_items"]}
    wo_e = create_work_order(
        ctx["project"]["id"],
        contractor_e["id"],
        [items["e1"]["id"], items["e2"]["id"]],
    )
    wo_p = create_work_order(
        ctx["project"]["id"], contractor_p["id"], [items["p1"]["id"]]
    )
    rows_c, meta_c = validate_paginated(
        api_client.list_trade_work_orders(
            STAFF, params={"contractor_id": contractor_p["id"]}
        )
    )
    assert len(rows_c) == 1 and rows_c[0]["id"] == wo_p["id"]
    rows_p, meta_p = validate_paginated(
        api_client.list_trade_work_orders(
            STAFF, params={"project_id": ctx["project"]["id"]}
        )
    )
    assert meta_p["total_count"] == 2
    for row in rows_p:
        assert row["status"] == "QUOTE_REQUESTED"
    by_id = {row["id"]: row for row in rows_p}
    assert by_id[wo_e["id"]]["trade"] == "ELECTRICAL"
    assert by_id[wo_p["id"]]["trade"] == "PLUMBING"


def test_pay_invoice_above_reserved_balance_returns_envelope_exceeded():
    """PRD §3.7: "Staff then pay `INVOICED` → `PAID`, but only while
    `invoice_cents` is at most the project's `reserved_balance_cents` — an
    invoice larger than the remaining reserve is `ERR_ENVELOPE_EXCEEDED` (HTTP
    402)."

    The fiscal guard sits at PAID, not at INVOICED: the 120000 invoice against
    the 115000 reserve is submittable but cannot be paid.

    Design: Corner/validations/pay_invoice_above_reserved_balance_returns_envelope_exceeded
    """
    ctx = setup_project_with_work_order(
        item_est=(100_000, 100_000),
        wo_target_status="INSPECTED",
        quote_cents=100_000,
    )
    wo_id = ctx["work_order"]["id"]
    contractor_id = ctx["contractor"]["id"]
    invoiced = invoice_work_order(wo_id, contractor_id, 120_000)
    assert invoiced["status"] == "INVOICED"
    resp = api_client.patch_trade_work_order(wo_id, {"status": "PAID"}, STAFF)
    validate_error(resp, ApiErrorId.ERR_ENVELOPE_EXCEEDED)
    assert get_work_order(wo_id)["status"] == "INVOICED", (
        "the failed payment leaves the state untouched"
    )
    assert get_project(ctx["project"]["id"])["reserved_balance_cents"] == 115_000
