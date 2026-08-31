"""Rebuild orders and part lines."""

from flask import Blueprint

import bench_ops
import calc
import store
import validate as v
import views
from auth import (ALL_ROLES, ORDER_ACTIONS, PART_LINE_ACTIONS, authenticate,
                  require_action_role, require_roles)
from errors import fail
from response import created, listing, ok

bp = Blueprint("orders", __name__)

SOURCE_CLASS = {"OEM", "AFTERMARKET"}
ORDER_ADVANCE = {"QUOTE", "SCHEDULE", "START", "COMPLETE", "DELIVER"}
PART_ADVANCE = {"SUBMIT", "REVISE"}
DECISIONS = {"APPROVE", "REJECT"}


def path_order(oid):
    rec = store.get("orders", oid)
    if rec is None:
        fail("ERR_ORDER_NOT_FOUND", "Rebuild order %s not found" % oid)
    return rec


def path_part_line(pid):
    rec = store.get("part_lines", pid)
    if rec is None:
        fail("ERR_PART_LINE_NOT_FOUND", "Part line %s not found" % pid)
    return rec


def _rollup(order):
    order["part_revision_counter"] = int(order["part_revision_counter"]) + 1
    order["approval_status"] = calc.approval_rollup(order["id"])
    store.touch(order)


# ---------------------------------------------------------------------------
# orders
# ---------------------------------------------------------------------------
@bp.post("/shop/rebuild-orders")
def create_order():
    _, role = authenticate()
    require_roles(role, ["Planner", "ShopAdmin"])
    body = v.body()
    customer_id = v.req_fk(body, "customer_id")
    core_unit_id = v.req_fk(body, "core_unit_id")
    asset_id = v.req_fk(body, "customer_asset_id")
    labor_hours = v.req_num(body, "labor_hours", exclusive_min=0)

    if store.get("customers", customer_id) is None:
        fail("ERR_CUSTOMER_NOT_FOUND", "Customer %s not found" % customer_id)
    core = store.get("core_units", core_unit_id)
    if core is None:
        fail("ERR_CORE_UNIT_NOT_FOUND", "Core unit %s not found" % core_unit_id)
    if store.get("assets", asset_id) is None:
        fail("ERR_ASSET_NOT_FOUND", "Asset %s not found" % asset_id)

    standard = store.get("standards", core["clearance_standard_id"])
    if standard is not None and int(core["rebuild_count"]) >= int(standard["max_rebuild_count"]):
        fail("ERR_REBUILD_LIMIT_REACHED", "core has reached its rebuild ceiling")

    rec = store.base_record()
    rec.update({
        "customer_id": customer_id,
        "core_unit_id": core_unit_id,
        "customer_asset_id": asset_id,
        "labor_hours": labor_hours,
        "work_status": "DRAFT",
        "approval_status": "PENDING",
        "expedited": False,
        "expedite_reason": None,
        "emergency_ref": None,
        "part_revision_counter": 0,
        "quoted_part_revision": None,
        "parts_subtotal_cents": None,
        "labor_cents": None,
        "pre_credit_subtotal_cents": None,
        "expedite_surcharge_cents": None,
        "gross_total_cents": None,
        "core_credit_applied_cents": None,
        "quote_total_cents": None,
        "covered_base_cents": None,
        "cancel_reason": None,
    })
    store.insert("orders", rec)
    return created(views.render("orders", rec))


@bp.get("/shop/rebuild-orders/<oid>")
def read_order(oid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    rec = path_order(oid)
    views.require_owner(role, uid, "orders", rec)
    return ok(views.render("orders", rec))


@bp.get("/shop/rebuild-orders")
def list_orders():
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    limit, offset = v.pagination()
    rows = store.all_rows("orders")
    for key in ("customer_id", "core_unit_id", "customer_asset_id",
                "work_status", "approval_status"):
        value = v.qparam(key)
        if value is not None:
            rows = [r for r in rows if r.get(key) == value]
    rows = views.scope_rows(role, uid, "orders", rows)
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("orders", page), limit, offset, total)


