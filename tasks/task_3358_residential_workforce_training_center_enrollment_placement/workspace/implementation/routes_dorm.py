"""Dormitory assignments: create (explicit or auto bed), list, checkout."""
import re

from flask import Blueprint

from auth import authenticate, require_role
from db import STORE, new_record, bump
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_CONDUCT_HOLD,
    ERR_BED_OVERLAP,
    ERR_NO_BED_AVAILABLE,
)
from helpers import get_body, check_unknown, as_str, as_date, pagination_params, paginate
import domain
import serializers

bp = Blueprint("dormitory", __name__)

BED_LABEL_RE = re.compile(r"^B-(\d{2,})$")


def _center_of_enrollment(enrollment):
    program = STORE.trade_programs[enrollment["trade_program_id"]]
    return STORE.centers[program["center_id"]]


def _bed_conflicts(center_id, bed_label, move_in_date):
    """Half-open [move_in_date, move_out_date) overlap against ACTIVE rows on
    the same center+bed. Adjacency (move_in == existing move_out) is allowed."""
    for d in STORE.dormitory_assignments.values():
        if d["status"] != "ACTIVE" or d["bed_label"] != bed_label:
            continue
        e = STORE.enrollments[d["enrollment_id"]]
        center = _center_of_enrollment(e)
        if center["id"] != center_id:
            continue
        if d["move_out_date"] is None or move_in_date < d["move_out_date"]:
            return True
    return False


@bp.route("/jc/dormitory-assignments", methods=["POST"])
def create_dormitory_assignment():
    user_id, role = authenticate()
    require_role(role, {"ResidentialAdvisor"})
    body = get_body()
    check_unknown(body, {"enrollment_id", "move_in_date", "bed_label"})
    enrollment_id = as_str(body, "enrollment_id", required=True)
    move_in_date = as_date(body, "move_in_date", required=True)
    enrollment = STORE.enrollments.get(enrollment_id)
    if enrollment is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    center = _center_of_enrollment(enrollment)
    bed_label = None
    if "bed_label" in body and body["bed_label"] is not None:
        bed_label = as_str(body, "bed_label")
        m = BED_LABEL_RE.match(bed_label)
        if not m or not (1 <= int(m.group(1)) <= center["total_beds"]):
            raise ApiError(
                ERR_INVALID_REQUEST[0],
                ERR_INVALID_REQUEST[1],
                "bed_label must be within B-01..B-{:02d} for this center".format(
                    center["total_beds"]
                ),
            )
    # Priority 8: the enrollment must be waiting for a bed.
    if enrollment["residential_status"] != "AWAITING_BED":
        raise ApiError(
            ERR_INVALID_STATE[0],
            ERR_INVALID_STATE[1],
            "Enrollment is not AWAITING_BED",
        )
    # Priority 9: conduct hold gates dormitory writes.
    domain.recompute_conduct_hold(enrollment["id"])
    if enrollment["conduct_hold"]:
        raise ApiError(
            ERR_CONDUCT_HOLD[0],
            ERR_CONDUCT_HOLD[1],
            "Enrollment conduct_hold is active",
        )
    if bed_label is not None:
        # Priority 15: explicit label overlap.
        if _bed_conflicts(center["id"], bed_label, move_in_date):
            raise ApiError(
                ERR_BED_OVERLAP[0],
                ERR_BED_OVERLAP[1],
                "Requested bed_label is occupied over a colliding interval",
            )
    else:
        # Priority 21: auto-select the lowest-numbered free bed label.
        for n in range(1, center["total_beds"] + 1):
            candidate = "B-{:02d}".format(n)
            if not _bed_conflicts(center["id"], candidate, move_in_date):
                bed_label = candidate
                break
        if bed_label is None:
            raise ApiError(
                ERR_NO_BED_AVAILABLE[0],
                ERR_NO_BED_AVAILABLE[1],
                "Every bed of the center is occupied",
            )
    rec = new_record()
    rec.update(
        {
            "enrollment_id": enrollment["id"],
            "bed_label": bed_label,
            "move_in_date": move_in_date,
            "move_out_date": None,
            "status": "ACTIVE",
        }
    )
    STORE.dormitory_assignments[rec["id"]] = rec
    enrollment["residential_status"] = "RESIDENT"
    bump(enrollment)
    return ok_object(serializers.dormitory_view(rec), status=201)


@bp.route("/jc/enrollments/<enrollment_id>/dormitory-assignments", methods=["GET"])
def list_enrollment_dormitory(enrollment_id):
    user_id, role = authenticate()
    require_role(role, {"ResidentialAdvisor", "EnrollmentManager"})
    e = STORE.enrollments.get(enrollment_id)
    if e is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Enrollment not found")
    limit, offset = pagination_params()
    items = [
        d for d in STORE.dormitory_assignments.values() if d["enrollment_id"] == e["id"]
    ]
    items.sort(key=lambda d: d["_seq"])
    page, meta = paginate([serializers.dormitory_view(d) for d in items], limit, offset)
    return ok_list(page, meta)


@bp.route("/jc/dormitory-assignments/<assignment_id>/checkout", methods=["POST"])
def checkout_dormitory(assignment_id):
    user_id, role = authenticate()
    require_role(role, {"ResidentialAdvisor"})
    d = STORE.dormitory_assignments.get(assignment_id)
    if d is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Dormitory assignment not found")
    body = get_body()
    check_unknown(body, {"move_out_date"})
    move_out_date = as_date(body, "move_out_date", required=True)
    if d["status"] != "ACTIVE":
        raise ApiError(
            ERR_INVALID_STATE[0],
            ERR_INVALID_STATE[1],
            "Only an ACTIVE assignment can be checked out",
        )
    if move_out_date < d["move_in_date"]:
        raise ApiError(
            ERR_INVALID_REQUEST[0],
            ERR_INVALID_REQUEST[1],
            "move_out_date must not fall before move_in_date",
        )
    d["status"] = "CHECKED_OUT"
    d["move_out_date"] = move_out_date
    bump(d)
    enrollment = STORE.enrollments[d["enrollment_id"]]
    if enrollment["residential_status"] == "RESIDENT":
        enrollment["residential_status"] = "RELEASED"
        bump(enrollment)
    return ok_object(serializers.dormitory_view(d), status=200)
