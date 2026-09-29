"""Laboratory rooms, their utility envelope, and fractional occupancy (PRD 3.5)."""

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

bp = Blueprint("spaces", __name__)

SPACE_CLASSES = ("WET", "DRY", "COMPUTATIONAL")
SPACE_STATUSES = ("AVAILABLE", "ASSIGNED", "UNDER_RENOVATION", "DECOMMISSIONED")
ASSIGNMENT_STATUSES = ("PROPOSED", "ACTIVE", "RELEASED", "WITHDRAWN")

SPACE_READ_ROLES = (
    authz.ROLE_FACILITIES,
    authz.ROLE_DEAN_OFFICE,
    authz.ROLE_DEAN,
    authz.ROLE_DEPARTMENT_CHAIR,
)


@bp.post("/lab-spaces")
def create_space():
    authz.actor((authz.ROLE_FACILITIES,))
    payload = validate.body()
    building_code = validate.string(payload, "building_code")
    room_number = validate.string(payload, "room_number")
    net_sq_ft = validate.integer(payload, "net_sq_ft", exclusive_min=0)
    space_class = validate.enum(payload, "space_class", SPACE_CLASSES)
    power = validate.number(payload, "power_kw_capacity", exclusive_min=0)
    chilled = validate.boolean(payload, "chilled_water_available")
    hoods = validate.integer(payload, "fume_hood_count", minimum=0)
    floor_load = validate.integer(payload, "floor_load_psf", exclusive_min=0)
    for existing in store.db.lab_spaces.values():
        if (
            existing["building_code"] == building_code
            and existing["room_number"] == room_number
        ):
            fail(
                "ERR_SPACE_ALREADY_REGISTERED",
                "building_code and room_number must be unique across the inventory",
            )
    record = {
        "id": store.new_id(),
        "building_code": building_code,
        "room_number": room_number,
        "net_sq_ft": net_sq_ft,
        "space_class": space_class,
        "status": "AVAILABLE",
        "power_kw_capacity": money.kw(power),
        "chilled_water_available": chilled,
        "fume_hood_count": hoods,
        "floor_load_psf": floor_load,
    }
    store.stamp_new(record)
    store.db.lab_spaces[record["id"]] = record
    return envelope.created(serialize.lab_space(record))


@bp.get("/lab-spaces")
def list_spaces():
    authz.actor(SPACE_READ_ROLES)
    limit, offset = validate.pagination()
    building_filter = validate.filter_value("building_code")
    class_filter = validate.filter_value("space_class", SPACE_CLASSES)
    status_filter = validate.filter_value("status", SPACE_STATUSES)
    records = store.by_created(list(store.db.lab_spaces.values()))
    if building_filter is not None:
        records = [s for s in records if s["building_code"] == building_filter]
    if class_filter is not None:
        records = [s for s in records if s["space_class"] == class_filter]
    if status_filter is not None:
        records = [s for s in records if s["status"] == status_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.lab_space(s) for s in page], limit, offset, total
    )


@bp.get("/lab-spaces/<space_id>")
def read_space(space_id):
    authz.actor(SPACE_READ_ROLES)
    record = lookups.get_space(space_id)
    return envelope.object_response(serialize.lab_space(record))


@bp.post("/lab-spaces/<space_id>/utility-upgrade")
def utility_upgrade(space_id):
    authz.actor((authz.ROLE_FACILITIES,))
    payload = validate.body()
    power = validate.number(payload, "power_kw_capacity", exclusive_min=0)
    hoods = validate.integer(payload, "fume_hood_count", minimum=0)
    chilled = validate.boolean(payload, "chilled_water_available")
    floor_load = validate.integer(payload, "floor_load_psf", exclusive_min=0)
    record = lookups.get_space(space_id)
    if money.kw(power) < derive.installed_power_kw(record):
        fail(
            "ERR_VALIDATION",
            "power_kw_capacity may not fall below the room's installed load",
        )
    if hoods < derive.installed_fume_hoods(record):
        fail(
            "ERR_VALIDATION",
            "fume_hood_count may not fall below the room's installed hoods",
        )
    if not chilled:
        for order in derive.orders_in_space(record["id"], "INSTALLED"):
            if order["requires_chilled_water"]:
                fail(
                    "ERR_VALIDATION",
                    "chilled water is required by an installed instrument",
                )
    record["power_kw_capacity"] = money.kw(power)
    record["fume_hood_count"] = hoods
    record["chilled_water_available"] = chilled
    record["floor_load_psf"] = floor_load
    store.touch(record)
    return envelope.object_response(serialize.lab_space(record))


