"""Vehicle order endpoints (PRD section 3.5)."""

from flask import Blueprint

import calc
import errors as E
import store
from errors import ApiError
from store import DB
from util import (auth, require_role, check_ownership, body, req_field, as_str,
                  as_int, as_enum, as_bool, find, ok, ok_list)

bp = Blueprint("orders", __name__)

_ORDER_READ_ROLES = {"PlatformAdmin", "FleetManager", "ComplianceOfficer",
                     "ProductionPlanner"}


@bp.post("/evfleet/vehicle-orders")
def create_vehicle_order():
    uid, role = auth()
    require_role(role, {"FleetManager"})
    b = body()
    fleet_customer_id = as_str(req_field(b, "fleet_customer_id"), "fleet_customer_id")
    depot_id = as_str(req_field(b, "depot_id"), "depot_id")
    battery_supplier_id = as_str(req_field(b, "battery_supplier_id"),
                                 "battery_supplier_id")
    # priority 3: body FK existence
    find(DB.customers, fleet_customer_id, "fleet customer")
    find(DB.depots, depot_id, "depot")
    find(DB.suppliers, battery_supplier_id, "supplier")
    # priority 4: ownership
    check_ownership(uid, fleet_customer_id)
    # priority 10: shape
    quantity = as_int(req_field(b, "quantity"), "quantity")
    if not (1 <= quantity <= 500):
        raise ApiError(E.ERR_VALIDATION, 400, "quantity must be in 1..500")
    battery_pack_kwh = as_int(req_field(b, "battery_pack_kwh"), "battery_pack_kwh")
    if battery_pack_kwh not in (52, 77):
        raise ApiError(E.ERR_VALIDATION, 400, "battery_pack_kwh must be one of {52, 77}")
    telematics_tier = as_enum(req_field(b, "telematics_tier"),
                              {"STANDARD", "ADVANCED"}, "telematics_tier")
    delivery_method = as_enum(req_field(b, "delivery_method"),
                              {"DIRECT_DELIVERY", "CUSTOMER_PICKUP"}, "delivery_method")
    requires_depot_charging = as_bool(req_field(b, "requires_depot_charging"),
                                      "requires_depot_charging")
    e = {
        "fleet_customer_id": fleet_customer_id,
        "depot_id": depot_id,
        "battery_supplier_id": battery_supplier_id,
        "quantity": quantity,
        "battery_pack_kwh": battery_pack_kwh,
        "telematics_tier": telematics_tier,
        "delivery_method": delivery_method,
        "requires_depot_charging": requires_depot_charging,
        "status": "DRAFT",
        "exemption_document_ref": None,
        "promised_delivery_date": None,
        "supply_risk_flag": False,
        "registered_count": 0,
        "hold_count": 0,
    }
    store.stamp_new(e)
    DB.orders[e["id"]] = e
    return ok(store.public(e), 201)


@bp.get("/evfleet/vehicle-orders/<oid>")
def get_vehicle_order(oid):
    _, role = auth()
    require_role(role, _ORDER_READ_ROLES)
    e = find(DB.orders, oid, "vehicle order")
    return ok(store.public(e), 200)


@bp.get("/evfleet/vehicle-orders")
def list_vehicle_orders():
    from flask import request
    _, role = auth()
    require_role(role, _ORDER_READ_ROLES)
    items = list(DB.orders.values())
    fc = request.args.get("fleet_customer_id")
    if fc is not None:
        items = [o for o in items if o["fleet_customer_id"] == fc]
    dp = request.args.get("depot_id")
    if dp is not None:
        items = [o for o in items if o["depot_id"] == dp]
    bs = request.args.get("battery_supplier_id")
    if bs is not None:
        items = [o for o in items if o["battery_supplier_id"] == bs]
    return ok_list(items)


_TRANSITION_ROLE_STATES = {
    "FleetManager": {"SUBMITTED", "CANCELLED"},
    "ComplianceOfficer": {"CONFIRMED", "FRANCHISE_HOLD"},
}


@bp.post("/evfleet/vehicle-orders/<oid>/transition")
def transition_vehicle_order(oid):
    uid, role = auth()
    # priority 2: role listed, and to_state restricts which listed role may act
    if role not in _TRANSITION_ROLE_STATES:
        raise ApiError(E.ERR_FORBIDDEN, 403,
                       "role %s is not permitted for this endpoint" % role)
    b = body()
    to_state = as_str(req_field(b, "to_state"), "to_state")
    if to_state not in _TRANSITION_ROLE_STATES[role]:
        raise ApiError(E.ERR_FORBIDDEN, 403,
                       "role %s may not drive to_state %s" % (role, to_state))
    # priority 3
    order = find(DB.orders, oid, "vehicle order")
    # priority 4: ownership for the FleetManager-driven transitions
    if role == "FleetManager":
        check_ownership(uid, order["fleet_customer_id"])
    # priority 6: terminal lockdown, then state preconditions
    if order["status"] in ("FULFILLED", "CANCELLED"):
        raise ApiError(E.ERR_ALREADY_TERMINAL, 409,
                       "vehicle order is in terminal state %s" % order["status"])
    st = order["status"]
    if to_state == "SUBMITTED":
        if st != "DRAFT":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "SUBMITTED is offered from DRAFT")
    elif to_state == "FRANCHISE_HOLD":
        if st != "SUBMITTED":
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "FRANCHISE_HOLD is offered from SUBMITTED")
    elif to_state == "CANCELLED":
        if st not in ("DRAFT", "SUBMITTED", "FRANCHISE_HOLD"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "cancellation is not offered from %s" % st)
    elif to_state == "CONFIRMED":
        if st not in ("SUBMITTED", "FRANCHISE_HOLD"):
            raise ApiError(E.ERR_INVALID_STATE, 409,
                           "CONFIRMED is offered from SUBMITTED or FRANCHISE_HOLD")
        # priority 8: franchise law
        depot = DB.depots[order["depot_id"]]
        if (depot["state_code"] in calc.FRANCHISE_BLOCKED_STATES
                and order["delivery_method"] == "DIRECT_DELIVERY"):
            ref = b.get("exemption_document_ref")
            if not isinstance(ref, str) or ref == "":
                raise ApiError(
                    E.ERR_FRANCHISE_EXEMPTION_REQUIRED, 422,
                    "DIRECT_DELIVERY into a franchise-blocked state requires a "
                    "non-empty exemption_document_ref")
    # side effects
    if to_state == "CONFIRMED":
        ref = b.get("exemption_document_ref")
        if isinstance(ref, str):
            order["exemption_document_ref"] = ref
        order["promised_delivery_date"] = calc.promise_date(store.now(),
                                                            order["quantity"])
    order["status"] = to_state
    store.touch(order)
    return ok(store.public(order), 200)
