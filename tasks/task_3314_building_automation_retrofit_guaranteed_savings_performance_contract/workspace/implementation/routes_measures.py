"""Measure routes."""
from flask import Blueprint, request

import db
import domain
import calc
from errors import ApiError, ok
from util import (body, new_id, now_iso, paginate_args, paginate_list,
                  req_enum, req_int, require_roles, touch)

bp = Blueprint("measures", __name__)

MEASURE_TYPES = ("LIGHTING", "HVAC", "CONTROLS", "ENVELOPE", "WATER", "OTHER")


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/measures", methods=["POST"])
def create_measure(contractId, bundleId):
    require_roles("ESCOEngineer")
    c, b = domain.get_bundle(contractId, bundleId)
    data = body()
    cost = req_int(data, "installed_cost_cents", min_v=1)
    savings = req_int(data, "annual_savings_cents", min_v=0)
    rec = {
        "id": new_id(),
        "bundle_id": b["id"],
        "contract_id": c["id"],
        "measure_type": req_enum(data, "measure_type", MEASURE_TYPES),
        "installed_cost_cents": cost,
        "annual_savings_cents": savings,
        "simple_payback_years": calc.simple_payback(cost, savings),
        "subsidy_draw_cents": 0,
        "status": "PROPOSED",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.measures[rec["id"]] = rec
    domain.recompute_bundle(b)
    return ok(domain.ser_measure(rec), code=201)


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/measures", methods=["GET"])
def list_measures(contractId, bundleId):
    require_roles()
    _, b = domain.get_bundle(contractId, bundleId)
    limit, offset = paginate_args()
    items = [m for m in db.measures.values() if m["bundle_id"] == b["id"]]
    items.sort(key=lambda m: (m["created_at"], m["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_measure(m) for m in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/measures/<measureId>", methods=["GET"])
def get_measure(contractId, bundleId, measureId):
    require_roles()
    _, _, m = domain.get_measure(contractId, bundleId, measureId)
    return ok(domain.ser_measure(m))


@bp.route("/performance-contracts/<contractId>/measures", methods=["GET"])
def list_contract_measures(contractId):
    require_roles()
    c = domain.get_contract(contractId)
    limit, offset = paginate_args()
    items = [m for m in db.measures.values() if m["contract_id"] == c["id"]]
    items.sort(key=lambda m: (m["created_at"], m["id"]))
    page, meta = paginate_list(items, limit, offset)
    return ok([domain.ser_measure(m) for m in page], response_type="array", pagination=meta)


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/measures/<measureId>/exclude", methods=["POST"])
def exclude_measure(contractId, bundleId, measureId):
    require_roles("ESCOEngineer")
    c, b, m = domain.get_measure(contractId, bundleId, measureId)
    if m["status"] not in ("PROPOSED", "INCLUDED"):
        raise ApiError("ERR_MEASURE_NOT_EXCLUDABLE", 409,
                       "measure must be in PROPOSED or INCLUDED")
    if c["status"] in ("PERFORMANCE", "CLOSED", "TERMINATED"):
        raise ApiError("ERR_CONTRACT_LOCKED", 409, "the measure set is immutable")
    m["status"] = "EXCLUDED"
    m["subsidy_draw_cents"] = 0
    touch(m)
    domain.recompute_bundle(b, mutate=False)
    domain.run_waterfall(b)
    touch(b)
    return ok(domain.ser_measure(m))


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/measures/<measureId>/install", methods=["POST"])
def install_measure(contractId, bundleId, measureId):
    require_roles("ESCOEngineer")
    c, b, m = domain.get_measure(contractId, bundleId, measureId)
    if m["status"] != "INCLUDED":
        raise ApiError("ERR_MEASURE_NOT_INCLUDED", 409, "measure must be in INCLUDED")
    if c["status"] != "CONSTRUCTION":
        raise ApiError("ERR_CONTRACT_NOT_IN_CONSTRUCTION", 409,
                       "contract must be in CONSTRUCTION")
    now = db.logical_now()
    active = [p for p in db.phases.values()
              if p["contract_id"] == c["id"] and p["status"] == "IN_PROGRESS"
              and p["_window_start"] <= now < p["_window_end"]]
    if not active:
        raise ApiError("ERR_NO_ACTIVE_PHASE_WINDOW", 409,
                       "no IN_PROGRESS phase window contains the logical clock")
    m["status"] = "INSTALLED"
    touch(m)
    return ok(domain.ser_measure(m))


@bp.route("/performance-contracts/<contractId>/bundles/<bundleId>/measures/<measureId>/verify", methods=["POST"])
def verify_measure(contractId, bundleId, measureId):
    require_roles("OwnerRep")
    _, b, m = domain.get_measure(contractId, bundleId, measureId)
    if m["status"] != "INSTALLED":
        raise ApiError("ERR_MEASURE_NOT_INSTALLED", 409, "measure must be in INSTALLED")
    m["status"] = "VERIFIED"
    touch(m)
    remaining = [x for x in domain.bundle_measures(b["id"])
                 if x["status"] not in ("VERIFIED", "EXCLUDED")]
    if not remaining and b["status"] == "ACTIVE":
        b["status"] = "COMPLETE"
        touch(b)
    return ok(domain.ser_measure(m))
