"""Refurbishment work orders."""

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

bp = Blueprint("refurb", __name__)


def _line_of(work_order):
    line = refs.return_line_of_work_order(work_order)
    if line is None:
        raise ApiError("ERR_RETURN_LINE_NOT_FOUND")
    return line


def _no_mandatory_recall(line):
    item = refs.item_of_return_line(line)
    if item is not None and item["recall_status"] == "MANDATORY":
        raise ApiError("ERR_RECALLED_ITEM_NOT_REFURBISHABLE")
    return item


@bp.post("/refurb-work-orders")
def create_work_order():
    user_id, _role = mw.require("RefurbTechnician", "CenterAdmin")
    body = response.body_json()
    return_line_id = shapes.req_id(body, "return_line_id")
    line = services.must_return_line(return_line_id)
    item = refs.item_of_return_line(line)
    if item is None:
        raise ApiError("ERR_CATALOG_ITEM_NOT_FOUND")
    if line["disposition_state"] != "DISPOSITION_ASSIGNED" or line["disposition"] != "REFURBISH":
        raise ApiError("ERR_LINE_INVALID_DISPOSITION_STATE")
    if item["recall_status"] == "MANDATORY":
        raise ApiError("ERR_RECALLED_ITEM_NOT_REFURBISHABLE")
    if not item["refurb_eligible"]:
        raise ApiError("ERR_LINE_NOT_REFURBISHABLE")
    row = {
        "id": db.new_id(),
        "return_line_id": line["id"],
        "bay_id": None,
        "assigned_technician_user_id": user_id,
        "status": "OPEN",
        "rework_cycles": 0,
        "labor_minutes_total": 0,
        "parts_cost_cents": 0,
        "packaging_cost_cents": 0,
        "total_cost_cents": 0,
        "resulting_grade": None,
        "test_window_start_at": None,
        "test_window_end_at": None,
        "qa_user_id": None,
    }
    db.stamp_new(row)
    db.insert("work_orders", row)
    line["disposition_state"] = "IN_REFURB"
    db.touch(line)
    return response.created(serialize.work_order(row))


@bp.get("/refurb-work-orders/<work_order_id>")
def get_work_order(work_order_id):
    user_id, role = mw.require(
        "CenterAdmin", "RefurbTechnician", "GradingInspector", "DispositionSupervisor", "ClientRep"
    )
    work_order = db.get("work_orders", work_order_id)
    if work_order is not None:
        mw.scope(role, user_id, refs.client_id_of_work_order(work_order))
    work_order = services.must_work_order(work_order_id)
    return response.ok(serialize.work_order(work_order))


@bp.get("/refurb-work-orders")
def list_work_orders():
    user_id, role = mw.require(
        "CenterAdmin", "RefurbTechnician", "GradingInspector", "DispositionSupervisor", "ClientRep"
    )
    bay_id = query.arg("bay_id")
    if bay_id is not None:
        services.must_bay(bay_id)
    return_line_id = query.arg("return_line_id")
    if return_line_id is not None:
        services.must_return_line(return_line_id)
    rows = db.sorted_rows(db.all_rows("work_orders"))
    if role == mw.CLIENT_REP:
        rows = [r for r in rows if refs.client_id_of_work_order(r) == user_id]
    rows = query.eq(rows, "return_line_id", return_line_id)
    rows = query.eq(rows, "bay_id", bay_id)
    rows = query.eq(rows, "status", query.arg("status"))
    return response.paginate(rows, serialize.work_order)


@bp.post("/refurb-work-orders/<work_order_id>/start-test")
def start_test(work_order_id):
    mw.require("RefurbTechnician")
    body = response.body_json()
    bay_id = shapes.req_id(body, "bay_id")
    start_at = shapes.req_instant(body, "test_window_start_at")
    end_at = shapes.req_instant(body, "test_window_end_at")
    shapes.window(start_at, end_at, "test_window_start_at", "test_window_end_at")
    bay = services.must_bay(bay_id)
    work_order = services.must_work_order(work_order_id)
    line = _line_of(work_order)
    if work_order["status"] not in ("OPEN", "TEST_FAILED"):
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    _no_mandatory_recall(line)
    re_entry = work_order["status"] == "TEST_FAILED"
    if re_entry and work_order["rework_cycles"] >= K.MAX_REWORK_CYCLES:
        raise ApiError("ERR_REWORK_LIMIT_EXCEEDED")
    if bay["status"] != "ACTIVE" or bay["bay_type"] != "GENERAL":
        raise ApiError("ERR_BAY_TYPE_MISMATCH")
    services.check_test_window(bay, work_order, start_at, end_at)
    if re_entry:
        work_order["rework_cycles"] += 1
    work_order["bay_id"] = bay["id"]
    work_order["test_window_start_at"] = db.fmt_instant(start_at)
    work_order["test_window_end_at"] = db.fmt_instant(end_at)
    work_order["status"] = "IN_TEST"
    db.touch(work_order)
    return response.ok(serialize.work_order(work_order))


