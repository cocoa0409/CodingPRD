"""Machine orders (two parallel status dimensions) and long-lead procurement
(PRD 3.3, 3.4)."""
from flask import Blueprint, g

import auth
import calc
import domain
import envelope
import store
import validation
from errors import ApiError

bp = Blueprint("orders", __name__)

FULFILLMENT_STATUSES = ("DRAFT", "ENGINEERED", "SLOTTED", "IN_BUILD", "FAT_PASSED",
                        "FAT_FAILED", "SHIPPED", "INSTALLED", "ACCEPTED", "CANCELLED")
COMMERCIAL_STATUSES = ("QUOTED", "PO_RECEIVED", "INVOICED", "PAID", "WRITTEN_OFF")
COMPONENT_STATUSES = ("PLANNED", "ON_ORDER", "RECEIVED")
ORDER_READERS = ("ApplicationEngineer", "ProductionPlanner", "QualityInspector",
                 "ServiceManager", "PlatformAdmin", "CustomerContact")
INVOICE_READY = ("FAT_PASSED", "SHIPPED", "INSTALLED", "ACCEPTED")
PO_REACHED = ("PO_RECEIVED", "INVOICED", "PAID")


# --------------------------------------------------------------------------
# machine orders
# --------------------------------------------------------------------------
@bp.post("/machine-orders")
def create_machine_order():
    auth.authorize(("ApplicationEngineer",))
    payload = validation.body()
    customer_id = validation.req_str(payload, "customer_id", 1, None)
    machine_model_id = validation.req_str(payload, "machine_model_id", 1, None)
    product_trial_id = validation.req_str(payload, "product_trial_id", 1, None)
    equipment_price_cents = validation.req_int(payload, "equipment_price_cents", 0)
    change_parts_price_cents = validation.opt_int(
        payload, "change_parts_price_cents", 0, None, 0)
    guarantee_basis = validation.opt_enum(
        payload, "guarantee_basis", ("NAMEPLATE", "PRODUCT_ADJUSTED"), "NAMEPLATE")
    customer = domain.must_get("customers", customer_id)
    domain.must_get("machine_models", machine_model_id)
    domain.must_get("product_trials", product_trial_id)
    if customer["status"] != "ACTIVE":
        raise ApiError("ERR_CUSTOMER_SUSPENDED",
                       "The buying customer is suspended.")
    row = store.insert("machine_orders", {
        "customer_id": customer_id,
        "machine_model_id": machine_model_id,
        "product_trial_id": product_trial_id,
        "fulfillment_status": "DRAFT",
        "commercial_status": "QUOTED",
        "guarantee_basis": guarantee_basis,
        "equipment_price_cents": equipment_price_cents,
        "change_parts_price_cents": change_parts_price_cents,
        "discount_tier": "NONE",
        "commissioning_fee_cents": 0,
        "order_total_cents": 0,
        "rework_days": 0,
        "fat_failure_count": 0,
    })
    domain.recompute_customer_open_orders(customer)
    return envelope.created(row)


@bp.get("/machine-orders")
def list_machine_orders():
    auth.authorize(ORDER_READERS)
    limit, offset = validation.pagination()
    filters = {
        "customer_id": validation.query_str("customer_id"),
        "machine_model_id": validation.query_str("machine_model_id"),
        "product_trial_id": validation.query_str("product_trial_id"),
        "fulfillment_status": validation.query_enum("fulfillment_status",
                                                    FULFILLMENT_STATUSES),
        "commercial_status": validation.query_enum("commercial_status",
                                                   COMMERCIAL_STATUSES),
    }
    items = [row for row in store.rows("machine_orders")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/machine-orders/<machine_order_id>")
def read_machine_order(machine_order_id):
    auth.authorize(ORDER_READERS)
    order = domain.must_get("machine_orders", machine_order_id)
    auth.require_owner(g.role, g.user_id, order["customer_id"])
    return envelope.ok(order)


@bp.post("/machine-orders/<machine_order_id>/engineer")
def engineer_machine_order(machine_order_id):
    auth.authorize(("ApplicationEngineer",))
    order = domain.must_get("machine_orders", machine_order_id)
    model = domain.order_model(order)
    trial = store.get("product_trials", order["product_trial_id"])
    # ladder: 7 model obsolete, 9 trial not passed, 11 order state, 55 mismatch
    if model["lifecycle_status"] != "ACTIVE":
        raise ApiError("ERR_MODEL_OBSOLETE", "The configured model is obsolete.")
    if trial is None or trial["status"] != "PASSED":
        raise ApiError("ERR_TRIAL_NOT_PASSED",
                       "The cited product trial has not passed.")
    if order["fulfillment_status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Only a DRAFT order may be released to engineering.")
    if (trial["customer_id"] != order["customer_id"]
            or trial["machine_model_id"] != order["machine_model_id"]):
        raise ApiError("ERR_TRIAL_ORDER_MISMATCH",
                       "The cited trial does not match this order's customer "
                       "and model.")
    tier, fee, total = calc.order_total_rollup(
        int(order["equipment_price_cents"]), int(order["change_parts_price_cents"]))
    order["discount_tier"] = tier
    order["commissioning_fee_cents"] = fee
    order["order_total_cents"] = total
    order["fulfillment_status"] = "ENGINEERED"
    store.touch(order)
    domain.recompute_customer_open_orders(domain.order_customer(order))
    return envelope.ok(order)


@bp.post("/machine-orders/<machine_order_id>/commercial-advance")
def commercial_advance(machine_order_id):
    auth.authorize(("PlatformAdmin",))
    payload = validation.body()
    target = validation.req_enum(payload, "target_status", COMMERCIAL_STATUSES)
    order = domain.must_get("machine_orders", machine_order_id)
    current = order["commercial_status"]
    fulfillment = order["fulfillment_status"]
    if target == "PO_RECEIVED":
        if current != "QUOTED" or fulfillment in ("DRAFT", "CANCELLED"):
            raise ApiError("ERR_INVALID_ORDER_STATE",
                           "A purchase order cannot be booked from %s / %s."
                           % (current, fulfillment))
    elif target == "INVOICED":
        if current != "PO_RECEIVED" or fulfillment not in INVOICE_READY:
            raise ApiError("ERR_INVALID_ORDER_STATE",
                           "The order cannot be invoiced from %s / %s."
                           % (current, fulfillment))
    elif target in ("PAID", "WRITTEN_OFF"):
        if current != "INVOICED":
            raise ApiError("ERR_INVALID_ORDER_STATE",
                           "The order cannot move to %s from %s."
                           % (target, current))
    else:
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "No commercial transition targets %s." % target)
    order["commercial_status"] = target
    store.touch(order)
    return envelope.ok(order)


