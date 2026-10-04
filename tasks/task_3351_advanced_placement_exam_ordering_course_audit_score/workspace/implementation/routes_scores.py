"""Exam scores: creation, the score machine and its cascades."""

import auth
import calc
import cascades
import clock
import core
from constants import CALIBRATION_PASS_THRESHOLD, CANCELLATION_DEADLINE_UTC, RAW_COMPOSITE_MAX, \
    RAW_COMPOSITE_MIN, READER_LOAD_CAP, READER_RELIABILITY_FLOOR
from core import app, body, bool_field, insert, number_field, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import ok
from validation import require_fk, transition_gate


def _deadline_passed():
    return clock.now() >= clock.parse_instant(CANCELLATION_DEADLINE_UTC)


def _apply_request_flags(score, payload):
    if "request_withholding" in payload:
        score["_withholding_requested"] = bool_field(payload, "request_withholding", False)
    if "request_cancellation" in payload:
        score["_cancellation_requested"] = bool_field(payload, "request_cancellation", False)


@app.route("/ap-program/exam-scores", methods=["POST"])
def create_exam_score():
    auth.authenticate(["ScoringSpecialist"])
    payload = body()
    exam_registration_id = str_field(payload, "exam_registration_id")
    raw_composite = number_field(payload, "raw_composite",
                                 minimum=RAW_COMPOSITE_MIN, maximum=RAW_COMPOSITE_MAX)
    registration = require_fk("exam_registrations", exam_registration_id, "exam_registration_id")
    if registration["status"] != "MATERIAL_ASSIGNED":
        fail("ERR_INVALID_STATE", "The registration has not reached material assignment.")
    reader_id = payload.get("reader_id")
    if reader_id is not None:
        reader = require_fk("readers", reader_id, "reader_id")
    else:
        reader = calc.select_reader(registration["exam_subject"])
        if reader is None:
            fail("ERR_NO_ELIGIBLE_READER")
    score = insert("exam_scores", make(
        "exam_scores",
        exam_registration_id=exam_registration_id,
        raw_composite=raw_composite,
        reader_id=reader["id"],
        reader_reliability_index=reader["reliability_index"],
    ))
    score["_withholding_requested"] = False
    score["_cancellation_requested"] = False
    cascades.recompute_assigned_scores(reader)
    return ok(serialize("exam_scores", score), status=201)


@app.route("/ap-program/exam-scores/<rid>", methods=["GET"])
def read_exam_score(rid):
    auth.authenticate(["PlatformAdmin", "ScoringSpecialist", "SchoolCoordinator"])
    return ok(serialize("exam_scores", require("exam_scores", rid)))


