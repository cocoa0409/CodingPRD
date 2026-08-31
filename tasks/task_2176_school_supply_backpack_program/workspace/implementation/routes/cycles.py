"""Drive cycles and the collection-site network."""
from flask import Blueprint

import derive
import find
import response as resp
import validators as v
from db import base_record, db, sort_records, touch
from errors import ApiError
from middleware import (ALL_ROLES, PROGRAM_DIRECTOR, SITE_COORDINATOR, auth,
                        site_scope)

bp = Blueprint("cycles", __name__)


@bp.post("/drive-cycles")
def create_cycle():
    auth([PROGRAM_DIRECTOR])
    data = v.body()
    name = v.req_str(data, "name")
    cadence = v.req_enum(data, "cadence", v.CADENCES)
    window_start, window_end = v.req_window(data)

    rec = base_record()
    rec.update({
        "name": name,
        "cadence": cadence,
        "window_start": window_start,
        "window_end": window_end,
        "status": "DRAFT",
        "cash_received_cents": 0,
        "cash_allocated_cents": 0,
        "cash_available_cents": 0,
        "unrestricted_gross_cents": 0,
        "supplemental_cap_cents": 0,
        "total_items_on_hand": 0,
    })
    db.drive_cycles[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.get("/drive-cycles/<cycle_id>")
def read_cycle(cycle_id):
    auth(ALL_ROLES)
    return resp.ok(find.cycle(cycle_id))


@bp.get("/drive-cycles/<cycle_id>/collection-sites")
def list_cycle_sites(cycle_id):
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    site_type = v.query_enum("site_type", v.SITE_TYPES)
    cycle = find.cycle(cycle_id)
    rows = [s for s in db.collection_sites.values()
            if s["drive_cycle_id"] == cycle["id"]]
    if site_type:
        rows = [s for s in rows if s["site_type"] == site_type]
    return resp.listing(sort_records(rows), limit, offset)


@bp.patch("/drive-cycles/<cycle_id>/status")
def move_cycle_status(cycle_id):
    auth([PROGRAM_DIRECTOR])
    data = v.body()
    target = v.target_status(data)
    cycle = find.cycle(cycle_id)
    current = cycle["status"]

    if target not in v.CYCLE_STATUSES:
        raise ApiError("ERR_INVALID_CYCLE_STATE")

    if target == "COLLECTING":
        if current not in ("DRAFT", "SORTING", "DISTRIBUTION"):
            raise ApiError("ERR_INVALID_CYCLE_STATE")
        if current == "DRAFT" and not cycle["window_start"] < cycle["window_end"]:
            raise ApiError("ERR_INVALID_CYCLE_STATE")
        if current == "DISTRIBUTION" and cycle["cadence"] != "YEAR_ROUND":
            raise ApiError("ERR_CADENCE_FORBIDS_REOPEN")
    elif target == "SORTING":
        if current != "COLLECTING":
            raise ApiError("ERR_INVALID_CYCLE_STATE")
    elif target == "DISTRIBUTION":
        if current != "SORTING":
            raise ApiError("ERR_INVALID_CYCLE_STATE")
        open_batch = any(b["status"] in ("RECEIVED", "INSPECTED", "REMEDIATED")
                         for b in derive.batches_of_cycle(cycle["id"]))
        if open_batch:
            raise ApiError("ERR_INVALID_CYCLE_STATE")
    elif target == "RECONCILED":
        if current != "DISTRIBUTION":
            raise ApiError("ERR_INVALID_CYCLE_STATE")
        live = any(e["status"] in ("PUBLISHED", "LOCKED")
                   for e in derive.events_of_cycle(cycle["id"]))
        if live:
            raise ApiError("ERR_INVALID_CYCLE_STATE")
    elif target == "CLOSED":
        if current != "RECONCILED":
            raise ApiError("ERR_INVALID_CYCLE_STATE")
        if (cycle["cash_allocated_cents"] + cycle["cash_available_cents"]
                != cycle["cash_received_cents"]):
            raise ApiError("ERR_INVALID_CYCLE_STATE")
    else:
        raise ApiError("ERR_INVALID_CYCLE_STATE")

    cycle["status"] = target

    if target == "DISTRIBUTION":
        for pos in derive.positions_of_cycle(cycle["id"]):
            derive.refresh_in_transit(cycle["id"], pos["supply_item_id"])
        derive.recompute_cycle_inventory(cycle)
    elif target == "RECONCILED":
        for order in derive.orders_of_cycle(cycle["id"]):
            if order["status"] == "DRAFT":
                order["status"] = "CANCELLED"
                touch(order)
        school_ids = {e["school_id"] for e in derive.events_of_cycle(cycle["id"])
                      if e["status"] == "CLOSED"}
        for school_id in sorted(school_ids):
            school = db.schools.get(school_id)
            if school is not None:
                derive.recompute_school(school)

    touch(cycle)
    return resp.ok(cycle)


# --------------------------------------------------------------------------
# CollectionSite
# --------------------------------------------------------------------------
@bp.post("/collection-sites")
def create_site():
    auth([PROGRAM_DIRECTOR])
    data = v.body()
    cycle_id = v.req_id(data, "drive_cycle_id")
    name = v.req_str(data, "name")
    site_type = v.req_enum(data, "site_type", v.SITE_TYPES)
    bin_capacity = v.req_int(data, "bin_capacity", minimum=1)
    pledged_item_count = v.opt_int(data, "pledged_item_count", 0, minimum=0)

    cycle = find.cycle(cycle_id)

    rec = base_record()
    rec.update({
        "drive_cycle_id": cycle["id"],
        "name": name,
        "site_type": site_type,
        "bin_capacity": bin_capacity,
        "operational_status": "PENDING",
        "pledge_status": "NONE",
        "pledged_item_count": pledged_item_count,
        "accepted_item_count": 0,
    })
    db.collection_sites[rec["id"]] = rec
    return resp.ok(rec, 201)


@bp.get("/collection-sites/<site_id>")
def read_site(site_id):
    auth(ALL_ROLES)
    return resp.ok(find.site(site_id))


@bp.get("/collection-sites/<site_id>/volunteer-events")
def list_site_volunteer_events(site_id):
    auth(ALL_ROLES)
    limit, offset = v.pagination()
    status = v.query_enum("status", v.VOLUNTEER_STATUSES)
    site = find.site(site_id)
    rows = [e for e in db.volunteer_events.values()
            if e["collection_site_id"] == site["id"]]
    if status:
        rows = [e for e in rows if e["status"] == status]
    return resp.listing(sort_records(rows), limit, offset)


@bp.patch("/collection-sites/<site_id>/operational-status")
def move_site_operational(site_id):
    auth([PROGRAM_DIRECTOR])
    data = v.body()
    target = v.target_status(data)
    site = find.site(site_id)
    current = site["operational_status"]

    if target not in v.SITE_OPERATIONAL_STATUSES:
        raise ApiError("ERR_INVALID_SITE_STATE")

    if target == "ACTIVE":
        if current not in ("PENDING", "PAUSED"):
            raise ApiError("ERR_INVALID_SITE_STATE")
        if current == "PENDING":
            cycle = db.drive_cycles.get(site["drive_cycle_id"])
            if cycle is None or cycle["status"] not in ("COLLECTING", "SORTING"):
                raise ApiError("ERR_INVALID_SITE_STATE")
            if (site["site_type"] == "CORPORATE"
                    and site["pledge_status"] not in ("PLEDGED", "PLEDGE_ACTIVE")):
                raise ApiError("ERR_INVALID_SITE_STATE")
    elif target == "PAUSED":
        if current != "ACTIVE":
            raise ApiError("ERR_INVALID_SITE_STATE")
    elif target == "CLOSED":
        if current not in ("ACTIVE", "PAUSED"):
            raise ApiError("ERR_INVALID_SITE_STATE")
        open_batch = any(b["status"] in ("RECEIVED", "INSPECTED", "REMEDIATED")
                         for b in derive.batches_of_site(site["id"]))
        if open_batch:
            raise ApiError("ERR_INVALID_SITE_STATE")
    else:
        raise ApiError("ERR_INVALID_SITE_STATE")

    site["operational_status"] = target

    if target == "PAUSED":
        for event in derive.sort_records(
                [e for e in db.volunteer_events.values()
                 if e["collection_site_id"] == site["id"]]):
            if event["status"] == "SCHEDULED":
                event["status"] = "CANCELLED"
                touch(event)
    elif target == "CLOSED":
        if (site["site_type"] == "CORPORATE"
                and site["pledge_status"] == "PLEDGE_ACTIVE"
                and site["accepted_item_count"] < site["pledged_item_count"]):
            site["pledge_status"] = "LAPSED"

    touch(site)
    return resp.ok(site)


@bp.patch("/collection-sites/<site_id>/pledge-status")
def move_site_pledge(site_id):
    user_id, role = auth([SITE_COORDINATOR])
    data = v.body()
    target = v.target_status(data)
    site = find.site(site_id)
    site_scope(role, user_id, site["id"])
    current = site["pledge_status"]

    if target not in v.SITE_PLEDGE_STATUSES:
        raise ApiError("ERR_INVALID_SITE_STATE")
    if site["site_type"] != "CORPORATE":
        raise ApiError("ERR_INVALID_SITE_STATE")

    if target == "PLEDGED":
        if current != "NONE":
            raise ApiError("ERR_INVALID_SITE_STATE")
        if site["pledged_item_count"] < 1:
            raise ApiError("ERR_INVALID_SITE_STATE")
    elif target == "PLEDGE_ACTIVE":
        if current != "PLEDGED":
            raise ApiError("ERR_INVALID_SITE_STATE")
        if site["operational_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_SITE_STATE")
    elif target == "FULFILLED":
        if current != "PLEDGE_ACTIVE":
            raise ApiError("ERR_INVALID_SITE_STATE")
        if site["accepted_item_count"] < site["pledged_item_count"]:
            raise ApiError("ERR_PLEDGE_SHORTFALL")
    elif target == "LAPSED":
        if current not in ("PLEDGED", "PLEDGE_ACTIVE"):
            raise ApiError("ERR_INVALID_SITE_STATE")
    else:
        raise ApiError("ERR_INVALID_SITE_STATE")

    site["pledge_status"] = target
    touch(site)
    return resp.ok(site)
