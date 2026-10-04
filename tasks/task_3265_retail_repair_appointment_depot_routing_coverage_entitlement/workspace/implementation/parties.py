"""Customers, devices, and coverage plans."""
from datetime import datetime

from flask import Blueprint

from core import (ApiError, STORE, auth, body, entity_bootstrap, get_customer, get_device,
                  get_location, get_plan, iso_z, logical_now, ok_obj, paginate, pagination,
                  parse_iso, require, require_bool, require_enum, require_int,
                  ser_customer, ser_device, ser_plan, touch)

bp = Blueprint("parties", __name__)

PLAN_TYPES = {"LIMITED_WARRANTY", "APPLECARE_PLUS", "OUT_OF_WARRANTY"}


# ---------------------------------------------------------------------------
# Customers
# ---------------------------------------------------------------------------

@bp.post("/customers")
def create_customer():
    auth({"Anonymous"})
    data = require(body(), "email", "full_name", "phone")
    email = data["email"]
    if not isinstance(email, str) or not email:
        raise ApiError("ERR_INVALID_REQUEST", "email is required", 400)
    for c in STORE["customers"].values():
        if c["email"] == email:
            raise ApiError("ERR_INVALID_REQUEST", "email must be unique across customers", 400)
    e = entity_bootstrap()
    e.update({
        "email": email,
        "full_name": data["full_name"],
        "phone": data["phone"],
        "account_status": "ACTIVE",
    })
    STORE["customers"][e["id"]] = e
    return ok_obj(ser_customer(e), 201)


@bp.get("/customers/<cid>")
def get_customer_view(cid):
    auth({"Customer", "CustomerService", "PlatformAdmin"})
    c = get_customer(cid)
    return ok_obj(ser_customer(c))


@bp.post("/customers/<cid>/lock")
def lock_customer(cid):
    auth({"CustomerService"})
    c = get_customer(cid)
    if c["account_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Customer account is not ACTIVE", 409)
    c["account_status"] = "LOCKED"
    touch(c)
    return ok_obj(ser_customer(c))


@bp.post("/customers/<cid>/unlock")
def unlock_customer(cid):
    auth({"CustomerService"})
    c = get_customer(cid)
    if c["account_status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", "Customer account is not LOCKED", 409)
    c["account_status"] = "ACTIVE"
    touch(c)
    return ok_obj(ser_customer(c))


@bp.post("/customers/<cid>/close")
def close_customer(cid):
    auth({"CustomerService"})
    c = get_customer(cid)
    if c["account_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Customer account is not ACTIVE", 409)
    c["account_status"] = "CLOSED"
    touch(c)
    return ok_obj(ser_customer(c))


@bp.get("/customers/<cid>/devices")
def list_customer_devices(cid):
    auth({"Customer", "CustomerService"})
    get_customer(cid)
    limit, offset = pagination()
    items = [ser_device(d) for d in STORE["devices"].values() if d["customer_id"] == cid]
    return paginate(items, limit, offset)


@bp.get("/customers/<cid>/appointments")
def list_customer_appointments(cid):
    auth({"Customer", "CustomerService"})
    get_customer(cid)
    limit, offset = pagination()
    from core import ser_appointment
    status = __import__("flask").request.args.get("status")
    items = [a for a in STORE["appointments"].values() if a["customer_id"] == cid]
    if status:
        items = [a for a in items if a["appointment_status"] == status]
    return paginate([ser_appointment(a) for a in items], limit, offset)


@bp.get("/customers/<cid>/repair-orders")
def list_customer_repair_orders(cid):
    auth({"Customer", "CustomerService"})
    get_customer(cid)
    limit, offset = pagination()
    from core import ser_repair_order
    status = __import__("flask").request.args.get("status")
    items = [o for o in STORE["repair_orders"].values() if o["customer_id"] == cid]
    if status:
        items = [o for o in items if o["repair_status"] == status]
    return paginate([ser_repair_order(o) for o in items], limit, offset)


# ---------------------------------------------------------------------------
# Devices
# ---------------------------------------------------------------------------

