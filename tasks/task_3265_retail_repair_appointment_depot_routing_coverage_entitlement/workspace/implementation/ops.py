"""Coverage entitlements, security verifications, repair shipments, quality follow-ups."""
import uuid as _uuid
from datetime import timedelta

from flask import Blueprint, request

from core import (ApiError, STORE, auth, body, entity_bootstrap, get_customer,
                  get_location, get_plan, get_repair_order, iso_z, logical_now, ok_obj,
                  out_of_warranty_price, paginate, pagination, require, require_enum,
                  ser_entitlement, ser_follow_up, ser_shipment, ser_verification, touch)

bp = Blueprint("ops", __name__)

VERIFICATION_TYPES = {"ACTIVATION_LOCK_REMOVAL", "OWNERSHIP_PROOF", "ACCOUNT_UNLOCK"}
SHIPMENT_TYPES = {"CUSTOMER_TO_DEPOT", "DEPOT_TO_CUSTOMER", "STORE_TO_DEPOT", "DEPOT_TO_STORE"}


def _tracking():
    return "TRK-" + _uuid.uuid4().hex[:12].upper()


# ---------------------------------------------------------------------------
# Coverage entitlements
# ---------------------------------------------------------------------------

@bp.post("/coverage-entitlements")
def create_entitlement():
    auth({"Technician", "CustomerService"})
    data = require(body(), "repair_order_id", "coverage_plan_id")
    order = get_repair_order(data["repair_order_id"])
    # The plan reference may name a plan that does not exist (repair proceeds
    # with no active coverage); existence is only consulted at resolution time.
    plan = STORE["coverage_plans"].get(data["coverage_plan_id"])
    if plan is not None and plan["device_id"] != order["device_id"]:
        raise ApiError("ERR_INVALID_REFERENCE",
                       "Coverage plan does not belong to the repair order's device", 422)
    device = STORE["devices"].get(order["device_id"]) or {}
    e = entity_bootstrap()
    e.update({
        "repair_order_id": order["id"],
        "coverage_plan_id": data["coverage_plan_id"],
        "entitlement_status": "PENDING_VERIFICATION",
        "quoted_price_cents": order.get("quoted_price_cents", 0),
        "requires_proof_of_purchase": not bool(device.get("proof_of_purchase_on_file")),
        "incident_counted": False,
    })
    STORE["coverage_entitlements"][e["id"]] = e
    return ok_obj(ser_entitlement(e), 201)


@bp.get("/coverage-entitlements/<eid>")
def get_entitlement(eid):
    auth({"Customer", "Technician", "CustomerService"})
    e = STORE["coverage_entitlements"].get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "Coverage entitlement not found", 404)
    return ok_obj(ser_entitlement(e))


