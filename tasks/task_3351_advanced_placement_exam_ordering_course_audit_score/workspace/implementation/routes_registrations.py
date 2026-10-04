"""Exam registrations: creation, the registration machine and fee settlement."""

from flask import request

import auth
import calc
import cascades
import core
from constants import BASE_EXAM_FEE_CENTS, MAX_EXAMINEES_PER_ORDER, MAX_EXAMS_PER_STUDENT
from core import app, body, bool_field, enum_field, insert, int_field, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import list_response, ok
from validation import require_fk, require_window_open, transition_gate


@app.route("/ap-program/exam-registrations", methods=["POST"])
def create_exam_registration():
    auth.authenticate(["SchoolCoordinator"])
    payload = body()
    exam_order_id = str_field(payload, "exam_order_id")
    student_id = str_field(payload, "student_id")
    exam_subject = str_field(payload, "exam_subject")
    tier = enum_field(payload, "registration_tier",
                      ["REGULAR", "LATE", "EMERGENCY"], required=False, default="REGULAR")
    order = require_fk("exam_orders", exam_order_id, "exam_order_id")
    student = require_fk("students", student_id, "student_id")
    require_window_open(calc.ordering_window())
    held = cascades.count_active_registrations_for_year(student["id"], order["administration_year"])
    if held >= MAX_EXAMS_PER_STUDENT:
        fail("ERR_MAX_EXAMS_EXCEEDED")
    if order["registration_count"] + 1 > MAX_EXAMINEES_PER_ORDER:
        fail("ERR_ORDER_CAPACITY")
    registration = insert("exam_registrations", make(
        "exam_registrations",
        exam_order_id=exam_order_id,
        student_id=student_id,
        exam_subject=exam_subject,
        registration_tier=tier,
    ))
    cascades.recompute_registration_count(order)
    core.touch(order)
    return ok(serialize("exam_registrations", registration), status=201)


@app.route("/ap-program/exam-registrations/<rid>", methods=["GET"])
def read_exam_registration(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator", "SchoolStudent"])
    return ok(serialize("exam_registrations", require("exam_registrations", rid)))


@app.route("/ap-program/exam-registrations/<rid>/alternate-exam-requests", methods=["GET"])
def list_registration_alternates(rid):
    auth.authenticate(["PlatformAdmin", "SchoolCoordinator"])
    require("exam_registrations", rid)
    matching = [a for a in rows("alternate_exam_requests") if a["exam_registration_id"] == rid]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, request.args, lambda r: serialize("alternate_exam_requests", r))


@app.route("/ap-program/exam-registrations/<rid>/exam-scores", methods=["GET"])
def list_registration_scores(rid):
    auth.authenticate(["PlatformAdmin", "ScoringSpecialist", "SchoolCoordinator"])
    require("exam_registrations", rid)
    matching = [s for s in rows("exam_scores") if s["exam_registration_id"] == rid]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, request.args, lambda r: serialize("exam_scores", r))


@app.route("/ap-program/exam-registrations/<rid>/irregularity-cases", methods=["GET"])
def list_registration_cases(rid):
    auth.authenticate(["IntegrityInvestigator", "PlatformAdmin"])
    require("exam_registrations", rid)
    matching = [c for c in rows("irregularity_cases") if c["exam_registration_id"] == rid]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, request.args, lambda r: serialize("irregularity_cases", r))


@app.route("/ap-program/exam-registrations/<rid>/fees", methods=["POST"])
def settle_registration_fees(rid):
    auth.authenticate(["SchoolCoordinator", "PlatformAdmin"])
    payload = body()
    registration = require("exam_registrations", rid)
    paid = int_field(payload, "fees_paid_cents", minimum=0)
    registration["fees_paid_cents"] = paid
    if bool_field(payload, "fee_waived", registration["fee_waived"]):
        registration["fee_waived"] = True
    registration["refundable_cents"] = min(
        max(0, paid - registration["late_fee_cents"]), BASE_EXAM_FEE_CENTS)
    core.touch(registration)
    return ok(serialize("exam_registrations", registration))


