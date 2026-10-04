"""Exam orders: creation, listing and the order machine."""

from flask import request

import auth
import calc
import cascades
import core
from constants import MAX_EXAMINEES_PER_ORDER, MIN_ORDER_SIZE
from core import app, body, insert, int_field, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import list_response, ok
from validation import require_fk, require_window_open, transition_gate

VOIDABLE_FROM = ("DRAFT", "OPEN", "SUBMITTED")
LOCKED_REGISTRATION_STATUSES = ("MATERIAL_ASSIGNED", "SCORED", "SCORE_RELEASED")


@app.route("/ap-program/exam-orders", methods=["POST"])
def create_exam_order():
    auth.authenticate(["SchoolCoordinator"])
    payload = body()
    school_id = str_field(payload, "school_id")
    course_audit_id = str_field(payload, "course_audit_id")
    administration_year = int_field(payload, "administration_year")
    require_fk("schools", school_id, "school_id")
    require_fk("course_audits", course_audit_id, "course_audit_id")
    order = insert("exam_orders", make(
        "exam_orders",
        school_id=school_id,
        course_audit_id=course_audit_id,
        administration_year=administration_year,
    ))
    school = core.require("schools", school_id)
    cascades.recompute_accrued_fees(school_id)
    core.touch(school)
    return ok(serialize("exam_orders", order), status=201)


@app.route("/ap-program/exam-orders", methods=["GET"])
def list_exam_orders():
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator"])
    args = request.args
    school_id = args.get("school_id")
    course_audit_id = args.get("course_audit_id")
    status = args.get("status")
    matching = [
        o for o in rows("exam_orders")
        if (school_id is None or o["school_id"] == school_id)
        and (course_audit_id is None or o["course_audit_id"] == course_audit_id)
        and (status is None or o["status"] == status)
    ]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, args, lambda r: serialize("exam_orders", r))


