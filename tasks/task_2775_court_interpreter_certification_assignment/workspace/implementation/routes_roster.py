"""The roster: enrolment, ethics training and quality scores (PRD 3.2)."""
from flask import Blueprint, request

import derive
import serializers as S
from auth import require
from envelope import array_response, object_response, paginate, read_pagination
from errors import ApiError
from store import db, new_row, touch
from util import fmt_date
from validation import (
    UPPER3,
    bool_field,
    body_of,
    date_field,
    query_enum,
    query_str,
    str_field,
)

bp = Blueprint("roster", __name__)

ROSTER_STATUSES = (
    "APPLICANT",
    "CANDIDATE",
    "ACTIVE",
    "SUSPENDED",
    "INACTIVE",
    "REVOKED",
)
TIER_FILTER = ("MASTER", "CERTIFIED", "REGISTERED", "PROVISIONAL", "NONE")


@bp.route("/interpreters", methods=["POST"])
def create_interpreter():
    require("CredentialingOfficer", "ProgramAdmin")
    body = body_of(request)
    full_name = str_field(body, "full_name")
    email = str_field(body, "email")
    phone = str_field(body, "phone", required=False, default=None)
    home_county_code = str_field(
        body, "home_county_code", pattern=UPPER3, label="three uppercase letters"
    )
    accepts_in_person = bool_field(body, "accepts_in_person", required=False, default=True)
    accepts_remote = bool_field(body, "accepts_remote", required=False, default=True)

    for existing in db.interpreters.values():
        if existing["email"] == email:
            raise ApiError(
                "ERR_DUPLICATE_INTERPRETER_EMAIL",
                "That email address is already enrolled.",
            )

    row = new_row()
    row.update(
        {
            "full_name": full_name,
            "email": email,
            "phone": phone,
            "home_county_code": home_county_code,
            "accepts_in_person": accepts_in_person,
            "accepts_remote": accepts_remote,
            "roster_status": "APPLICANT",
            "ethics_training_status": "NOT_STARTED",
            "ethics_completed_on": None,
            "suspension_through": None,
        }
    )
    db.interpreters[row["id"]] = row
    return object_response(S.interpreter_out(row), 201)


@bp.route("/interpreters", methods=["GET"])
def list_interpreters():
    require(
        "ProgramAdmin",
        "CredentialingOfficer",
        "SchedulingCoordinator",
        "FiscalOfficer",
        "QualityReviewer",
    )
    limit, offset = read_pagination(request.args)
    roster_status = query_enum(request.args, "roster_status", ROSTER_STATUSES)
    credential_tier = query_enum(request.args, "credential_tier", TIER_FILTER)
    language_id = query_str(request.args, "language_id")
    home_county_code = query_str(request.args, "home_county_code")

    rows = []
    for row in db.interpreters.values():
        if roster_status is not None and row["roster_status"] != roster_status:
            continue
        if credential_tier is not None and derive.credential_tier(row["id"]) != credential_tier:
            continue
        if language_id is not None and language_id not in derive.credentialed_language_ids(
            row["id"]
        ):
            continue
        if home_county_code is not None and row["home_county_code"] != home_county_code:
            continue
        rows.append(row)
    rows = sorted(rows, key=lambda r: (r["full_name"], r["created_at"], r["_seq"]))
    page, total = paginate(rows, limit, offset)
    return array_response([S.interpreter_out(r) for r in page], limit, offset, total)


@bp.route("/interpreters/<interpreter_id>", methods=["GET"])
def get_interpreter(interpreter_id):
    require(
        "ProgramAdmin",
        "CredentialingOfficer",
        "SchedulingCoordinator",
        "FiscalOfficer",
        "QualityReviewer",
        "Interpreter",
    )
    row = derive.get_interpreter(interpreter_id)
    return object_response(S.interpreter_out(row))


@bp.route("/interpreters/<interpreter_id>/ethics-training", methods=["POST"])
def record_ethics_training(interpreter_id):
    require("CredentialingOfficer", "ProgramAdmin")
    body = body_of(request)
    completed_on = date_field(body, "completed_on")
    str_field(body, "provider")

    row = derive.get_interpreter(interpreter_id)
    row["ethics_training_status"] = "COMPLETED"
    row["ethics_completed_on"] = fmt_date(completed_on)
    touch(row)
    return object_response(S.interpreter_out(row))


@bp.route("/interpreters/<interpreter_id>/quality-score", methods=["GET"])
def get_quality_score(interpreter_id):
    require("ProgramAdmin", "QualityReviewer", "SchedulingCoordinator", "Interpreter")
    row = derive.get_interpreter(interpreter_id)
    recent, older = derive.quality_points(row["id"])
    rolling, lifetime = derive.quality_scores(row["id"])
    return object_response(
        {
            "interpreter_id": row["id"],
            "rolling_12_month_score": rolling,
            "lifetime_score": lifetime,
            "complaint_points": derive.complaint_points(row["id"]),
            "recent_points": recent,
            "older_points": older,
        }
    )
