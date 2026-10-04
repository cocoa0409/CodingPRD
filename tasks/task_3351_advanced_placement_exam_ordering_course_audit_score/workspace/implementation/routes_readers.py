"""Reader recruitment, calibration and the reader's nested reads."""

from flask import request

import auth
import calc
import cascades
import core
from constants import CALIBRATION_PASS_THRESHOLD, MIN_CALIBRATION_SAMPLES, READER_LOAD_CAP, \
    READER_RELIABILITY_FLOOR
from core import app, body, insert, number_field, require, rows, str_field
from entities import make, serialize
from errors import fail
from response import list_response, ok
from validation import transition_gate


@app.route("/ap-program/readers", methods=["POST"])
def create_reader():
    auth.authenticate(["ScoringSpecialist"])
    payload = body()
    full_name = str_field(payload, "full_name")
    subject_expertise = str_field(payload, "subject_expertise")
    reader = insert("readers", make(
        "readers",
        full_name=full_name,
        subject_expertise=subject_expertise,
        calibration_sample_count=0,
        calibration_agreement_rate=0.0,
    ))
    return ok(serialize("readers", reader), status=201)


@app.route("/ap-program/readers/<rid>", methods=["GET"])
def read_reader(rid):
    auth.authenticate(["PlatformAdmin", "ScoringSpecialist", "Reader"])
    return ok(serialize("readers", require("readers", rid)))


@app.route("/ap-program/readers/<rid>/calibration-summary", methods=["GET"])
def read_reader_summary(rid):
    auth.authenticate(["PlatformAdmin", "ScoringSpecialist", "Reader"])
    reader = require("readers", rid)
    return ok({
        "calibration_index": reader["calibration_index"],
        "reliability_index": reader["reliability_index"],
        "calibration_round_count": reader["calibration_round_count"],
        "load_status": reader["load_status"],
        "pass_threshold_met": reader["calibration_index"] >= CALIBRATION_PASS_THRESHOLD,
    })


@app.route("/ap-program/readers/<rid>/exam-scores", methods=["GET"])
def list_reader_scores(rid):
    auth.authenticate(["PlatformAdmin", "ScoringSpecialist", "Reader"])
    require("readers", rid)
    matching = [s for s in rows("exam_scores") if s["reader_id"] == rid]
    matching.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return list_response(matching, request.args, lambda r: serialize("exam_scores", r))


@app.route("/ap-program/readers/<rid>/status-transitions", methods=["POST"])
def transition_reader(rid):
    role, actor = auth.authenticate(["ScoringSpecialist", "PlatformAdmin", "Reader"])
    payload = body()
    reader, to_status = transition_gate("readers", rid, payload, actor=actor)

    if to_status == "CALIBRATING" and role == "Reader" and actor != reader["id"]:
        fail("ERR_UNAUTHORIZED", "A reader may only drive its own calibration.")
    if role == "Reader" and to_status != "CALIBRATING":
        fail("ERR_UNAUTHORIZED", "A reader may only drive its own calibration.")
    if to_status == "INACTIVE" and role != "PlatformAdmin":
        fail("ERR_UNAUTHORIZED", "Only a PlatformAdmin may retire a reader.")

    if payload.get("calibration_sample_count") is not None:
        reader["calibration_sample_count"] = number_field(
            payload, "calibration_sample_count", minimum=0, maximum=40)
        reader["calibration_sample_count"] = int(reader["calibration_sample_count"])
    if payload.get("calibration_agreement_rate") is not None:
        reader["calibration_agreement_rate"] = number_field(
            payload, "calibration_agreement_rate", minimum=0.0, maximum=1.0)
    if payload.get("calibration_index") is not None:
        reader["calibration_index"] = number_field(
            payload, "calibration_index", minimum=0.0, maximum=1.0)

    if to_status == "CALIBRATING":
        if reader["calibration_status"] == "DEMOTED" and payload.get("calibration_agreement_rate") is None \
                and payload.get("calibration_sample_count") is None:
            fail("ERR_INVALID_STATE", "A demoted reader needs a new calibration pass.")
        reader["calibration_status"] = "CALIBRATING"
        core.touch(reader)

    elif to_status == "CALIBRATED":
        if reader["calibration_sample_count"] < MIN_CALIBRATION_SAMPLES:
            fail("ERR_INVALID_STATE", "The calibration pass scored too few papers.")
        if reader["calibration_agreement_rate"] < READER_RELIABILITY_FLOOR:
            fail("ERR_INVALID_STATE", "The calibration agreement rate is below the floor.")
        reader["calibration_round_count"] = reader["calibration_round_count"] + 1
        reader["reliability_index"] = reader["calibration_agreement_rate"]
        reader["calibration_index"] = calc.calibration_index_weighted(
            reader["calibration_sample_count"], reader["calibration_agreement_rate"])
        reader["calibration_status"] = "CALIBRATED"
        reader["load_status"] = "AT_CAPACITY" if reader["assigned_score_count"] >= READER_LOAD_CAP \
            else "AVAILABLE"
        core.touch(reader)
        cascades.refresh_reader_reliability(reader)

    elif to_status == "RECRUITED":
        if reader["calibration_index"] >= CALIBRATION_PASS_THRESHOLD:
            fail("ERR_INVALID_STATE", "The calibration index has already cleared the threshold.")
        reader["calibration_status"] = "RECRUITED"
        core.touch(reader)

    elif to_status == "DEMOTED":
        rate = payload.get("calibration_agreement_rate")
        if rate is None or float(rate) >= READER_RELIABILITY_FLOOR:
            fail("ERR_INVALID_STATE", "Demotion requires an agreement rate below the floor.")
        reader["reliability_index"] = reader["calibration_agreement_rate"]
        reader["load_status"] = "DEMOTED"
        reader["calibration_status"] = "DEMOTED"
        core.touch(reader)
        cascades.refresh_reader_reliability(reader)
        for score in rows("exam_scores"):
            if score["reader_id"] != reader["id"] or score["status"] != "RUBRIC_PENDING":
                continue
            replacement = calc.select_reader(
                core.require("exam_registrations", score["exam_registration_id"])["exam_subject"],
                exclude_reader_ids=[reader["id"]])
            if replacement is not None:
                score["reader_id"] = replacement["id"]
                score["reader_reliability_index"] = replacement["reliability_index"]
                core.touch(score)

    elif to_status == "INACTIVE":
        if reader["assigned_score_count"] != 0:
            fail("ERR_INVALID_STATE", "The reader still carries assigned scores.")
        reader["calibration_status"] = "INACTIVE"
        reader["load_status"] = "INACTIVE"
        core.touch(reader)

    return ok(serialize("readers", reader))
