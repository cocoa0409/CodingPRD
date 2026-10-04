"""WarrantyClaim routes: file/list/get/start-review/decide."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list, iso_utc
from services import warranty_credit_amount
from util import new_id, stamp_new, touch, req_enum, req_pos_number

bp = Blueprint("claims", __name__)

DEFECT_TYPES = {"CELL_DEFECT", "CAPACITY_SHORTFALL", "RTE_SHORTFALL", "BMS_FAULT"}
CREDIT_VARIANTS = {"STRAIGHT_LINE", "OUTPUT_BASED"}


def serialize_claim(c):
    return dict(c)


def get_claim_or_404(cid):
    c = store.claims.get(cid)
    if c is None:
        raise ApiError("ERR_NOT_FOUND", 404, "WarrantyClaim not found")
    return c


@bp.route("/warranty-claims", methods=["POST"])
@require_roles({"WarrantyAdmin"})
def create_claim():
    body = request.get_json(silent=True) or {}
    esa_id = body.get("esa_id")
    if not isinstance(esa_id, str) or esa_id not in store.esas:
        raise ApiError("ERR_ESA_NOT_FOUND", 404, "esa_id does not reference an existing EquipmentSupplyAgreement")
    esa = store.esas[esa_id]
    defect = req_enum(body, "defect_type", DEFECT_TYPES)
    loss = req_pos_number(body, "claimed_capacity_loss_mwh")
    if esa["status"] not in ("EXECUTED", "COMPLETED"):
        raise ApiError("ERR_ESA_NOT_EXECUTABLE_STATE", 409,
                       "Claims can only be filed against an ESA in EXECUTED or COMPLETED")
    c = {
        "id": new_id(),
        "esa_id": esa_id,
        "defect_type": defect,
        "claimed_capacity_loss_mwh": loss,
        "credit_variant": None,
        "credit_amount_cents": None,
        "decided_at": None,
        "status": "SUBMITTED",
    }
    stamp_new(c)
    store.claims[c["id"]] = c
    return success_object(serialize_claim(c), 201)


@bp.route("/warranty-claims", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_claims():
    esa_id = request.args.get("esa_id")
    items = [c for c in store.claims.values()
             if esa_id is None or c["esa_id"] == esa_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_claim(c) for c in page], limit, offset, total)


@bp.route("/warranty-claims/<cid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_claim(cid):
    return success_object(serialize_claim(get_claim_or_404(cid)))


@bp.route("/warranty-claims/<cid>/start-review", methods=["POST"])
@require_roles({"WarrantyAdmin"})
def start_review(cid):
    c = get_claim_or_404(cid)
    if c["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_NOT_SUBMITTED", 409, "Start-review requires SUBMITTED")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success_object(serialize_claim(c))


@bp.route("/warranty-claims/<cid>/decide", methods=["POST"])
@require_roles({"WarrantyAdmin"})
def decide_claim(cid):
    c = get_claim_or_404(cid)
    if c["status"] != "UNDER_REVIEW":
        raise ApiError("ERR_CLAIM_NOT_UNDER_REVIEW", 409, "Decide requires UNDER_REVIEW")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    if decision not in ("APPROVED", "REJECTED"):
        raise ApiError("ERR_INVALID_REQUEST", 400, "decision must be APPROVED or REJECTED")
    esa = store.esas.get(c["esa_id"])
    if decision == "APPROVED":
        if esa["status"] not in ("EXECUTED", "COMPLETED"):
            raise ApiError("ERR_ESA_NOT_EXECUTABLE_STATE", 409,
                           "Approval requires the ESA in EXECUTED or COMPLETED")
        variant = body.get("credit_variant")
        if variant not in CREDIT_VARIANTS:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "credit_variant must be STRAIGHT_LINE or OUTPUT_BASED")
        throughput = body.get("throughput_mwh")
        if variant == "OUTPUT_BASED":
            if (isinstance(throughput, bool) or not isinstance(throughput, (int, float))
                    or throughput <= 0):
                raise ApiError("ERR_INVALID_REQUEST", 400,
                               "throughput_mwh is required for OUTPUT_BASED and must be > 0")
        c["credit_variant"] = variant
        c["credit_amount_cents"] = warranty_credit_amount(c, esa, variant, throughput)
        c["status"] = "APPROVED"
    else:
        c["status"] = "REJECTED"
    c["decided_at"] = iso_utc(store.clock())
    touch(c)
    return success_object(serialize_claim(c))