@app.route("/ap-program/exam-scores/<rid>/status-transitions", methods=["POST"])
def transition_exam_score(rid):
    role, actor = auth.authenticate(["ScoringSpecialist", "PlatformAdmin"])
    payload = body()
    score, to_status = transition_gate(
        "exam_scores", rid, payload, occ_field="expected_exam_score_version", actor=actor)
    _apply_request_flags(score, payload)
    registration = core.require("exam_registrations", score["exam_registration_id"])
    reader = core.get("readers", score["reader_id"]) if score["reader_id"] else None

    if to_status == "RUBRIC_PENDING":
        if registration["status"] != "MATERIAL_ASSIGNED":
            fail("ERR_INVALID_STATE", "The registration is not material-assigned.")
        if reader is None:
            fail("ERR_NO_ELIGIBLE_READER")
        if reader["calibration_status"] != "CALIBRATED":
            fail("ERR_INVALID_STATE", "The assigned reader is not calibrated.")
        if reader["calibration_index"] < CALIBRATION_PASS_THRESHOLD:
            fail("ERR_INVALID_STATE", "The assigned reader has not cleared the calibration threshold.")
        score["status"] = "RUBRIC_PENDING"
        core.touch(score)
        cascades.recompute_assigned_scores(reader)
        if reader["assigned_score_count"] >= READER_LOAD_CAP:
            reader["load_status"] = "AT_CAPACITY"

    elif to_status == "AGGREGATED":
        if score["raw_composite"] is None or score["raw_composite"] < 0.0 \
                or score["raw_composite"] > 120.0:
            fail("ERR_INVALID_REQUEST", "raw_composite must lie between 0.0 and 120.0.")
        if reader is None:
            fail("ERR_NO_ELIGIBLE_READER")
        if reader["reliability_index"] < READER_RELIABILITY_FLOOR:
            fail("ERR_READER_RELIABILITY_BELOW_FLOOR")
        if score["status"] == "CANCELLED":
            score["ap_score"] = calc.ap_score_marginal(score["raw_composite"])
        else:
            score["ap_score"] = calc.ap_score_cross_total(score["raw_composite"])
        score["status"] = "AGGREGATED"
        core.touch(score)
        if registration["status"] == "MATERIAL_ASSIGNED":
            registration["status"] = "SCORED"
            core.touch(registration)
        cascades.recompute_assigned_scores(reader)

    elif to_status == "RELEASED":
        if score["release_blocked"]:
            fail("ERR_RELEASE_BLOCKED")
        if clock.now() < calc.score_release_open(registration["id"]):
            fail("ERR_SCORE_RELEASE_TOO_EARLY")
        if registration.get("accommodation_flag") \
                and not cascades.registration_material_assignable(registration):
            fail("ERR_ACCOMMODATION_PROVISION_INCOMPLETE")
        if score["status"] == "WITHHELD" and score.get("_withholding_requested"):
            fail("ERR_INVALID_STATE", "The withholding request has not been withdrawn.")
        score["status"] = "RELEASED"
        core.touch(score)
        if registration["status"] == "SCORED":
            registration["status"] = "SCORE_RELEASED"
            core.touch(registration)
        cascades.recompute_assigned_scores(reader)
        order = core.get("exam_orders", registration["exam_order_id"])
        if order is not None:
            cascades.maybe_auto_deliver(order)

    elif to_status == "WITHHELD":
        if not score.get("_withholding_requested"):
            fail("ERR_INVALID_STATE", "No withholding request is recorded for this score.")
        if score["status"] == "RELEASED" and _deadline_passed():
            fail("ERR_CANCELLATION_DEADLINE_PASSED")
        score["status"] = "WITHHELD"
        core.touch(score)
        _cancel_sends(score)

    elif to_status == "CANCELLED":
        if score["status"] == "RELEASED":
            if not score.get("_cancellation_requested"):
                fail("ERR_INVALID_STATE", "No cancellation request is recorded for this score.")
        else:
            if not score.get("_cancellation_requested"):
                fail("ERR_INVALID_STATE", "No cancellation request is recorded for this score.")
            if _deadline_passed():
                fail("ERR_CANCELLATION_DEADLINE_PASSED")
        score["status"] = "CANCELLED"
        core.touch(score)
        _cancel_sends(score)

    elif to_status == "INVALIDATED":
        if not any(c["exam_registration_id"] == registration["id"] and c["status"] == "CONFIRMED"
                   and c["finding_code"] == "SCORE_INVALIDATION_REQUIRED"
                   for c in rows("irregularity_cases")):
            fail("ERR_INVALID_STATE", "No confirmed invalidation finding exists.")
        score["status"] = "INVALIDATED"
        core.touch(score)
        _cancel_sends(score)

    return ok(serialize("exam_scores", score))


def _cancel_sends(score):
    for send in rows("score_sends"):
        if send["exam_score_id"] != score["id"]:
            continue
        if send["status"] in ("PENDING", "SENT"):
            send["status"] = "CANCELLED"
            send["credit_back_cents"] = send["fee_cents"]
            core.touch(send)
    for send in rows("score_sends"):
        if send["exam_score_id"] == score["id"]:
            cascades.recompute_designation_slots(_school_of_send(send))


def _school_of_send(send):
    score = core.get("exam_scores", send["exam_score_id"])
    if score is None:
        return None
    reg = core.get("exam_registrations", score["exam_registration_id"])
    if reg is None:
        return None
    student = core.get("students", reg["student_id"])
    if student is None:
        return None
    school = core.get("schools", student["school_id"])
    return school["id"] if school else None
