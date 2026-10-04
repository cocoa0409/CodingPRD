"""Applicants: create, list, fetch, center assignment, per-applicant cases."""
from flask import Blueprint

from auth import authenticate, require_role, ALL_ROLES
from db import STORE, new_record, bump
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_STALE_VERSION,
    ERR_INVALID_STATE,
    ERR_APPLICANT_NOT_ELIGIBLE,
    ERR_NO_ELIGIBLE_CENTER,
)
from helpers import (
    get_body,
    check_unknown,
    as_str,
    as_date,
    as_int,
    as_bool,
    pagination_params,
    paginate,
)
import domain
import serializers

bp = Blueprint("applicants", __name__)


def get_applicant_or_404(applicant_id):
    a = STORE.applicants.get(applicant_id)
    if a is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Applicant not found")
    return a


@bp.route("/jc/applicants", methods=["POST"])
def create_applicant():
    user_id, role = authenticate()
    require_role(role, {"AdmissionsCounselor"})
    body = get_body()
    check_unknown(body, {"full_name", "date_of_birth", "home_region_code", "desired_trade_code"})
    rec = new_record()
    rec.update(
        {
            "full_name": as_str(body, "full_name", required=True),
            "date_of_birth": as_date(body, "date_of_birth", required=True),
            "home_region_code": as_str(body, "home_region_code", required=True),
            "desired_trade_code": as_str(body, "desired_trade_code", required=True),
            "assigned_center_id": None,
            "assignment_status": "NONE",
        }
    )
    STORE.applicants[rec["id"]] = rec
    return ok_object(serializers.applicant_view(rec), status=201)


@bp.route("/jc/applicants", methods=["GET"])
def list_applicants():
    user_id, role = authenticate()
    require_role(
        role,
        {"AdmissionsCounselor", "EligibilityReviewer", "EnrollmentManager", "OperatorAdmin"},
    )
    limit, offset = pagination_params()
    items = list(STORE.applicants.values())
    f_center = _q("assigned_center_id")
    f_status = _q("assignment_status")
    if f_center is not None:
        items = [a for a in items if a["assigned_center_id"] == f_center]
    if f_status is not None:
        items = [a for a in items if a["assignment_status"] == f_status]
    items.sort(key=lambda a: a["_seq"])
    page, meta = paginate([serializers.applicant_view(a) for a in items], limit, offset)
    return ok_list(page, meta)


def _q(name):
    from flask import request

    return request.args.get(name)


@bp.route("/jc/applicants/<applicant_id>", methods=["GET"])
def get_applicant(applicant_id):
    user_id, role = authenticate()
    require_role(role, ALL_ROLES)
    a = get_applicant_or_404(applicant_id)
    return ok_object(serializers.applicant_view(a))


@bp.route("/jc/applicants/<applicant_id>/applications", methods=["GET"])
def list_applicant_applications(applicant_id):
    user_id, role = authenticate()
    require_role(role, {"AdmissionsCounselor", "EligibilityReviewer", "OperatorAdmin"})
    a = get_applicant_or_404(applicant_id)
    limit, offset = pagination_params()
    items = [ap for ap in STORE.applications.values() if ap["applicant_id"] == a["id"]]
    # Documented exception to the default sort: newest first.
    items.sort(key=lambda ap: -ap["_seq"])
    page, meta = paginate([serializers.application_view(ap) for ap in items], limit, offset)
    return ok_list(page, meta)


@bp.route("/jc/applicants/<applicant_id>/center-assignment", methods=["POST"])
def center_assignment(applicant_id):
    user_id, role = authenticate()
    require_role(role, {"AdmissionsCounselor"})
    a = get_applicant_or_404(applicant_id)
    body = get_body()
    check_unknown(body, {"expected_applicant_version", "residential_track"})
    expected_version = as_int(body, "expected_applicant_version", required=True)
    residential_track = as_bool(body, "residential_track", required=True)
    # Priority 6: optimistic concurrency on the applicant.
    if expected_version != a["version"]:
        raise ApiError(
            ERR_STALE_VERSION[0],
            ERR_STALE_VERSION[1],
            "expected_applicant_version does not match the applicant's current version",
        )
    # Priority 8: assignment is undefined from ENROLLED.
    if a["assignment_status"] == "ENROLLED":
        raise ApiError(
            ERR_INVALID_STATE[0],
            ERR_INVALID_STATE[1],
            "An actively enrolled applicant cannot be reassigned",
        )
    # Eligibility gate (PRD 3.2): an ELIGIBLE case must be on file.
    eligible = any(
        ap["applicant_id"] == a["id"] and ap["status"] == "ELIGIBLE"
        for ap in STORE.applications.values()
    )
    if not eligible:
        raise ApiError(
            ERR_APPLICANT_NOT_ELIGIBLE[0],
            ERR_APPLICANT_NOT_ELIGIBLE[1],
            "Applicant has no ELIGIBLE application on file",
        )
    ranked = domain.rank_centers(a, residential_track)
    if not ranked:
        raise ApiError(
            ERR_NO_ELIGIBLE_CENTER[0],
            ERR_NO_ELIGIBLE_CENTER[1],
            "Center assignment produced an empty candidate pool",
        )
    winner = ranked[0]
    a["assigned_center_id"] = winner["center"]["id"]
    a["assignment_status"] = "ASSIGNED"
    bump(a)
    data = {
        "assignment_status": a["assignment_status"],
        "assigned_center_id": a["assigned_center_id"],
        "assigned_center_score": float(winner["score"]),
        "ranked_candidates": [
            {
                "center_id": r["center"]["id"],
                "score": float(r["score"]),
                "trade_points": r["trade_points"],
                "capacity_points": r["capacity_points"],
                "geo_points": r["geo_points"],
                "beds_available": r["beds_available"],
            }
            for r in ranked
        ],
    }
    return ok_object(data, status=200)
