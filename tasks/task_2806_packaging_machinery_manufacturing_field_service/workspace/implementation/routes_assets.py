"""Installed machines, aftermarket format kits and spare-parts stocking
recommendations (PRD 3.6, 3.7)."""
from flask import Blueprint, g

import auth
import calc
import domain
import envelope
import store
import validation
from errors import ApiError

bp = Blueprint("assets", __name__)

MACHINE_READERS = ("ServiceManager", "QualityInspector", "PlatformAdmin",
                   "CustomerContact")
KIT_READERS = ("ServiceManager", "PlatformAdmin", "CustomerContact")
KIT_STATUSES = ("DRAFT", "QUOTED", "ORDERED", "DELIVERED")
RECOMMENDATION_STATUSES = ("ACTIVE", "SUPERSEDED")


# --------------------------------------------------------------------------
# installed machines
# --------------------------------------------------------------------------
@bp.post("/installed-machines")
def create_installed_machine():
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    machine_order_id = validation.req_str(payload, "machine_order_id", 1, None)
    customer_id = validation.req_str(payload, "customer_id", 1, None)
    serial_number = validation.req_str(payload, "serial_number", 4, 32)
    remote_diagnostics_enabled = validation.opt_bool(
        payload, "remote_diagnostics_enabled", False)
    order = domain.must_get("machine_orders", machine_order_id)
    domain.must_get("customers", customer_id)
    if order["fulfillment_status"] != "SHIPPED":
        raise ApiError("ERR_INVALID_ORDER_STATE",
                       "Only a SHIPPED order may be recorded as installed.")
    for existing in store.rows("installed_machines"):
        if existing["serial_number"] == serial_number:
            raise ApiError("ERR_DUPLICATE_IDENTIFIER",
                           "serial_number '%s' already exists." % serial_number)
    if customer_id != order["customer_id"]:
        raise ApiError("ERR_MACHINE_ORDER_CUSTOMER_MISMATCH",
                       "The asset owner is not the order's buyer.")
    trial = store.get("product_trials", order["product_trial_id"])
    row = store.insert("installed_machines", {
        "machine_order_id": order["id"],
        "customer_id": customer_id,
        "serial_number": serial_number,
        "current_format_family": trial["container_family"] if trial else None,
        "remote_diagnostics_enabled": remote_diagnostics_enabled,
        "status": "INSTALLED",
        "open_claim_count": 0,
    })
    domain.set_order_fulfillment(order, "INSTALLED")
    return envelope.created(row)