@bp.post("/machine-orders/<machine_order_id>/ship")
def ship_machine_order(machine_order_id):
    auth.authorize(("ProductionPlanner",))
    order = domain.must_get("machine_orders", machine_order_id)
    if order["fulfillment_status"] != "FAT_PASSED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Only a FAT_PASSED order may be shipped.")
    if order["commercial_status"] not in PO_REACHED:
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "The money track has not reached PO_RECEIVED.")
    components = domain.children("long_lead_components", "machine_order_id",
                                 order["id"])
    if any(component["status"] != "RECEIVED" for component in components):
        raise ApiError("ERR_COMPONENTS_NOT_RECEIVED",
                       "Not every long-lead component has been received.")
    domain.set_order_fulfillment(order, "SHIPPED")
    return envelope.ok(order)


# --------------------------------------------------------------------------
# long-lead components
# --------------------------------------------------------------------------
@bp.post("/long-lead-components")
def create_long_lead_component():
    auth.authorize(("ProductionPlanner",))
    payload = validation.body()
    machine_order_id = validation.req_str(payload, "machine_order_id", 1, None)
    part_number = validation.req_str(payload, "part_number", 1, 40)
    lead_time_days = validation.req_int(payload, "lead_time_days", 0)
    domain.must_get("machine_orders", machine_order_id)
    row = store.insert("long_lead_components", {
        "machine_order_id": machine_order_id,
        "part_number": part_number,
        "lead_time_days": lead_time_days,
        "po_released_on": None,
        "promised_date": None,
        "status": "PLANNED",
    })
    return envelope.created(row)


@bp.get("/long-lead-components")
def list_long_lead_components():
    auth.authorize(("ProductionPlanner", "ApplicationEngineer", "PlatformAdmin"))
    limit, offset = validation.pagination()
    filters = {
        "machine_order_id": validation.query_str("machine_order_id"),
        "status": validation.query_enum("status", COMPONENT_STATUSES),
    }
    items = [row for row in store.rows("long_lead_components")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/long-lead-components/<component_id>")
def read_long_lead_component(component_id):
    auth.authorize(("ProductionPlanner", "ApplicationEngineer", "PlatformAdmin"))
    return envelope.ok(domain.must_get("long_lead_components", component_id))


@bp.post("/long-lead-components/<component_id>/release-po")
def release_po(component_id):
    auth.authorize(("ProductionPlanner",))
    component = domain.must_get("long_lead_components", component_id)
    order = store.get("machine_orders", component["machine_order_id"])
    if component["status"] != "PLANNED":
        raise ApiError("ERR_INVALID_COMPONENT_STATE",
                       "Only a PLANNED procurement line may release its "
                       "purchase order.")
    if order is None or order["fulfillment_status"] in ("DRAFT", "CANCELLED"):
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "The order is not in a state that admits procurement.")
    released_on = store.fmt_date(store.today())
    component["po_released_on"] = released_on
    component["promised_date"] = store.add_days(
        released_on, int(component["lead_time_days"]))
    component["status"] = "ON_ORDER"
    store.touch(component)
    return envelope.ok(component)


@bp.post("/long-lead-components/<component_id>/receive")
def receive_component(component_id):
    auth.authorize(("ProductionPlanner",))
    component = domain.must_get("long_lead_components", component_id)
    if component["status"] != "ON_ORDER":
        raise ApiError("ERR_INVALID_COMPONENT_STATE",
                       "Only an ON_ORDER procurement line may be received.")
    promised = component["promised_date"]
    if promised is not None and store.today() < store.parse_date(promised):
        raise ApiError("ERR_COMPONENT_NOT_DUE",
                       "The component is not due until %s." % promised)
    component["status"] = "RECEIVED"
    store.touch(component)
    return envelope.ok(component)