@bp.post("/devices")
def create_device():
    auth({"Customer", "CustomerService"})
    data = require(body(), "customer_id", "serial_number", "model_code", "purchase_date")
    require_bool(data, "activation_lock_enabled", "proof_of_purchase_on_file")
    get_customer(data["customer_id"])
    # serial_number unique per model family (model_code)
    for d in STORE["devices"].values():
        if (d["serial_number"] == data["serial_number"]
                and d["model_code"] == data["model_code"]):
            raise ApiError("ERR_INVALID_REQUEST",
                           "serial_number must be unique per device model family", 400)
    # validate purchase_date parses
    parse_iso(data["purchase_date"])
    e = entity_bootstrap()
    e.update({
        "customer_id": data["customer_id"],
        "serial_number": data["serial_number"],
        "model_code": data["model_code"],
        "activation_lock_enabled": data["activation_lock_enabled"],
        "proof_of_purchase_on_file": data["proof_of_purchase_on_file"],
        "purchase_date": data["purchase_date"],
        "device_status": "ACTIVE",
    })
    STORE["devices"][e["id"]] = e
    return ok_obj(ser_device(e), 201)


@bp.get("/devices/<did>")
def get_device_view(did):
    auth({"Customer", "Technician", "CustomerService", "PlatformAdmin"})
    return ok_obj(ser_device(get_device(did)))


@bp.get("/devices")
def list_devices():
    auth({"Customer", "Technician", "CustomerService", "PlatformAdmin"})
    from flask import request
    limit, offset = pagination()
    items = list(STORE["devices"].values())
    cid = request.args.get("customer_id")
    mc = request.args.get("model_code")
    ds = request.args.get("device_status")
    if cid:
        items = [d for d in items if d["customer_id"] == cid]
    if mc:
        items = [d for d in items if d["model_code"] == mc]
    if ds:
        items = [d for d in items if d["device_status"] == ds]
    return paginate([ser_device(d) for d in items], limit, offset)


@bp.get("/devices/<did>/coverage-plans")
def list_device_plans(did):
    auth({"Customer", "Technician", "CustomerService"})
    get_device(did)
    limit, offset = pagination()
    items = [ser_plan(p) for p in STORE["coverage_plans"].values() if p["device_id"] == did]
    return paginate(items, limit, offset)


# ---------------------------------------------------------------------------
# Coverage plans
# ---------------------------------------------------------------------------

@bp.post("/coverage-plans")
def create_plan():
    auth({"CustomerService", "PlatformAdmin"})
    data = require(body(), "device_id", "plan_type", "starts_on", "expires_on")
    require_int(data, "accidental_damage_incident_limit", "service_fee_cents")
    require_enum(data, "plan_type", PLAN_TYPES)
    get_device(data["device_id"])
    parse_iso(data["starts_on"])
    parse_iso(data["expires_on"])
    if data["accidental_damage_incident_limit"] < 0 or data["service_fee_cents"] < 0:
        raise ApiError("ERR_INVALID_REQUEST", "numeric fields must be >= 0", 400)
    e = entity_bootstrap()
    e.update({
        "device_id": data["device_id"],
        "plan_type": data["plan_type"],
        "starts_on": data["starts_on"],
        "expires_on": data["expires_on"],
        "accidental_damage_incidents_used": 0,
        "accidental_damage_incident_limit": data["accidental_damage_incident_limit"],
        "service_fee_cents": data["service_fee_cents"],
        "coverage_status": "ACTIVE",
    })
    STORE["coverage_plans"][e["id"]] = e
    return ok_obj(ser_plan(e), 201)


@bp.get("/coverage-plans/<pid>")
def get_plan_view(pid):
    auth({"Customer", "Technician", "CustomerService"})
    return ok_obj(ser_plan(get_plan(pid)))


@bp.get("/coverage-plans")
def list_plans():
    auth({"Customer", "Technician", "CustomerService", "PlatformAdmin"})
    from flask import request
    limit, offset = pagination()
    items = list(STORE["coverage_plans"].values())
    did = request.args.get("device_id")
    pt = request.args.get("plan_type")
    cs = request.args.get("coverage_status")
    if did:
        items = [p for p in items if p["device_id"] == did]
    if pt:
        items = [p for p in items if p["plan_type"] == pt]
    if cs:
        items = [p for p in items if p["coverage_status"] == cs]
    return paginate([ser_plan(p) for p in items], limit, offset)


@bp.post("/coverage-plans/<pid>/cancel")
def cancel_plan(pid):
    auth({"Customer", "CustomerService"})
    p = get_plan(pid)
    if p["coverage_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "Coverage plan is not ACTIVE", 409)
    p["coverage_status"] = "CANCELLED"
    touch(p)
    return ok_obj(ser_plan(p))
