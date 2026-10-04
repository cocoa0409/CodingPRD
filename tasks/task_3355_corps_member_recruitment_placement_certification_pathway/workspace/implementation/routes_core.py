"""Regions, partner districts and partner schools."""

from flask import Blueprint, request

import serialize
import validation
from envelope import ok, paginate, read_json, require_auth, sorted_by_created
from errors import ApiError
from store import DISTRICTS, REGIONS, SCHOOLS, stamp
from util import iso

bp = Blueprint("core", __name__)

PROJECTIONS = ("ACTUAL", "FORWARD_LOOKING")


# --------------------------------------------------------------------------
# Regions
# --------------------------------------------------------------------------
@bp.route("/corps/regions", methods=["POST"])
def create_region():
    require_auth(["PlatformAdmin"])
    body = read_json()
    validation.require(
        body,
        "region_code",
        "name",
        "state_code",
        "term_start_date",
        "base_placement_fee_cents",
        "max_corps_members",
    )
    region_code = validation.string(body, "region_code")
    name = validation.string(body, "name")
    state_code = validation.state_code(body, "state_code")
    term_start_date = validation.timestamp(body, "term_start_date")
    base_fee = validation.integer(body, "base_placement_fee_cents", minimum=0)
    max_members = validation.integer(body, "max_corps_members", minimum=1)
    if any(r["region_code"] == region_code for r in REGIONS.values()):
        validation.bad("Field 'region_code' is already held by another region.")
    record = {
        "region_code": region_code,
        "name": name,
        "state_code": state_code,
        "term_start_date": iso(term_start_date),
        "base_placement_fee_cents": base_fee,
        "max_corps_members": max_members,
    }
    stamp(record)
    REGIONS[record["id"]] = record
    return ok(serialize.region(record), 201)


# --------------------------------------------------------------------------
# Partner districts
# --------------------------------------------------------------------------
@bp.route("/corps/partner-districts", methods=["POST"])
def create_district():
    require_auth(["PlatformAdmin"])
    body = read_json()
    validation.require(
        body,
        "region_id",
        "name",
        "hiring_commitment_slots",
        "placement_fee_per_member_cents",
        "unfilled_slot_penalty_cents",
        "fee_budget_cents",
    )
    region_id = validation.string(body, "region_id")
    name = validation.string(body, "name")
    slots = validation.integer(body, "hiring_commitment_slots", minimum=0)
    fee = validation.integer(body, "placement_fee_per_member_cents", minimum=0)
    penalty = validation.integer(body, "unfilled_slot_penalty_cents", minimum=0)
    budget = validation.integer(body, "fee_budget_cents", minimum=0)
    if region_id not in REGIONS:
        raise ApiError("ERR_REGION_NOT_FOUND")
    record = {
        "region_id": region_id,
        "name": name,
        "agreement_status": "DRAFT",
        "hiring_commitment_slots": slots,
        "placement_fee_per_member_cents": fee,
        "unfilled_slot_penalty_cents": penalty,
        "fee_budget_cents": budget,
        "committed_placement_count": 0,
        "invoice_amount_cents": 0,
    }
    stamp(record)
    DISTRICTS[record["id"]] = record
    return ok(serialize.district(record), 201)


@bp.route("/corps/partner-districts", methods=["GET"])
def list_districts():
    require_auth(["PlatformAdmin", "PlacementCoordinator"])
    region_id = request.args.get("region_id")
    rows = sorted_by_created(DISTRICTS.values())
    if region_id:
        rows = [r for r in rows if r["region_id"] == region_id]
    page, window = paginate(rows)
    return ok([serialize.district(r) for r in page], 200, page=window)


@bp.route("/corps/partner-districts/<district_id>", methods=["GET"])
def get_district(district_id):
    require_auth(["PlatformAdmin", "PlacementCoordinator"])
    district = DISTRICTS.get(district_id)
    if district is None:
        raise ApiError("ERR_DISTRICT_NOT_FOUND")
    projection = request.args.get("projection")
    if projection is not None and projection not in PROJECTIONS:
        raise ApiError("ERR_INVALID_REQUEST", "projection must be ACTUAL or FORWARD_LOOKING.")
    return ok(serialize.district(district, projection=projection), 200)