@app.route("/ap-program/exam-orders/<rid>", methods=["GET"])
def read_exam_order(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator"])
    return ok(serialize("exam_orders", require("exam_orders", rid)))


@app.route("/ap-program/exam-orders/<rid>/registrations", methods=["GET"])
def list_order_registrations(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator"])
    require("exam_orders", rid)
    matching = [r for r in rows("exam_registrations") if r["exam_order_id"] == rid]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, request.args, lambda r: serialize("exam_registrations", r))


@app.route("/ap-program/exam-orders/<rid>/material-shipments", methods=["GET"])
def list_order_shipments(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator"])
    require("exam_orders", rid)
    matching = [s for s in rows("material_shipments") if s["exam_order_id"] == rid]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, request.args, lambda r: serialize("material_shipments", r))


@app.route("/ap-program/exam-orders/<rid>/status-transitions", methods=["POST"])
def transition_exam_order(rid):
    role, actor = auth.authenticate(["SchoolCoordinator", "PlatformAdmin"])
    payload = body()
    order, to_status = transition_gate(
        "exam_orders", rid, payload,
        occ_field="expected_exam_order_version", actor=actor,
    )
    school = core.require("schools", order["school_id"])

    if to_status == "OPEN":
        audit = core.get("course_audits", order["course_audit_id"])
        if audit is None or audit["status"] != "APPROVED" \
                or not school["program_label_authorized"]:
            fail("ERR_COURSE_AUDIT_NOT_APPROVED")
        if school["test_center_status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "The school's test center is not ACTIVE.")
        order["status"] = "OPEN"
        order["ordering_window"] = calc.ordering_window()
        cascades.refresh_order_fees(order)
        core.touch(order)

    elif to_status == "SUBMITTED":
        require_window_open(order["ordering_window"])
        if order["registration_count"] < MIN_ORDER_SIZE:
            fail("ERR_ORDER_MIN_SIZE")
        for reg in cascades.regs_of_order(order["id"]):
            if reg["status"] not in ("REGISTERED", "FEE_PENDING", "CONFIRMED"):
                fail("ERR_INVALID_STATE", "A registration is already past confirmation.")
        cascades.refresh_order_fees(order)
        order["status"] = "SUBMITTED"
        core.touch(order)

    elif to_status == "MATERIALS_SHIPPED":
        regs = cascades.regs_of_order(order["id"])
        shipments = [s for s in rows("material_shipments") if s["exam_order_id"] == order["id"]]
        for reg in regs:
            if reg["status"] != "CONFIRMED":
                fail("ERR_INVALID_STATE", "Not every registration is confirmed.")
        if not shipments:
            fail("ERR_INVALID_STATE", "No material shipment covers this order.")
        for shipment in shipments:
            if shipment["status"] not in ("CREATED", "DISPATCHED", "IN_TRANSIT"):
                fail("ERR_INVALID_STATE", "A shipment is already past dispatch.")
        order["status"] = "MATERIALS_SHIPPED"
        order["materials_sealed"] = True
        core.touch(order)

    elif to_status == "MATERIALS_RECEIVED":
        shipments = [s for s in rows("material_shipments") if s["exam_order_id"] == order["id"]]
        for shipment in shipments:
            if shipment["status"] != "RECEIVED" or not shipment["seal_verified"]:
                fail("ERR_INVALID_STATE", "Not every shipment is received with a verified seal.")
        if order["registration_count"] > MAX_EXAMINEES_PER_ORDER:
            fail("ERR_ORDER_CAPACITY")
        confirmed = [r for r in cascades.regs_of_order(order["id"]) if r["status"] == "CONFIRMED"]
        for reg in confirmed:
            if not cascades.registration_material_assignable(reg):
                fail("ERR_ACCOMMODATION_PROVISION_INCOMPLETE")
        for reg in confirmed:
            reg["status"] = "MATERIAL_ASSIGNED"
            core.touch(reg)
        order["status"] = "MATERIALS_RECEIVED"
        core.touch(order)

    elif to_status == "DELIVERED":
        if order["registration_count"] < MIN_ORDER_SIZE:
            fail("ERR_ORDER_MIN_SIZE")
        for shipment in rows("material_shipments"):
            if shipment["exam_order_id"] != order["id"]:
                continue
            if shipment["status"] in ("SEAL_BROKEN", "IN_TRANSIT", "DISPATCHED"):
                fail("ERR_INVALID_STATE", "A shipment is still in flight or compromised.")
        cascades.deliver_order(order)

    elif to_status == "VOIDED":
        if order["status"] in ("DRAFT", "OPEN") and role != "SchoolCoordinator":
            fail("ERR_UNAUTHORIZED", "Only a SchoolCoordinator may void a %s order." % order["status"])
        if order["status"] == "SUBMITTED" and role != "PlatformAdmin":
            fail("ERR_UNAUTHORIZED", "Only a PlatformAdmin may void a SUBMITTED order.")
        regs = cascades.regs_of_order(order["id"])
        for reg in regs:
            if reg["status"] in LOCKED_REGISTRATION_STATUSES:
                fail("ERR_INVALID_STATE", "A registration has already consumed material.")
        if order["status"] == "SUBMITTED":
            for reg in regs:
                reg["status"] = "CANCELLED"
                reg["refundable_cents"] = reg.get("fees_paid_cents") or 0
                core.touch(reg)
            order["order_fee_cents"] = 0
            core.touch(school)
        elif order["status"] == "OPEN":
            for reg in regs:
                if reg["status"] == "REGISTERED":
                    reg["status"] = "CANCELLED"
                    reg["refundable_cents"] = 0
                    core.touch(reg)
            core.touch(school)
        order["status"] = "VOIDED"
        core.touch(order)

    cascades.recompute_registration_count(order)
    cascades.recompute_accrued_fees(order["school_id"])
    return ok(serialize("exam_orders", order))
