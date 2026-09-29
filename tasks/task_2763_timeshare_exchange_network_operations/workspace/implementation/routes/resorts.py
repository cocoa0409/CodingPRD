"""Resort registration, affiliation lifecycle, compliance and quality reviews."""

from flask import Blueprint

import calc
import shapes
from authz import (authenticate, require_acting_identity, require_owner,
                   require_resort_manager)
from errors import ApiError
from response import object_response
from routes.common import ENUM, FK, TEXT, listing, one, read
from services import resorts as resort_service
from store import (db, serialize, touch, AFFILIATION_STATUSES, QUALITY_RATINGS)

bp = Blueprint("resorts", __name__)

ALL_ROLES = ["Member", "ResortManager", "NetworkOperator", "DisputeAnalyst"]

RESORT_TRANSITIONS = {
    "PENDING_AFFILIATION": [],
    "ACTIVE": ["PROBATION", "SUSPENDED"],
    "PROBATION": ["ACTIVE", "SUSPENDED", "TERMINATED"],
    "SUSPENDED": ["ACTIVE", "TERMINATED"],
    "TERMINATED": [],
}


@bp.route("/resorts", methods=["POST"])
def create_resort():
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    name = shapes.take_string(payload, "name", min_len=1, max_len=120)
    region_code = shapes.take_string(payload, "region_code", min_len=2, max_len=8)
    obligation = shapes.take_int(payload, "required_annual_deposit_units", minimum=1)
    initial_rating = shapes.take_enum(payload, "initial_quality_rating", QUALITY_RATINGS)
    units_per_size = shapes.take_int(payload, "units_per_size", required=False,
                                    minimum=1, default=2)
    demand_index = shapes.take_int(payload, "demand_index", required=False,
                                  minimum=1, maximum=5, default=3)
    require_acting_identity(caller)
    row = db.new_row({
        "name": name,
        "region_code": region_code,
        "units_per_size": units_per_size,
        "demand_index": demand_index,
        "required_annual_deposit_units": obligation,
        "initial_quality_rating": initial_rating,
        "affiliation_status": "PENDING_AFFILIATION",
        "affiliated_on": None,
        "quality_score": None,
        "review_count": 0,
        "quality_rating": initial_rating,
        "complaint_strikes": 0,
        "downgrade_notches": 0,
        "deposits_committed_count": 0,
        "committed_nights": 0,
    })
    db.resorts[row["id"]] = row
    return object_response(serialize(row), 201)


@bp.route("/resorts/<resort_id>", methods=["GET"])
def get_resort(resort_id):
    read(ALL_ROLES)
    return one(shapes.find_resort(resort_id))


@bp.route("/resorts", methods=["GET"])
def list_resorts():
    return listing(ALL_ROLES, db.resorts, [
        ("region_code", "region_code", TEXT, None),
        ("affiliation_status", "affiliation_status", ENUM, AFFILIATION_STATUSES),
        ("quality_rating", "quality_rating", ENUM, QUALITY_RATINGS),
    ])


@bp.route("/resorts/<resort_id>", methods=["PATCH"])
def patch_resort(resort_id):
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    demand_index = shapes.take_int(payload, "demand_index", required=False,
                                  minimum=1, maximum=5)
    units_per_size = shapes.take_int(payload, "units_per_size", required=False, minimum=1)
    obligation = shapes.take_int(payload, "required_annual_deposit_units",
                                required=False, minimum=1)
    require_acting_identity(caller)
    resort = shapes.find_resort(resort_id)
    if demand_index is not None:
        resort["demand_index"] = demand_index
    if units_per_size is not None:
        resort["units_per_size"] = units_per_size
    if obligation is not None:
        resort["required_annual_deposit_units"] = obligation
    touch(resort)
    return one(resort)