@bp.get("/coverage-entitlements")
def list_entitlements():
    auth({"Customer", "Technician", "CustomerService", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["coverage_entitlements"].values())
    for key in ("repair_order_id", "coverage_plan_id", "entitlement_status"):
        v = request.args.get(key)
        if v:
            items = [e for e in items if e[key] == v]
    return paginate([ser_entitlement(e) for e in items], limit, offset)


def _get_entitlement(eid):
    e = STORE["coverage_entitlements"].get(eid)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", "Coverage entitlement not found", 404)
    return e


def _proof_satisfied(ent, order):
    device = STORE["devices"].get(order["device_id"]) or {}
    return bool(device.get("proof_of_purchase_on_file")) or not ent.get("requires_proof_of_purchase")


def _resolve_side_effects(ent, order, price):
    ent["quoted_price_cents"] = price
    touch(ent)
    order["quoted_price_cents"] = price
    touch(order)


@bp.post("/coverage-entitlements/<eid>/resolve")
def resolve_entitlement(eid):
    auth({"Technician", "CustomerService"})
    ent = _get_entitlement(eid)
    if ent["entitlement_status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Entitlement is not PENDING_VERIFICATION", 409)
    order = get_repair_order(ent["repair_order_id"])
    plan = STORE["coverage_plans"].get(ent["coverage_plan_id"])
    device = STORE["devices"].get(order["device_id"]) or {}
    data = body()
    expected = data.get("expected_coverage_plan_version")
    if plan is None:
        # No referenced plan: the plan is not ACTIVE, so the claim resolves
        # NOT_ENTITLED at the full out-of-warranty price. With no plan there is
        # no version to match, so the OCC check cannot fail.
        ent["entitlement_status"] = "NOT_ENTITLED"
        _resolve_side_effects(ent, order, out_of_warranty_price(device, order["issue_category"]))
        return ok_obj(ser_entitlement(ent))
    # coverage eligibility (priority 10): plan must be ACTIVE
    if plan["coverage_status"] != "ACTIVE":
        raise ApiError("ERR_COVERAGE_EXHAUSTED", "Coverage plan is not ACTIVE", 422)
    # proof-of-purchase requirement -> NOT_ENTITLED resolution (not a rejection)
    proof_ok = _proof_satisfied(ent, order)
    # accidental damage incident availability
    if order.get("is_accidental_damage") and proof_ok:
        if plan["accidental_damage_incidents_used"] >= plan["accidental_damage_incident_limit"]:
            raise ApiError("ERR_COVERAGE_EXHAUSTED",
                           "Coverage plan has no remaining accidental damage incidents", 422)
    # OCC (priority 14)
    if expected is not None and expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_coverage_plan_version does not match", 412)
    if not proof_ok:
        ent["entitlement_status"] = "NOT_ENTITLED"
        _resolve_side_effects(ent, order, out_of_warranty_price(device, order["issue_category"]))
    else:
        ent["entitlement_status"] = "ENTITLED"
        price = plan["service_fee_cents"] if order.get("is_accidental_damage") else 0
        _resolve_side_effects(ent, order, price)
    return ok_obj(ser_entitlement(ent))


@bp.post("/coverage-entitlements/<eid>/resolve-partial")
def resolve_partial(eid):
    auth({"Technician", "CustomerService"})
    ent = _get_entitlement(eid)
    if ent["entitlement_status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Entitlement is not PENDING_VERIFICATION", 409)
    order = get_repair_order(ent["repair_order_id"])
    plan = STORE["coverage_plans"].get(ent["coverage_plan_id"])
    if plan is None or plan["coverage_status"] != "ACTIVE":
        raise ApiError("ERR_COVERAGE_EXHAUSTED", "Coverage plan is not ACTIVE", 422)
    if not _proof_satisfied(ent, order):
        raise ApiError("ERR_COVERAGE_EXHAUSTED",
                       "Proof of purchase requirement is not met", 422)
    data = body()
    expected = data.get("expected_coverage_plan_version")
    if expected is not None and expected != plan["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_coverage_plan_version does not match", 412)
    device = STORE["devices"].get(order["device_id"]) or {}
    ent["entitlement_status"] = "PARTIALLY_ENTITLED"
    _resolve_side_effects(ent, order, out_of_warranty_price(device, order["issue_category"]))
    return ok_obj(ser_entitlement(ent))


@bp.post("/coverage-entitlements/<eid>/waive")
def waive_entitlement(eid):
    auth({"CustomerService"})
    ent = _get_entitlement(eid)
    if ent["entitlement_status"] != "PENDING_VERIFICATION":
        raise ApiError("ERR_INVALID_STATE", "Entitlement is not PENDING_VERIFICATION", 409)
    order = get_repair_order(ent["repair_order_id"])
    ent["entitlement_status"] = "WAIVED"
    _resolve_side_effects(ent, order, 0)
    return ok_obj(ser_entitlement(ent))


# ---------------------------------------------------------------------------
# Security verifications
# ---------------------------------------------------------------------------

@bp.post("/security-verifications")
def create_verification():
    auth({"Technician", "CustomerService"})
    data = require(body(), "repair_order_id", "verification_type")
    require_enum(data, "verification_type", VERIFICATION_TYPES)
    order = get_repair_order(data["repair_order_id"])
    e = entity_bootstrap()
    e.update({
        "repair_order_id": order["id"],
        "verification_type": data["verification_type"],
        "verification_status": "PENDING",
        "verified_by": None,
        "verified_at": None,
    })
    STORE["security_verifications"][e["id"]] = e
    return ok_obj(ser_verification(e), 201)


def _get_verification(vid):
    v = STORE["security_verifications"].get(vid)
    if v is None:
        raise ApiError("ERR_NOT_FOUND", "Security verification not found", 404)
    return v


@bp.get("/security-verifications/<vid>")
def get_verification(vid):
    auth({"Technician", "CustomerService"})
    return ok_obj(ser_verification(_get_verification(vid)))


@bp.get("/security-verifications")
def list_verifications():
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["security_verifications"].values())
    for key in ("repair_order_id", "verification_type", "verification_status"):
        v = request.args.get(key)
        if v:
            items = [e for e in items if e[key] == v]
    return paginate([ser_verification(e) for e in items], limit, offset)