@bp.post("/space-assignments")
def create_assignment():
    authz.actor((authz.ROLE_DEAN_OFFICE,))
    payload = validate.body()
    space_id = validate.identifier(payload, "space_id")
    faculty_id = validate.identifier(payload, "faculty_id")
    share_pct = validate.percent(payload, "share_pct", minimum=1)
    effective_from = validate.instant(payload, "effective_from")
    effective_to = validate.instant(payload, "effective_to", required=False)
    expected_version = validate.integer(payload, "expected_space_version", minimum=0)
    validate.strictly_before(
        effective_from,
        effective_to,
        "effective_to must be strictly after effective_from",
    )
    record_faculty = lookups.get_faculty(faculty_id)
    space = lookups.get_space(space_id)
    if expected_version != int(space["version"]):
        fail(
            "ERR_STALE_SPACE_VERSION",
            "expected_space_version does not match the room's current version",
        )
    if record_faculty["appointment_status"] not in ("ACTIVE", "CANDIDATE"):
        fail(
            "ERR_FACULTY_NOT_ACTIVE",
            "a room may only be assigned to an ACTIVE or CANDIDATE faculty member",
        )
    window_from = store.iso(effective_from)
    window_to = None if effective_to is None else store.iso(effective_to)
    peers = derive.overlapping_share_pct(space["id"], window_from, window_to)
    if peers + share_pct > 100:
        fail(
            "ERR_SPACE_SHARE_EXCEEDED",
            "the room's overlapping occupancy would exceed 100 percent",
        )
    record = {
        "id": store.new_id(),
        "space_id": space["id"],
        "faculty_id": record_faculty["id"],
        "share_pct": share_pct,
        "effective_from": window_from,
        "effective_to": window_to,
        "status": "PROPOSED",
        "released_on": None,
    }
    store.stamp_new(record)
    store.db.space_assignments[record["id"]] = record
    # The room's allocated_share_pct is re-derived, so the room's version moves.
    store.touch(space)
    return envelope.created(serialize.space_assignment(record))


@bp.post("/space-assignments/<assignment_id>/activate")
def activate_assignment(assignment_id):
    authz.actor((authz.ROLE_FACILITIES,))
    record = lookups.get_assignment_action(assignment_id)
    if record["status"] != "PROPOSED":
        fail(
            "ERR_SPEND_ITEM_STATE_INVALID",
            "only a PROPOSED assignment may be activated",
        )
    record_faculty = store.db.faculty.get(record["faculty_id"])
    if record_faculty is None or record_faculty["appointment_status"] not in (
        "ACTIVE",
        "CANDIDATE",
    ):
        fail(
            "ERR_FACULTY_NOT_ACTIVE",
            "the occupant must still be ACTIVE or CANDIDATE",
        )
    space = store.db.lab_spaces.get(record["space_id"])
    if space is None:
        fail("ERR_SPACE_NOT_FOUND", "the assigned room no longer exists")
    if space["status"] == "DECOMMISSIONED":
        fail(
            "ERR_SPEND_ITEM_STATE_INVALID",
            "a DECOMMISSIONED room cannot take an assignment",
        )
    peers = derive.overlapping_share_pct(
        space["id"], record["effective_from"], record["effective_to"], record["id"]
    )
    if peers + int(record["share_pct"]) > 100:
        fail(
            "ERR_SPACE_SHARE_EXCEEDED",
            "the room's overlapping occupancy would exceed 100 percent",
        )
    record["status"] = "ACTIVE"
    store.touch(record)
    if space["status"] == "AVAILABLE" and derive.window_contains(
        record, ledger.clock_iso()
    ):
        space["status"] = "ASSIGNED"
    store.touch(space)
    return envelope.object_response(serialize.space_assignment(record))


@bp.post("/space-assignments/<assignment_id>/release")
def release_assignment(assignment_id):
    authz.actor((authz.ROLE_FACILITIES,))
    payload = validate.body()
    released_on = validate.instant(payload, "released_on")
    record = lookups.get_assignment_action(assignment_id)
    moment = store.iso(released_on)
    if moment < record["effective_from"]:
        fail(
            "ERR_VALIDATION",
            "released_on must be at or after the assignment's effective_from",
        )
    if record["status"] != "ACTIVE":
        fail(
            "ERR_SPEND_ITEM_STATE_INVALID",
            "only an ACTIVE assignment may be released",
        )
    record["status"] = "RELEASED"
    record["released_on"] = moment
    record["effective_to"] = moment
    store.touch(record)
    space = store.db.lab_spaces.get(record["space_id"])
    if space is not None:
        cascades.refresh_space_status(space)
        store.touch(space)
    return envelope.object_response(serialize.space_assignment(record))


@bp.get("/space-assignments")
def list_assignments():
    authz.actor(SPACE_READ_ROLES)
    limit, offset = validate.pagination()
    space_filter = validate.filter_value("space_id")
    faculty_filter = validate.filter_value("faculty_id")
    status_filter = validate.filter_value("status", ASSIGNMENT_STATUSES)
    records = store.by_created(list(store.db.space_assignments.values()))
    if space_filter is not None:
        records = [a for a in records if a["space_id"] == space_filter]
    if faculty_filter is not None:
        records = [a for a in records if a["faculty_id"] == faculty_filter]
    if status_filter is not None:
        records = [a for a in records if a["status"] == status_filter]
    page, total = validate.paginate(records, limit, offset)
    return envelope.array_response(
        [serialize.space_assignment(a) for a in page], limit, offset, total
    )


@bp.get("/space-assignments/<assignment_id>")
def read_assignment(assignment_id):
    act = authz.actor(SPACE_READ_ROLES + (authz.ROLE_FACULTY,))
    record = lookups.get_assignment_resource(assignment_id)
    authz.faculty_scope(act, record["faculty_id"])
    return envelope.object_response(serialize.space_assignment(record))
