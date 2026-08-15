"""Quality complaints (PRD §3.10): lab retest loop, heat-shock gate, and the
substantiation cascade."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_HEAT_SHOCK_NOT_PROVEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_LAB_CYCLE_EXHAUSTED,
    ERR_LAB_RESULT_REQUIRED,
    ERR_NOT_RESOURCE_OWNER,
)
from middleware import authenticate, ALL_ROLES
from response import success_obj, success_list
from services import (
    HEAT_SHOCK_LIMIT_UM,
    LAB_CYCLE_CAP,
    D,
    quarantine_lot_cascade,
    serialize,
)
from util import (
    apply_filters,
    body_json,
    check_shape,
    exist_body_fks,
    paginate,
    pagination_params,
    path_entity,
)

bp = Blueprint("complaints", __name__)

COMPLAINT_SPEC = {
    "complaint_code": {"type": "string", "required": True},
    "lot_id": {"type": "string", "required": True},
    "complaint_type": {
        "type": "enum",
        "values": {"HEAT_SHOCK", "TEXTURE", "SHELF_LIFE_SHORTFALL", "FOREIGN_MATERIAL"},
        "required": True,
    },
}

LAB_RESULT_SPEC = {
    "measured_ice_crystal_um": {"type": "number"},
}

DISPOSITION_SPEC = {
    "outcome": {"type": "enum", "values": {"SUBSTANTIATED", "UNFOUNDED"}, "required": True},
    "disposition_rationale": {"type": "string"},
}


@bp.route("/quality-complaints", methods=["POST"])
def create_complaint():
    user_id, role = authenticate({"QAManager", "CustomerRep"})
    body = body_json()
    exist_body_fks(body, {"lot_id": ("lots", "inventory lot")})
    check_shape(body, COMPLAINT_SPEC)
    lot = db.get("lots", body["lot_id"])
    complaint = db.new_entity("complaints", {
        "complaint_code": body["complaint_code"],
        "lot_id": lot["id"],
        # CustomerRep filings carry the filer's id; QA-internal filings are null.
        "customer_id": user_id if role == "CustomerRep" else None,
        "complaint_type": body["complaint_type"],
        "status": "UNDER_REVIEW",
        "measured_ice_crystal_um": None,
        "lab_cycle_count": 0,
        "disposition_rationale": None,
    })
    return success_obj(serialize("complaints", complaint), 201)


@bp.route("/quality-complaints", methods=["GET"])
def list_complaints():
    authenticate(ALL_ROLES)
    items = apply_filters(
        db.all_of("complaints"), ["lot_id", "customer_id", "status", "complaint_type"]
    )
    limit, offset = pagination_params()
    page, total, has_more = paginate(items, limit, offset)
    return success_list([serialize("complaints", e) for e in page],
                        limit, offset, total, has_more)


@bp.route("/quality-complaints/<complaint_id>", methods=["GET"])
def get_complaint(complaint_id):
    authenticate(ALL_ROLES)
    complaint = path_entity("complaints", complaint_id, "complaint")
    return success_obj(serialize("complaints", complaint))


@bp.route("/quality-complaints/<complaint_id>/send-to-lab", methods=["POST"])
def send_complaint_to_lab(complaint_id):
    authenticate({"QAManager"})
    complaint = path_entity("complaints", complaint_id, "complaint")
    if complaint["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "complaint is not UNDER_REVIEW")
    # Priority 31: the retest loop is bounded at 3 lab cycles.
    if complaint["lab_cycle_count"] >= LAB_CYCLE_CAP:
        raise ApiError(ERR_LAB_CYCLE_EXHAUSTED, 409, "lab cycle cap reached")
    complaint["lab_cycle_count"] += 1
    complaint["status"] = "LAB_TEST"
    db.touch(complaint)
    return success_obj(serialize("complaints", complaint))


@bp.route("/quality-complaints/<complaint_id>/record-lab-result", methods=["POST"])
def record_lab_result(complaint_id):
    authenticate({"QAManager"})
    complaint = path_entity("complaints", complaint_id, "complaint")
    body = body_json()
    check_shape(body, LAB_RESULT_SPEC)
    if complaint["status"] != "LAB_TEST":
        raise ApiError(ERR_INVALID_STATE, 409, "complaint is not LAB_TEST")
    if complaint["complaint_type"] == "HEAT_SHOCK" and (
        "measured_ice_crystal_um" not in body or body["measured_ice_crystal_um"] is None
    ):
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "measured_ice_crystal_um is required for HEAT_SHOCK complaints",
        )
    if "measured_ice_crystal_um" in body and body["measured_ice_crystal_um"] is not None:
        complaint["measured_ice_crystal_um"] = body["measured_ice_crystal_um"]
    complaint["status"] = "UNDER_REVIEW"
    db.touch(complaint)
    return success_obj(serialize("complaints", complaint))


@bp.route("/quality-complaints/<complaint_id>/disposition", methods=["POST"])
def disposition_complaint(complaint_id):
    user_id, _role = authenticate({"QAManager"})
    complaint = path_entity("complaints", complaint_id, "complaint")
    body = body_json()
    check_shape(body, DISPOSITION_SPEC)
    if complaint["status"] != "UNDER_REVIEW":
        raise ApiError(ERR_INVALID_STATE, 409, "complaint is not UNDER_REVIEW")
    if body.get("disposition_rationale") is not None:
        complaint["disposition_rationale"] = body["disposition_rationale"]
    if body["outcome"] == "SUBSTANTIATED":
        if complaint["complaint_type"] == "HEAT_SHOCK":
            # Priority 29: a recorded lab result is required.
            measured = complaint["measured_ice_crystal_um"]
            if measured is None:
                raise ApiError(
                    ERR_LAB_RESULT_REQUIRED,
                    422,
                    "HEAT_SHOCK disposition requires a recorded measured_ice_crystal_um",
                )
            # Priority 30: strictly greater than the format threshold.
            lot = db.get("lots", complaint["lot_id"])
            product = db.get("products", lot["product_id"]) if lot else None
            limit = HEAT_SHOCK_LIMIT_UM[product["format"]] if product else HEAT_SHOCK_LIMIT_UM["NOVELTY"]
            if not (D(measured) > limit):
                raise ApiError(
                    ERR_HEAT_SHOCK_NOT_PROVEN,
                    422,
                    "measured ice crystal size does not exceed the format limit",
                )
        # Substantiation cascade (PRD §3.10): every AVAILABLE lot on the same
        # run quarantines; its ACTIVE allocations release; affected LOADED
        # shipments regress to PLANNED.
        complaint_lot = db.get("lots", complaint["lot_id"])
        run_id = complaint_lot["run_id"] if complaint_lot else None
        for lot in db.all_of("lots"):
            if lot["run_id"] == run_id and lot["status"] == "AVAILABLE":
                quarantine_lot_cascade(lot, user_id)
        complaint["status"] = "DISPOSITIONED_SUBSTANTIATED"
    else:
        complaint["status"] = "CLOSED_UNFOUNDED"
    db.touch(complaint)
    return success_obj(serialize("complaints", complaint))


@bp.route("/quality-complaints/<complaint_id>/withdraw", methods=["POST"])
def withdraw_complaint(complaint_id):
    user_id, role = authenticate({"QAManager", "CustomerRep"})
    complaint = path_entity("complaints", complaint_id, "complaint")
    if complaint["status"] not in ("UNDER_REVIEW", "LAB_TEST"):
        raise ApiError(ERR_INVALID_STATE, 409, "complaint is not UNDER_REVIEW or LAB_TEST")
    # A CustomerRep may withdraw only their own complaint; QA may withdraw any.
    if role == "CustomerRep" and complaint["customer_id"] != user_id:
        raise ApiError(
            ERR_NOT_RESOURCE_OWNER, 403, "caller does not own this complaint"
        )
    complaint["status"] = "WITHDRAWN"
    db.touch(complaint)
    return success_obj(serialize("complaints", complaint))
