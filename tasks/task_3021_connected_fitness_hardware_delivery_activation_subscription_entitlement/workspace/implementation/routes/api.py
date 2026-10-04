"""Every declared route, mounted under the scaffold's /fitness prefix.

Route order per request (PRD section 2 / scaffold section 1.4):
  auth (priority 1-2) -> payload shape and existence (3) -> optimistic
  concurrency (4) -> state (5) -> business rules (6-10).
The state and business-rule evaluation order lives in services/.
"""

import json

from flask import Blueprint, request

import db
from errors import api_error
from response import success_array, success_object
from services import calc, classes, delivery, device as device_service
from services import financing, household
from services import membership as membership_service
from services import ops, order as order_service, parts
from services import refurb
from services import service_order as service_order_service
from services.common import (
    authenticate,
    class_enrollment_view,
    class_session_view,
    delivery_appointment_view,
    device_view,
    financing_plan_view,
    hardware_order_view,
    household_user_view,
    membership_view,
    paginate,
    parts_inventory_view,
    query_matches,
    refurb_batch_view,
    reject_unknown,
    require_role,
    scope_membership,
    service_order_view,
)

api = Blueprint("api", __name__, url_prefix="/fitness")

OWNER_ADMIN = ("MembershipOwner", "PlatformAdmin")
TECH_ADMIN = ("ServiceTechnician", "PlatformAdmin")
OWNER_TECH_ADMIN = ("MembershipOwner", "ServiceTechnician", "PlatformAdmin")
TEACHING_ROLES = ("MembershipOwner", "Instructor", "PlatformAdmin")
INSTRUCTOR_ADMIN = ("Instructor", "PlatformAdmin")
PLATFORM_ADMIN = ("PlatformAdmin",)
QUOTE_ROLES = ("ServiceTechnician", "PlatformAdmin", "MembershipOwner")


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def body():
    """Parse the request body as a JSON object; {} when nothing is supplied."""
    if request.is_json:
        parsed = request.get_json(silent=True)
        return parsed if isinstance(parsed, dict) else {}
    raw = request.get_data()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def caller(allowed):
    """Priority 1 then priority 2."""
    who = authenticate(request.headers)
    require_role(who, allowed)
    return who


def render_membership(membership):
    """Refresh the derived aggregate so every read is self-consistent."""
    calc.recompute_stream_counters(membership)
    calc.apply_delinquency_derivatives(membership)
    calc.recompute_posture(membership)
    return membership_view(membership)


def render_device(device):
    """Refresh the derived entitlement so every read is self-consistent."""
    membership = db.STORE["memberships"].get(device["membership_id"])
    if membership is not None:
        calc.recompute_posture(membership)
    calc.recompute_device_entitlement(device)
    return device_view(device)


def load_membership(membership_id, who=None):
    membership = db.require("memberships", membership_id)
    if who is not None:
        scope_membership(who, membership)
    return membership


def load_owned(entity, row_id, who):
    """Resolve a row and apply the entity-backed ownership check."""
    row = db.require(entity, row_id)
    if who is not None and who.is_owner:
        resolver = _OWNERSHIP_RESOLVERS.get(entity)
        if resolver is not None:
            owner_id = resolver(row)
            if owner_id is not None and owner_id != who.user_id:
                raise api_error("ERR_UNAUTHORIZED")
    return row


def _device_membership(row):
    device = db.STORE["devices"].get(row.get("device_id"))
    return device["membership_id"] if device is not None else None


def _user_membership(row):
    user = db.STORE["household_users"].get(row.get("enroller_user_id"))
    return user["membership_id"] if user is not None else None


_OWNERSHIP_RESOLVERS = {
    "household_users": lambda row: row["membership_id"],
    "devices": lambda row: row["membership_id"],
    "hardware_orders": lambda row: row["membership_id"],
    "financing_plans": lambda row: row["membership_id"],
    "delivery_appointments": _device_membership,
    "service_orders": _device_membership,
    "class_enrollments": _user_membership,
}


def no_auth():
    """The logical clock panel: the only capability not requiring headers.

    PRD section 3.10 states the clock-advancing capability is the only one that
    does not require an authenticated header pair, so no header check is
    applied here.
    """
    return None


