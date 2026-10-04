"""Repair orders and part allocations."""
from datetime import timedelta

from flask import Blueprint, request

from core import (ApiError, BASE_PRICE_BY_ISSUE, ISSUE_CATEGORIES, REPEAT_WINDOW_DAYS, STORE,
                  auth, body, compute_triage_mode, depot_shipping_cost, entity_bootstrap,
                  get_appointment, get_customer, get_device, get_location, get_repair_order,
                  inventory_at, iso_z, logical_now, ok_obj, paginate, pagination, parse_iso,
                  require, require_bool, require_enum, required_parts_for, ser_allocation,
                  ser_repair_order, ser_shipment, touch)

bp = Blueprint("orders", __name__)

TERMINAL_REPAIR_STATES = {"COMPLETED", "CANCELLED"}


def _allocations_for(order_id):
    return [a for a in STORE["part_allocations"].values() if a["repair_order_id"] == order_id]


def _entitlements_for(order_id):
    return [e for e in STORE["coverage_entitlements"].values() if e["repair_order_id"] == order_id]


def _resolved_entitlement(order_id):
    for e in _entitlements_for(order_id):
        if e["entitlement_status"] in ("ENTITLED", "PARTIALLY_ENTITLED", "NOT_ENTITLED", "WAIVED"):
            return e
    return None


def _find_depot_location(exclude_id=None):
    for loc in STORE["service_locations"].values():
        if loc["location_type"] == "MAIL_IN_DEPOT" and loc["location_status"] == "ACTIVE":
            if exclude_id is not None and loc["id"] == exclude_id:
                continue
            return loc
    return None


def _new_tracking_number():
    import uuid as _uuid
    return "TRK-" + _uuid.uuid4().hex[:12].upper()


@bp.post("/repair-orders")
def create_repair_order():
    auth({"Technician", "CustomerService"})
    data = require(body(), "appointment_id", "device_id", "customer_id",
                   "origin_location_id", "issue_category")
    require_enum(data, "issue_category", ISSUE_CATEGORIES)
    require_bool(data, "is_accidental_damage", "data_backup_acknowledged", "privacy_wipe_consent")
    appointment = get_appointment(data["appointment_id"])
    device = get_device(data["device_id"])
    customer = get_customer(data["customer_id"])
    origin = get_location(data["origin_location_id"])
    # account lockout (priority 6)
    if customer["account_status"] in ("LOCKED", "CLOSED"):
        raise ApiError("ERR_ACCOUNT_LOCKED", "Customer account is locked or closed", 403)
    # location availability (priority 8)
    if origin["location_status"] != "ACTIVE":
        raise ApiError("ERR_LOCATION_UNAVAILABLE", "Service location is not ACTIVE", 422)
    # referential integrity (priority 9)
    if device["customer_id"] != customer["id"]:
        raise ApiError("ERR_INVALID_REFERENCE", "Device does not belong to customer", 422)
    if appointment["device_id"] != device["id"] or appointment["customer_id"] != customer["id"]:
        raise ApiError("ERR_INVALID_REFERENCE",
                       "Repair order must reference a valid appointment", 422)
    # OCC (priority 14)
    expected = data.get("expected_device_version")
    if expected is not None and expected != device["version"]:
        raise ApiError("ERR_STALE_VERSION", "expected_device_version does not match", 412)
    e = entity_bootstrap()
    e.update({
        "appointment_id": appointment["id"],
        "device_id": device["id"],
        "customer_id": customer["id"],
        "origin_location_id": origin["id"],
        "current_location_id": origin["id"],
        "issue_category": data["issue_category"],
        "is_accidental_damage": data["is_accidental_damage"],
        "triage_mode": None,
        "repair_status": "TRIAGED",
        "quoted_price_cents": BASE_PRICE_BY_ISSUE[data["issue_category"]],  # provisional
        "data_backup_acknowledged": data["data_backup_acknowledged"],
        "privacy_wipe_consent": data["privacy_wipe_consent"],
        "repeat_repair_count": 0,
        "completed_at": None,
    })
    STORE["repair_orders"][e["id"]] = e
    e["triage_mode"] = compute_triage_mode(e)
    touch(device)  # creating a repair order bumps device version
    return ok_obj(ser_repair_order(e), 201)


