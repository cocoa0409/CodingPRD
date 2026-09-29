"""Circulator registration lifecycle and circulation assignments."""

from datetime import timedelta

from flask import Blueprint

import response
import validation as v
from db import (APPROVED_TRAINING_COURSES, ASSIGNMENT_BUFFER_DAYS, db,
                fmt_instant, get_assignment, get_circulator, get_county,
                get_petition, new_resource, now, serialize, touch)
from errors import ApiError
from middleware import (require_auth, require_circulator_self,
                        require_petition_owner)
from services import calculations as calc
from services import cascades

READ_ROLES = ("SosAdmin", "ElectionsExaminer", "Proponent", "CountyClerk",
              "CirculatorAgent")

bp = Blueprint("circulators", __name__)


def recompute_paid_disclosure(circulator):
    if not circulator["is_paid"]:
        circulator["paid_disclosure_on_file"] = True
    else:
        circulator["paid_disclosure_on_file"] = bool(
            circulator["employer_name"] and circulator["disclosure_document_id"])


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------
@bp.route("/circulators", methods=["POST"])
def create_circulator():
    require_auth(["SosAdmin", "Proponent"])
    body = v.body()
    full_name = v.as_string(v.required(body, "full_name"), "full_name")
    residency_state_code = v.as_string(v.required(body, "residency_state_code"),
                                       "residency_state_code", exact_len=2, upper=True)
    is_paid = v.as_bool(v.optional(body, "is_paid", False), "is_paid")
    employer_name = v.optional(body, "employer_name")
    if employer_name is not None:
        employer_name = v.as_string(employer_name, "employer_name")
    circulator = new_resource({
        "full_name": full_name,
        "residency_state_code": residency_state_code,
        "is_paid": is_paid,
        "employer_name": employer_name,
        "disclosure_document_id": None,
        "paid_disclosure_on_file": True,
        "registration_status": "PENDING_TRAINING",
        "training_course_code": None,
        "training_completed_at": None,
        "affidavit_filed_at": None,
        "misconduct_strike_count": 0,
        "credibility_score_bps": 10000,
    })
    recompute_paid_disclosure(circulator)
    db.circulators[circulator["id"]] = circulator
    return response.single(serialize(circulator), 201)


@bp.route("/circulators/<circulator_id>", methods=["GET"])
def read_circulator(circulator_id):
    require_auth(READ_ROLES)
    return response.single(serialize(get_circulator(circulator_id)))


@bp.route("/circulators", methods=["GET"])
def list_circulators():
    require_auth(READ_ROLES)
    return response.listing(list(db.circulators.values()), {
        "registration_status": ("str", "registration_status"),
        "is_paid": ("bool", "is_paid"),
    })


@bp.route("/circulators/<circulator_id>/training", methods=["POST"])
def record_training(circulator_id):
    user_id, role = require_auth(["SosAdmin", "CirculatorAgent"])
    body = v.body()
    course_code = v.as_string(v.required(body, "training_course_code"),
                              "training_course_code")
    circulator = get_circulator(circulator_id)
    require_circulator_self(circulator, user_id, role)
    if circulator["registration_status"] != "PENDING_TRAINING":
        raise ApiError("ERR_INVALID_CIRCULATOR_STATE")
    if course_code not in APPROVED_TRAINING_COURSES:
        raise ApiError("ERR_TRAINING_COURSE_NOT_APPROVED")
    circulator["training_course_code"] = course_code
    circulator["training_completed_at"] = fmt_instant(now())
    circulator["registration_status"] = "TRAINED"
    touch(circulator)
    return response.single(serialize(circulator))


@bp.route("/circulators/<circulator_id>/paid-disclosure", methods=["PUT"])
def record_paid_disclosure(circulator_id):
    user_id, role = require_auth(["SosAdmin", "CirculatorAgent"])
    body = v.body()
    disclosure_document_id = v.as_string(v.required(body, "disclosure_document_id"),
                                         "disclosure_document_id")
    employer_name = v.optional(body, "employer_name")
    if employer_name is not None:
        employer_name = v.as_string(employer_name, "employer_name")
    circulator = get_circulator(circulator_id)
    require_circulator_self(circulator, user_id, role)
    circulator["disclosure_document_id"] = disclosure_document_id
    if employer_name is not None:
        circulator["employer_name"] = employer_name
    recompute_paid_disclosure(circulator)
    touch(circulator)
    return response.single(serialize(circulator))


@bp.route("/circulators/<circulator_id>/affidavit", methods=["POST"])
def file_affidavit(circulator_id):
    user_id, role = require_auth(["CirculatorAgent", "SosAdmin"])
    body = v.body()
    sworn = v.as_bool(v.required(body, "sworn"), "sworn")
    circulator = get_circulator(circulator_id)
    require_circulator_self(circulator, user_id, role)
    if circulator["registration_status"] != "TRAINED":
        raise ApiError("ERR_TRAINING_NOT_COMPLETE")
    if not circulator["paid_disclosure_on_file"]:
        raise ApiError("ERR_PAID_DISCLOSURE_MISSING")
    if not sworn:
        raise ApiError("ERR_AFFIDAVIT_NOT_SWORN")
    circulator["affidavit_filed_at"] = fmt_instant(now())
    circulator["registration_status"] = "REGISTERED"
    touch(circulator)
    return response.single(serialize(circulator))


