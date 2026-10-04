"""Placement matching, confirmation, capacity, activation and the ending pair."""

from flask import Blueprint

import calc
import serialize
import services
import validation
from envelope import ok, read_json, require_auth
from errors import ApiError
from store import (
    APPLICATIONS,
    DISTRICTS,
    MEMBERS,
    PLACEMENTS,
    SCHOOLS,
    now,
    stamp,
    touch,
)
from util import iso

bp = Blueprint("placements", __name__)

READINESS_GATE = 60.0


def _load_placement(placement_id):
    placement = PLACEMENTS.get(placement_id)
    if placement is None:
        raise ApiError("ERR_PLACEMENT_NOT_FOUND")
    return placement


def _context(placement):
    school = SCHOOLS.get(placement["school_id"])
    district = DISTRICTS.get(school["district_id"]) if school else None
    member = MEMBERS.get(placement["corps_member_id"])
    return school, district, member


def _projected_invoice(district, extra_filled):
    filled = calc.district_filled_count(district) + extra_filled
    unfilled = max(0, district["hiring_commitment_slots"] - filled)
    return (
        filled * district["placement_fee_per_member_cents"]
        + unfilled * district["unfilled_slot_penalty_cents"]
    )


@bp.route("/corps/placements", methods=["POST"])
def create_placement():
    require_auth(["PlacementCoordinator"])
    body = read_json()
    validation.require(
        body,
        "corps_member_id",
        "school_id",
        "subject_area",
        "grade_band",
        "term_start_date",
        "term_end_date",
        "expected_corps_member_version",
    )
    corps_member_id = validation.string(body, "corps_member_id")
    school_id = validation.string(body, "school_id")
    subject_area = validation.enum(body, "subject_area", validation.SUBJECT_AREAS)
    grade_band = validation.enum(body, "grade_band", validation.GRADE_BANDS)
    term_start = validation.timestamp(body, "term_start_date")
    term_end = validation.timestamp(body, "term_end_date")
    expected_version = validation.integer(body, "expected_corps_member_version")

    # A placement payload names both a corps member and a school: the member is
    # resolved first (PRD 2.11).
    member = MEMBERS.get(corps_member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    school = SCHOOLS.get(school_id)
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND")
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")
    if member["service_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")

    district = DISTRICTS.get(school["district_id"])
    if district is not None and _projected_invoice(district, 1) > district["fee_budget_cents"]:
        raise ApiError("ERR_DISTRICT_BUDGET_EXCEEDED")

    record = {
        "corps_member_id": corps_member_id,
        "school_id": school_id,
        "subject_area": subject_area,
        "grade_band": grade_band,
        "status": "MATCHED",
        "term_start_date": iso(term_start),
        "term_end_date": iso(term_end),
        "confirmed_at": None,
        "activated_at": None,
        "early_exit_reason": None,
        "employment_eligible": False,
        "placement_fee_cents": 0,
    }
    stamp(record)
    PLACEMENTS[record["id"]] = record
    touch(member)
    return ok(serialize.placement(record), 201)


@bp.route("/corps/placements/<placement_id>/confirm", methods=["POST"])
def confirm_placement(placement_id):
    require_auth(["PlacementCoordinator"])
    read_json()
    placement = _load_placement(placement_id)
    if placement["status"] == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if placement["status"] != "MATCHED":
        raise ApiError("ERR_INVALID_STATE", "Only a MATCHED placement can be confirmed.")
    school, district, member = _context(placement)
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND")
    if district is None:
        raise ApiError("ERR_DISTRICT_NOT_FOUND")
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")

    if placement["subject_area"] not in (school.get("subject_needs") or []):
        raise ApiError("ERR_INVALID_STATE", "The school has not declared a need for this subject.")
    application = APPLICATIONS.get(member.get("application_id"))
    if placement["grade_band"] != school["grade_band"]:
        raise ApiError("ERR_INVALID_STATE", "The placement's grade band does not match the school's.")
    if application is not None and placement["grade_band"] != application["grade_preference"]:
        raise ApiError("ERR_INVALID_STATE", "The placement's grade band does not match the application's preference.")

    if district["agreement_status"] != "ACTIVE":
        raise ApiError("ERR_DISTRICT_NOT_ACTIVE")
    if member["service_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")

    occupied = services.overlapping_occupied_count(
        school, placement["term_start_date"], placement["term_end_date"], exclude_id=placement["id"]
    )
    if occupied >= school["classroom_capacity"]:
        raise ApiError("ERR_SCHOOL_CAPACITY_EXCEEDED")

    placement["status"] = "CONFIRMED"
    placement["confirmed_at"] = iso(now())
    placement["placement_fee_cents"] = calc.placement_fee_cents(placement)
    placement["employment_eligible"] = calc.employment_eligible(placement)
    touch(placement)
    services.refresh_district(district)
    return ok(serialize.placement(placement), 200)


@bp.route("/corps/placements/<placement_id>/activate", methods=["POST"])
def activate_placement(placement_id):
    require_auth(["PlacementCoordinator"])
    read_json()
    placement = _load_placement(placement_id)
    if placement["status"] == "COMPLETED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if placement["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_STATE", "Only a CONFIRMED placement can be activated.")
    _school, district, member = _context(placement)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    if member["institute_status"] != "COMPLETED":
        raise ApiError("ERR_INSTITUTE_INCOMPLETE")
    if member["readiness_score"] < READINESS_GATE:
        raise ApiError("ERR_INVALID_STATE", "The member's readiness score is below the activation gate.")
    placement["status"] = "ACTIVE"
    placement["activated_at"] = iso(now())
    placement["placement_fee_cents"] = calc.placement_fee_cents(placement)
    placement["employment_eligible"] = calc.employment_eligible(placement)
    touch(placement)
    if district is not None:
        services.refresh_district(district)
    return ok(serialize.placement(placement), 200)


@bp.route("/corps/placements/<placement_id>/early-exit", methods=["POST"])
def early_exit_placement(placement_id):
    require_auth(["PlacementCoordinator"])
    body = read_json()
    reason = validation.string(body, "early_exit_reason")
    placement = _load_placement(placement_id)
    if placement["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Only an ACTIVE placement can exit early.")
    school, district, _member = _context(placement)
    placement["status"] = "EXITED_EARLY"
    placement["early_exit_reason"] = reason
    placement["employment_eligible"] = False
    touch(placement)
    if school is not None:
        services.refresh_school(school)
    if district is not None:
        services.refresh_district(district)
        if district["invoice_amount_cents"] > district["fee_budget_cents"]:
            district["agreement_status"] = "SUSPENDED"
            touch(district)
    return ok(serialize.placement(placement), 200)


@bp.route("/corps/placements/<placement_id>/reinstate", methods=["POST"])
def reinstate_placement(placement_id):
    require_auth(["PlacementCoordinator"])
    read_json()
    placement = _load_placement(placement_id)
    if placement["status"] != "EXITED_EARLY":
        raise ApiError("ERR_INVALID_STATE", "Only an EXITED_EARLY placement can be reinstated.")
    school, district, member = _context(placement)
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND")
    if district is None:
        raise ApiError("ERR_DISTRICT_NOT_FOUND")
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    if district["agreement_status"] != "ACTIVE":
        raise ApiError("ERR_DISTRICT_NOT_ACTIVE")
    if member["service_status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_NOT_ACTIVE")
    occupied = services.overlapping_occupied_count(
        school, placement["term_start_date"], placement["term_end_date"], exclude_id=placement["id"]
    )
    if occupied >= school["classroom_capacity"]:
        raise ApiError("ERR_SCHOOL_CAPACITY_EXCEEDED")
    placement["status"] = "ACTIVE"
    placement["early_exit_reason"] = None
    placement["employment_eligible"] = calc.employment_eligible(placement)
    touch(placement)
    services.refresh_school(school)
    services.refresh_district(district)
    return ok(serialize.placement(placement), 200)
