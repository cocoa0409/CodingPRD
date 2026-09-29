"""Identity, role and client-scope gates, and the order they fire in."""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CLIENT_SCOPE_VIOLATION,
    ERR_ROLE_NOT_PERMITTED,
    ERR_UNAUTHENTICATED,
)
from test_helpers.assertions import (
    assert_line_states,
    assert_money,
    assert_page_meta,
    assert_pct_equals,
    expected_recovery_credit,
    sole_entry_of_type,
)
from test_helpers.constants import (
    CHANNEL_TYPE_BULK_LIQUIDATOR,
    DISPOSITION_LIQUIDATE,
    DISPOSITION_PENDING,
    DO_APPROVED,
    DO_EXECUTED,
    DO_PROPOSED,
    DS_DISPOSITION_ASSIGNED,
    DS_RECEIVED_UNGRADED,
    ENTRY_RECOVERY_CREDIT,
    GRADE_A,
    GRADE_B,
    GRADE_C,
    GRADE_D,
    GRADE_UNGRADED,
    REASON_BUYER_REMORSE,
    REASON_DEFECTIVE,
    ROLE_CENTER_ADMIN,
    UNKNOWN_ROLE,
    USER_ADMIN,
    USER_GRADER,
    USER_SUPERVISOR_2,
)
from test_helpers.test_users import (
    ADMIN,
    ANALYST,
    CLERK,
    GRADER,
    SUPERVISOR,
    SUPERVISOR_2,
    client_rep_headers,
    headers_blank_user_id,
    headers_for,
)

LOT_WINDOW_START = "2026-08-03T08:00:00Z"
LOT_WINDOW_END = "2026-08-03T12:00:00Z"


def _liquidation_channel(api, channel_code, name):
    """A BULK_LIQUIDATOR taking grades C and D at a 12 percent commission."""
    return fx.make_channel(
        api,
        **fx.auction_channel_kwargs(
            channel_code=channel_code,
            name=name,
            channel_type=CHANNEL_TYPE_BULK_LIQUIDATOR,
            accepted_grades=[GRADE_C, GRADE_D],
            min_lot_value_cents=1000,
        ),
    )


