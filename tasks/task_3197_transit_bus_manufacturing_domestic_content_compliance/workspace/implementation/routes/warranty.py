"""Routes: warranty claims."""
import math
from flask import Blueprint, request
from db import DB, stamp_new, touch, _fmt_logical, _parse_iso
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_fiscal,
    err_deadline, err_sod, err_review_loop,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate
from services.core import warranty_approval_amount, stock_for, update_stock_status

bp = Blueprint("warranty", __name__)

WARRANTY_WINDOW_DAYS = 365


def get_claim_or_404(cid):
    c = DB.claims.get(cid)
    if c is None:
        raise err_not_found("WarrantyClaim not found")
    return c


@bp.post("/api/warranty-claims")
def create_claim():
    require_roles("WarrantyAdmin", "AgencyAdmin")
    body = get_body()
    bus_unit_id = body.get("bus_unit_id")
    defect_code = body.get("defect_code")
    component_id = body.get("component_id")
    claimed = body.get("claimed_amount_cents")
    if bus_unit_id is None:
        raise err_invalid_request("Missing required field: bus_unit_id")
    if defect_code is None:
        raise err_invalid_request("Missing required field: defect_code")
    if component_id is None:
        raise err_invalid_request("Missing required field: component_id")
    if claimed is None:
        raise err_invalid_request("Missing required field: claimed_amount_cents")
    if not isinstance(claimed, int) or isinstance(claimed, bool):
        raise err_invalid_request("claimed_amount_cents must be an integer")
    bus = DB.buses.get(bus_unit_id)
    if bus is None:
        raise err_not_found("BusUnit not found")
    if component_id not in DB.components:
        raise err_not_found("Component not found")
    if claimed <= 0:
        raise err_fiscal("claimed_amount_cents must be positive")
    rec = {
        "bus_unit_id": bus_unit_id,
        "reported_at": _fmt_logical(DB.clock.now()),
        "defect_code": defect_code,
        "component_id": component_id,
        "claimed_amount_cents": claimed,
        "approved_amount_cents": None,
        "status": "FILED",
        "_approved_by": None,
        "_review_loops": 0,
        "_reserved_units": 0,
    }
    stamp_new(rec)
    DB.claims[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/warranty-claims")
def list_claims():
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    limit, offset = parse_pagination(request.args)
    bus_unit_id = request.args.get("bus_unit_id")
    component_id = request.args.get("component_id")
    status = request.args.get("status")
    items = list(DB.claims.values())
    if bus_unit_id is not None:
        items = [c for c in items if c["bus_unit_id"] == bus_unit_id]
    if component_id is not None:
        items = [c for c in items if c["component_id"] == component_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(c) for c in window], limit, offset, total)


@bp.get("/api/warranty-claims/<warrantyClaimId>")
def get_claim(warrantyClaimId):
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    c = get_claim_or_404(warrantyClaimId)
    return success_obj(public(c))


@bp.get("/api/bus-units/<busUnitId>/warranty-claims")
def bus_claims(busUnitId):
    require_roles("PlatformAdmin", "WarrantyAdmin", "AgencyAdmin")
    if busUnitId not in DB.buses:
        raise err_not_found("BusUnit not found")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    items = [c for c in DB.claims.values() if c["bus_unit_id"] == busUnitId]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(c) for c in window], limit, offset, total)


