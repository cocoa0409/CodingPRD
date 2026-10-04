"""MeasureBundle routes."""
from flask import Blueprint

import db
import domain
from errors import ApiError, ok
from util import (body, new_id, now_iso, paginate_args, paginate_list,
                  req_string, require_roles, touch)

bp = Blueprint("bundles", __name__)


@bp.route("/performance-contracts/<contractId>/bundles", methods=["POST"])
def create_bundle(contractId):
    require_roles("ESCOEngineer")
    c = domain.get_contract(contractId)
    data = body()
    rec = {
        "id": new_id(),
        "contract_id": c["id"],
        "name": req_string(data, "name"),
        "blended_payback_years": None,
        "subsidy_pool_cents": 0,
        "status": "DRAFT",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.bundles[rec["id"]] = rec
    return ok(domain.ser_bundle(rec), code=201)


@bp.route("/performance-contracts/<contractId>/bundles", methods=["GET"])
def list_bundles(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    limit, offset = paginate_args()
    items = [b for b in db.bundles.values() if b["contract_id"] == c["id"]]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_bundle(b) for b in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>", methods=["GET"])
def get_bundle(contractId, bundleId):
    require_roles()
    _, b = domain.get_bundle(contractId, bundleId)
    return ok(domain.ser_bundle(b))


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/propose", methods=["POST"])
def propose_bundle(contractId, bundleId):
    require_roles("ESCOEngineer")
    c, b = domain.get_bundle(contractId, bundleId)
    if b["status"] != "DRAFT":
        raise ApiError("ERR_BUNDLE_NOT_DRAFT", 409, "bundle must be in DRAFT")
    if c["status"] not in ("AUDIT", "SCOPED"):
        raise ApiError("ERR_CONTRACT_NOT_SCOPABLE", 409,
                       "contract must be in AUDIT or SCOPED")
    counted = [m for m in domain.bundle_measures(b["id"])
               if m["status"] in ("PROPOSED", "INCLUDED")]
    if not counted:
        raise ApiError("ERR_BUNDLE_EMPTY", 409, "bundle has no measures")
    b["status"] = "PROPOSED"
    domain.recompute_bundle(b)
    return ok(domain.ser_bundle(b))


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/approve", methods=["POST"])
def approve_bundle(contractId, bundleId):
    require_roles("OwnerRep")
    c, b = domain.get_bundle(contractId, bundleId)
    if b["status"] != "PROPOSED":
        raise ApiError("ERR_BUNDLE_NOT_PROPOSED", 409, "bundle must be in PROPOSED")
    domain.recompute_bundle(b, mutate=False)
    if b["blended_payback_years"] is None or b["blended_payback_years"] > c["contract_term_years"]:
        raise ApiError("ERR_BUNDLE_PAYBACK_EXCEEDS_TERM", 422,
                       "blended payback exceeds the contract term")
    for m in domain.bundle_measures(b["id"]):
        if m["status"] == "PROPOSED":
            m["status"] = "INCLUDED"
            touch(m)
    b["status"] = "APPROVED"
    domain.recompute_bundle(b, mutate=False)
    domain.run_waterfall(b)
    touch(b)
    return ok(domain.ser_bundle(b))


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/withdraw", methods=["POST"])
def withdraw_bundle(contractId, bundleId):
    require_roles("ESCOEngineer")
    _, b = domain.get_bundle(contractId, bundleId)
    if b["status"] not in ("DRAFT", "PROPOSED"):
        raise ApiError("ERR_BUNDLE_NOT_WITHDRAWABLE", 409,
                       "bundle must be in DRAFT or PROPOSED")
    b["status"] = "WITHDRAWN"
    for m in domain.bundle_measures(b["id"]):
        if m["status"] == "PROPOSED":
            m["status"] = "EXCLUDED"
            touch(m)
    touch(b)
    return ok(domain.ser_bundle(b))