@bp.post("/security-verifications/<vid>/verify")
def verify(vid):
    user_id, role = auth({"Technician"})
    v = _get_verification(vid)
    if v["verification_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Verification is not PENDING", 409)
    created = __import__("core").parse_iso(v["created_at"])
    if logical_now() > created + timedelta(hours=24):
        v["verification_status"] = "EXPIRED"
        touch(v)
        raise ApiError("ERR_INVALID_STATE", "Verification window has expired", 409)
    v["verification_status"] = "VERIFIED"
    v["verified_by"] = user_id
    v["verified_at"] = iso_z(logical_now())
    touch(v)
    return ok_obj(ser_verification(v))


@bp.post("/security-verifications/<vid>/fail")
def fail_verification(vid):
    auth({"Technician"})
    v = _get_verification(vid)
    if v["verification_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", "Verification is not PENDING", 409)
    v["verification_status"] = "FAILED"
    touch(v)
    return ok_obj(ser_verification(v))


# ---------------------------------------------------------------------------
# Repair shipments
# ---------------------------------------------------------------------------

@bp.post("/repair-shipments")
def create_shipment():
    auth({"DepotAgent", "CustomerService"})
    data = require(body(), "repair_order_id", "from_location_id", "to_location_id",
                   "shipment_type")
    require_enum(data, "shipment_type", SHIPMENT_TYPES)
    order = get_repair_order(data["repair_order_id"])
    get_location(data["from_location_id"])
    get_location(data["to_location_id"])
    e = entity_bootstrap()
    e.update({
        "repair_order_id": order["id"],
        "from_location_id": data["from_location_id"],
        "to_location_id": data["to_location_id"],
        "shipment_type": data["shipment_type"],
        "shipment_status": "LABEL_CREATED",
        "tracking_number": _tracking(),
        "shipped_at": None,
        "received_at": None,
    })
    STORE["repair_shipments"][e["id"]] = e
    return ok_obj(ser_shipment(e), 201)


def _get_shipment(sid):
    s = STORE["repair_shipments"].get(sid)
    if s is None:
        raise ApiError("ERR_NOT_FOUND", "Repair shipment not found", 404)
    return s


@bp.get("/repair-shipments/<sid>")
def get_shipment(sid):
    auth({"Customer", "Technician", "CustomerService", "DepotAgent"})
    return ok_obj(ser_shipment(_get_shipment(sid)))


