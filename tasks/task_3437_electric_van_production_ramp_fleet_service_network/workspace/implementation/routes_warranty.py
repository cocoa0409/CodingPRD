"""Warranty claim endpoints (PRD section 3.11)."""

from flask import Blueprint, request

import calc
import errors as E
import store
from errors import ApiError
from store import DB
from util import (auth, require_role, check_ownership, body, req_field, as_str,
                  as_int, as_num, as_enum, find, ok, ok_list)

bp = Blueprint("warranty", __name__)

_CLAIM_READ_ROLES = {"PlatformAdmin", "FleetManager", "ServiceTechnician",
                     "ClaimsAdjuster"}

_COMPONENT_CLASSES = {"BATTERY", "POWERTRAIN", "CHARGING", "BODY"}


@bp.post("/evfleet/warranty-claims")
def create_warranty_claim():
    uid, role = auth()
    require_role(role, {"FleetManager"})
    b = body()
    vehicle_id = as_str(req_field(b, "vehicle_id"), "vehicle_id")
    # priority 3: existence — vehicle, then the optional referenced visit
    vehicle = find(DB.vehicles, vehicle_id, "vehicle")
    visit_id = b.get("service_visit_id")
    visit = None
    if visit_id is not None:
        as_str(visit_id, "service_visit_id")
        visit = find(DB.visits, visit_id, "service visit")
    # priority 4: ownership follows the vehicle's order customer
    order = DB.orders[vehicle["vehicle_order_id"]]
    check_ownership(uid, order["fleet_customer_id"])
    # priority 10: shape — non-empty claim lines with valid entries
    raw_lines = req_field(b, "claim_lines")
    if not isinstance(raw_lines, list) or len(raw_lines) == 0:
        raise ApiError(E.ERR_VALIDATION, 400, "claim_lines must be a non-empty list")
    lines = []
    for ln in raw_lines:
        if not isinstance(ln, dict):
            raise ApiError(E.ERR_VALIDATION, 400, "each claim line must be an object")
        component_class = as_enum(req_field(ln, "component_class"),
                                  _COMPONENT_CLASSES, "component_class")
        part_cost_cents = as_int(req_field(ln, "part_cost_cents"), "part_cost_cents")
        if part_cost_cents < 0:
            raise ApiError(E.ERR_VALIDATION, 400, "part_cost_cents must be >= 0")
        labor_hours = as_num(req_field(ln, "labor_hours"), "labor_hours")
        if calc.D(labor_hours) < 0:
            raise ApiError(E.ERR_VALIDATION, 400, "labor_hours must be >= 0")
        lines.append({
            "component_class": component_class,
            "part_cost_cents": part_cost_cents,
            "labor_hours": labor_hours,
        })
    # priority 13: cross-entity references
    if vehicle["delivery_status"] != "COMMISSIONED":
        raise ApiError(E.ERR_VEHICLE_NOT_IN_SERVICE, 409,
                       "warranty claims require a COMMISSIONED vehicle")
    if visit is not None:
        if visit["vehicle_id"] != vehicle_id or visit["status"] != "COMPLETED":
            raise ApiError(E.ERR_SERVICE_VISIT_NOT_COMPLETED, 422,
                           "referenced visit must belong to the same vehicle and "
                           "be COMPLETED")
    e = {
        "vehicle_id": vehicle_id,
        "service_visit_id": visit_id,
        "claim_lines": lines,
        "status": "SUBMITTED",
        "diagnosed_by_user_id": None,
        "diagnosis_notes": None,
        "adjudicated_by_user_id": None,
        "settlement_cents": None,
        "denial_reason": None,
    }
    store.stamp_new(e)
    DB.claims[e["id"]] = e
    return ok(store.public(e), 201)


@bp.get("/evfleet/warranty-claims/<cid>")
def get_warranty_claim(cid):
    _, role = auth()
    require_role(role, _CLAIM_READ_ROLES)
    e = find(DB.claims, cid, "warranty claim")
    return ok(store.public(e), 200)


@bp.get("/evfleet/warranty-claims")
def list_warranty_claims():
    _, role = auth()
    require_role(role, _CLAIM_READ_ROLES)
    items = list(DB.claims.values())
    vh = request.args.get("vehicle_id")
    if vh is not None:
        items = [c for c in items if c["vehicle_id"] == vh]
    sv = request.args.get("service_visit_id")
    if sv is not None:
        items = [c for c in items if c["service_visit_id"] == sv]
    return ok_list(items)


@bp.post("/evfleet/warranty-claims/<cid>/diagnose")
def diagnose_warranty_claim(cid):
    uid, role = auth()
    require_role(role, {"ServiceTechnician"})
    claim = find(DB.claims, cid, "warranty claim")
    # priority 6: terminal lockdown, then state preconditions
    if claim["status"] in ("SETTLED", "DENIED"):
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                       "warranty claim is in terminal state %s" % claim["status"])
    if claim["status"] != "SUBMITTED":
        raise ApiError(E.ERR_INVALID_STATE, 409,
                       "diagnosis is offered from SUBMITTED")
    notes = body().get("diagnosis_notes")
    if not isinstance(notes, str) or notes == "":
        raise ApiError(E.ERR_VALIDATION, 400, "diagnosis_notes must be non-empty")
    claim["diagnosed_by_user_id"] = uid
    claim["diagnosis_notes"] = notes
    claim["status"] = "DIAGNOSED"
    store.touch(claim)
    return ok(store.public(claim), 200)


@bp.post("/evfleet/warranty-claims/<cid>/adjudicate")
def adjudicate_warranty_claim(cid):
    uid, role = auth()
    require_role(role, {"ClaimsAdjuster"})
    claim = find(DB.claims, cid, "warranty claim")
    # priority 6: terminal lockdown, then the diagnosed precondition
    if claim["status"] in ("SETTLED", "DENIED"):
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                       "warranty claim is in terminal state %s" % claim["status"])
    if claim["status"] == "SUBMITTED":
        raise ApiError(E.ERR_CLAIM_NOT_DIAGNOSED, 409,
                       "adjudication requires a DIAGNOSED claim")
    # priority 7: segregation — adjudicator != diagnostician
    if uid == claim["diagnosed_by_user_id"]:
        raise ApiError(E.ERR_SEGREGATION_VIOLATION, 403,
                       "the diagnostician may not adjudicate their own claim")
    b = body()
    decision = as_enum(req_field(b, "decision"), {"APPROVE", "DENY"}, "decision")
    if decision == "DENY":
        reason = b.get("denial_reason")
        if not isinstance(reason, str) or reason == "":
            raise ApiError(E.ERR_VALIDATION, 400, "denial_reason must be non-empty")
        claim["denial_reason"] = reason
        claim["status"] = "DENIED"
    else:
        claim["settlement_cents"] = calc.warranty_settlement(claim["claim_lines"])
        claim["status"] = "SETTLED"
    claim["adjudicated_by_user_id"] = uid
    store.touch(claim)
    return ok(store.public(claim), 200)