# ===========================================================================
# Membership
# ===========================================================================
@api.post("/memberships")
def create_membership():
    # No ownership check applies: the row does not exist yet and the caller's
    # identifier is not compared against a server-minted id at creation time.
    caller(OWNER_ADMIN)
    membership = membership_service.create(body())
    return success_object(render_membership(membership), 201)


@api.get("/memberships")
def list_memberships():
    caller(OWNER_ADMIN)
    rows = list(db.STORE["memberships"].values())
    rows = [
        row for row in rows
        if query_matches(request.args, "status", row["status"])
        and query_matches(request.args, "plan_tier", row["plan_tier"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([render_membership(row) for row in page], limit, offset, total)


@api.get("/memberships/<membership_id>")
def get_membership(membership_id):
    who = caller(OWNER_ADMIN)
    return success_object(render_membership(load_membership(membership_id, who)))


@api.post("/memberships/<membership_id>/activate")
def activate_membership(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    membership_service.activate(membership, body())
    return success_object(render_membership(membership))


@api.post("/memberships/<membership_id>/pause")
def pause_membership(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    membership_service.pause(membership, body())
    return success_object(render_membership(membership))


@api.post("/memberships/<membership_id>/resume")
def resume_membership(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    membership_service.resume(membership, body())
    return success_object(render_membership(membership))


@api.post("/memberships/<membership_id>/cancel")
def cancel_membership(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    membership_service.cancel(membership, body())
    return success_object(render_membership(membership))


@api.post("/memberships/<membership_id>/reactivate")
def reactivate_membership(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    membership_service.reactivate(membership, body())
    return success_object(render_membership(membership))


@api.get("/memberships/<membership_id>/summary")
def membership_summary(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    view = render_membership(membership)
    view["devices"] = [
        render_device(row) for row in db.STORE["devices"].values()
        if row["membership_id"] == membership["id"]
    ]
    return success_object(view)


# ===========================================================================
# HouseholdUser
# ===========================================================================
@api.get("/household-users")
def list_household_users():
    caller(OWNER_ADMIN)
    rows = list(db.STORE["household_users"].values())
    wanted_membership = request.args.get("membership_id")
    if wanted_membership:
        db.require("memberships", wanted_membership)
        rows = [row for row in rows if row["membership_id"] == wanted_membership]
    rows = [
        row for row in rows
        if query_matches(request.args, "streaming_device_serial", row["streaming_device_serial"])
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([household_user_view(row) for row in page], limit, offset, total)


@api.post("/memberships/<membership_id>/household-users")
def create_household_user(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    user = household.create(membership, body())
    return success_object(household_user_view(user), 201)


@api.get("/memberships/<membership_id>/household-users")
def list_membership_household_users(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    rows = [
        row for row in db.STORE["household_users"].values()
        if row["membership_id"] == membership["id"]
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([household_user_view(row) for row in page], limit, offset, total)


@api.get("/household-users/<user_id>")
def get_household_user(user_id):
    who = caller(OWNER_ADMIN)
    return success_object(household_user_view(load_owned("household_users", user_id, who)))


@api.post("/household-users/<user_id>/verify")
def verify_household_user(user_id):
    user = load_owned("household_users", user_id, caller(("MembershipOwner", "PlatformAdmin", "Anonymous")))
    household.verify(user, body())
    return success_object(household_user_view(user))


@api.post("/household-users/<user_id>/start-stream")
def start_stream(user_id):
    user = load_owned("household_users", user_id, caller(OWNER_ADMIN))
    household.start_stream(user, body())
    return success_object(household_user_view(user))


@api.post("/household-users/<user_id>/suspend")
def suspend_household_user(user_id):
    caller(PLATFORM_ADMIN)
    user = db.require("household_users", user_id)
    household.suspend(user, body())
    return success_object(household_user_view(user))


@api.post("/household-users/<user_id>/unsuspend")
def unsuspend_household_user(user_id):
    user = load_owned("household_users", user_id, caller(OWNER_ADMIN))
    household.unsuspend(user)
    return success_object(household_user_view(user))


# ===========================================================================
# Device
# ===========================================================================
@api.post("/memberships/<membership_id>/devices")
def create_device(membership_id):
    caller(TECH_ADMIN)
    membership = load_membership(membership_id)
    device = device_service.create(membership, body())
    return success_object(render_device(device), 201)


@api.get("/memberships/<membership_id>/devices")
def list_membership_devices(membership_id):
    who = caller(OWNER_TECH_ADMIN)
    membership = load_membership(membership_id, who)
    rows = [
        row for row in db.STORE["devices"].values()
        if row["membership_id"] == membership["id"]
        and query_matches(request.args, "activation_status", row["activation_status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([render_device(row) for row in page], limit, offset, total)


@api.get("/devices/<device_id>")
def get_device(device_id):
    who = caller(OWNER_TECH_ADMIN)
    return success_object(render_device(load_owned("devices", device_id, who)))


@api.post("/devices/<device_id>/link")
def link_device(device_id):
    caller(TECH_ADMIN)
    device = db.require("devices", device_id)
    device_service.link(device, body())
    return success_object(render_device(device))


@api.post("/devices/<device_id>/warranty-reset")
def warranty_reset(device_id):
    caller(TECH_ADMIN)
    device = db.require("devices", device_id)
    device_service.warranty_reset(device)
    return success_object(render_device(device))


@api.get("/devices")
def list_devices():
    caller(TECH_ADMIN)
    rows = list(db.STORE["devices"].values())
    for field_name in ("membership_id", "certifying_device_id", "return_device_id",
                       "activation_status"):
        rows = [row for row in rows if query_matches(request.args, field_name, row.get(field_name))]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([render_device(row) for row in page], limit, offset, total)


# ===========================================================================
# HardwareOrder
# ===========================================================================
@api.post("/memberships/<membership_id>/hardware-orders")
def create_hardware_order(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    order = order_service.create(membership, body())
    # Placing an order bumps the membership's version (order membership stale
    # rule): the returned row is refreshed so its version field is current.
    db.touch(membership)
    return success_object(hardware_order_view(order), 201)


@api.get("/memberships/<membership_id>/hardware-orders")
def list_membership_orders(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    rows = [
        row for row in db.STORE["hardware_orders"].values()
        if row["membership_id"] == membership["id"]
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([hardware_order_view(row) for row in page], limit, offset, total)


@api.get("/hardware-orders/<order_id>")
def get_hardware_order(order_id):
    who = caller(OWNER_ADMIN)
    return success_object(hardware_order_view(load_owned("hardware_orders", order_id, who)))


@api.get("/hardware-orders")
def list_hardware_orders():
    caller(OWNER_ADMIN)
    rows = list(db.STORE["hardware_orders"].values())
    for field_name in ("membership_id", "device_id", "return_device_id", "status"):
        rows = [row for row in rows if query_matches(request.args, field_name, row.get(field_name))]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([hardware_order_view(row) for row in page], limit, offset, total)


@api.post("/hardware-orders/<order_id>/refund-dispute")
def refund_dispute(order_id):
    caller(PLATFORM_ADMIN)
    order = db.require("hardware_orders", order_id)
    order_service.record_dispute(order, body())
    return success_object(hardware_order_view(order))


@api.post("/hardware-orders/<order_id>/redeem-refund")
def redeem_refund(order_id):
    who = caller(OWNER_ADMIN)
    order = load_owned("hardware_orders", order_id, who)
    membership = load_membership(order["membership_id"], who)
    order_service.redeem_refund(order, membership, body())
    return success_object(hardware_order_view(order))


@api.get("/devices/<device_id>/hardware-orders")
def list_device_orders(device_id):
    caller(OWNER_TECH_ADMIN)
    db.require("devices", device_id)
    rows = [
        row for row in db.STORE["hardware_orders"].values()
        if row["device_id"] == device_id or row["return_device_id"] == device_id
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([hardware_order_view(row) for row in page], limit, offset, total)


@api.get("/hardware-orders/<order_id>/delivery-appointments")
def list_order_appointments(order_id):
    caller(TECH_ADMIN)
    db.require("hardware_orders", order_id)
    rows = [
        row for row in db.STORE["delivery_appointments"].values()
        if row["hardware_order_id"] == order_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([delivery_appointment_view(row) for row in page], limit, offset, total)


@api.get("/hardware-orders/<order_id>/service-orders")
def list_order_service_orders(order_id):
    caller(TECH_ADMIN)
    db.require("hardware_orders", order_id)
    rows = [
        row for row in db.STORE["service_orders"].values()
        if row["order_id"] == order_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([service_order_view(row) for row in page], limit, offset, total)


@api.post("/hardware-orders/<order_id>/cancel")
def cancel_hardware_order(order_id):
    who = caller(OWNER_ADMIN)
    order = load_owned("hardware_orders", order_id, who)
    order_service.cancel(order)
    return success_object(hardware_order_view(order))


# ===========================================================================
# DeliveryAppointment
# ===========================================================================
@api.post("/delivery-appointments")
def create_delivery_appointment():
    caller(TECH_ADMIN)
    appointment = delivery.create(body())
    return success_object(delivery_appointment_view(appointment), 201)


@api.get("/delivery-appointments")
def list_delivery_appointments():
    caller(TECH_ADMIN)
    rows = list(db.STORE["delivery_appointments"].values())
    for field_name in ("device_id", "hardware_order_id", "technician_crew_code", "status"):
        rows = [row for row in rows if query_matches(request.args, field_name, row.get(field_name))]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([delivery_appointment_view(row) for row in page], limit, offset, total)


@api.get("/delivery-appointments/<appointment_id>")
def get_delivery_appointment(appointment_id):
    who = caller(TECH_ADMIN)
    return success_object(
        delivery_appointment_view(load_owned("delivery_appointments", appointment_id, who))
    )


@api.get("/devices/<device_id>/delivery-appointments")
def list_device_appointments(device_id):
    caller(TECH_ADMIN)
    db.require("devices", device_id)
    rows = [
        row for row in db.STORE["delivery_appointments"].values()
        if row["device_id"] == device_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([delivery_appointment_view(row) for row in page], limit, offset, total)


@api.post("/delivery-appointments/<appointment_id>/schedule")
def schedule_appointment(appointment_id):
    caller(TECH_ADMIN)
    appointment = db.require("delivery_appointments", appointment_id)
    delivery.schedule(appointment, body())
    return success_object(delivery_appointment_view(appointment))


@api.post("/delivery-appointments/<appointment_id>/start")
def start_appointment(appointment_id):
    caller(TECH_ADMIN)
    appointment = db.require("delivery_appointments", appointment_id)
    delivery.start(appointment)
    return success_object(delivery_appointment_view(appointment))


@api.post("/delivery-appointments/<appointment_id>/complete")
def complete_appointment(appointment_id):
    caller(TECH_ADMIN)
    appointment = db.require("delivery_appointments", appointment_id)
    delivery.complete(appointment, body())
    return success_object(delivery_appointment_view(appointment))


@api.post("/delivery-appointments/<appointment_id>/fail")
def fail_appointment(appointment_id):
    caller(TECH_ADMIN)
    appointment = db.require("delivery_appointments", appointment_id)
    delivery.fail(appointment, body())
    return success_object(delivery_appointment_view(appointment))


@api.post("/delivery-appointments/<appointment_id>/reschedule")
def reschedule_appointment(appointment_id):
    caller(TECH_ADMIN)
    appointment = db.require("delivery_appointments", appointment_id)
    delivery.reschedule(appointment, body())
    return success_object(delivery_appointment_view(appointment))


@api.post("/delivery-quotes")
def delivery_quote():
    caller(QUOTE_ROLES)
    return success_object(delivery.quote(body()))


# ===========================================================================
# FinancingPlan
# ===========================================================================
@api.get("/financing-plans")
def list_financing_plans():
    caller(OWNER_ADMIN)
    rows = list(db.STORE["financing_plans"].values())
    for field_name in ("membership_id", "order_id", "status"):
        rows = [row for row in rows if query_matches(request.args, field_name, row.get(field_name))]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([financing_plan_view(row) for row in page], limit, offset, total)


@api.post("/financing-plans")
def create_financing_plan():
    caller(OWNER_ADMIN)
    plan = financing.create(body())
    return success_object(financing_plan_view(plan), 201)


@api.get("/memberships/<membership_id>/financing-plans")
def list_membership_plans(membership_id):
    who = caller(OWNER_ADMIN)
    membership = load_membership(membership_id, who)
    rows = [
        row for row in db.STORE["financing_plans"].values()
        if row["membership_id"] == membership["id"]
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([financing_plan_view(row) for row in page], limit, offset, total)


@api.get("/hardware-orders/<order_id>/financing-plans")
def list_order_plans(order_id):
    caller(OWNER_ADMIN)
    db.require("hardware_orders", order_id)
    rows = [row for row in db.STORE["financing_plans"].values() if row["order_id"] == order_id]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([financing_plan_view(row) for row in page], limit, offset, total)


@api.get("/financing-plans/<plan_id>")
def get_financing_plan(plan_id):
    who = caller(OWNER_ADMIN)
    return success_object(financing_plan_view(load_owned("financing_plans", plan_id, who)))


@api.post("/financing-plans/<plan_id>/installments/pay")
def pay_installment(plan_id):
    who = caller(OWNER_ADMIN)
    plan = load_owned("financing_plans", plan_id, who)
    financing.pay(plan)
    return success_object(financing_plan_view(plan))


@api.post("/financing-plans/<plan_id>/installments/fail")
def fail_installment(plan_id):
    caller(PLATFORM_ADMIN)
    plan = db.require("financing_plans", plan_id)
    financing.fail(plan)
    return success_object(financing_plan_view(plan))


@api.post("/financing-plans/<plan_id>/installments/rolling-correction")
def rolling_correction(plan_id):
    caller(PLATFORM_ADMIN)
    plan = db.require("financing_plans", plan_id)
    financing.rolling_correction(plan)
    return success_object(financing_plan_view(plan))


# ===========================================================================
# ServiceOrder
# ===========================================================================
@api.get("/service-orders")
def list_service_orders():
    caller(TECH_ADMIN)
    rows = list(db.STORE["service_orders"].values())
    for field_name in ("device_id", "order_id", "part_id", "status"):
        rows = [row for row in rows if query_matches(request.args, field_name, row.get(field_name))]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([service_order_view(row) for row in page], limit, offset, total)


@api.post("/service-orders")
def dispatch_service_order():
    who = caller(OWNER_TECH_ADMIN)
    payload = body()
    if who.is_owner:
        device_id = payload.get("device_id")
        device = db.require("devices", device_id) if device_id else None
        if device is None or device["membership_id"] != who.user_id:
            raise api_error("ERR_UNAUTHORIZED")
    order = service_order_service.dispatch(payload)
    return success_object(service_order_view(order), 201)


@api.get("/service-orders/<service_order_id>")
def get_service_order(service_order_id):
    who = caller(TECH_ADMIN)
    return success_object(
        service_order_view(load_owned("service_orders", service_order_id, who))
    )


@api.get("/devices/<device_id>/service-orders")
def list_device_service_orders(device_id):
    caller(TECH_ADMIN)
    db.require("devices", device_id)
    rows = [
        row for row in db.STORE["service_orders"].values()
        if row["device_id"] == device_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([service_order_view(row) for row in page], limit, offset, total)


@api.post("/service-orders/<service_order_id>/reserve-part")
def reserve_part(service_order_id):
    caller(TECH_ADMIN)
    order = db.require("service_orders", service_order_id)
    service_order_service.reserve_part(order, body())
    return success_object(service_order_view(order))


@api.post("/parts-inventory/<part_id>/reservation-release")
def reservation_release(part_id):
    caller(PLATFORM_ADMIN)
    part = db.require("parts_inventory", part_id)
    order = service_order_service.release_reservation(part, body())
    return success_object(service_order_view(order))


@api.post("/service-orders/<service_order_id>/schedule")
def schedule_service_order(service_order_id):
    caller(TECH_ADMIN)
    order = db.require("service_orders", service_order_id)
    service_order_service.schedule(order, body())
    return success_object(service_order_view(order))


@api.post("/service-orders/<service_order_id>/start-repair")
def start_repair(service_order_id):
    caller(TECH_ADMIN)
    order = db.require("service_orders", service_order_id)
    service_order_service.start_repair(order)
    return success_object(service_order_view(order))


@api.post("/service-orders/<service_order_id>/resolve")
def resolve_service_order(service_order_id):
    caller(TECH_ADMIN)
    order = db.require("service_orders", service_order_id)
    service_order_service.resolve(order, body())
    return success_object(service_order_view(order))


@api.post("/service-orders/<service_order_id>/fail-repair")
def fail_repair(service_order_id):
    caller(TECH_ADMIN)
    order = db.require("service_orders", service_order_id)
    service_order_service.fail_repair(order, body())
    return success_object(service_order_view(order))


# ===========================================================================
# PartsInventory
# ===========================================================================
@api.get("/parts-inventory")
def list_parts():
    caller(TECH_ADMIN)
    rows = [
        row for row in db.STORE["parts_inventory"].values()
        if query_matches(request.args, "compatible_sku", row["compatible_sku"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([parts_inventory_view(row) for row in page], limit, offset, total)


@api.get("/parts-inventory/<part_id>/service-orders")
def list_part_service_orders(part_id):
    caller(TECH_ADMIN)
    db.require("parts_inventory", part_id)
    rows = [
        row for row in db.STORE["service_orders"].values()
        if row["part_id"] == part_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([service_order_view(row) for row in page], limit, offset, total)


@api.post("/parts-inventory")
def register_part():
    caller(PLATFORM_ADMIN)
    part = parts.register(body())
    return success_object(parts_inventory_view(part), 201)


@api.get("/parts-inventory/<part_id>")
def get_part(part_id):
    caller(TECH_ADMIN)
    return success_object(parts_inventory_view(db.require("parts_inventory", part_id)))


@api.post("/parts-inventory/<part_id>/restock")
def restock_part(part_id):
    caller(PLATFORM_ADMIN)
    part = db.require("parts_inventory", part_id)
    parts.restock(part, body())
    return success_object(parts_inventory_view(part))


@api.get("/service-orders/<service_order_id>/parts")
def list_service_order_parts(service_order_id):
    caller(TECH_ADMIN)
    order = db.require("service_orders", service_order_id)
    rows = []
    if order["part_id"] is not None:
        part = db.STORE["parts_inventory"].get(order["part_id"])
        if part is not None:
            rows.append(part)
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([parts_inventory_view(row) for row in page], limit, offset, total)


# ===========================================================================
# ClassSession
# ===========================================================================
@api.post("/class-sessions")
def create_class_session():
    caller(INSTRUCTOR_ADMIN)
    session = classes.create_session(body())
    return success_object(class_session_view(session), 201)


@api.get("/class-sessions/<session_id>")
def get_class_session(session_id):
    caller(TEACHING_ROLES)
    return success_object(class_session_view(db.require("class_sessions", session_id)))


@api.get("/class-sessions")
def list_class_sessions():
    caller(TEACHING_ROLES)
    rows = list(db.STORE["class_sessions"].values())
    for field_name in ("instructor_name", "discipline", "delivery_mode", "scheduled_status"):
        rows = [row for row in rows if query_matches(request.args, field_name, row.get(field_name))]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([class_session_view(row) for row in page], limit, offset, total)


@api.post("/class-sessions/<session_id>/publish")
def publish_class_session(session_id):
    caller(INSTRUCTOR_ADMIN)
    session = db.require("class_sessions", session_id)
    classes.publish(session)
    return success_object(class_session_view(session))


@api.post("/class-sessions/<session_id>/cancel")
def cancel_class_session(session_id):
    caller(INSTRUCTOR_ADMIN)
    session = db.require("class_sessions", session_id)
    classes.cancel_session(session)
    return success_object(class_session_view(session))


@api.get("/class-sessions/<session_id>/leaderboard")
def class_leaderboard(session_id):
    caller(TEACHING_ROLES)
    session = db.require("class_sessions", session_id)
    return success_object(classes.leaderboard(session))


# ===========================================================================
# ClassEnrollment
# ===========================================================================
@api.get("/class-enrollments")
def list_class_enrollments():
    caller(TEACHING_ROLES)
    rows = list(db.STORE["class_enrollments"].values())
    for field_name in ("class_session_id", "device_id", "enroller_user_id", "status"):
        rows = [row for row in rows if query_matches(request.args, field_name, row.get(field_name))]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([class_enrollment_view(row) for row in page], limit, offset, total)


@api.post("/class-enrollments")
def create_class_enrollment():
    caller(OWNER_ADMIN)
    enrollment = classes.enroll(body())
    return success_object(class_enrollment_view(enrollment), 201)


@api.get("/class-sessions/<session_id>/class-enrollments")
def list_session_enrollments(session_id):
    caller(TEACHING_ROLES)
    db.require("class_sessions", session_id)
    rows = [
        row for row in db.STORE["class_enrollments"].values()
        if row["class_session_id"] == session_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([class_enrollment_view(row) for row in page], limit, offset, total)


@api.get("/devices/<device_id>/class-enrollments")
def list_device_enrollments(device_id):
    caller(OWNER_TECH_ADMIN)
    db.require("devices", device_id)
    rows = [
        row for row in db.STORE["class_enrollments"].values()
        if row["device_id"] == device_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([class_enrollment_view(row) for row in page], limit, offset, total)


@api.get("/household-users/<user_id>/class-enrollments")
def list_user_enrollments(user_id):
    who = caller(OWNER_ADMIN)
    load_owned("household_users", user_id, who)
    rows = [
        row for row in db.STORE["class_enrollments"].values()
        if row["enroller_user_id"] == user_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([class_enrollment_view(row) for row in page], limit, offset, total)


@api.post("/class-enrollments/<enrollment_id>/complete")
def complete_enrollment(enrollment_id):
    who = caller(OWNER_ADMIN)
    enrollment = load_owned("class_enrollments", enrollment_id, who)
    classes.complete(enrollment, body())
    return success_object(class_enrollment_view(enrollment))


@api.post("/class-enrollments/<enrollment_id>/drop")
def drop_enrollment(enrollment_id):
    who = caller(OWNER_ADMIN)
    enrollment = load_owned("class_enrollments", enrollment_id, who)
    classes.drop(enrollment)
    return success_object(class_enrollment_view(enrollment))


@api.get("/class-enrollments/<enrollment_id>")
def get_class_enrollment(enrollment_id):
    who = caller(TEACHING_ROLES)
    return success_object(
        class_enrollment_view(load_owned("class_enrollments", enrollment_id, who))
    )


# ===========================================================================
# RefurbBatch
# ===========================================================================
@api.post("/refurb-batches")
def open_refurb_batch():
    caller(TECH_ADMIN)
    batch = refurb.open_batch(body())
    return success_object(refurb_batch_view(batch), 201)


@api.get("/devices/<device_id>/refurb-batches")
def list_device_refurb_batches(device_id):
    caller(TECH_ADMIN)
    db.require("devices", device_id)
    rows = [
        row for row in db.STORE["refurb_batches"].values()
        if row["source_device_id"] == device_id
        and query_matches(request.args, "status", row["status"])
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([refurb_batch_view(row) for row in page], limit, offset, total)


@api.get("/devices/<device_id>/refurb-batches-sold")
def list_device_refurb_batches_sold(device_id):
    caller(TECH_ADMIN)
    db.require("devices", device_id)
    rows = [
        row for row in db.STORE["refurb_batches"].values()
        if row["sold_device_id"] == device_id
    ]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([refurb_batch_view(row) for row in page], limit, offset, total)


@api.get("/refurb-batches")
def list_refurb_batches():
    caller(TECH_ADMIN)
    rows = list(db.STORE["refurb_batches"].values())
    for field_name in ("source_device_id", "sold_device_id", "status"):
        rows = [row for row in rows if query_matches(request.args, field_name, row.get(field_name))]
    page, limit, offset, total = paginate(rows, request.args)
    return success_array([refurb_batch_view(row) for row in page], limit, offset, total)


@api.get("/refurb-batches/<batch_id>")
def get_refurb_batch(batch_id):
    caller(TECH_ADMIN)
    return success_object(refurb_batch_view(db.require("refurb_batches", batch_id)))


@api.post("/refurb-batches/<batch_id>/certify")
def certify_refurb_batch(batch_id):
    caller(TECH_ADMIN)
    batch = db.require("refurb_batches", batch_id)
    refurb.certify(batch, body())
    return success_object(refurb_batch_view(batch))


@api.post("/refurb-batches/<batch_id>/list")
def list_refurb_batch(batch_id):
    caller(PLATFORM_ADMIN)
    batch = db.require("refurb_batches", batch_id)
    refurb.list_batch(batch)
    return success_object(refurb_batch_view(batch))


@api.post("/refurb-batches/<batch_id>/sell")
def sell_refurb_batch(batch_id):
    caller(PLATFORM_ADMIN)
    batch = db.require("refurb_batches", batch_id)
    refurb.sell(batch, body())
    return success_object(refurb_batch_view(batch))


# ===========================================================================
# Test-driving endpoints
# ===========================================================================
@api.post("/_clock/set_current_utc")
def set_current_utc():
    no_auth()
    payload = body()
    reject_unknown(payload, {"current_utc"})
    return success_object(ops.set_current_utc(payload))


@api.post("/_run_ops")
def run_ops():
    caller(PLATFORM_ADMIN)
    return success_object(ops.run_sweep())