@bp.get("/installed-machines")
def list_installed_machines():
    auth.authorize(MACHINE_READERS)
    limit, offset = validation.pagination()
    filters = {
        "machine_order_id": validation.query_str("machine_order_id"),
        "customer_id": validation.query_str("customer_id"),
        "status": validation.query_enum("status", ("INSTALLED", "ACCEPTED")),
    }
    items = [row for row in store.rows("installed_machines")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/installed-machines/<installed_machine_id>")
def read_installed_machine(installed_machine_id):
    auth.authorize(MACHINE_READERS)
    return envelope.ok(domain.must_get("installed_machines", installed_machine_id))


# --------------------------------------------------------------------------
# format kits
# --------------------------------------------------------------------------
def _components(payload):
    raw = validation.opt_list(payload, "components", [])
    components = []
    for index, element in enumerate(raw):
        if not isinstance(element, dict):
            raise validation.invalid(
                "components[%d] must be an object." % index)
        components.append({
            "part_number": validation.req_str(element, "part_number", 1, 40),
            "lead_time_days": validation.req_int(element, "lead_time_days", 0),
            "unit_price_cents": validation.req_int(element, "unit_price_cents", 0),
            "qty": validation.req_int(element, "qty", 1),
        })
    return components


@bp.post("/format-kits")
def create_format_kit():
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    installed_machine_id = validation.req_str(payload, "installed_machine_id",
                                              1, None)
    container_family = validation.req_str(payload, "container_family", 1, 32)
    container_diameter_mm = validation.req_int(payload, "container_diameter_mm", 1)
    components = _components(payload)
    domain.must_get("installed_machines", installed_machine_id)
    row = store.insert("format_kits", {
        "installed_machine_id": installed_machine_id,
        "container_family": container_family,
        "container_diameter_mm": container_diameter_mm,
        "components": components,
        "component_count": len(components),
        "quoted_lead_time_days": 0,
        "price_cents": 0,
        "status": "DRAFT",
        "_ordered_on": None,
    })
    return envelope.created(row)


@bp.get("/format-kits")
def list_format_kits():
    auth.authorize(KIT_READERS)
    limit, offset = validation.pagination()
    filters = {
        "installed_machine_id": validation.query_str("installed_machine_id"),
        "status": validation.query_enum("status", KIT_STATUSES),
    }
    items = [row for row in store.rows("format_kits")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/format-kits/<format_kit_id>")
def read_format_kit(format_kit_id):
    auth.authorize(KIT_READERS)
    return envelope.ok(domain.must_get("format_kits", format_kit_id))


@bp.post("/format-kits/<format_kit_id>/quote")
def quote_format_kit(format_kit_id):
    auth.authorize(("ServiceManager",))
    kit = domain.must_get("format_kits", format_kit_id)
    machine = store.get("installed_machines", kit["installed_machine_id"])
    if machine["status"] != "ACCEPTED":
        raise ApiError("ERR_MACHINE_NOT_ACCEPTED",
                       "The covered machine has not been accepted.")
    if kit["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_KIT_STATE", "Only a DRAFT kit may be quoted.")
    if int(kit["component_count"]) < 1:
        raise ApiError("ERR_KIT_HAS_NO_COMPONENTS",
                       "The kit carries no change-part components.")
    model = domain.machine_model(machine)
    kit["quoted_lead_time_days"] = calc.format_kit_lead_time(
        kit["components"], kit["container_family"],
        machine["current_format_family"], int(kit["container_diameter_mm"]),
        int(model["min_container_diameter_mm"]),
        int(model["max_container_diameter_mm"]))
    kit["price_cents"] = calc.format_kit_price(kit["components"])
    kit["status"] = "QUOTED"
    store.touch(kit)
    return envelope.ok(kit)


@bp.post("/format-kits/<format_kit_id>/order")
def order_format_kit(format_kit_id):
    auth.authorize(("CustomerContact",))
    kit = domain.must_get("format_kits", format_kit_id)
    machine = store.get("installed_machines", kit["installed_machine_id"])
    auth.require_owner(g.role, g.user_id, machine["customer_id"])
    if kit["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_KIT_STATE",
                       "Only a QUOTED kit may be ordered.")
    kit["status"] = "ORDERED"
    kit["_ordered_on"] = store.fmt_date(store.today())
    store.touch(kit)
    return envelope.ok(kit)


@bp.post("/format-kits/<format_kit_id>/deliver")
def deliver_format_kit(format_kit_id):
    auth.authorize(("ServiceManager",))
    kit = domain.must_get("format_kits", format_kit_id)
    if kit["status"] != "ORDERED":
        raise ApiError("ERR_INVALID_KIT_STATE",
                       "Only an ORDERED kit may be delivered.")
    ordered_on = kit.get("_ordered_on")
    if ordered_on is not None:
        due = store.add_days(ordered_on, int(kit["quoted_lead_time_days"]))
        if store.today() < store.parse_date(due):
            raise ApiError("ERR_KIT_LEAD_TIME_NOT_ELAPSED",
                           "The kit lead time has not elapsed until %s." % due)
    kit["status"] = "DELIVERED"
    store.touch(kit)
    machine = store.get("installed_machines", kit["installed_machine_id"])
    if machine is not None:
        machine["current_format_family"] = kit["container_family"]
        store.touch(machine)
    return envelope.ok(kit)


# --------------------------------------------------------------------------
# spare-parts stocking recommendations
# --------------------------------------------------------------------------
def _recompute_qty(rec):
    rec["recommended_qty"] = calc.spare_stocking_qty(
        int(rec["annual_usage_qty"]), int(rec["unit_lead_time_days"]),
        rec["criticality"], rec["basis"], rec["obsolescence_status"])


@bp.post("/stocking-recommendations")
def create_stocking_recommendation():
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    installed_machine_id = validation.req_str(payload, "installed_machine_id",
                                              1, None)
    part_number = validation.req_str(payload, "part_number", 1, 40)
    annual_usage_qty = validation.req_int(payload, "annual_usage_qty", 0)
    unit_lead_time_days = validation.req_int(payload, "unit_lead_time_days", 0)
    criticality = validation.req_enum(payload, "criticality", ("A", "B", "C"))
    basis = validation.req_enum(payload, "basis",
                                ("LEAD_TIME_DEMAND", "SERVICE_LEVEL"))
    # PRD 2.7: non-optional on this endpoint (a missing field is rung 3)
    expected_version = validation.req_int(
        payload, "expected_installed_machine_version", None, None)
    machine = domain.must_get("installed_machines", installed_machine_id)
    if machine["status"] != "ACCEPTED":
        raise ApiError("ERR_MACHINE_NOT_ACCEPTED",
                       "The covered machine has not been accepted.")
    if int(expected_version) != int(machine["version"]):
        raise ApiError("ERR_STALE_MACHINE_VERSION",
                       "expected_installed_machine_version %s does not match "
                       "the current machine version %s."
                       % (expected_version, machine["version"]))
    for prior in store.rows("stocking_recommendations"):
        if (prior["installed_machine_id"] == installed_machine_id
                and prior["part_number"] == part_number
                and prior["status"] == "ACTIVE"):
            prior["status"] = "SUPERSEDED"
            store.touch(prior)
    row = store.insert("stocking_recommendations", {
        "installed_machine_id": installed_machine_id,
        "part_number": part_number,
        "annual_usage_qty": annual_usage_qty,
        "unit_lead_time_days": unit_lead_time_days,
        "criticality": criticality,
        "obsolescence_status": "ACTIVE",
        "basis": basis,
        "recommended_qty": 0,
        "status": "ACTIVE",
    })
    _recompute_qty(row)
    store.touch(machine)
    return envelope.created(row)


@bp.get("/stocking-recommendations")
def list_stocking_recommendations():
    auth.authorize(("ServiceManager", "PlatformAdmin", "CustomerContact"))
    limit, offset = validation.pagination()
    filters = {
        "installed_machine_id": validation.query_str("installed_machine_id"),
        "part_number": validation.query_str("part_number"),
        "status": validation.query_enum("status", RECOMMENDATION_STATUSES),
    }
    items = [row for row in store.rows("stocking_recommendations")
             if all(value is None or row.get(key) == value
                    for key, value in filters.items())]
    return envelope.ok_list(validation.paginate(items, limit, offset),
                            limit, offset, len(items))


@bp.get("/stocking-recommendations/<stocking_recommendation_id>")
def read_stocking_recommendation(stocking_recommendation_id):
    auth.authorize(("ServiceManager", "PlatformAdmin", "CustomerContact"))
    return envelope.ok(domain.must_get("stocking_recommendations",
                                       stocking_recommendation_id))


@bp.post("/stocking-recommendations/<stocking_recommendation_id>"
         "/obsolescence-notice")
def publish_obsolescence_notice(stocking_recommendation_id):
    auth.authorize(("ServiceManager",))
    payload = validation.body()
    notice_type = validation.req_enum(payload, "notice_type",
                                      tuple(calc.OBSOLESCENCE_CHAIN))
    rec = domain.must_get("stocking_recommendations", stocking_recommendation_id)
    if rec["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_RECOMMENDATION_STATE",
                       "A SUPERSEDED recommendation can no longer be amended.")
    chain = calc.OBSOLESCENCE_CHAIN
    if chain.index(notice_type) <= chain.index(rec["obsolescence_status"]):
        raise ApiError("ERR_OBSOLESCENCE_REGRESSION",
                       "notice_type %s is not a forward move from %s."
                       % (notice_type, rec["obsolescence_status"]))
    rec["obsolescence_status"] = notice_type
    _recompute_qty(rec)
    store.touch(rec)
    return envelope.ok(rec)