def test_a_blank_identity_and_an_undeclared_role_are_both_unauthenticated(api):
    """PRD §2.1: "A request missing either header, carrying an empty value for
    either, or naming a role outside that set of seven is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/corner_rbac_blank_or_unknown_identity_headers_are_unauthenticated
    """
    client = fx.make_client(
        api, **fx.liquidation_client_kwargs("RB1", name="Rbac One")
    )

    validate_error(
        api.get_client(client["id"], headers_blank_user_id(ROLE_CENTER_ADMIN)),
        ERR_UNAUTHENTICATED,
        401,
    )
    validate_error(
        api.get_client(client["id"], headers_for(USER_ADMIN, UNKNOWN_ROLE)),
        ERR_UNAUTHENTICATED,
        401,
    )

    # A declared role that simply is not on the endpoint's list fails one rung
    # later, at 403 — the two statuses are never interchangeable.
    validate_error(
        api.list_clients(client_rep_headers(client["id"]), {"limit": 100}),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    reachable = validate_success(api.get_client(client["id"], ADMIN), 200)
    assert reachable["id"] == client["id"]


def test_a_receiving_clerk_may_not_grade_the_line_it_scanned(api):
    """PRD §2.6: "Priority 2 checks that the presented role appears on the target
    endpoint's authorized-role list, failing with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/corner_rbac_receiving_clerk_cannot_grade_a_line
    """
    world = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("RB2", name="Rbac Two"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-RB2",
    )
    line = world["line"]

    validate_error(
        api.grade_line(line["id"], f.grade_payload(GRADE_B), CLERK),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    untouched = fx.read_return_line(api, line["id"])
    assert_line_states(
        untouched,
        condition_grade=GRADE_UNGRADED,
        disposition=DISPOSITION_PENDING,
        disposition_state=DS_RECEIVED_UNGRADED,
    )
    assert untouched["graded_by_user_id"] is None

    graded = validate_success(
        api.grade_line(line["id"], f.grade_payload(GRADE_B), GRADER), 200
    )
    assert graded["condition_grade"] == GRADE_B
    assert graded["graded_by_user_id"] == USER_GRADER

    # The clerk keeps every read the endpoint table grants it.
    _, meta = validate_paginated(
        api.list_line_fraud_checks(line["id"], CLERK, {"limit": 100})
    )
    assert meta["total_count"] >= 1


def test_a_grading_inspector_may_not_route_the_line_it_graded(api):
    """PRD §2.5: "A recognised operator whose role is not listed in the Authorized
    Role(s) column for the endpoint receives `403 Forbidden` with
    `ERR_ROLE_NOT_PERMITTED`, and a `ClientRep` who reaches past their own client's
    data receives `403 Forbidden` with `ERR_CLIENT_SCOPE_VIOLATION`."

    Design: Corner/rbac/corner_rbac_grading_inspector_cannot_create_a_disposition_order
    """
    channel = _liquidation_channel(api, "BL-RB3", "Bulk Liquidators")
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("RB3", name="Rbac Three"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-RB3",
    )
    line = world["line"]
    assert_line_states(line, disposition=DISPOSITION_LIQUIDATE)
    body = f.disposition_order_payload(
        line["id"],
        line["version"],
        channel_id=channel["id"],
        channel_window_start_at=LOT_WINDOW_START,
        channel_window_end_at=LOT_WINDOW_END,
    )

    validate_error(
        api.create_disposition_order(body, GRADER), ERR_ROLE_NOT_PERMITTED, 403
    )

    assert fx.orders_for_line(api, line["id"]) == []
    unchanged = fx.read_return_line(api, line["id"])
    assert unchanged["version"] == line["version"], (
        "the refused write did not consume the concurrency token"
    )
    assert_line_states(unchanged, disposition_state=DS_DISPOSITION_ASSIGNED)

    order = validate_success(api.create_disposition_order(body, SUPERVISOR), 201)
    assert order["status"] == DO_PROPOSED
    assert order["disposition"] == DISPOSITION_LIQUIDATE
    assert_money(order["unit_price_cents"], 7200, "frozen unit_price_cents")
    # Realized economics stay at zero until the order executes.
    assert_money(order["gross_lot_value_cents"], 0, "gross_lot_value_cents")
    assert_pct_equals(order["effective_fee_pct"], 0.00, "effective_fee_pct")
    assert_money(order["net_recovery_cents"], 0, "net_recovery_cents")


def test_a_refund_analyst_may_not_execute_a_disposition_order(api):
    """PRD §2.6: "Priority 2 checks that the presented role appears on the target
    endpoint's authorized-role list, failing with `ERR_ROLE_NOT_PERMITTED`."

    Design: Corner/rbac/corner_rbac_refund_analyst_cannot_execute_a_disposition_order
    """
    channel = _liquidation_channel(api, "BL-RB4", "Bulk Liquidators")
    world = fx.graded_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("RB4", name="Rbac Four"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        condition_grade=GRADE_C,
        tracking_reference="TRK-RB4",
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

    validate_error(
        api.execute_disposition_order(order["id"], ANALYST, f.execute_payload()),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    stalled = fx.read_order(api, order["id"])
    assert stalled["status"] == DO_APPROVED
    assert stalled["executed_by_user_id"] is None
    assert stalled["executed_at"] is None
    _, meta = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN, {"return_line_id": line["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 0, "no money moved on the refused call"

    executed = fx.execute_order(api, order["id"], headers=SUPERVISOR_2)
    assert executed["status"] == DO_EXECUTED
    assert executed["executed_by_user_id"] == USER_SUPERVISOR_2
    entries, _ = validate_paginated(
        api.list_shrink_ledger_entries(
            ADMIN, {"return_line_id": line["id"], "limit": 100}
        )
    )
    credit = sole_entry_of_type(entries, ENTRY_RECOVERY_CREDIT)
    assert_money(
        credit["amount_cents"], expected_recovery_credit(5904), "RECOVERY_CREDIT"
    )


def test_the_admin_break_glass_stops_at_the_refund_verbs(api):
    """PRD §2.5: "A recognised operator whose role is not listed in the Authorized
    Role(s) column for the endpoint receives `403 Forbidden` with
    `ERR_ROLE_NOT_PERMITTED`, and a `ClientRep` who reaches past their own client's
    data receives `403 Forbidden` with `ERR_CLIENT_SCOPE_VIOLATION`."

    Design: Corner/rbac/corner_rbac_center_admin_break_glass_stops_at_the_money_axis
    """
    client = fx.make_client(
        api, **fx.liquidation_client_kwargs("RB5", name="Rbac Five")
    )
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
        order_reference="ORD-RB5",
        customer_reference="CUST-RB5",
    )
    # The admin stands in for the clerk and the inspector on the same line.
    receipt = fx.make_receipt(
        api, issued["rma"]["id"], 1400, tracking_reference="TRK-RB5", headers=ADMIN
    )
    scanned = fx.scan_line(
        api, receipt["id"], issued["lines"][0]["id"], quantity=1, headers=ADMIN
    )
    graded = fx.grade_line(api, scanned["id"], GRADE_C, headers=ADMIN)
    assert graded["graded_by_user_id"] == USER_ADMIN
    assert graded["condition_grade"] == GRADE_C

    validate_error(
        api.release_refund(scanned["id"], ADMIN), ERR_ROLE_NOT_PERMITTED, 403
    )
    validate_error(
        api.deny_refund(scanned["id"], f.deny_refund_payload(), ADMIN),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    release = fx.refund_release_for_line(api, scanned["id"])
    assert release["released_at"] is None
    assert release["released_by_user_id"] is None
    assert fx.read_return_line(api, scanned["id"])["version"] == graded["version"], (
        "neither refused refund verb bumped the line"
    )


def test_a_client_rep_naming_another_clients_id_is_refused_not_lied_to(api):
    """PRD §2.1: "Filtered list reads are silently narrowed to the caller's own
    client rather than erroring — a `ClientRep` listing return lines simply sees
    only its own — but an explicit path identifier belonging to another client is
    rejected with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_client_rep_cannot_read_another_clients_resources
    """
    client_a = fx.make_client(
        api, **fx.liquidation_client_kwargs("R6A", name="Rbac Six A")
    )
    world_b = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("R6B", name="Rbac Six B"),
        items=[fx.widget_item_kwargs()],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-R6B",
    )
    client_b = world_b["client"]
    line_b = world_b["line"]
    rep_a = client_rep_headers(client_a["id"])
    rep_b = client_rep_headers(client_b["id"])

    validate_error(
        api.get_return_line(line_b["id"], rep_a), ERR_CLIENT_SCOPE_VIOLATION, 403
    )
    validate_error(
        api.get_client(client_b["id"], rep_a), ERR_CLIENT_SCOPE_VIOLATION, 403
    )
    validate_error(
        api.get_disposition_audit(client_b["id"], rep_a),
        ERR_CLIENT_SCOPE_VIOLATION,
        403,
    )

    own = validate_success(api.get_client(client_a["id"], rep_a), 200)
    assert own["id"] == client_a["id"], "the role itself is not blanket-denied"
    theirs = validate_success(api.get_return_line(line_b["id"], rep_b), 200)
    assert theirs["id"] == line_b["id"], "only the caller was ever wrong"
    assert validate_success(api.get_return_line(line_b["id"], ADMIN), 200)["id"] == (
        line_b["id"]
    )


def test_a_client_reps_unfiltered_listings_are_narrowed_not_refused(api):
    """PRD §2.1: "Filtered list reads are silently narrowed to the caller's own
    client rather than erroring — a `ClientRep` listing return lines simply sees
    only its own — but an explicit path identifier belonging to another client is
    rejected with `ERR_CLIENT_SCOPE_VIOLATION` (HTTP 403)."

    Design: Corner/rbac/corner_rbac_client_rep_collection_reads_are_silently_narrowed
    """
    world_a = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("R7A", name="Rbac Seven A"),
        items=[fx.widget_item_kwargs(sku="WIDGET-A", description="Widget for A")],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-R7A",
    )
    world_b = fx.received_scenario(
        api,
        client_kwargs=fx.liquidation_client_kwargs("R7B", name="Rbac Seven B"),
        items=[fx.widget_item_kwargs(sku="WIDGET-B", description="Widget for B")],
        lines=[{"authorized_quantity": 1, "reason_code": REASON_DEFECTIVE}],
        tracking_reference="TRK-R7B",
    )
    rep_a = client_rep_headers(world_a["client"]["id"])

    rows, meta = validate_paginated(
        api.list_return_lines(rep_a, {"limit": 10, "offset": 0})
    )
    assert_page_meta(meta, limit=10, offset=0, total_count=1, has_more=False)
    assert [row["id"] for row in rows] == [world_a["line"]["id"]]
    assert world_b["line"]["id"] not in [row["id"] for row in rows]

    _, admin_meta = validate_paginated(api.list_return_lines(ADMIN, {"limit": 10}))
    assert admin_meta["total_count"] == 2, "both rows really exist"

    rma_rows, rma_meta = validate_paginated(api.list_rmas(rep_a, {"limit": 10}))
    assert rma_meta["total_count"] == 1, "narrowing is not specific to one collection"
    assert [row["id"] for row in rma_rows] == [world_a["rma"]["id"]]

    # A filter naming the other client's receipt is narrowed rather than
    # refused, so the intersection with the caller's own client is empty.
    other_rows, other_meta = validate_paginated(
        api.list_return_lines(rep_a, {"receipt_id": world_b["receipt"]["id"]})
    )
    assert other_rows == [], "the filtered read was narrowed to the caller's client"
    assert other_meta["total_count"] == 0


def test_the_role_gate_fires_before_the_scope_gate_would_have_passed(api):
    """PRD §2.6: "Priority 3 applies to every endpoint whose authorized roles
    include `ClientRep` and enforces the client-scoping rule of §2.1, failing with
    `ERR_CLIENT_SCOPE_VIOLATION`."

    Design: Corner/rbac/corner_rbac_client_rep_cannot_grade_even_its_own_line
    """
    client = fx.make_client(
        api, **fx.liquidation_client_kwargs("RB8", name="Rbac Eight")
    )
    item = fx.make_catalog_item(api, client["id"], **fx.widget_item_kwargs())
    rep = client_rep_headers(client["id"])

    # The rep raises, populates and issues the authorization itself.
    rma = validate_success(
        api.create_rma(
            f.rma_payload(
                client["id"],
                order_reference="ORD-RB8",
                customer_reference="CUST-RB8",
            ),
            rep,
        ),
        201,
    )
    rma_line = validate_success(
        api.create_rma_line(
            rma["id"],
            f.rma_line_payload(
                item["id"], authorized_quantity=1, reason_code=REASON_BUYER_REMORSE
            ),
            rep,
        ),
        201,
    )
    validate_success(api.issue_rma(rma["id"], rep), 200)

    receipt = fx.make_receipt(api, rma["id"], 1400, tracking_reference="TRK-RB8")
    scanned = fx.scan_line(
        api, receipt["id"], rma_line["id"], quantity=1,
        reason_code=REASON_BUYER_REMORSE,
    )

    # Grading is refused for the role, never for the ownership that would pass.
    validate_error(
        api.grade_line(scanned["id"], f.grade_payload(GRADE_A), rep),
        ERR_ROLE_NOT_PERMITTED,
        403,
    )

    visible = validate_success(api.get_return_line(scanned["id"], rep), 200)
    assert visible["condition_grade"] == GRADE_UNGRADED, (
        "the rep can see the line it may not grade"
    )
    assert visible["graded_by_user_id"] is None
    assert_line_states(visible, disposition_state=DS_RECEIVED_UNGRADED)
