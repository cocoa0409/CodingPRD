"""Outcome records: amendment and voiding (PRD 3.10)."""

from datetime import timedelta
from body import body
from bp import api
from clock import AMENDMENT_WINDOW_DAYS, parse_dt
from db import db
from errors import APIError
from helpers import (
    recompute_clinic_quality,
    recompute_member,
)
from listing import apply_filters, ordered, paginate
from middleware import resolve_actor
from response import ok
from serializers import serialize


def outcome_record(record_id):
    row = db.find("outcome_records", record_id)
    if row is None:
        raise APIError("ERR_NOT_FOUND", "The outcome record does not resolve.")
    return row


@api.route("/outcome-records/<record_id>", methods=["GET"])
def get_outcome_record(record_id):
    resolve_actor()
    row = outcome_record(record_id)
    return ok(serialize("outcome_records", row))


@api.route("/outcome-records", methods=["GET"])
def list_outcome_records():
    resolve_actor()
    rows = ordered(db.all("outcome_records"))
    rows = apply_filters(rows, {
        "clinic_id": "clinic_id",
        "treatment_cycle_id": "treatment_cycle_id",
        "member_id": "member_id",
        "outcome_status": "outcome_status",
    })
    return paginate(rows, "outcome_records")


@api.route("/outcome-records/<record_id>/amend", methods=["POST"])
def amend_outcome(record_id):
    resolve_actor()
    row = outcome_record(record_id)
    data = body()

    # Priority 5: the declared-state rule.
    if row["outcome_status"] != "RECORDED":
        if row["outcome_status"] == "AMENDED":
            raise APIError("ERR_DUPLICATE_OPERATION", "The record has already been amended.")
        raise APIError("ERR_INVALID_STATE", "The record is not RECORDED.")

    # Priority 16: the amendment window.
    recorded_on = parse_dt(row["outcome_recorded_on"])
    if db.now() >= recorded_on + timedelta(days=AMENDMENT_WINDOW_DAYS):
        raise APIError("ERR_AMENDMENT_WINDOW_CLOSED", "The amendment window has closed.")

    if "live_birth" in data and data["live_birth"] is not None:
        row["live_birth"] = bool(data["live_birth"])
    if "births_count" in data and data["births_count"] is not None:
        row["births_count"] = data["births_count"]
    if "multiple_birth" in data and data["multiple_birth"] is not None:
        row["multiple_birth"] = bool(data["multiple_birth"])
    if "gestational_weeks" in data and data["gestational_weeks"] is not None:
        row["gestational_weeks"] = data["gestational_weeks"]
    row["amendment_reason"] = data.get("amendment_reason")
    row["outcome_status"] = "AMENDED"
    db.touch(row)

    clinic = db.find("clinics", row["clinic_id"])
    if clinic is not None:
        from routes.clinics import _apply_posture
        recompute_clinic_quality(db, clinic)
        _apply_posture(clinic)
        db.touch(clinic)

    member = db.find("members", row["member_id"])
    if member is not None:
        recompute_member(db, member)
    return ok(serialize("outcome_records", row))


@api.route("/outcome-records/<record_id>/void", methods=["POST"])
def void_outcome(record_id):
    resolve_actor()
    row = outcome_record(record_id)
    data = body()

    if row["outcome_status"] == "VOIDED":
        raise APIError("ERR_DUPLICATE_OPERATION", "The record has already been voided.")
    if row["outcome_status"] not in ("RECORDED", "AMENDED"):
        raise APIError("ERR_INVALID_STATE", "The record is not RECORDED or AMENDED.")

    # A record that already supports a paid claim cannot be erased.
    for claim in db.all("claims"):
        if claim.get("treatment_cycle_id") == row["treatment_cycle_id"] and claim["claim_status"] == "PAID":
            raise APIError("ERR_INVALID_STATE", "A paid claim references this record's cycle.")

    row["outcome_status"] = "VOIDED"
    row["void_reason"] = data.get("void_reason")
    row["amendment_reason"] = None
    db.touch(row)

    clinic = db.find("clinics", row["clinic_id"])
    if clinic is not None:
        from routes.clinics import _apply_posture
        recompute_clinic_quality(db, clinic)
        _apply_posture(clinic)
        db.touch(clinic)

    member = db.find("members", row["member_id"])
    if member is not None:
        recompute_member(db, member)
    return ok(serialize("outcome_records", row))