@bp.route("/circulators/<circulator_id>/suspend", methods=["POST"])
def suspend_circulator(circulator_id):
    require_auth(["SosAdmin"])
    body = v.body()
    if "reason" in body and body["reason"] is not None:
        v.as_string(body["reason"], "reason")
    circulator = get_circulator(circulator_id)
    if circulator["registration_status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_CIRCULATOR_STATE")
    circulator["registration_status"] = "SUSPENDED"
    cascades.suspend_active_assignments(circulator)
    touch(circulator)
    return response.single(serialize(circulator))


@bp.route("/circulators/<circulator_id>/reinstate", methods=["POST"])
def reinstate_circulator(circulator_id):
    require_auth(["SosAdmin"])
    v.body()
    circulator = get_circulator(circulator_id)
    if circulator["registration_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_CIRCULATOR_STATE")
    if circulator["misconduct_strike_count"] >= 1:
        raise ApiError("ERR_CIRCULATOR_REINSTATEMENT_BARRED")
    circulator["registration_status"] = "REGISTERED"
    cascades.reactivate_suspended_assignments(circulator)
    touch(circulator)
    return response.single(serialize(circulator))


@bp.route("/circulators/<circulator_id>/revoke", methods=["POST"])
def revoke_circulator(circulator_id):
    require_auth(["SosAdmin"])
    body = v.body()
    if "reason" in body and body["reason"] is not None:
        v.as_string(body["reason"], "reason")
    circulator = get_circulator(circulator_id)
    if circulator["registration_status"] == "REVOKED":
        raise ApiError("ERR_INVALID_CIRCULATOR_STATE")
    circulator["registration_status"] = "REVOKED"
    cascades.revoke_cascade(circulator)
    calc.recompute_credibility(circulator)
    touch(circulator)
    return response.single(serialize(circulator))


# ---------------------------------------------------------------------------
# circulation assignments
# ---------------------------------------------------------------------------
@bp.route("/circulation-assignments", methods=["POST"])
def create_assignment():
    user_id, role = require_auth(["SosAdmin", "Proponent"])
    body = v.body()
    petition_id = v.as_id(v.required(body, "petition_id"), "petition_id")
    circulator_id = v.as_id(v.required(body, "circulator_id"), "circulator_id")
    effective_from, effective_from_dt = v.as_instant(
        v.required(body, "effective_from"), "effective_from")
    effective_to, effective_to_dt = v.as_instant(
        v.required(body, "effective_to"), "effective_to")
    county_codes = v.as_str_array(v.required(body, "assigned_county_codes"),
                                  "assigned_county_codes", min_items=1, max_items=10)
    expected_version = v.as_int(v.required(body, "expected_circulator_version"),
                                "expected_circulator_version")
    paid_disclosure_ack = v.as_bool(v.optional(body, "paid_disclosure_ack", False),
                                    "paid_disclosure_ack")
    if effective_to_dt <= effective_from_dt:
        raise ApiError("ERR_INVALID_REQUEST",
                       "effective_to must be strictly after effective_from")

    petition = get_petition(petition_id)
    circulator = get_circulator(circulator_id)
    known_codes = {c["county_code"] for c in db.counties.values()}
    for code in county_codes:
        if code not in known_codes:
            raise ApiError("ERR_COUNTY_NOT_FOUND")

    require_petition_owner(petition, user_id, role)

    if expected_version != circulator["version"]:
        raise ApiError("ERR_STALE_CIRCULATOR_VERSION")
    if circulator["registration_status"] != "REGISTERED":
        raise ApiError("ERR_INVALID_CIRCULATOR_STATE")

    buffer = timedelta(days=ASSIGNMENT_BUFFER_DAYS)
    for existing in db.assignments.values():
        if existing["circulator_id"] != circulator["id"]:
            continue
        if existing["status"] not in ("ACTIVE", "SUSPENDED"):
            continue
        if (effective_from_dt - existing["_effective_to_dt"]) < buffer \
                and (existing["_effective_from_dt"] - effective_to_dt) < buffer:
            raise ApiError("ERR_ASSIGNMENT_WINDOW_CONFLICT")

    assignment = new_resource({
        "petition_id": petition["id"],
        "circulator_id": circulator["id"],
        "effective_from": effective_from,
        "effective_to": effective_to,
        "assigned_county_codes": county_codes,
        "paid_disclosure_ack": paid_disclosure_ack,
        "status": "ACTIVE",
        "_effective_from_dt": effective_from_dt,
        "_effective_to_dt": effective_to_dt,
    })
    db.assignments[assignment["id"]] = assignment
    touch(circulator)
    return response.single(serialize(assignment), 201)


@bp.route("/circulation-assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    require_auth(READ_ROLES)
    return response.single(serialize(get_assignment(assignment_id)))


@bp.route("/circulation-assignments", methods=["GET"])
def list_assignments():
    require_auth(READ_ROLES)
    return response.listing(list(db.assignments.values()), {
        "petition_id": ("str", "petition_id"),
        "circulator_id": ("str", "circulator_id"),
        "status": ("str", "status"),
    })


@bp.route("/circulation-assignments/<assignment_id>/terminate", methods=["POST"])
def terminate_assignment(assignment_id):
    user_id, role = require_auth(["SosAdmin", "Proponent"])
    body = v.body()
    if "reason" in body and body["reason"] is not None:
        v.as_string(body["reason"], "reason")
    assignment = get_assignment(assignment_id)
    petition = db.petitions.get(assignment["petition_id"])
    if petition is not None:
        require_petition_owner(petition, user_id, role)
    if assignment["status"] not in ("ACTIVE", "SUSPENDED"):
        raise ApiError("ERR_INVALID_PETITION_STATE")
    assignment["status"] = "TERMINATED"
    touch(assignment)
    return response.single(serialize(assignment))
