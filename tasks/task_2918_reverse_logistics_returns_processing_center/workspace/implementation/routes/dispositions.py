"""Disposition orders, channel pricing feedback, the shrink ledger and the clock."""

from decimal import Decimal
from flask import Blueprint

import aggregates
import calc
import constants as K
import db
import middleware as mw
import query
import refs
import response
import serialize
import services
import shapes
from errors import ApiError

bp = Blueprint("dispositions", __name__)


def _line_context(line):
    item = refs.item_of_return_line(line)
    client = refs.client_of_return_line(line)
    if item is None or client is None:
        raise ApiError("ERR_RETURN_LINE_NOT_FOUND")
    return item, client


@bp.post("/disposition-orders")
def create_order():
    _user_id, _role = mw.require("DispositionSupervisor", "CenterAdmin")
    body = response.body_json()
    return_line_id = shapes.req_id(body, "return_line_id")
    expected_return_line_version = shapes.req_int(body, "expected_return_line_version")
    channel_id = shapes.opt_id(body, "channel_id")
    echo_disposition = shapes.opt_enum(body, "disposition", K.ORDER_DISPOSITIONS)
    echo_quantity = shapes.opt_int(body, "quantity", None, 1, 999)
    window_start = shapes.opt_instant(body, "channel_window_start_at")
    window_end = shapes.opt_instant(body, "channel_window_end_at")
    shapes.window(window_start, window_end, "channel_window_start_at", "channel_window_end_at")

    channel = services.must_channel(channel_id) if channel_id is not None else None
    line = services.must_return_line(return_line_id)
    item, client = _line_context(line)
    services.require_active(client)

    if line["disposition_state"] != "DISPOSITION_ASSIGNED":
        raise ApiError("ERR_LINE_INVALID_DISPOSITION_STATE")
    if line["disposition"] not in K.ORDER_DISPOSITIONS:
        raise ApiError("ERR_LINE_INVALID_DISPOSITION_STATE")

    is_restock = line["disposition"] == "RESTOCK"
    if channel is not None and not is_restock and channel["status"] != "ACTIVE":
        raise ApiError("ERR_CHANNEL_PAUSED")
    if expected_return_line_version != line["version"]:
        raise ApiError("ERR_STALE_RETURN_LINE_VERSION")
    if not is_restock and (window_start is None or window_end is None):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "Fields 'channel_window_start_at' and 'channel_window_end_at' are required.",
        )

    requested = echo_disposition if echo_disposition is not None else line["disposition"]
    if item["recall_status"] == "MANDATORY" and requested != "DESTROY":
        raise ApiError("ERR_RECALL_DISPOSITION_LOCKED")
    if requested == "DONATE" and (
        item["regulated_flag"]
        or item["hazard_class"] != "NONE"
        or not client["donation_allowed"]
    ):
        raise ApiError("ERR_REGULATED_DONATION_FORBIDDEN")

    if channel is not None and not is_restock:
        if item["hazard_class"] != "NONE" and not channel["hazard_certified"]:
            raise ApiError("ERR_CHANNEL_NOT_HAZARD_CERTIFIED")
        if item["recall_status"] == "MANDATORY" and not channel["recall_certified"]:
            raise ApiError("ERR_CHANNEL_NOT_HAZARD_CERTIFIED")
        if line["condition_grade"] not in channel["accepted_grades"] or not services.channel_serves(
            channel, line["disposition"]
        ):
            raise ApiError("ERR_CHANNEL_GRADE_NOT_ACCEPTED")

    if echo_disposition is not None and echo_disposition != line["disposition"]:
        raise ApiError("ERR_DISPOSITION_DRIFT")
    if echo_quantity is not None and echo_quantity != line["quantity"]:
        raise ApiError("ERR_DISPOSITION_DRIFT")
    reserved = 0
    for existing in refs.orders_of_line(line["id"]):
        if existing["status"] in ("PROPOSED", "APPROVED"):
            reserved += existing["quantity"]
    if line["quantity"] != line["quantity"] - reserved:
        raise ApiError("ERR_DISPOSITION_DRIFT")

    selected_by_policy = False
    if is_restock:
        channel = None
    elif channel is None:
        channel = services.select_channel(
            line, item, line["disposition"], window_start, window_end
        )
        if channel is None:
            raise ApiError("ERR_NO_ELIGIBLE_CHANNEL")
        selected_by_policy = True
    else:
        if not services.window_admits(channel, window_start, window_end):
            raise ApiError("ERR_CHANNEL_WINDOW_CAPACITY_EXCEEDED")
        unit_price = calc.unit_price_cents(
            line["disposition"], line["recovery_value_cents"], line["quantity"], channel, item
        )
        if calc.projected_net_recovery(channel, unit_price, line["quantity"]) < channel[
            "min_lot_value_cents"
        ]:
            raise ApiError("ERR_CHANNEL_MIN_LOT_NOT_MET")

    unit_price = calc.unit_price_cents(
        line["disposition"], line["recovery_value_cents"], line["quantity"], channel, item
    )
    row = {
        "id": db.new_id(),
        "return_line_id": line["id"],
        "channel_id": channel["id"] if channel is not None else None,
        "disposition": line["disposition"],
        "quantity": line["quantity"],
        "unit_price_cents": unit_price,
        "channel_window_start_at": db.fmt_instant(window_start),
        "channel_window_end_at": db.fmt_instant(window_end),
        "gross_lot_value_cents": 0,
        "effective_fee_pct": Decimal("0.00"),
        "channel_fee_cents": 0,
        "net_recovery_cents": 0,
        "refurb_cost_cents": 0,
        "status": "PROPOSED",
        "approved_by_user_id": None,
        "executed_by_user_id": None,
        "executed_at": None,
        "selected_by_policy": selected_by_policy,
    }
    db.stamp_new(row)
    db.insert("disposition_orders", row)
    db.touch(line)
    return response.created(serialize.disposition_order(row))


