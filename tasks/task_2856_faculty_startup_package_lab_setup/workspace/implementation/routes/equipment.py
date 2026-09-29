"""Equipment procurement and the installation fork (PRD 3.7)."""

from flask import Blueprint

import authz
import cascades
import derive
import envelope
import ledger
import lookups
import money
import serialize
import store
import validate
from errors import fail

bp = Blueprint("equipment", __name__)

ORDER_STATUSES = (
    "REQUESTED",
    "ORDERED",
    "DELIVERED",
    "INSTALLED",
    "UTILITY_BLOCKED",
    "CANCELLED",
)
BLOCK_REASONS = ("POWER", "CHILLED_WATER", "FUME_HOOD", "FLOOR_LOAD")
CANCELLABLE = ("REQUESTED", "ORDERED", "DELIVERED", "UTILITY_BLOCKED")

READ_ROLES = (
    authz.ROLE_DEAN_OFFICE,
    authz.ROLE_FACILITIES,
    authz.ROLE_DEAN,
    authz.ROLE_DEPARTMENT_CHAIR,
)


def _package_of(order):
    package = store.db.packages.get(order["package_id"])
    if package is None:
        fail("ERR_PACKAGE_NOT_FOUND", "the funding package no longer exists")
    return package


def _utility_block_reason(order, space):
    """The four-check feasibility test in its pinned order; first failure wins."""
    power_headroom = money.kw(
        money.dec(space["power_kw_capacity"]) - derive.installed_power_kw(space)
    )
    if money.kw(order["required_power_kw"]) > power_headroom:
        return "POWER"
    if order["requires_chilled_water"] and not space["chilled_water_available"]:
        return "CHILLED_WATER"
    hood_headroom = int(space["fume_hood_count"]) - derive.installed_fume_hoods(space)
    if int(order["required_fume_hoods"]) > hood_headroom:
        return "FUME_HOOD"
    if int(order["required_floor_load_psf"]) > int(space["floor_load_psf"]):
        return "FLOOR_LOAD"
    return None


@bp.post("/equipment-orders")
def create_order():
    act = authz.actor((authz.ROLE_DEAN_OFFICE, authz.ROLE_FACULTY))
    payload = validate.body()
    package_id = validate.identifier(payload, "package_id")
    space_id = validate.identifier(payload, "install_space_id")
    vendor_name = validate.string(payload, "vendor_name")
    item_description = validate.string(payload, "item_description")
    quoted = validate.cents(payload, "quoted_cents", positive=True)
    lead_time_days = validate.integer(payload, "lead_time_days", minimum=0)
    required_power = validate.number(payload, "required_power_kw", minimum=0)
    requires_chilled = validate.boolean(payload, "requires_chilled_water")
    required_hoods = validate.integer(payload, "required_fume_hoods", minimum=0)
    required_floor_load = validate.integer(
        payload, "required_floor_load_psf", exclusive_min=0
    )
    package = lookups.get_package(package_id)
    space = lookups.get_space(space_id)
    authz.faculty_scope(act, package["faculty_id"])
    record = {
        "id": store.new_id(),
        "package_id": package["id"],
        "install_space_id": space["id"],
        "vendor_name": vendor_name,
        "item_description": item_description,
        "quoted_cents": quoted,
        "lead_time_days": lead_time_days,
        "required_power_kw": money.kw(required_power),
        "requires_chilled_water": requires_chilled,
        "required_fume_hoods": required_hoods,
        "required_floor_load_psf": required_floor_load,
        "status": "REQUESTED",
        "utility_block_reason": None,
        "placed_on": None,
        "expected_delivery_on": None,
        "delivered_on": None,
        "installed_on": None,
        "transfer_disposition": None,
    }
    store.stamp_new(record)
    store.db.equipment_orders[record["id"]] = record
    return envelope.created(serialize.equipment_order(record))