@bp.get("/shop/rebuild-orders/<oid>/quote")
def read_quote(oid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    order = path_order(oid)
    views.require_owner(role, uid, "orders", order)
    gross = order.get("gross_total_cents")
    data = {
        "work_status": order["work_status"],
        "approval_status": order["approval_status"],
        "parts_subtotal_cents": order["parts_subtotal_cents"],
        "labor_cents": order["labor_cents"],
        "pre_credit_subtotal_cents": order["pre_credit_subtotal_cents"],
        "expedite_surcharge_cents": order["expedite_surcharge_cents"],
        "gross_total_cents": gross,
        "credit_cap_cents": calc.credit_cap_for(gross),
        "core_credit_applied_cents": order["core_credit_applied_cents"],
        "quote_total_cents": order["quote_total_cents"],
        "covered_base_cents": order["covered_base_cents"],
        "quoted_part_revision": order["quoted_part_revision"],
        "part_revision_counter": order["part_revision_counter"],
        "quote_stale": order["quoted_part_revision"] != order["part_revision_counter"],
    }
    return ok(store._scrub(data))


@bp.post("/shop/rebuild-orders/<oid>/advance")
def advance_order(oid):
    _, role = authenticate()
    require_roles(role, ["Planner", "ShopAdmin"])
    raw = v.body()
    require_action_role(role, raw.get("action"), ORDER_ACTIONS)
    order = path_order(oid)
    action = v.req_enum(raw, "action", ORDER_ADVANCE)

    if action == "QUOTE":
        _quote(order)
    elif action == "SCHEDULE":
        _schedule(order)
    elif action == "START":
        _start(order)
    elif action == "COMPLETE":
        _complete(order)
    else:
        _deliver(order)
    return ok(views.render("orders", order))


def _quote(order):
    if order["work_status"] not in ("DRAFT", "QUOTED"):
        fail("ERR_ORDER_INVALID_STATE", "order may not be quoted from %s" % order["work_status"])
    calc.quote_full(order)
    order["work_status"] = "QUOTED"
    store.touch(order)


def _schedule(order):
    if order["work_status"] != "QUOTED":
        fail("ERR_ORDER_INVALID_STATE", "order is not QUOTED")
    if order["approval_status"] != "APPROVED":
        fail("ERR_PART_APPROVAL_PENDING", "part lines are not fully approved")
    confirmed = [r for r in calc.reservations_of_order(order["id"]) if r["status"] == "CONFIRMED"]
    if not confirmed:
        fail("ERR_NO_CONFIRMED_BENCH", "no confirmed bench reservation")
    if order["quoted_part_revision"] != order["part_revision_counter"]:
        fail("ERR_QUOTE_STALE", "quote is stale")
    order["work_status"] = "SCHEDULED"
    store.touch(order)


def _start(order):
    if order["work_status"] != "SCHEDULED":
        fail("ERR_ORDER_INVALID_STATE", "order is not SCHEDULED")
    core = store.get("core_units", order["core_unit_id"])
    if core is None or core["status"] != "GRADED":
        fail("ERR_CORE_NOT_GRADED", "core is not GRADED")
    if core.get("condition_grade") == "SCRAP" or core["status"] == "SCRAPPED":
        fail("ERR_CORE_SCRAPPED", "core is scrap")
    inspection = calc.accepted_inspection_of_order(order["id"])
    if inspection is not None:
        governing = calc.governing_measurements(inspection["id"])
        for m in governing.values():
            if m["band_result"] == "OUT_OF_SPEC":
                fail("ERR_CLEARANCE_OUT_OF_SPEC", "a governing feature is out of specification")
    order["work_status"] = "IN_PROGRESS"
    store.touch(order)
    core["status"] = "REBUILDING"
    store.touch(core)


def _complete(order):
    if order["work_status"] != "IN_PROGRESS":
        fail("ERR_ORDER_INVALID_STATE", "order is not IN_PROGRESS")
    order["work_status"] = "COMPLETED"
    store.touch(order)
    core = store.get("core_units", order["core_unit_id"])
    if core is not None:
        core["status"] = "REBUILT"
        core["rebuild_count"] = int(core["rebuild_count"]) + 1
        store.touch(core)
    bench_ops.consume_order_reservations(order)


def _deliver(order):
    if order["work_status"] != "COMPLETED":
        fail("ERR_ORDER_INVALID_STATE", "order is not COMPLETED")
    order["work_status"] = "DELIVERED"
    store.touch(order)
    core = store.get("core_units", order["core_unit_id"])
    if core is not None:
        core["status"] = "SHIPPED"
        store.touch(core)


@bp.post("/shop/rebuild-orders/<oid>/cancel")
def cancel_order(oid):
    _, role = authenticate()
    require_roles(role, ["Planner", "ShopAdmin"])
    order = path_order(oid)
    body = v.body()
    reason = v.req_str(body, "cancel_reason")
    if order["work_status"] not in ("DRAFT", "QUOTED", "SCHEDULED", "IN_PROGRESS"):
        fail("ERR_ORDER_INVALID_STATE", "order may not be cancelled from %s" % order["work_status"])
    was_in_progress = order["work_status"] == "IN_PROGRESS"
    order["work_status"] = "CANCELLED"
    order["cancel_reason"] = reason
    store.touch(order)
    bench_ops.release_order_reservations(order)
    if was_in_progress:
        core = store.get("core_units", order["core_unit_id"])
        if core is not None and core["status"] == "REBUILDING":
            core["status"] = "GRADED"
            store.touch(core)
    return ok(views.render("orders", order))


@bp.post("/shop/rebuild-orders/<oid>/expedite")
def expedite_order(oid):
    _, role = authenticate()
    require_roles(role, ["Planner", "ShopAdmin"])
    order = path_order(oid)
    body = v.body()
    reason = v.req_str(body, "expedite_reason")
    emergency_ref = v.opt_str(body, "emergency_ref", None)
    if order["work_status"] not in ("DRAFT", "QUOTED") or order["expedited"]:
        fail("ERR_EXPEDITE_NOT_AVAILABLE", "expedite is not available for this order")
    order["expedited"] = True
    order["expedite_reason"] = reason
    order["emergency_ref"] = emergency_ref
    if order["work_status"] == "QUOTED":
        calc.quote_full(order)
    store.touch(order)
    return ok(views.render("orders", order))


# ---------------------------------------------------------------------------
# part lines
# ---------------------------------------------------------------------------
def _aftermarket_guard(order, source_class, waiver_ref):
    if source_class != "AFTERMARKET":
        return
    asset = store.get("assets", order["customer_asset_id"])
    if asset is not None and asset["criticality"] == "CRITICAL":
        if not (waiver_ref and waiver_ref.strip()):
            fail("ERR_AFTERMARKET_NOT_PERMITTED",
                 "an engineering waiver is required for aftermarket parts on a critical asset")


@bp.post("/shop/rebuild-orders/<oid>/part-lines")
def create_part_line(oid):
    _, role = authenticate()
    require_roles(role, ["Planner", "ShopAdmin"])
    order = path_order(oid)
    body = v.body()
    part_no = v.req_str(body, "part_no")
    source_class = v.req_enum(body, "source_class", SOURCE_CLASS)
    qty = v.req_int(body, "qty", minimum=1)
    unit_cost = v.req_int(body, "unit_cost_cents", minimum=0)
    waiver_ref = v.opt_str(body, "engineering_waiver_ref", None)
    expected = v.req_int(body, "expected_order_version")

    if expected != order["version"]:
        fail("ERR_STALE_VERSION", "expected_order_version does not match")
    if order["work_status"] not in ("DRAFT", "QUOTED"):
        fail("ERR_ORDER_INVALID_STATE", "order does not accept new part lines")
    _aftermarket_guard(order, source_class, waiver_ref)

    rec = store.base_record()
    rec.update({
        "rebuild_order_id": order["id"],
        "part_no": part_no,
        "source_class": source_class,
        "qty": qty,
        "unit_cost_cents": unit_cost,
        "engineering_waiver_ref": waiver_ref,
        "approval_status": "PROPOSED",
        "revision_count": 0,
        "decision_note": None,
        "line_total_cents": qty * unit_cost,
    })
    store.insert("part_lines", rec)
    _rollup(order)
    return created(views.render("part_lines", rec))


@bp.get("/shop/rebuild-orders/<oid>/part-lines")
def list_part_lines(oid):
    uid, role = authenticate()
    require_roles(role, ALL_ROLES)
    order = path_order(oid)
    limit, offset = v.pagination()
    views.require_owner(role, uid, "orders", order)
    rows = calc.part_lines_of(order["id"])
    status = v.qparam("approval_status")
    if status is not None:
        rows = [r for r in rows if r["approval_status"] == status]
    rows = store.sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return listing(views.render_many("part_lines", page), limit, offset, total)


@bp.post("/shop/part-lines/<pid>/advance")
def advance_part_line(pid):
    _, role = authenticate()
    require_roles(role, ["Planner", "ShopAdmin"])
    raw = v.body()
    require_action_role(role, raw.get("action"), PART_LINE_ACTIONS)
    line = path_part_line(pid)
    action = v.req_enum(raw, "action", PART_ADVANCE)
    part_no = v.opt_str(raw, "part_no", None)
    source_class = v.opt_enum(raw, "source_class", SOURCE_CLASS, None)
    qty = v.opt_int(raw, "qty", None, minimum=1)
    unit_cost = v.opt_int(raw, "unit_cost_cents", None, minimum=0)
    waiver_ref = v.opt_str(raw, "engineering_waiver_ref", None)

    order = store.get("orders", line["rebuild_order_id"])

    if order is None or order["work_status"] not in ("DRAFT", "QUOTED"):
        fail("ERR_PART_LINE_INVALID_STATE", "the parent order does not admit part-line changes")
    if action == "SUBMIT":
        if line["approval_status"] != "PROPOSED":
            fail("ERR_PART_LINE_INVALID_STATE", "line is not PROPOSED")
        line["approval_status"] = "SUBMITTED"
    else:
        if line["approval_status"] != "REJECTED":
            fail("ERR_PART_LINE_INVALID_STATE", "line is not REJECTED")
        next_source = source_class if source_class is not None else line["source_class"]
        next_waiver = waiver_ref if waiver_ref is not None else line["engineering_waiver_ref"]
        _aftermarket_guard(order, next_source, next_waiver)
        if part_no is not None:
            line["part_no"] = part_no
        if source_class is not None:
            line["source_class"] = source_class
        if qty is not None:
            line["qty"] = qty
        if unit_cost is not None:
            line["unit_cost_cents"] = unit_cost
        if waiver_ref is not None:
            line["engineering_waiver_ref"] = waiver_ref
        line["line_total_cents"] = int(line["qty"]) * int(line["unit_cost_cents"])
        line["revision_count"] = int(line["revision_count"]) + 1
        line["approval_status"] = "PROPOSED"

    store.touch(line)
    _rollup(order)
    return ok(views.render("part_lines", line))


@bp.post("/shop/part-lines/<pid>/decide")
def decide_part_line(pid):
    uid, role = authenticate()
    require_roles(role, ["Customer"])
    line = path_part_line(pid)
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)
    note = v.opt_str(body, "decision_note", None)

    order = store.get("orders", line["rebuild_order_id"])
    if order is None or order["customer_id"] != uid:
        fail("ERR_NOT_RESOURCE_OWNER", "part line does not belong to the calling account")
    if line["approval_status"] != "SUBMITTED":
        fail("ERR_PART_LINE_INVALID_STATE", "line is not SUBMITTED")

    line["approval_status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    line["decision_note"] = note
    store.touch(line)
    _rollup(order)
    return ok(views.render("part_lines", line))