@bp.get("/disposition-orders/<disposition_order_id>")
def get_order(disposition_order_id):
    user_id, role = mw.require(
        "CenterAdmin", "DispositionSupervisor", "RefundAnalyst", "ClientRep"
    )
    order = db.get("disposition_orders", disposition_order_id)
    if order is not None:
        mw.scope(role, user_id, refs.client_id_of_order(order))
    order = services.must_order(disposition_order_id)
    return response.ok(serialize.disposition_order(order))


@bp.get("/disposition-orders")
def list_orders():
    user_id, role = mw.require(
        "CenterAdmin", "DispositionSupervisor", "RefundAnalyst", "ClientRep"
    )
    channel_id = query.arg("channel_id")
    if channel_id is not None:
        services.must_channel(channel_id)
    return_line_id = query.arg("return_line_id")
    if return_line_id is not None:
        services.must_return_line(return_line_id)
    rows = db.sorted_rows(db.all_rows("disposition_orders"))
    if role == mw.CLIENT_REP:
        rows = [r for r in rows if refs.client_id_of_order(r) == user_id]
    rows = query.eq(rows, "return_line_id", return_line_id)
    rows = query.eq(rows, "channel_id", channel_id)
    rows = query.eq(rows, "status", query.arg("status"))
    rows = query.eq(rows, "disposition", query.arg("disposition"))
    rows = query.eq(rows, "selected_by_policy", query.arg_bool("selected_by_policy"))
    return response.paginate(rows, serialize.disposition_order)


@bp.post("/disposition-orders/<disposition_order_id>/approve")
def approve_order(disposition_order_id):
    user_id, _role = mw.require("DispositionSupervisor", "CenterAdmin")
    response.body_json()
    order = services.must_order(disposition_order_id)
    line = refs.return_line_of_order(order)
    if order["status"] != "PROPOSED":
        raise ApiError("ERR_DISPOSITION_ORDER_INVALID_STATE")
    channel = db.get("channels", order["channel_id"]) if order["channel_id"] else None
    if channel is not None and channel["status"] != "ACTIVE":
        raise ApiError("ERR_CHANNEL_PAUSED")
    if line is None or line["disposition"] != order["disposition"]:
        raise ApiError("ERR_DISPOSITION_DRIFT")
    order["status"] = "APPROVED"
    order["approved_by_user_id"] = user_id
    db.touch(order)
    return response.ok(serialize.disposition_order(order))