@bp.post("/refurb-work-orders/<work_order_id>/record-test-result")
def record_test_result(work_order_id):
    user_id, _role = mw.require("RefurbTechnician", "GradingInspector")
    body = response.body_json()
    result = shapes.req_enum(body, "result", K.TEST_RESULTS)
    labor_minutes = shapes.req_int(body, "labor_minutes", 0)
    parts_cost_cents = shapes.opt_int(body, "parts_cost_cents", 0, 0)
    work_order = services.must_work_order(work_order_id)
    line = _line_of(work_order)
    if work_order["status"] != "IN_TEST":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    _no_mandatory_recall(line)
    if user_id == work_order["assigned_technician_user_id"]:
        raise ApiError("ERR_QA_SELF_INSPECTION")
    work_order["labor_minutes_total"] += labor_minutes
    work_order["parts_cost_cents"] += parts_cost_cents
    work_order["qa_user_id"] = user_id
    work_order["status"] = "PASSED_QA" if result == "PASS" else "TEST_FAILED"
    db.touch(work_order)
    return response.ok(serialize.work_order(work_order))


@bp.post("/refurb-work-orders/<work_order_id>/repackage")
def repackage(work_order_id):
    user_id, _role = mw.require("RefurbTechnician", "CenterAdmin")
    body = response.body_json()
    packaging_cost_cents = shapes.req_int(body, "packaging_cost_cents", 0)
    resulting_grade = shapes.req_enum(body, "resulting_grade", ("A", "B"))
    work_order = services.must_work_order(work_order_id)
    line = _line_of(work_order)
    if work_order["status"] != "PASSED_QA":
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    item = _no_mandatory_recall(line)
    if work_order["qa_user_id"] is not None and user_id == work_order["qa_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    client = refs.client_of_return_line(line)

    work_order["packaging_cost_cents"] = packaging_cost_cents
    work_order["resulting_grade"] = resulting_grade
    work_order["total_cost_cents"] = calc.refurb_total_cost(
        work_order["labor_minutes_total"], work_order["parts_cost_cents"], packaging_cost_cents
    )
    work_order["status"] = "REPACKAGED"
    db.touch(work_order)
    if work_order["total_cost_cents"] != 0:
        aggregates.append_entry(
            client["id"],
            line["id"],
            "REFURB_COST",
            -work_order["total_cost_cents"],
            "refurbishment repackaged",
        )

    line["condition_grade"] = resulting_grade
    line["recovery_value_cents"] = calc.provisional_recovery(
        item["declared_value_cents"], resulting_grade, line["reason_code"], line["quantity"]
    )
    services.recompute_refund(line, item, client)
    line["_refurb_forfeited"] = True
    services.run_matrix(line, item, client)
    line["disposition_state"] = "DISPOSITION_ASSIGNED"
    db.touch(line)
    return response.ok(serialize.work_order(work_order))


@bp.post("/refurb-work-orders/<work_order_id>/abandon")
def abandon(work_order_id):
    mw.require("RefurbTechnician", "CenterAdmin")
    body = response.body_json()
    shapes.req_str(body, "abandon_reason")
    work_order = services.must_work_order(work_order_id)
    line = _line_of(work_order)
    if work_order["status"] not in ("OPEN", "IN_TEST", "TEST_FAILED", "PASSED_QA"):
        raise ApiError("ERR_WORK_ORDER_INVALID_STATE")
    item = refs.item_of_return_line(line)
    client = refs.client_of_return_line(line)
    services.abandon_work_order(work_order, line)
    line["_refurb_forfeited"] = True
    services.run_matrix(line, item, client)
    line["disposition_state"] = "DISPOSITION_ASSIGNED"
    db.touch(line)
    return response.ok(serialize.work_order(work_order))
