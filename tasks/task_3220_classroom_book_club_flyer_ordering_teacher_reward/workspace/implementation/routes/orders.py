"""Class order and order line endpoints: open, line mutations, submit, cancel."""

from flask import Blueprint, request

import db
from errors import raise_err
from middleware import require_roles, current_role, current_user_id
from response import object_response, list_response, paginate
from services import (
    new_record, touch, serialize_order, serialize_line, recompute_order,
    order_lines_of, school_posture, accrue_royalty, reverse_royalty,
    title_license_status, append_ledger, ROYALTY_PER_UNIT_CENTS,
)
from routes.common import get_body, path_get, ref_get, req_field, req_int, req_enum

bp = Blueprint("orders", __name__)


def _order_open_gate(order):
    """Line mutation gate: parent order OPEN and its cycle PUBLISHED."""
    cycle = db.flyer_cycles.get(order["cycle_id"])
    if order["status"] != "OPEN" or cycle is None or cycle["status"] != "PUBLISHED":
        raise_err("ERR_ORDER_NOT_OPEN",
                  "Line mutation requires parent order OPEN on a PUBLISHED cycle")


@bp.post("/club/class-orders")
@require_roles("Teacher")
def create_order():
    body = get_body()
    cycle_id = req_field(body, "cycle_id")
    teacher_id = req_field(body, "teacher_id")
    cycle = ref_get(db.flyer_cycles, cycle_id, "FlyerCycle")
    teacher = ref_get(db.teachers, teacher_id, "Teacher")
    if teacher["grade_band"] != cycle["grade_band"] or teacher["school_id"] != cycle["school_id"]:
        raise_err("ERR_GRADE_BAND_MISMATCH",
                  "Teacher must teach at the cycle's school and match its grade_band")
    if cycle["status"] != "PUBLISHED":
        raise_err("ERR_CYCLE_NOT_PUBLISHED", "ClassOrder creation requires a PUBLISHED cycle")
    order = new_record({
        "cycle_id": cycle_id,
        "teacher_id": teacher_id,
        "status": "OPEN",
        "ship_status": "PENDING",
        "points_status": "UNAWARDED",
        "subtotal_cents": 0,
        "rewardable_subtotal_cents": 0,
        "discount_cents": 0,
        "net_total_cents": 0,
        "shipping_fee_cents": 0,
        "awarded_base_points": 0,
        "awarded_bonus_points": 0,
        "awarded_total_points": 0,
    })
    db.class_orders[order["id"]] = order
    recompute_order(order)
    return object_response(serialize_order(order), 201)


@bp.get("/club/class-orders/<oid>")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent")
def get_order(oid):
    return object_response(serialize_order(path_get(db.class_orders, oid, "ClassOrder")))


@bp.get("/club/class-orders/<oid>/lines")
@require_roles("ClubAdmin", "SchoolAdmin", "Teacher", "Parent")
def list_lines(oid):
    path_get(db.class_orders, oid, "ClassOrder")
    items = order_lines_of(oid, include_cancelled=True)
    st = request.args.get("status")
    if st:
        items = [l for l in items if l["status"] == st]
    page, total, limit, offset = paginate(items)
    return list_response(([serialize_line(l) for l in page], total, limit, offset))


@bp.post("/club/class-orders/<oid>/lines")
@require_roles("Teacher", "Parent")
def add_line(oid):
    order = path_get(db.class_orders, oid, "ClassOrder")
    body = get_body()
    offering_id = req_field(body, "offering_id")
    offering = ref_get(db.offerings, offering_id, "FlyerOffering")
    student_name = req_field(body, "student_name")
    submitted_by = req_enum(body, "submitted_by", {"PARENT_ONLINE", "TEACHER"})
    qty = req_int(body, "qty")
    if not isinstance(student_name, str):
        raise_err("ERR_INVALID_REQUEST", "student_name must be a string")
    if qty < 1:
        raise_err("ERR_INVALID_REQUEST", "qty must be >= 1")
    if current_role() == "Parent" and submitted_by != "PARENT_ONLINE":
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "Parent may only create lines with submitted_by PARENT_ONLINE")
    _order_open_gate(order)
    from services import offering_fair_overlap
    line = new_record({
        "class_order_id": oid,
        "offering_id": offering_id,
        "student_name": student_name,
        "submitted_by": submitted_by,
        "qty": qty,
        "unit_price_cents": offering["flyer_price_cents"],
        "fair_overlap": offering_fair_overlap(offering),
        "donation_funded": False,
        "status": "ACTIVE",
        "points_earned": 0,
    })
    db.order_lines[line["id"]] = line
    recompute_order(order)
    touch(order)
    return object_response(serialize_line(line), 201)


@bp.patch("/club/order-lines/<lid>")
@require_roles("Teacher", "Parent")
def update_line(lid):
    line = path_get(db.order_lines, lid, "OrderLine")
    order = path_get(db.class_orders, line["class_order_id"], "ClassOrder")
    body = get_body()
    qty = req_int(body, "qty")
    if qty < 1:
        raise_err("ERR_INVALID_REQUEST", "qty must be >= 1")
    if line["status"] == "CANCELLED":
        raise_err("ERR_ALREADY_TERMINAL", "Line is CANCELLED")
    if current_role() == "Parent" and line["submitted_by"] != "PARENT_ONLINE":
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "Parent may update only lines with submitted_by PARENT_ONLINE")
    _order_open_gate(order)
    line["qty"] = qty
    touch(line)
    recompute_order(order)
    touch(order)
    return object_response(serialize_line(line))