@bp.get("/repair-shipments")
def list_shipments():
    auth({"Customer", "Technician", "CustomerService", "DepotAgent", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["repair_shipments"].values())
    for key in ("repair_order_id", "from_location_id", "to_location_id", "shipment_status"):
        v = request.args.get(key)
        if v:
            items = [s for s in items if s[key] == v]
    return paginate([ser_shipment(s) for s in items], limit, offset)


@bp.post("/repair-shipments/<sid>/ship")
def ship(sid):
    auth({"DepotAgent"})
    s = _get_shipment(sid)
    if s["shipment_status"] != "LABEL_CREATED":
        raise ApiError("ERR_INVALID_STATE", "Shipment is not LABEL_CREATED", 409)
    s["shipment_status"] = "IN_TRANSIT"
    s["shipped_at"] = iso_z(logical_now())
    touch(s)
    return ok_obj(ser_shipment(s))


@bp.post("/repair-shipments/<sid>/receive")
def receive(sid):
    auth({"DepotAgent"})
    s = _get_shipment(sid)
    if s["shipment_status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", "Shipment is not IN_TRANSIT", 409)
    s["shipment_status"] = "RECEIVED"
    s["received_at"] = iso_z(logical_now())
    touch(s)
    return ok_obj(ser_shipment(s))


@bp.post("/repair-shipments/<sid>/deliver")
def deliver(sid):
    auth({"DepotAgent"})
    s = _get_shipment(sid)
    if s["shipment_status"] != "RECEIVED":
        raise ApiError("ERR_INVALID_STATE", "Shipment is not RECEIVED", 409)
    s["shipment_status"] = "DELIVERED"
    touch(s)
    return ok_obj(ser_shipment(s))


@bp.post("/repair-shipments/<sid>/mark-lost")
def mark_lost(sid):
    auth({"CustomerService"})
    s = _get_shipment(sid)
    if s["shipment_status"] != "IN_TRANSIT":
        raise ApiError("ERR_INVALID_STATE", "Shipment is not IN_TRANSIT", 409)
    s["shipment_status"] = "LOST"
    touch(s)
    order = STORE["repair_orders"].get(s["repair_order_id"])
    if order is not None and order["repair_status"] not in ("COMPLETED", "CANCELLED"):
        order["repair_status"] = "ESCALATED_REPEAT"
        touch(order)
    return ok_obj(ser_shipment(s))


# ---------------------------------------------------------------------------
# Quality follow-ups
# ---------------------------------------------------------------------------

@bp.post("/quality-follow-ups")
def create_follow_up():
    auth({"CustomerService"})
    data = require(body(), "repair_order_id", "customer_id")
    order = get_repair_order(data["repair_order_id"])
    customer = get_customer(data["customer_id"])
    e = entity_bootstrap()
    e.update({
        "repair_order_id": order["id"],
        "customer_id": customer["id"],
        "follow_up_status": "OPEN",
        "opened_at": iso_z(logical_now()),
        "resolved_at": None,
    })
    STORE["quality_follow_ups"][e["id"]] = e
    return ok_obj(ser_follow_up(e), 201)


def _get_follow_up(fid):
    f = STORE["quality_follow_ups"].get(fid)
    if f is None:
        raise ApiError("ERR_NOT_FOUND", "Quality follow-up not found", 404)
    return f


@bp.get("/quality-follow-ups/<fid>")
def get_follow_up(fid):
    auth({"Customer", "CustomerService"})
    return ok_obj(ser_follow_up(_get_follow_up(fid)))


@bp.get("/quality-follow-ups")
def list_follow_ups():
    auth({"Customer", "CustomerService", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["quality_follow_ups"].values())
    for key in ("repair_order_id", "customer_id", "follow_up_status"):
        v = request.args.get(key)
        if v:
            items = [f for f in items if f[key] == v]
    return paginate([ser_follow_up(f) for f in items], limit, offset)


@bp.post("/quality-follow-ups/<fid>/resolve-satisfied")
def resolve_satisfied(fid):
    auth({"Customer", "CustomerService"})
    f = _get_follow_up(fid)
    if f["follow_up_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Follow-up is not OPEN", 409)
    f["follow_up_status"] = "RESOLVED_SATISFIED"
    f["resolved_at"] = iso_z(logical_now())
    touch(f)
    return ok_obj(ser_follow_up(f))


@bp.post("/quality-follow-ups/<fid>/resolve-repeat")
def resolve_repeat(fid):
    auth({"CustomerService"})
    f = _get_follow_up(fid)
    if f["follow_up_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Follow-up is not OPEN", 409)
    order = get_repair_order(f["repair_order_id"])
    if order["repair_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE",
                       "Repair order must be COMPLETED to resolve as repeat repair", 409)
    f["follow_up_status"] = "RESOLVED_REPEAT_REPAIR"
    f["resolved_at"] = iso_z(logical_now())
    touch(f)
    order["repair_status"] = "ESCALATED_REPEAT"
    touch(order)
    return ok_obj(ser_follow_up(f))


@bp.post("/quality-follow-ups/<fid>/escalate")
def escalate_follow_up(fid):
    auth({"CustomerService"})
    f = _get_follow_up(fid)
    if f["follow_up_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Follow-up is not OPEN", 409)
    f["follow_up_status"] = "ESCALATED"
    touch(f)
    return ok_obj(ser_follow_up(f))