@bp.route("/resorts/<resort_id>/affiliation", methods=["POST"])
def affiliate_resort(resort_id):
    caller = authenticate(["NetworkOperator"])
    shapes.body()
    require_acting_identity(caller)
    resort = shapes.find_resort(resort_id)
    if resort["affiliation_status"] != "PENDING_AFFILIATION":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    has_band = any(band["resort_id"] == resort["id"] for band in db.season_bands.values())
    if not has_band:
        raise ApiError("ERR_AFFILIATION_REQUIRES_SEASON_BANDS")
    resort["affiliation_status"] = "ACTIVE"
    resort["affiliated_on"] = db.now_iso()
    resort["quality_rating"] = resort["initial_quality_rating"]
    touch(resort)
    return one(resort)


@bp.route("/resorts/<resort_id>/status-changes", methods=["POST"])
def change_resort_status(resort_id):
    caller = authenticate(["NetworkOperator"])
    payload = shapes.body()
    to_status = shapes.take_enum(payload, "to_status", AFFILIATION_STATUSES)
    shapes.take_string(payload, "reason", required=False)
    require_acting_identity(caller)
    resort = shapes.find_resort(resort_id)
    if to_status not in RESORT_TRANSITIONS[resort["affiliation_status"]]:
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if resort["affiliation_status"] == "PROBATION" and to_status == "ACTIVE":
        if resort_service.shortfall_by_stay_year(resort) != 0:
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
    resort["affiliation_status"] = to_status
    touch(resort)
    return one(resort)


@bp.route("/resorts/<resort_id>/compliance", methods=["GET"])
def resort_compliance(resort_id):
    caller = authenticate(["NetworkOperator", "ResortManager"])
    require_acting_identity(caller)
    resort = shapes.find_resort(resort_id)
    require_resort_manager(caller, resort["id"])
    return object_response(resort_service.compliance_report(resort))


# ---------------------------------------------------------------------------
# quality reviews
# ---------------------------------------------------------------------------
@bp.route("/resorts/<resort_id>/quality-reviews", methods=["POST"])
def create_quality_review(resort_id):
    caller = authenticate(["Member"])
    payload = shapes.body()
    confirmation_id = shapes.take_id(payload, "confirmation_id")
    cleanliness = shapes.take_int(payload, "cleanliness_score", minimum=1, maximum=10)
    service = shapes.take_int(payload, "service_score", minimum=1, maximum=10)
    amenities = shapes.take_int(payload, "amenities_score", minimum=1, maximum=10)
    expected_version = shapes.take_int(payload, "expected_resort_version")
    require_acting_identity(caller)
    resort = shapes.find_resort(resort_id)
    confirmation = shapes.find_confirmation(confirmation_id)
    stay_request = db.exchange_requests[confirmation["exchange_request_id"]]
    require_owner(caller, stay_request["member_id"])
    if expected_version != resort["version"]:
        raise ApiError("ERR_STALE_VERSION")
    if confirmation["status"] != "COMPLETED":
        raise ApiError("ERR_STAY_NOT_COMPLETED")
    for existing in db.resort_quality_reviews.values():
        if existing["confirmation_id"] == confirmation["id"]:
            raise ApiError("ERR_DUPLICATE_QUALITY_REVIEW")
    awarded = db.deposits[confirmation["awarded_deposit_id"]]
    if awarded["resort_id"] != resort["id"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "resort_id must be the resort of the week the confirmation awarded.")
    row = db.new_row({
        "resort_id": resort["id"],
        "confirmation_id": confirmation["id"],
        "cleanliness_score": cleanliness,
        "service_score": service,
        "amenities_score": amenities,
        "composite_score": float(calc.composite_score(cleanliness, service, amenities)),
    })
    db.resort_quality_reviews[row["id"]] = row
    resort_service.recompute_quality(resort)
    touch(resort)
    return object_response(serialize(row), 201)


@bp.route("/resort-quality-reviews/<review_id>", methods=["GET"])
def get_quality_review(review_id):
    read(ALL_ROLES)
    return one(shapes.find_review(review_id))


@bp.route("/resort-quality-reviews", methods=["GET"])
def list_quality_reviews():
    return listing(ALL_ROLES, db.resort_quality_reviews, [
        ("resort_id", "resort_id", FK, shapes.find_resort),
        ("confirmation_id", "confirmation_id", FK, shapes.find_confirmation),
    ])