@bp.delete("/club/order-lines/<lid>")
@require_roles("Teacher", "Parent")
def delete_line(lid):
    line = path_get(db.order_lines, lid, "OrderLine")
    order = path_get(db.class_orders, line["class_order_id"], "ClassOrder")
    if line["status"] == "CANCELLED":
        raise_err("ERR_ALREADY_TERMINAL", "Line is CANCELLED")
    if current_role() == "Parent" and line["submitted_by"] != "PARENT_ONLINE":
        raise_err("ERR_FORBIDDEN_OWNERSHIP",
                  "Parent may cancel only lines with submitted_by PARENT_ONLINE")
    _order_open_gate(order)
    line["status"] = "CANCELLED"
    touch(line)
    recompute_order(order)
    touch(order)
    return object_response(serialize_line(line))


@bp.post("/club/class-orders/<oid>/submit")
@require_roles("Teacher")
def submit_order(oid):
    order = path_get(db.class_orders, oid, "ClassOrder")
    body = get_body()
    expected = req_int(body, "expected_class_order_version")
    # State (5) then terminal (6).
    if order["status"] == "CANCELLED":
        raise_err("ERR_ALREADY_TERMINAL", "ClassOrder is CANCELLED")
    if order["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "Submit requires status OPEN")
    # Posture (7).
    cycle = db.flyer_cycles.get(order["cycle_id"])
    if cycle is not None and school_posture(cycle["school_id"]) != "NORMAL":
        raise_err("ERR_SCHOOL_RESTRICTED", "School posture is RESTRICTED")
    # Cycle published gate.
    if cycle is None or cycle["status"] != "PUBLISHED":
        raise_err("ERR_CYCLE_NOT_PUBLISHED", "Submit requires the cycle PUBLISHED")
    # Ownership (21).
    if current_user_id() != order["teacher_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Acting teacher is not the order's teacher")
    # Non-empty (24).
    lines = order_lines_of(oid)
    if not lines:
        raise_err("ERR_ORDER_EMPTY", "Submit requires at least one non-CANCELLED line")
    # OCC (25).
    if expected != order["version"]:
        raise_err("ERR_STALE_VERSION",
                  "expected_class_order_version does not match current version")

    # Pin aggregates at submit.
    recompute_order(order)
    teacher = db.teachers[order["teacher_id"]]

    # Award points.
    total = order["awarded_total_points"]
    order["status"] = "SUBMITTED"
    order["points_status"] = "AWARDED"
    teacher["points_balance"] += total
    teacher["points_earned_total"] += total
    touch(teacher)
    append_ledger(teacher["id"], "EARN", total, "CLASS_ORDER", order["id"])

    # Royalty accrual per line qty (chronological by line created_at).
    for line in lines:
        offering = db.offerings.get(line["offering_id"])
        title = db.titles.get(offering["title_id"]) if offering else None
        if title is not None:
            accrue_royalty(title, line["qty"])

    # Backorder pass: non-cancelled lines whose title license is now SUSPENDED.
    for line in lines:
        if line["status"] == "CANCELLED":
            continue
        offering = db.offerings.get(line["offering_id"])
        title = db.titles.get(offering["title_id"]) if offering else None
        if title is not None and title_license_status(title) == "SUSPENDED":
            line["status"] = "BACKORDERED"
            touch(line)

    backordered = sum(1 for l in order_lines_of(oid) if l["status"] == "BACKORDERED")
    order["ship_status"] = "PENDING" if backordered > 0 else "SHIPPED"
    touch(order)
    return object_response(serialize_order(order))


@bp.post("/club/class-orders/<oid>/cancel")
@require_roles("Teacher")
def cancel_order(oid):
    order = path_get(db.class_orders, oid, "ClassOrder")
    if order["status"] == "CANCELLED":
        raise_err("ERR_ALREADY_TERMINAL", "ClassOrder is CANCELLED")
    if order["status"] not in ("OPEN", "SUBMITTED"):
        raise_err("ERR_INVALID_STATE", "Cancel requires status OPEN or SUBMITTED")
    if order["status"] == "SUBMITTED" and order["ship_status"] != "PENDING":
        raise_err("ERR_ORDER_HAS_SHIPPED", "Cancel-from-SUBMITTED requires ship_status PENDING")
    if current_user_id() != order["teacher_id"]:
        raise_err("ERR_FORBIDDEN_OWNERSHIP", "Acting teacher is not the order's teacher")

    teacher = db.teachers[order["teacher_id"]]
    if order["status"] == "SUBMITTED":
        # Clawback solvency (19).
        if teacher["points_balance"] < order["awarded_total_points"]:
            raise_err("ERR_POINTS_BALANCE_NEGATIVE",
                      "Clawback would drive Teacher.points_balance below 0")
        # Reverse royalty accrual.
        for line in order_lines_of(oid):
            offering = db.offerings.get(line["offering_id"])
            title = db.titles.get(offering["title_id"]) if offering else None
            if title is not None:
                reverse_royalty(title, line["qty"])
        # Clawback.
        total = order["awarded_total_points"]
        teacher["points_balance"] -= total
        touch(teacher)
        append_ledger(teacher["id"], "CLAWBACK", -total, "CLASS_ORDER", order["id"])
        order["points_status"] = "CLAWED_BACK"

    for line in order_lines_of(oid):
        if line["status"] != "CANCELLED":
            line["status"] = "CANCELLED"
            touch(line)
    order["status"] = "CANCELLED"
    recompute_order(order)
    touch(order)
    return object_response(serialize_order(order))
