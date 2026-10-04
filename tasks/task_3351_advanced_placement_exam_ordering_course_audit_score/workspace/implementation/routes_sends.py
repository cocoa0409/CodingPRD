"""Score sends: designation, the send machine and the designation budget."""

from flask import request

import auth
import calc
import cascades
import clock
import core
from constants import DESIGNATION_SLOT_BUDGET, SEND_CANCEL_WINDOW_DAYS
from core import app, body, enum_field, insert, int_field, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import list_response, ok
from validation import require_fk, transition_gate


def _school_of_score(score):
    registration = core.get("exam_registrations", score["exam_registration_id"])
    if registration is None:
        return None
    student = core.get("students", registration["student_id"])
    if student is None:
        return None
    return core.get("schools", student["school_id"])


def _recipient_resolves(send):
    if send["recipient_type"] == "SCHOOL":
        return any(s["school_code"] == send["recipient_code"] for s in rows("schools"))
    if send["recipient_type"] == "STUDENT":
        return any(s["student_code"] == send["recipient_code"] for s in rows("students"))
    return False


@app.route("/ap-program/score-sends", methods=["POST"])
def create_score_send():
    auth.authenticate(["ScoringSpecialist", "SchoolCoordinator"])
    payload = body()
    exam_score_id = str_field(payload, "exam_score_id")
    recipient_type = enum_field(payload, "recipient_type", ["COLLEGE", "STUDENT", "SCHOOL"])
    recipient_code = str_field(payload, "recipient_code")
    designation_year = int_field(payload, "designation_year")
    score = require_fk("exam_scores", exam_score_id, "exam_score_id")
    if score["release_blocked"]:
        fail("ERR_RELEASE_BLOCKED")
    if score["status"] != "RELEASED":
        fail("ERR_INVALID_STATE", "The score has not been released.")
    school = _school_of_score(score)
    if recipient_type == "COLLEGE" and school is not None \
            and school["designation_slots_used"] >= DESIGNATION_SLOT_BUDGET:
        fail("ERR_DESIGNATION_SLOTS_EXHAUSTED")
    send = insert("score_sends", make(
        "score_sends",
        exam_score_id=exam_score_id,
        recipient_type=recipient_type,
        recipient_code=recipient_code,
        designation_year=designation_year,
        fee_cents=calc.score_send_fee(exam_score_id, recipient_type),
    ))
    send["_fees_paid_cents"] = 0
    if school is not None:
        cascades.recompute_designation_slots(school["id"])
        core.touch(school)
    return ok(serialize("score_sends", send), status=201)


@app.route("/ap-program/score-sends", methods=["GET"])
def list_score_sends():
    auth.authenticate(["ScoringSpecialist", "PlatformAdmin", "SchoolCoordinator"])
    args = request.args
    exam_score_id = args.get("exam_score_id")
    recipient_type = args.get("recipient_type")
    status = args.get("status")
    matching = [
        s for s in rows("score_sends")
        if (exam_score_id is None or s["exam_score_id"] == exam_score_id)
        and (recipient_type is None or s["recipient_type"] == recipient_type)
        and (status is None or s["status"] == status)
    ]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, args, lambda r: serialize("score_sends", r))


@app.route("/ap-program/score-sends/<rid>", methods=["GET"])
def read_score_send(rid):
    auth.authenticate(["PlatformAdmin", "ScoringSpecialist", "SchoolCoordinator"])
    return ok(serialize("score_sends", require("score_sends", rid)))


@app.route("/ap-program/score-sends/<rid>/status-transitions", methods=["POST"])
def transition_score_send(rid):
    role, actor = auth.authenticate(
        ["ScoringSpecialist", "SchoolCoordinator", "PlatformAdmin", "SchoolStudent"])
    payload = body()
    send, to_status = transition_gate("score_sends", rid, payload, actor=actor)
    score = core.require("exam_scores", send["exam_score_id"])

    if role == "SchoolStudent":
        if to_status != "CANCELLED":
            fail("ERR_UNAUTHORIZED", "A student may only cancel a send.")
        registration = core.get("exam_registrations", score["exam_registration_id"])
        if registration is None or registration["student_id"] != actor:
            fail("ERR_UNAUTHORIZED", "The send does not belong to the acting student.")

    if payload.get("fees_paid_cents") is not None:
        send["_fees_paid_cents"] = int_field(payload, "fees_paid_cents", minimum=0)

    if to_status == "SENT":
        if score["status"] != "RELEASED":
            fail("ERR_INVALID_STATE", "The score has not been released.")
        if send["recipient_type"] == "COLLEGE":
            registration = core.get("exam_registrations", score["exam_registration_id"])
            order = core.get("exam_orders", registration["exam_order_id"]) if registration else None
            if order is None or send["designation_year"] != order["administration_year"]:
                fail("ERR_INVALID_STATE",
                     "The designation year must match the exam's administration year.")
        if (send.get("_fees_paid_cents") or 0) < send["fee_cents"]:
            fail("ERR_SEND_FEE_UNPAID")
        send["status"] = "SENT"
        core.touch(send)

    elif to_status == "ACKNOWLEDGED":
        send["status"] = "ACKNOWLEDGED"
        core.touch(send)

    elif to_status == "FAILED":
        if _recipient_resolves(send):
            fail("ERR_INVALID_STATE", "The recipient code resolves to a known recipient.")
        send["status"] = "FAILED"
        core.touch(send)

    elif to_status == "CANCELLED":
        if send["status"] == "PENDING":
            deadline = clock.later(
                clock.shift_days(clock.parse_instant(send["created_at"]), SEND_CANCEL_WINDOW_DAYS),
                clock.parse_instant("2027-07-31T23:59:59Z"))
            if clock.now() > deadline:
                fail("ERR_INVALID_STATE", "The send cancellation window has closed.")
        else:
            if score["status"] not in ("WITHHELD", "INVALIDATED"):
                fail("ERR_INVALID_STATE",
                     "A dispatched send is only cancelled by a withheld or invalidated score.")
        send["status"] = "CANCELLED"
        send["credit_back_cents"] = send["fee_cents"]
        core.touch(send)

    school = _school_of_score(score)
    if school is not None:
        cascades.recompute_designation_slots(school["id"])
    return ok(serialize("score_sends", send))
