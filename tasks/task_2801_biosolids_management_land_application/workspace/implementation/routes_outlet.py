"""Alternative outlet and diversion order endpoints (PRD 3.10)."""

from decimal import Decimal

from flask import Blueprint

import store
from auth import roles
from calc import cost_breakdown
from derive import recompute_batch_balance, recompute_outlet_ytd, refresh_facility_storage
from envelope import object_response
from errors import fail
from listing import emit_list
from store import D, now_iso, public, r1, r2, r3, touch
from validate import (get_body, qenum, qstr, resolve_fks, venum, vint, vnum, vstr)

bp = Blueprint("outlets", __name__, url_prefix="/api/v1")

OUTLET_TYPES = ("COMPOST", "LANDFILL", "THERMAL")
OUTLET_STATUSES = ("ACCEPTING", "SUSPENDED", "CLOSED")
ORDER_STATUSES = ("DRAFT", "COMMITTED", "SETTLED", "VOIDED")
OUTLET_READ_ROLES = ("FacilityOperator", "ComplianceOfficer", "Agronomist",
                     "PublicLiaison")
ORDER_READ_ROLES = ("FacilityOperator", "ComplianceOfficer", "PublicLiaison")


def get_outlet(outlet_id):
    outlet = store.outlets.get(outlet_id)
    if outlet is None:
        fail("ERR_OUTLET_NOT_FOUND", "Outlet %s does not exist." % outlet_id)
    return outlet


def get_order(order_id):
    order = store.orders.get(order_id)
    if order is None:
        fail("ERR_ORDER_NOT_FOUND", "Diversion order %s does not exist." % order_id)
    return order


@bp.post("/alternative-outlets")
@roles("FacilityOperator", "ComplianceOfficer")
def create_outlet():
    body = get_body()
    name = vstr(body, "name", required=True, min_len=1, max_len=120)
    outlet_type = venum(body, "outlet_type", OUTLET_TYPES, required=True)
    gate_fee = vnum(body, "gate_fee_per_wet_ton", required=True, ge=0)
    haul_rate = vnum(body, "haul_rate_per_mile_per_wet_ton", required=True, ge=0)
    min_load = vnum(body, "min_load_wet_tons", required=True, ge=0)
    max_annual = vnum(body, "max_annual_wet_tons", required=True, gt=0)
    min_percent_solids = vnum(body, "min_percent_solids", required=False,
                              default=Decimal("0.0"), ge=0, lt=100)
    outlet = store.new_record({
        "name": name,
        "outlet_type": outlet_type,
        "gate_fee_per_wet_ton": gate_fee,
        "haul_rate_per_mile_per_wet_ton": haul_rate,
        "min_load_wet_tons": r2(min_load),
        "max_annual_wet_tons": max_annual,
        "min_percent_solids": min_percent_solids,
        "status": "ACCEPTING",
        "ytd_accepted_wet_tons": r2(0),
        "updated_at": now_iso(),
        "version": 1,
    })
    store.outlets[outlet["id"]] = outlet
    return object_response(public(outlet), 201)


@bp.get("/alternative-outlets/<outlet_id>")
@roles(*OUTLET_READ_ROLES)
def read_outlet(outlet_id):
    return object_response(public(get_outlet(outlet_id)))


@bp.get("/alternative-outlets")
@roles(*OUTLET_READ_ROLES)
def list_outlets():
    outlet_type = qenum("outlet_type", OUTLET_TYPES)
    status = qenum("status", OUTLET_STATUSES)
    rows = [o for o in store.outlets.values()
            if (outlet_type is None or o["outlet_type"] == outlet_type)
            and (status is None or o["status"] == status)]
    return emit_list(rows, ("created_at",))


@bp.post("/alternative-outlets/<outlet_id>/set-status")
@roles("ComplianceOfficer")
def set_outlet_status(outlet_id):
    outlet = get_outlet(outlet_id)
    body = get_body()
    status = venum(body, "status", OUTLET_STATUSES, required=True)
    outlet["status"] = status
    touch(outlet)
    return object_response(public(outlet))


@bp.post("/diversion-orders")
@roles("FacilityOperator")
def create_order():
    body = get_body()
    fks = resolve_fks(body, ("batch_id", "outlet_id"))
    for key in ("batch_id", "outlet_id"):
        value = body.get(key)
        if not isinstance(value, str) or not value.strip():
            fail("ERR_INVALID_REQUEST", "Field '%s' is required." % key)
    batch = fks["batch_id"]
    outlet = fks["outlet_id"]
    expected_batch_version = vint(body, "expected_batch_version", required=True)
    dry_tons = vnum(body, "dry_tons", required=True, gt=0)
    wet_tons = vnum(body, "wet_tons", required=True, gt=0)
    haul_miles = vnum(body, "haul_miles", required=True, gt=0)

    if expected_batch_version != batch["version"]:
        fail("ERR_STALE_BATCH_VERSION",
             "Batch version is %d but expected_batch_version was %d."
             % (batch["version"], expected_batch_version))
    dry_tons = r3(dry_tons)
    wet_tons = r2(wet_tons)
    haul_miles = r1(haul_miles)
    if dry_tons > D(batch["unallocated_dry_tons"]):
        fail("ERR_INSUFFICIENT_UNALLOCATED_TONS",
             "dry_tons exceeds the batch unallocated_dry_tons.")

    costs = cost_breakdown(wet_tons, dry_tons, haul_miles, outlet)
    order = store.new_record({
        "batch_id": batch["id"],
        "outlet_id": outlet["id"],
        "dry_tons": dry_tons,
        "wet_tons": wet_tons,
        "haul_miles": haul_miles,
        "processing_cost": costs["processing_cost"],
        "hauling_cost": costs["hauling_cost"],
        "subtotal_cost": costs["subtotal_cost"],
        "surcharge_pct": costs["surcharge_pct"],
        "surcharge_cost": costs["surcharge_cost"],
        "total_cost": costs["total_cost"],
        "cost_per_dry_ton": costs["cost_per_dry_ton"],
        "status": "DRAFT",
        "committed_at": None,
        "settled_at": None,
        "void_reason": None,
        "updated_at": now_iso(),
        "version": 1,
    })
    store.orders[order["id"]] = order
    recompute_batch_balance(batch)
    touch(batch)
    return object_response(public(order), 201)