@bp.get("/repair-orders/<oid>")
def get_repair_order_view(oid):
    auth({"Customer", "Technician", "CustomerService", "DepotAgent"})
    return ok_obj(ser_repair_order(get_repair_order(oid)))


@bp.get("/repair-orders")
def list_repair_orders():
    auth({"Customer", "Technician", "CustomerService", "DepotAgent", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["repair_orders"].values())
    for key in ("appointment_id", "device_id", "customer_id", "origin_location_id",
                "current_location_id", "repair_status"):
        v = request.args.get(key)
        if v:
            items = [o for o in items if o[key] == v]
    return paginate([ser_repair_order(o) for o in items], limit, offset)


def _guard_not_terminal(o):
    if o["repair_status"] in TERMINAL_REPAIR_STATES:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "RepairOrder is already in a terminal state", 409)


@bp.post("/repair-orders/<oid>/allocate-parts")
def allocate_parts(oid):
    auth({"Technician"})
    o = get_repair_order(oid)
    if o["repair_status"] != "TRIAGED":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not TRIAGED", 409)
    if o["triage_mode"] == "WHOLE_UNIT_REPLACEMENT":
        raise ApiError("ERR_INVALID_STATE",
                       "Allocation is skipped for WHOLE_UNIT_REPLACEMENT orders", 409)
    parts = required_parts_for(o)
    # check availability for every required part first (atomicity)
    allocations = []
    for p in parts:
        inv = inventory_at(o["current_location_id"], p["id"])
        available = 0
        if inv is not None:
            available = inv["on_hand_quantity"] - inv["reserved_quantity"] - inv["express_replacement_quantity"]
        if available <= 0:
            raise ApiError("ERR_INSUFFICIENT_PARTS",
                           "Part inventory does not have sufficient available quantity", 422)
        allocations.append((p, inv, 1))
    for p, inv, qty in allocations:
        inv["reserved_quantity"] += qty
        touch(inv)
        a = entity_bootstrap()
        a.update({
            "repair_order_id": o["id"],
            "part_id": p["id"],
            "location_id": o["current_location_id"],
            "quantity": qty,
            "allocation_status": "RESERVED",
        })
        STORE["part_allocations"][a["id"]] = a
    o["repair_status"] = "PARTS_ALLOCATED"
    touch(o)
    return ok_obj(ser_repair_order(o))


def _verification_satisfied(order_id, vtype):
    for v in STORE["security_verifications"].values():
        if (v["repair_order_id"] == order_id and v["verification_type"] == vtype
                and v["verification_status"] == "VERIFIED"):
            return True
    return False