@bp.post("/equipment-orders/<order_id>/place")
def place_order(order_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    expected_version = validate.integer(
        payload, "expected_package_version", minimum=0
    )
    order = lookups.get_order(order_id)
    package = _package_of(order)
    if expected_version != int(package["version"]):
        fail(
            "ERR_STALE_PACKAGE_VERSION",
            "expected_package_version does not match the package's current version",
        )
    if package["spend_status"] != "SPENDING":
        fail(
            "ERR_PACKAGE_SPEND_FROZEN",
            "the funding package is not in spend_status SPENDING",
        )
    if order["status"] != "REQUESTED":
        fail("ERR_SPEND_ITEM_STATE_INVALID", "only a REQUESTED order may be placed")
    record_faculty = store.db.faculty.get(package["faculty_id"])
    if record_faculty is None or record_faculty["appointment_status"] != "ACTIVE":
        fail("ERR_FACULTY_NOT_ACTIVE", "the package's faculty member must be ACTIVE")
    quoted = int(order["quoted_cents"])
    ledger.check_waterfall(package, "EQUIPMENT", quoted)
    order["status"] = "ORDERED"
    order["placed_on"] = ledger.clock_iso()
    order["expected_delivery_on"] = store.iso(
        store.add_days(store.now(), int(order["lead_time_days"]))
    )
    store.touch(order)
    ledger.run_waterfall(
        package,
        "EQUIPMENT",
        quoted,
        ledger.SOURCE_EQUIPMENT_ORDER,
        order["id"],
        "equipment purchase order placed",
    )
    return envelope.object_response(serialize.equipment_order(order))


@bp.post("/equipment-orders/<order_id>/receive")
def receive_order(order_id):
    authz.actor((authz.ROLE_FACILITIES,))
    order = lookups.get_order(order_id)
    if order["status"] != "ORDERED":
        fail("ERR_SPEND_ITEM_STATE_INVALID", "only an ORDERED item may be received")
    order["status"] = "DELIVERED"
    order["delivered_on"] = ledger.clock_iso()
    store.touch(order)
    return envelope.object_response(serialize.equipment_order(order))


@bp.post("/equipment-orders/<order_id>/install")
def install_order(order_id):
    authz.actor((authz.ROLE_FACILITIES,))
    order = lookups.get_order(order_id)
    package = _package_of(order)
    if package["spend_status"] != "SPENDING":
        fail(
            "ERR_PACKAGE_SPEND_FROZEN",
            "the funding package is not in spend_status SPENDING",
        )
    if order["status"] not in ("DELIVERED", "UTILITY_BLOCKED"):
        fail(
            "ERR_SPEND_ITEM_STATE_INVALID",
            "only a DELIVERED or UTILITY_BLOCKED item may be installed",
        )
    space = store.db.lab_spaces.get(order["install_space_id"])
    if space is None:
        fail("ERR_SPACE_NOT_FOUND", "the installation room no longer exists")
    moment = ledger.clock_iso()
    covered = False
    for assignment in derive.assignments_of_space(space["id"]):
        if assignment["status"] != "ACTIVE":
            continue
        if assignment["faculty_id"] != package["faculty_id"]:
            continue
        if derive.window_contains(assignment, moment):
            covered = True
            break
    if not covered:
        fail(
            "ERR_SPACE_NOT_ASSIGNED_TO_FACULTY",
            "the room is not covered by an ACTIVE assignment of this faculty member",
        )
    if space["status"] != "ASSIGNED":
        fail(
            "ERR_SPACE_NOT_READY_FOR_INSTALL",
            "the room must be in status ASSIGNED to receive equipment",
        )
    reason = _utility_block_reason(order, space)
    if reason is not None:
        # The block is a branch, not an error: nothing else happens at all.
        order["status"] = "UTILITY_BLOCKED"
        order["utility_block_reason"] = reason
        store.touch(order)
        return envelope.object_response(serialize.equipment_order(order))
    cascades.install_order(order, package, space)
    return envelope.object_response(serialize.equipment_order(order))


@bp.post("/equipment-orders/<order_id>/cancel")
def cancel_order(order_id):
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    order = lookups.get_order(order_id)
    package = _package_of(order)
    if order["status"] not in CANCELLABLE:
        fail(
            "ERR_SPEND_ITEM_STATE_INVALID",
            "an INSTALLED or CANCELLED order can no longer be cancelled",
        )
    cascades.cancel_order(order, package)
    return envelope.object_response(serialize.equipment_order(order))


@bp.get("/equipment-orders")
def list_orders():
    authz.actor(READ_ROLES)
    limit, offset = validate.pagination()
    package_filter = validate.filter_value("package_id")
    space_filter = validate.filter_value("install_space_id")
    status_filter = validate.filter_value("status", ORDER_STATUSES)
    reason_filter = validate.filter_value("utility_block_reason", BLOCK_REASONS)
    records = store.by_created(list(store.db.equipment_orders.values()))
    if package_filter is not None:
        records = [o for o in records if o["package_id"] == package_filter]
    if space_filter is not None:
        records = [o for o in records if o["install_space_id"] == space_filter]
    if status_filter is not None:
        records = [o for o in records if o["status"] == status_filter]
    if reason_filter is not None:
        records = [o for o in records if o["utility_block_reason"] == reason_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.equipment_order(o) for o in page], limit, offset, total
    )


@bp.get("/equipment-orders/<order_id>")
def read_order(order_id):
    act = authz.actor(READ_ROLES + (authz.ROLE_FACULTY,))
    order = lookups.get_order(order_id)
    package = store.db.packages.get(order["package_id"])
    if package is not None:
        authz.faculty_scope(act, package["faculty_id"])
    return envelope.object_response(serialize.equipment_order(order))