@bp.get("/diversion-orders/<order_id>")
@roles(*ORDER_READ_ROLES)
def read_order(order_id):
    return object_response(public(get_order(order_id)))


@bp.get("/diversion-orders")
@roles(*ORDER_READ_ROLES)
def list_orders():
    batch_id = qstr("batch_id")
    outlet_id = qstr("outlet_id")
    status = qenum("status", ORDER_STATUSES)
    rows = [o for o in store.orders.values()
            if (batch_id is None or o["batch_id"] == batch_id)
            and (outlet_id is None or o["outlet_id"] == outlet_id)
            and (status is None or o["status"] == status)]
    return emit_list(rows, ("created_at",))


@bp.post("/diversion-orders/<order_id>/commit")
@roles("FacilityOperator", "ComplianceOfficer")
def commit_order(order_id):
    order = get_order(order_id)
    get_body()
    if order["status"] != "DRAFT":
        fail("ERR_ORDER_INVALID_STATE", "Only a DRAFT order may be committed.")
    outlet = store.outlets.get(order["outlet_id"])
    batch = store.batches.get(order["batch_id"])
    if outlet["status"] != "ACCEPTING":
        fail("ERR_OUTLET_NOT_ACCEPTING", "The outlet is not ACCEPTING.")
    if (D(order["wet_tons"]) < D(outlet["min_load_wet_tons"])
            or D(batch["percent_solids"]) < D(outlet["min_percent_solids"])):
        fail("ERR_OUTLET_ACCEPTANCE_CRITERIA",
             "The order does not meet the outlet acceptance criteria.")
    current_ytd = recompute_outlet_ytd(outlet)
    if current_ytd + D(order["wet_tons"]) > D(outlet["max_annual_wet_tons"]):
        fail("ERR_OUTLET_ANNUAL_CAP_EXCEEDED",
             "The order exceeds the outlet annual acceptance cap.")
    order["status"] = "COMMITTED"
    order["committed_at"] = now_iso()
    touch(order)
    recompute_outlet_ytd(outlet)
    touch(outlet)
    return object_response(public(order))


@bp.post("/diversion-orders/<order_id>/settle")
@roles("FacilityOperator", "ComplianceOfficer")
def settle_order(order_id):
    order = get_order(order_id)
    get_body()
    if order["status"] != "COMMITTED":
        fail("ERR_ORDER_INVALID_STATE", "Only a COMMITTED order may be settled.")
    order["status"] = "SETTLED"
    order["settled_at"] = now_iso()
    touch(order)
    batch = store.batches.get(order["batch_id"])
    facility = store.facilities.get(batch["facility_id"]) if batch else None
    if facility is not None:
        refresh_facility_storage(facility)
    return object_response(public(order))


@bp.post("/diversion-orders/<order_id>/void")
@roles("ComplianceOfficer")
def void_order(order_id):
    order = get_order(order_id)
    body = get_body()
    void_reason = vstr(body, "void_reason", required=True, min_len=1)
    if order["status"] not in ("DRAFT", "COMMITTED"):
        fail("ERR_ORDER_INVALID_STATE",
             "Only a DRAFT or COMMITTED order may be voided.")
    was_committed = order["status"] == "COMMITTED"
    order["status"] = "VOIDED"
    order["void_reason"] = void_reason
    touch(order)
    batch = store.batches.get(order["batch_id"])
    if batch is not None:
        recompute_batch_balance(batch)
        touch(batch)
    if was_committed:
        outlet = store.outlets.get(order["outlet_id"])
        if outlet is not None:
            recompute_outlet_ytd(outlet)
            touch(outlet)
    return object_response(public(order))


@bp.get("/diversion-orders/<order_id>/cost-comparison")
@roles("FacilityOperator", "ComplianceOfficer")
def cost_comparison(order_id):
    order = get_order(order_id)
    candidates = [o for o in store.outlets.values() if o["status"] == "ACCEPTING"]
    options = []
    for outlet in candidates:
        breakdown = cost_breakdown(order["wet_tons"], order["dry_tons"],
                                   order["haul_miles"], outlet)
        option = {
            "outlet_id": outlet["id"],
            "name": outlet["name"],
            "outlet_type": outlet["outlet_type"],
        }
        option.update(breakdown)
        option["_created_at"] = outlet["created_at"]
        option["_seq"] = outlet["_seq"]
        options.append(option)
    options.sort(key=lambda o: (o["cost_per_dry_ton"], o["_created_at"], o["_seq"]))
    for option in options:
        option.pop("_created_at", None)
        option.pop("_seq", None)
    recommended = options[0]["outlet_id"] if options else None
    return object_response({
        "order_id": order["id"],
        "batch_id": order["batch_id"],
        "dry_tons": order["dry_tons"],
        "wet_tons": order["wet_tons"],
        "recommended_outlet_id": recommended,
        "options": options,
    })