@bp.post("/api/warranty-claims/<warrantyClaimId>/start-review")
def start_review(warrantyClaimId):
    require_roles("WarrantyAdmin")
    c = get_claim_or_404(warrantyClaimId)
    if c["status"] == "APPROVED":
        if c.get("_review_loops", 0) >= 1:
            raise err_review_loop()
        # Release prior stock reservation.
        bus = DB.buses.get(c["bus_unit_id"])
        contract = DB.contracts.get(bus["contract_id"]) if bus else None
        if contract is not None:
            stock = stock_for(contract["agency_id"], c["component_id"])
            if stock is not None:
                stock["reserved_quantity"] = max(0, stock["reserved_quantity"] - c.get("_reserved_units", 0))
                touch(stock)
                update_stock_status(stock)
        c["_reserved_units"] = 0
        c["approved_amount_cents"] = None
        c["_approved_by"] = None
        c["_review_loops"] = c.get("_review_loops", 0) + 1
        c["status"] = "UNDER_REVIEW"
        touch(c)
        return success_obj(public(c))
    if c["status"] != "FILED":
        raise err_invalid_state("Claim is not FILED")
    bus = DB.buses.get(c["bus_unit_id"])
    if bus is None:
        raise err_not_found("BusUnit not found")
    if bus["status"] != "ACCEPTED":
        raise err_invalid_state("Bus is not ACCEPTED")
    # warranty window: reported_at <= delivered_at + 365 days
    from datetime import timedelta
    if bus.get("delivered_at") is not None:
        window_end = _parse_iso(bus["delivered_at"]) + timedelta(days=WARRANTY_WINDOW_DAYS)
        if _parse_iso(c["reported_at"]) > window_end:
            raise err_deadline("Claim reported outside the base warranty window")
    c["status"] = "UNDER_REVIEW"
    touch(c)
    return success_obj(public(c))


@bp.post("/api/warranty-claims/<warrantyClaimId>/approve")
def approve_claim(warrantyClaimId):
    uid, role = require_roles("WarrantyAdmin")
    c = get_claim_or_404(warrantyClaimId)
    if c["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Claim is not UNDER_REVIEW")
    if c["claimed_amount_cents"] <= 0:
        raise err_fiscal("claimed_amount_cents must be positive")
    bus = DB.buses.get(c["bus_unit_id"])
    if bus is None:
        raise err_not_found("BusUnit not found")
    approved = warranty_approval_amount(c, bus)
    c["approved_amount_cents"] = approved
    component = DB.components.get(c["component_id"])
    units = 0
    if component is not None and component["unit_cost_cents"] > 0:
        units = math.ceil(approved / component["unit_cost_cents"])
    contract = DB.contracts.get(bus["contract_id"])
    if contract is not None:
        stock = stock_for(contract["agency_id"], c["component_id"])
        if stock is not None:
            stock["reserved_quantity"] += units
            touch(stock)
            update_stock_status(stock)
    c["_reserved_units"] = units
    c["_approved_by"] = uid
    c["status"] = "APPROVED"
    touch(c)
    return success_obj(public(c))


@bp.post("/api/warranty-claims/<warrantyClaimId>/deny")
def deny_claim(warrantyClaimId):
    require_roles("WarrantyAdmin")
    c = get_claim_or_404(warrantyClaimId)
    if c["status"] != "UNDER_REVIEW":
        raise err_invalid_state("Claim is not UNDER_REVIEW")
    c["status"] = "DENIED"
    touch(c)
    return success_obj(public(c))


@bp.post("/api/warranty-claims/<warrantyClaimId>/pay")
def pay_claim(warrantyClaimId):
    uid, role = require_roles("WarrantyAdmin")
    c = get_claim_or_404(warrantyClaimId)
    if c["status"] != "APPROVED":
        raise err_invalid_state("Claim is not APPROVED")
    if c.get("_approved_by") is not None and uid == c["_approved_by"]:
        raise err_sod("Payer must differ from approver")
    bus = DB.buses.get(c["bus_unit_id"])
    contract = DB.contracts.get(bus["contract_id"]) if bus else None
    if contract is not None:
        stock = stock_for(contract["agency_id"], c["component_id"])
        if stock is not None:
            units = c.get("_reserved_units", 0)
            stock["reserved_quantity"] = max(0, stock["reserved_quantity"] - units)
            stock["quantity"] -= units
            touch(stock)
            update_stock_status(stock)
    c["_reserved_units"] = 0
    c["status"] = "PAID"
    touch(c)
    return success_obj(public(c))


@bp.post("/api/warranty-claims/<warrantyClaimId>/close")
def close_claim(warrantyClaimId):
    require_roles("WarrantyAdmin")
    c = get_claim_or_404(warrantyClaimId)
    if c["status"] != "DENIED":
        raise err_invalid_state("Claim is not DENIED")
    c["status"] = "CLOSED"
    touch(c)
    return success_obj(public(c))