@bp.post("/disposition-orders/<disposition_order_id>/execute")
def execute_order(disposition_order_id):
    user_id, _role = mw.require("DispositionSupervisor", "CenterAdmin")
    body = response.body_json()
    realized_unit_price_cents = shapes.opt_int(body, "realized_unit_price_cents", None, 0)
    order = services.must_order(disposition_order_id)
    line = refs.return_line_of_order(order)
    if order["status"] != "APPROVED":
        raise ApiError("ERR_DISPOSITION_ORDER_INVALID_STATE")
    channel = db.get("channels", order["channel_id"]) if order["channel_id"] else None
    if channel is not None and channel["status"] != "ACTIVE":
        raise ApiError("ERR_CHANNEL_PAUSED")
    if line is None:
        raise ApiError("ERR_RETURN_LINE_NOT_FOUND")
    item, client = _line_context(line)
    if (
        order["disposition"] == "DESTROY"
        and client["destroy_requires_dual_signoff"]
        and order["approved_by_user_id"] is not None
        and user_id == order["approved_by_user_id"]
    ):
        raise ApiError("ERR_DUAL_SIGNOFF_REQUIRED")
    if line["disposition"] != order["disposition"]:
        raise ApiError("ERR_DISPOSITION_DRIFT")

    unit_price = (
        realized_unit_price_cents
        if realized_unit_price_cents is not None
        else order["unit_price_cents"]
    )
    refurb_cost = 0
    for work_order in refs.work_orders_of_line(line["id"]):
        if work_order["status"] == "REPACKAGED":
            refurb_cost = work_order["total_cost_cents"]
    gross, fee_pct, fee, net = calc.lot_economics(
        channel, unit_price, order["quantity"], refurb_cost
    )
    order["gross_lot_value_cents"] = gross
    order["effective_fee_pct"] = fee_pct
    order["channel_fee_cents"] = fee
    order["refurb_cost_cents"] = refurb_cost
    order["net_recovery_cents"] = net
    order["status"] = "EXECUTED"
    order["executed_by_user_id"] = user_id
    order["executed_at"] = db.now_str()
    db.touch(order)

    services.execute_cascade(order, line, item, client)
    if line["financial_state"] == "HOLD_PENDING_DISPOSITION":
        line["financial_state"] = "RELEASE_PENDING"
        services.stamp_release_eligible(line, client, db.parse_instant(order["executed_at"]))
    return response.ok(serialize.disposition_order(order))


@bp.post("/disposition-orders/<disposition_order_id>/cancel")
def cancel_order(disposition_order_id):
    mw.require("DispositionSupervisor", "CenterAdmin")
    body = response.body_json()
    shapes.req_str(body, "cancel_reason")
    order = services.must_order(disposition_order_id)
    if order["status"] not in ("PROPOSED", "APPROVED"):
        raise ApiError("ERR_DISPOSITION_ORDER_INVALID_STATE")
    order["status"] = "CANCELLED"
    db.touch(order)
    return response.ok(serialize.disposition_order(order))


# ------------------------------------------------------------ pricing feedback

def _feedback_of_channel(channel_id):
    rows = [
        row
        for row in db.all_rows("pricing_feedback")
        if row["channel_id"] == channel_id
    ]
    rows.sort(key=lambda row: row["sequence_no"])
    return rows


def _reindex_channel(channel):
    window = _feedback_of_channel(channel["id"])[-K.PRICE_INDEX_WINDOW:]
    ratios = [
        calc.feedback_ratio(row["realized_price_cents"], row["expected_price_cents"])
        for row in window
    ]
    index = calc.price_index_from_ratios(ratios)
    if index is None:
        return
    channel["price_index_pct"] = index
    db.touch(channel)


