"""GovContract endpoints (PRD 3.9): award, list, get, start-fulfillment
(Berry gate), initiate-audit, complete-audit (outcome-computing)."""
from decimal import Decimal

from flask import Blueprint, request

import cascade
import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, touch, sorted_items
from validation import body, req_str, req_int, req_date

bp = Blueprint("gov_contracts", __name__)

_OPEN_CONTRACT_STATES = ("AWARDED", "IN_FULFILLMENT", "COMPLIANCE_AUDIT")


def get_contract(gid):
    g = DB["contracts"].get(gid)
    if g is None:
        raise ApiError("ERR_CONTRACT_NOT_FOUND", "government contract id does not resolve")
    return g


@bp.post("/footwear/gov-contracts")
@require_roles("PlatformAdmin")
def create_contract(_uid, _role):
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    mid = b.get("model_id")
    if mid is not None and mid not in DB["models"]:
        raise ApiError("ERR_MODEL_NOT_FOUND", "model id does not resolve")
    fid = b.get("factory_id")
    if fid is not None and fid not in DB["factories"]:
        raise ApiError("ERR_FACTORY_NOT_FOUND", "factory id does not resolve")
    number = req_str(b, "contract_number")
    mid = req_str(b, "model_id")
    fid = req_str(b, "factory_id")
    awarded = req_int(b, "awarded_units", min_v=1)
    fs = req_date(b, "fulfillment_start")
    fe = req_date(b, "fulfillment_end")
    if fe <= fs:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "fulfillment_end must be strictly after fulfillment_start",
        )
    # Family 8 (temporal): closed-interval windows on one factory may not touch.
    for other in DB["contracts"].values():
        if other["factory_id"] == fid and other["status"] in _OPEN_CONTRACT_STATES:
            if fs <= other["fulfillment_end"] and other["fulfillment_start"] <= fe:
                raise ApiError(
                    "ERR_GOV_CONTRACT_WINDOW_CONFLICT",
                    "the fulfillment window intersects another open contract at this factory",
                )
    # Family 9 (structural): contract_number uniqueness.
    if any(c["contract_number"] == number for c in DB["contracts"].values()):
        raise ApiError("ERR_CONTRACT_NUMBER_EXISTS", "contract_number already in use")
    g = base_fields()
    g.update({
        "contract_number": number,
        "model_id": mid,
        "factory_id": fid,
        "awarded_units": awarded,
        "fulfillment_start": fs,
        "fulfillment_end": fe,
        "fulfilled_units": 0,
        "audit_passed": None,
        "status": "AWARDED",
    })
    DB["contracts"][g["id"]] = g
    return ok_obj(serializers.pub(g), 201)


@bp.get("/footwear/gov-contracts")
@require_roles(*constants.ALL_ROLES)
def list_contracts(_uid, _role):
    items = sorted_items(DB["contracts"])
    mid = request.args.get("model_id")
    fid = request.args.get("factory_id")
    status = request.args.get("status")
    if mid is not None:
        items = [g for g in items if g["model_id"] == mid]
    if fid is not None:
        items = [g for g in items if g["factory_id"] == fid]
    if status is not None:
        items = [g for g in items if g["status"] == status]
    return list_response([serializers.pub(g) for g in items])


@bp.get("/footwear/gov-contracts/<gid>")
@require_roles(*constants.ALL_ROLES)
def get_one_contract(gid, _uid, _role):
    return ok_obj(serializers.pub(get_contract(gid)))