@bp.route("/corps/partner-districts/<district_id>/status", methods=["POST"])
def change_district_status(district_id):
    require_auth(["PlatformAdmin"])
    body = read_json()
    to_status = validation.enum(body, "to_status", validation.AGREEMENT_STATUSES)
    district = DISTRICTS.get(district_id)
    if district is None:
        raise ApiError("ERR_DISTRICT_NOT_FOUND")
    current = district["agreement_status"]
    if current == "EXPIRED":
        raise ApiError("ERR_ALREADY_TERMINAL")
    if to_status == "ACTIVE":
        if current == "DRAFT":
            has_school = any(s["district_id"] == district["id"] for s in SCHOOLS.values())
            if not has_school:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "A district agreement cannot become ACTIVE before it has a partner school.",
                )
        elif current == "SUSPENDED":
            if district["invoice_amount_cents"] > district["fee_budget_cents"]:
                raise ApiError(
                    "ERR_INVALID_STATE",
                    "A suspended agreement returns to ACTIVE only within its fee budget.",
                )
        else:
            raise ApiError("ERR_INVALID_STATE")
    elif to_status == "SUSPENDED":
        if current != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
    else:
        raise ApiError("ERR_INVALID_STATE")
    district["agreement_status"] = to_status
    from store import touch

    touch(district)
    return ok(serialize.district(district), 200)


@bp.route("/corps/partner-districts/<district_id>/partner-schools", methods=["GET"])
def list_district_schools(district_id):
    require_auth(["PlatformAdmin", "PlacementCoordinator"])
    district = DISTRICTS.get(district_id)
    if district is None:
        raise ApiError("ERR_DISTRICT_NOT_FOUND")
    rows = [s for s in sorted_by_created(SCHOOLS.values()) if s["district_id"] == district_id]
    page, window = paginate(rows)
    return ok([serialize.school(s) for s in page], 200, page=window)


# --------------------------------------------------------------------------
# Partner schools
# --------------------------------------------------------------------------
@bp.route("/corps/partner-schools", methods=["POST"])
def create_school():
    require_auth(["PlatformAdmin"])
    body = read_json()
    validation.require(
        body,
        "district_id",
        "name",
        "grade_band",
        "subject_needs",
        "classroom_capacity",
        "expected_district_version",
    )
    district_id = validation.string(body, "district_id")
    name = validation.string(body, "name")
    grade_band = validation.enum(body, "grade_band", validation.GRADE_BANDS)
    subject_needs = validation.subject_needs(body, "subject_needs")
    capacity = validation.integer(body, "classroom_capacity", minimum=1)
    expected_version = validation.integer(body, "expected_district_version")
    district = DISTRICTS.get(district_id)
    if district is None:
        raise ApiError("ERR_DISTRICT_NOT_FOUND")
    if expected_version != district["version"]:
        raise ApiError("ERR_STALE_DISTRICT_VERSION")
    record = {
        "district_id": district_id,
        "name": name,
        "grade_band": grade_band,
        "subject_needs": subject_needs,
        "classroom_capacity": capacity,
        "occupied_classrooms": 0,
    }
    stamp(record)
    SCHOOLS[record["id"]] = record
    from store import touch

    touch(district)
    return ok(serialize.school(record), 201)


@bp.route("/corps/partner-schools/<school_id>", methods=["GET"])
def get_school(school_id):
    require_auth(["PlatformAdmin", "PlacementCoordinator"])
    school = SCHOOLS.get(school_id)
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND")
    return ok(serialize.school(school), 200)


@bp.route("/corps/partner-schools/<school_id>/placements", methods=["GET"])
def list_school_placements(school_id):
    require_auth(["PlatformAdmin", "PlacementCoordinator"])
    from store import PLACEMENTS

    school = SCHOOLS.get(school_id)
    if school is None:
        raise ApiError("ERR_SCHOOL_NOT_FOUND")
    rows = [p for p in sorted_by_created(PLACEMENTS.values()) if p["school_id"] == school_id]
    page, window = paginate(rows)
    return ok([serialize.placement(p) for p in page], 200, page=window)