@app.route("/ap-program/exam-registrations/<rid>/status-transitions", methods=["POST"])
def transition_exam_registration(rid):
    role, actor = auth.authenticate(["SchoolCoordinator", "PlatformAdmin"])
    payload = body()
    registration, to_status = transition_gate("exam_registrations", rid, payload, actor=actor)
    order = core.require("exam_orders", registration["exam_order_id"])
    student = core.get("students", registration["student_id"])

    if to_status == "FEE_PENDING":
        if order["status"] not in ("OPEN", "SUBMITTED"):
            fail("ERR_INVALID_STATE", "The owning order is not open for fees.")
        if student is None or not student["enrolled"]:
            fail("ERR_INVALID_STATE", "The student is not enrolled.")
        held = cascades.count_active_registrations_for_year(
            registration["student_id"], order["administration_year"])
        if held >= MAX_EXAMS_PER_STUDENT:
            fail("ERR_MAX_EXAMS_EXCEEDED")
        window = calc.ordering_window()
        registration["late_fee_cents"] = calc.late_fee_per_registration(
            registration["registration_tier"], window)
        if registration["registration_tier"] == "LATE":
            registration["refundable_cents"] = BASE_EXAM_FEE_CENTS + registration["late_fee_cents"]
        else:
            registration["refundable_cents"] = BASE_EXAM_FEE_CENTS
        registration["status"] = "FEE_PENDING"
        core.touch(registration)
        cascades.recompute_registration_count(order)
        core.touch(order)

    elif to_status == "REGISTERED":
        if role != "PlatformAdmin":
            fail("ERR_UNAUTHORIZED", "Only a PlatformAdmin may reverse this transition.")
        if registration["status"] == "FEE_PENDING":
            if not bool_field(payload, "fee_waived", False):
                fail("ERR_INVALID_STATE", "The assessed late fee must be waived to reverse.")
            registration["fee_waived"] = True
            registration["late_fee_cents"] = 0
        else:
            if order["status"] != "OPEN" or calc.ordering_window() != "REGULAR":
                fail("ERR_INVALID_STATE", "Reinstatement requires an OPEN order in the REGULAR window.")
            registration["refundable_cents"] = BASE_EXAM_FEE_CENTS + registration["late_fee_cents"]
        registration["status"] = "REGISTERED"
        core.touch(registration)
        cascades.recompute_registration_count(order)

    elif to_status == "CONFIRMED":
        if registration["late_fee_cents"] > 0 and \
                (registration.get("fees_paid_cents") or 0) < registration["late_fee_cents"]:
            fail("ERR_LATE_FEE_UNPAID")
        if registration["status"] == "REGISTERED" and registration["late_fee_cents"] != 0:
            fail("ERR_LATE_FEE_UNPAID")
        if registration["status"] == "FEE_PENDING" \
                and order["status"] not in ("OPEN", "SUBMITTED", "MATERIALS_SHIPPED", "MATERIALS_RECEIVED"):
            fail("ERR_INVALID_STATE", "The owning order cannot confirm registrations.")
        registration["status"] = "CONFIRMED"
        if student is not None:
            registration["accommodation_flag"] = cascades.refresh_student_flag(student)
        core.touch(registration)
        cascades.recompute_registration_count(order)

    elif to_status == "MATERIAL_ASSIGNED":
        if not cascades.registration_material_assignable(registration):
            fail("ERR_ACCOMMODATION_PROVISION_INCOMPLETE")
        registration["status"] = "MATERIAL_ASSIGNED"
        core.touch(registration)

    elif to_status == "SCORED":
        if not any(s["exam_registration_id"] == rid and s["status"] == "AGGREGATED"
                   for s in rows("exam_scores")):
            fail("ERR_INVALID_STATE", "No aggregated score exists for this registration.")
        registration["status"] = "SCORED"
        core.touch(registration)

    elif to_status == "SCORE_RELEASED":
        if not any(s["exam_registration_id"] == rid and s["status"] == "RELEASED"
                   for s in rows("exam_scores")):
            fail("ERR_INVALID_STATE", "No released score exists for this registration.")
        registration["status"] = "SCORE_RELEASED"
        core.touch(registration)

    elif to_status == "INVALIDATED":
        if not any(c["exam_registration_id"] == rid and c["status"] == "CONFIRMED"
                   and c["finding_code"] == "SCORE_INVALIDATION_REQUIRED"
                   for c in rows("irregularity_cases")):
            fail("ERR_INVALID_STATE", "No confirmed invalidation finding exists.")
        cascades.invalidation_cascade(registration)

    elif to_status == "CANCELLED":
        registration["refundable_cents"] = BASE_EXAM_FEE_CENTS
        registration["status"] = "CANCELLED"
        core.touch(registration)
        cascades.recompute_registration_count(order)
        core.touch(order)
        school = core.get("schools", order["school_id"])
        if school is not None:
            core.touch(school)

    cascades.recompute_registration_count(order)
    return ok(serialize("exam_registrations", registration))