@bp.post("/footwear/gov-contracts/<gid>/start-fulfillment")
@require_roles("ComplianceOfficer")
def start_fulfillment(gid, _uid, _role):
    g = get_contract(gid)
    # Family 6 (state).
    if g["status"] != "AWARDED":
        raise ApiError("ERR_INVALID_STATE", "contract must be AWARDED to start fulfillment")
    model = DB["models"][g["model_id"]]
    if model["status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_NOT_ACTIVE", "the contract's model must be ACTIVE")
    factory = DB["factories"][g["factory_id"]]
    if factory["status"] != "ACTIVE":
        raise ApiError("ERR_FACTORY_NOT_ACTIVE", "the contract's factory must be ACTIVE")
    # Family 7 (regulatory), in the pinned family order: Berry 100.00% first,
    # then DOMESTIC_ONLY policy, then cleared domestic factory.
    berry_ok = False
    for rep in DB["reports"].values():
        if rep["variant"] == "CERTIFIED" and rep["status"] == "ACTIVE":
            run = DB["runs"][rep["run_id"]]
            if run["model_id"] == g["model_id"] and run["factory_id"] == g["factory_id"] \
                    and Decimal(str(rep["us_content_pct"])) == constants.BERRY_REQUIRED_PCT:
                berry_ok = True
                break
    if not berry_ok:
        raise ApiError(
            "ERR_BERRY_CONTENT_NOT_PROVEN",
            "no ACTIVE CERTIFIED report with us_content_pct == 100.00 on a run of "
            "this contract's (model_id, factory_id)",
        )
    if model["production_policy"] != "DOMESTIC_ONLY":
        raise ApiError(
            "ERR_POLICY_NOT_DOMESTIC_ONLY",
            "contract start-fulfillment requires a DOMESTIC_ONLY model",
        )
    if not (factory["location_type"] == "DOMESTIC" and factory["government_cleared"]):
        raise ApiError(
            "ERR_FACTORY_NOT_CLEARED",
            "contract start-fulfillment requires a DOMESTIC government-cleared factory",
        )
    g["status"] = "IN_FULFILLMENT"
    touch(g)
    return ok_obj(serializers.pub(g))


@bp.post("/footwear/gov-contracts/<gid>/initiate-audit")
@require_roles("ComplianceOfficer")
def initiate_audit(gid, _uid, _role):
    g = get_contract(gid)
    if g["status"] != "IN_FULFILLMENT":
        raise ApiError("ERR_INVALID_STATE", "contract must be IN_FULFILLMENT to initiate an audit")
    g["status"] = "COMPLIANCE_AUDIT"
    touch(g)
    return ok_obj(serializers.pub(g))


@bp.post("/footwear/gov-contracts/<gid>/complete-audit")
@require_roles("ComplianceOfficer")
def complete_audit(gid, _uid, _role):
    g = get_contract(gid)
    if g["status"] != "COMPLIANCE_AUDIT":
        raise ApiError("ERR_INVALID_STATE", "contract must be COMPLIANCE_AUDIT to complete the audit")
    runs = [
        r for r in DB["runs"].values()
        if r["model_id"] == g["model_id"] and r["factory_id"] == g["factory_id"]
        and r["run_type"] == "GOVERNMENT" and r["status"] == "COMPLETED"
    ]
    fulfilled = sum(r["planned_units"] for r in runs)
    # Pass conditions: fulfilled volume meets the award, every consumed lot
    # carries a VERIFIED unexpired origin cert, and every qualifying run
    # carries a VERIFIED unexpired labor record (lazy expiry applies).
    lots_ok = True
    for r in runs:
        for e in r["consumed_lots"]:
            if not any(
                d for d in DB["docs"].values()
                if d["material_lot_id"] == e["lot_id"]
                and d["doc_type"] == "SUPPLIER_ORIGIN_CERT"
                and cascade.doc_live_verified(d)
            ):
                lots_ok = False
    runs_ok = all(
        any(
            d for d in DB["docs"].values()
            if d["production_run_id"] == r["id"]
            and d["doc_type"] == "ASSEMBLY_LABOR_RECORD"
            and cascade.doc_live_verified(d)
        )
        for r in runs
    )
    passed = fulfilled >= g["awarded_units"] and lots_ok and runs_ok
    g["fulfilled_units"] = fulfilled
    g["audit_passed"] = passed
    g["status"] = "CLOSED" if passed else "DEFAULTED"
    touch(g)
    return ok_obj(serializers.pub(g))
