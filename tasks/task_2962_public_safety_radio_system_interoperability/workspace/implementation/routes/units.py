"""Subscriber unit inventory and its two independent state dimensions."""
from flask import Blueprint

import common
import compute
import db
import enums
import response
import serialize
import validate
from errors import ApiError
from validate import AGENCY_RADIO_MANAGER

bp = Blueprint("units", __name__, url_prefix=common.PREFIX)


@bp.post("/units")
def create_unit():
    actor = validate.authenticate([AGENCY_RADIO_MANAGER])
    body = validate.get_body()
    agency = validate.req_fk(body, "agency_id", "agencies")
    serial = validate.req_str(body, "serial_number", 6, 24, r"^[A-Z0-9]+$")
    radio_id = validate.req_int(body, "radio_id", 1, 16777215)
    model = validate.req_enum(body, "model", enums.UNIT_MODELS)
    priority = validate.opt_int(body, "priority_class", 1, 10, 5)
    emergency = validate.opt_bool(body, "emergency_button_enabled", False)
    common.require_scope(actor, agency["id"])
    for existing in db.store.units.values():
        if existing["serial_number"] == serial or existing["radio_id"] == radio_id:
            raise ApiError("ERR_DUPLICATE_RADIO_ID")
    row = db.base_row({
        "agency_id": agency["id"],
        "template_id": None,
        "active_keyset_id": None,
        "serial_number": serial,
        "radio_id": radio_id,
        "model": model,
        "provision_status": "INVENTORY",
        "key_status": "KEYLESS",
        "priority_class": priority,
        "emergency_button_enabled": emergency,
        "assigned_at": None,
        "retired_at": None,
        "last_otar_at": None,
        "billable": False,
        "days_in_service_last_period": 0,
    })
    db.store.units[row["id"]] = row
    return response.ok(serialize.unit(row), 201)


@bp.get("/units")
def list_units():
    validate.authenticate(common.ANY_ROLE)
    filters = (
        ("agency_id", validate.filter_str("agency_id")),
        ("template_id", validate.filter_str("template_id")),
        ("active_keyset_id", validate.filter_str("active_keyset_id")),
        ("provision_status", validate.filter_enum("provision_status", enums.PROVISION_STATUSES)),
        ("key_status", validate.filter_enum("key_status", enums.KEY_STATUSES)),
    )
    return common.list_endpoint("units", serialize.unit, filters)


@bp.get("/units/<unit_id>")
def read_unit(unit_id):
    validate.authenticate(common.ANY_ROLE)
    unit = validate.lookup("units", unit_id)
    return response.ok(serialize.unit(unit))


@bp.post("/units/<unit_id>/lifecycle")
def unit_lifecycle(unit_id):
    actor = validate.authenticate([AGENCY_RADIO_MANAGER])
    unit = validate.lookup("units", unit_id)
    body = validate.get_body()
    template = validate.opt_fk(body, "template_id", "templates")
    action = validate.req_enum(body, "action", enums.UNIT_ACTIONS)
    if action == "ASSIGN" and template is None:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'template_id' is required for ASSIGN.")
    common.require_scope(actor, unit["agency_id"])
    agency = db.store.agencies.get(unit["agency_id"])

    if action == "ZEROIZE":
        if unit["key_status"] == "ZEROIZED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        previous = unit["active_keyset_id"]
        unit["key_status"] = "ZEROIZED"
        unit["active_keyset_id"] = None
        db.touch(unit)
        if previous is not None:
            keyset = db.store.keysets.get(previous)
            if keyset is not None:
                compute.recompute_keyset_loaded_count(keyset)
        return response.ok(serialize.unit(unit))

    if action == "RETIRE":
        if unit["provision_status"] == "RETIRED":
            raise ApiError("ERR_UNIT_RETIRED")
        unit["provision_status"] = "RETIRED"
        unit["retired_at"] = db.now()
        unit["billable"] = False
        db.touch(unit)
        if agency is not None:
            compute.recompute_billable_count(agency)
        return response.ok(serialize.unit(unit))

    if action == "ASSIGN":
        if unit["provision_status"] != "INVENTORY":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        if template["status"] != "PUBLISHED":
            raise ApiError("ERR_TEMPLATE_NOT_PUBLISHED")
        live = 0
        for talkgroup in db.store.talkgroups.values():
            if talkgroup["owner_agency_id"] == unit["agency_id"] and \
                    talkgroup["status"] in compute.LIVE_TALKGROUP_STATUSES:
                live += 1
        if live > template["talkgroup_slot_count"]:
            raise ApiError("ERR_TEMPLATE_SLOT_CAPACITY_EXCEEDED")
        unit["template_id"] = template["id"]
        unit["assigned_at"] = db.now()
        unit["billable"] = True
        unit["provision_status"] = "ASSIGNED"
        db.touch(unit)
        if agency is not None:
            compute.recompute_billable_count(agency)
        compute.recompute_template_deployed_count(template)
        return response.ok(serialize.unit(unit))

    if action == "SUSPEND":
        if unit["provision_status"] != "ASSIGNED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION")
        unit["provision_status"] = "SUSPENDED"
        unit["billable"] = True
        db.touch(unit)
        site_ids = set()
        for request_row in db.sort_rows(list(db.store.talkpaths.values())):
            if request_row["unit_id"] != unit["id"]:
                continue
            if request_row["outcome"] != "GRANTED" or request_row["released_at"] is not None:
                continue
            request_row["outcome"] = "RELEASED"
            request_row["released_at"] = db.now()
            request_row["hold_seconds"] = compute.hold_seconds_for(request_row)
            db.touch(request_row)
            site_ids.add(request_row["site_id"])
        for site_id in site_ids:
            site = db.store.sites.get(site_id)
            if site is not None:
                compute.recompute_site_counters(site)
        if agency is not None:
            compute.recompute_billable_count(agency)
        return response.ok(serialize.unit(unit))

    # REINSTATE
    if unit["provision_status"] != "SUSPENDED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    unit["provision_status"] = "ASSIGNED"
    unit["billable"] = True
    db.touch(unit)
    if agency is not None:
        compute.recompute_billable_count(agency)
    return response.ok(serialize.unit(unit))