@bp.post("/repair-orders/<oid>/start-repair")
def start_repair(oid):
    auth({"Technician"})
    o = get_repair_order(oid)
    if o["repair_status"] != "PARTS_ALLOCATED":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not PARTS_ALLOCATED", 409)
    device = get_device(o["device_id"])
    # security gate (priority 5)
    activation_ok = (not device.get("activation_lock_enabled")) or \
        _verification_satisfied(o["id"], "ACTIVATION_LOCK_REMOVAL")
    ownership_ok = device.get("proof_of_purchase_on_file") or \
        _verification_satisfied(o["id"], "OWNERSHIP_PROOF")
    if not (activation_ok and ownership_ok):
        raise ApiError("ERR_SECURITY_VERIFICATION_REQUIRED",
                       "Activation lock or ownership proof verification is required", 422)
    # data backup (priority 15)
    if not o.get("data_backup_acknowledged") or not o.get("privacy_wipe_consent"):
        raise ApiError("ERR_DATA_BACKUP_REQUIRED",
                       "Data backup acknowledgment or privacy wipe consent is missing", 422)
    o["repair_status"] = "IN_PROGRESS"
    touch(o)
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/complete-repair")
def complete_repair(oid):
    auth({"Technician"})
    o = get_repair_order(oid)
    if o["repair_status"] != "IN_PROGRESS":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not IN_PROGRESS", 409)
    o["repair_status"] = "QUALITY_CHECK"
    touch(o)
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/pass-quality-check")
def pass_quality_check(oid):
    auth({"Technician"})
    o = get_repair_order(oid)
    if o["repair_status"] != "QUALITY_CHECK":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not QUALITY_CHECK", 409)
    if o["triage_mode"] != "SAME_DAY_IN_STORE":
        raise ApiError("ERR_INVALID_STATE",
                       "pass-quality-check applies only to SAME_DAY_IN_STORE orders", 409)
    o["repair_status"] = "READY_FOR_PICKUP"
    touch(o)
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/ship-to-depot")
def ship_to_depot(oid):
    auth({"Technician"})
    o = get_repair_order(oid)
    if o["repair_status"] != "QUALITY_CHECK":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not QUALITY_CHECK", 409)
    if o["triage_mode"] != "MAIL_IN_DEPOT":
        raise ApiError("ERR_INVALID_STATE",
                       "ship-to-depot applies only to MAIL_IN_DEPOT orders", 409)
    depot = _find_depot_location(exclude_id=o["origin_location_id"]) or _find_depot_location()
    if depot is None:
        raise ApiError("ERR_LOCATION_UNAVAILABLE", "No active mail-in depot available", 422)
    o["repair_status"] = "SHIPPED_TO_DEPOT"
    o["depot_location_id"] = depot["id"]
    touch(o)
    s = entity_bootstrap()
    s.update({
        "repair_order_id": o["id"],
        "from_location_id": o["origin_location_id"],
        "to_location_id": depot["id"],
        "shipment_type": "STORE_TO_DEPOT",
        "shipment_status": "LABEL_CREATED",
        "tracking_number": _new_tracking_number(),
        "shipped_at": None,
        "received_at": None,
    })
    STORE["repair_shipments"][s["id"]] = s
    # depot routing cost propagation
    ent = _resolved_entitlement(o["id"])
    if ent is not None and ent["entitlement_status"] in ("NOT_ENTITLED", "PARTIALLY_ENTITLED"):
        cost = depot_shipping_cost(o["origin_location_id"], depot["id"])
        if cost:
            o["quoted_price_cents"] = o.get("quoted_price_cents", 0) + cost
            touch(o)
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/receive-at-depot")
def receive_at_depot(oid):
    auth({"DepotAgent"})
    o = get_repair_order(oid)
    if o["repair_status"] != "SHIPPED_TO_DEPOT":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not SHIPPED_TO_DEPOT", 409)
    o["repair_status"] = "IN_TRANSIT_BACK"
    if o.get("depot_location_id"):
        o["current_location_id"] = o["depot_location_id"]
    touch(o)
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/receive-back-from-depot")
def receive_back_from_depot(oid):
    auth({"DepotAgent"})
    o = get_repair_order(oid)
    if o["repair_status"] != "IN_TRANSIT_BACK":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not IN_TRANSIT_BACK", 409)
    o["repair_status"] = "READY_FOR_PICKUP"
    o["current_location_id"] = o["origin_location_id"]
    touch(o)
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/complete-pickup")
def complete_pickup(oid):
    auth({"Customer", "Technician"})
    o = get_repair_order(oid)
    if o["repair_status"] != "READY_FOR_PICKUP":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not READY_FOR_PICKUP", 409)
    # consume allocations
    for a in _allocations_for(o["id"]):
        if a["allocation_status"] == "RESERVED":
            a["allocation_status"] = "CONSUMED"
            touch(a)
            inv = inventory_at(a["location_id"], a["part_id"])
            if inv is not None:
                inv["on_hand_quantity"] = max(0, inv["on_hand_quantity"] - a["quantity"])
                inv["reserved_quantity"] = max(0, inv["reserved_quantity"] - a["quantity"])
                touch(inv)
    # accidental damage incident counting
    ent = _resolved_entitlement(o["id"])
    if (ent is not None and ent["entitlement_status"] == "ENTITLED"
            and o.get("is_accidental_damage") and not ent.get("incident_counted")):
        plan = STORE["coverage_plans"].get(ent["coverage_plan_id"])
        if plan is not None:
            plan["accidental_damage_incidents_used"] += 1
            touch(plan)
        ent["incident_counted"] = True
        touch(ent)
    o["repair_status"] = "COMPLETED"
    touch(o)
    o["completed_at"] = o["updated_at"]
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/cancel")
def cancel_repair_order(oid):
    auth({"Customer", "CustomerService"})
    o = get_repair_order(oid)
    customer = get_customer(o["customer_id"])
    if customer["account_status"] in ("LOCKED", "CLOSED"):
        raise ApiError("ERR_ACCOUNT_LOCKED", "Customer account is locked or closed", 403)
    if o["repair_status"] in TERMINAL_REPAIR_STATES:
        raise ApiError("ERR_ALREADY_TERMINAL",
                       "RepairOrder is already in a terminal state", 409)
    if o["repair_status"] not in ("TRIAGED", "PARTS_ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE",
                       "Repair order cannot be cancelled from its current state", 409)
    if o["repair_status"] == "PARTS_ALLOCATED":
        for a in _allocations_for(o["id"]):
            if a["allocation_status"] == "RESERVED":
                a["allocation_status"] = "RELEASED"
                touch(a)
                inv = inventory_at(a["location_id"], a["part_id"])
                if inv is not None:
                    inv["reserved_quantity"] = max(0, inv["reserved_quantity"] - a["quantity"])
                    touch(inv)
    o["repair_status"] = "CANCELLED"
    touch(o)
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/escalate-repeat")
def escalate_repeat(oid):
    auth({"CustomerService"})
    o = get_repair_order(oid)
    if o["repair_status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not COMPLETED", 409)
    completed_at = parse_iso(o["completed_at"]) if o.get("completed_at") else parse_iso(o["updated_at"])
    days_since = int((logical_now() - completed_at).total_seconds() // 86400)
    if days_since > REPEAT_WINDOW_DAYS:
        raise ApiError("ERR_REPEAT_WINDOW_EXPIRED",
                       "Repeat repair escalation is outside the 90-day window", 422)
    follow_ups = [f for f in STORE["quality_follow_ups"].values()
                  if f["repair_order_id"] == o["id"]]
    if any(f["follow_up_status"] == "RESOLVED_SATISFIED" for f in follow_ups):
        raise ApiError("ERR_INVALID_STATE",
                       "A follow-up for this repair order is RESOLVED_SATISFIED", 409)
    o["repair_status"] = "ESCALATED_REPEAT"
    o["repeat_repair_count"] = o.get("repeat_repair_count", 0) + 1
    touch(o)
    for f in follow_ups:
        if f["follow_up_status"] == "OPEN":
            f["follow_up_status"] = "ESCALATED"
            touch(f)
    return ok_obj(ser_repair_order(o))


@bp.post("/repair-orders/<oid>/re-triage")
def re_triage(oid):
    auth({"Technician"})
    o = get_repair_order(oid)
    if o["repair_status"] != "ESCALATED_REPEAT":
        raise ApiError("ERR_INVALID_STATE", "Repair order is not ESCALATED_REPEAT", 409)
    o["repair_status"] = "TRIAGED"
    touch(o)
    return ok_obj(ser_repair_order(o))


# ---------------------------------------------------------------------------
# Part allocations
# ---------------------------------------------------------------------------

@bp.get("/part-allocations/<aid>")
def get_allocation(aid):
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    a = STORE["part_allocations"].get(aid)
    if a is None:
        raise ApiError("ERR_NOT_FOUND", "Part allocation not found", 404)
    return ok_obj(ser_allocation(a))


@bp.get("/part-allocations")
def list_allocations():
    auth({"Technician", "CustomerService", "PlatformAdmin"})
    limit, offset = pagination()
    items = list(STORE["part_allocations"].values())
    for key in ("repair_order_id", "part_id", "location_id", "allocation_status"):
        v = request.args.get(key)
        if v:
            items = [a for a in items if a[key] == v]
    return paginate([ser_allocation(a) for a in items], limit, offset)