@bp.post("/pricing-feedback")
def create_feedback():
    mw.require("DispositionSupervisor", "CenterAdmin")
    body = response.body_json()
    disposition_order_id = shapes.req_id(body, "disposition_order_id")
    channel_id = shapes.req_id(body, "channel_id")
    realized_price_cents = shapes.req_int(body, "realized_price_cents", 0)

    channel = services.must_channel(channel_id)
    order = services.must_order(disposition_order_id)
    if order["channel_id"] != channel["id"]:
        raise ApiError("ERR_LINE_RMA_MISMATCH")

    expected = order["unit_price_cents"]
    existing = _feedback_of_channel(channel["id"])
    row = {
        "id": db.new_id(),
        "disposition_order_id": order["id"],
        "channel_id": channel["id"],
        "expected_price_cents": expected,
        "realized_price_cents": realized_price_cents,
        "variance_pct": calc.variance_pct(realized_price_cents, expected),
        "sequence_no": (existing[-1]["sequence_no"] + 1) if existing else 1,
    }
    db.stamp_new(row, versioned=False)
    db.insert("pricing_feedback", row)
    _reindex_channel(channel)
    return response.created(serialize.pricing_feedback(row))


@bp.get("/pricing-feedback/<pricing_feedback_id>")
def get_feedback(pricing_feedback_id):
    mw.require("CenterAdmin", "DispositionSupervisor", "ClientRep")
    row = services.must_feedback(pricing_feedback_id)
    return response.ok(serialize.pricing_feedback(row))


@bp.get("/pricing-feedback")
def list_feedback():
    mw.require("CenterAdmin", "DispositionSupervisor", "ClientRep")
    channel_id = query.arg("channel_id")
    if channel_id is not None:
        services.must_channel(channel_id)
    disposition_order_id = query.arg("disposition_order_id")
    if disposition_order_id is not None:
        services.must_order(disposition_order_id)
    rows = db.sorted_rows(db.all_rows("pricing_feedback"))
    rows = query.eq(rows, "disposition_order_id", disposition_order_id)
    rows = query.eq(rows, "channel_id", channel_id)
    return response.paginate(rows, serialize.pricing_feedback)


# --------------------------------------------------------------- shrink ledger

@bp.get("/shrink-ledger-entries/<shrink_ledger_entry_id>")
def get_ledger_entry(shrink_ledger_entry_id):
    user_id, role = mw.require(
        "CenterAdmin", "DispositionSupervisor", "RefundAnalyst", "ClientRep"
    )
    row = db.get("shrink_ledger_entries", shrink_ledger_entry_id)
    if row is not None:
        mw.scope(role, user_id, row["client_id"])
    row = services.must_ledger_entry(shrink_ledger_entry_id)
    return response.ok(serialize.shrink_ledger_entry(row))


@bp.get("/shrink-ledger-entries")
def list_ledger_entries():
    user_id, role = mw.require(
        "CenterAdmin", "DispositionSupervisor", "RefundAnalyst", "ClientRep"
    )
    client_id = query.arg("client_id")
    if client_id is not None:
        services.must_client(client_id)
    return_line_id = query.arg("return_line_id")
    if return_line_id is not None:
        services.must_return_line(return_line_id)
    rows = db.all_rows("shrink_ledger_entries")
    rows.sort(key=lambda row: (row["sequence_no"], row["created_at"], row["_seq"]))
    if role == mw.CLIENT_REP:
        rows = [row for row in rows if row["client_id"] == user_id]
    rows = query.eq(rows, "client_id", client_id)
    rows = query.eq(rows, "return_line_id", return_line_id)
    rows = query.eq(rows, "entry_type", query.arg("entry_type"))
    return response.paginate(rows, serialize.shrink_ledger_entry)


# ------------------------------------------------------------------- the clock

@bp.post("/_clock/set_current_utc")
def set_clock():
    mw.require("CenterAdmin")
    body = response.body_json()
    current_utc = shapes.req_instant(body, "current_utc")
    db.set_now(current_utc)
    services.expiry_sweep(current_utc)
    return response.ok({})
