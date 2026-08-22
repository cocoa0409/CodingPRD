"""Logical clock, projects, boiler zones, casting beds and yard slots."""
from flask import Blueprint

import auth
import calc
import constants
import db
import errors
import listing
import lookup
import response
import serialize
import validation

bp = Blueprint("plant", __name__)


# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4)
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require(constants.ROLE_PLANT_ADMIN)
    body = validation.get_body()
    instant = validation.req_datetime(body, "to_iso8601")
    db.store.clock = instant
    return response.object_response({"current_utc": db.store.now_iso()}, 200)


# ---------------------------------------------------------------------------
# Project (PRD 3.2)
# ---------------------------------------------------------------------------
@bp.post("/projects")
def create_project():
    auth.require(constants.ROLE_PLANT_ADMIN)
    body = validation.get_body()
    name = validation.req_str(body, "name")
    jobsite_city = validation.req_str(body, "jobsite_city")
    erection_start_date = validation.req_date(body, "erection_start_date")
    row = db.new_row(db.store.projects, {
        "name": name,
        "jobsite_city": jobsite_city,
        "erection_start_date": erection_start_date,
    })
    db.mark_fresh(row)
    return response.object_response(serialize.project(row), 201)


@bp.get("/projects/<project_id>")
def get_project(project_id):
    auth.require_any()
    row = lookup.project(project_id)
    return response.object_response(serialize.project(row), 200)


# ---------------------------------------------------------------------------
# SteamZone (PRD 3.4)
# ---------------------------------------------------------------------------
@bp.post("/steam-zones")
def create_steam_zone():
    auth.require(constants.ROLE_PLANT_ADMIN)
    body = validation.get_body()
    zone_code = validation.req_str(body, "zone_code")
    capacity = validation.req_number(body, "boiler_capacity_bhp", exclusive_min=0)
    rate = validation.req_int(body, "therm_rate_cents_per_therm", exclusive_min=0)
    for existing in db.store.steam_zones.values():
        if existing["zone_code"] == zone_code:
            errors.fail(errors.ERR_DUPLICATE_RESOURCE_CODE,
                        "zone_code %s is already registered." % zone_code)
    row = db.new_row(db.store.steam_zones, {
        "zone_code": zone_code,
        "boiler_capacity_bhp": capacity,
        "therm_rate_cents_per_therm": rate,
    })
    db.mark_fresh(row)
    return response.object_response(serialize.steam_zone(row), 201)


@bp.get("/steam-zones/<zone_id>")
def get_steam_zone(zone_id):
    auth.require_any()
    row = lookup.steam_zone(zone_id)
    return response.object_response(serialize.steam_zone(row), 200)


@bp.get("/steam-zones/<zone_id>/casting-beds")
def list_zone_beds(zone_id):
    auth.require_any()
    lookup.steam_zone(zone_id)
    rows = [b for b in db.store.casting_beds.values()
            if b["steam_zone_id"] == zone_id]
    return listing.list_response(rows, serialize.casting_bed)


@bp.get("/steam-zones/<zone_id>/curing-cycles")
def list_zone_cycles(zone_id):
    auth.require_any()
    lookup.steam_zone(zone_id)
    status = validation.query_filter("status")
    rows = [c for c in db.store.curing_cycles.values()
            if c["steam_zone_id"] == zone_id
            and (status is None or c["status"] == status)]
    return listing.list_response(rows, serialize.curing_cycle)


# ---------------------------------------------------------------------------
# CastingBed (PRD 3.3)
# ---------------------------------------------------------------------------
@bp.post("/casting-beds")
def create_casting_bed():
    auth.require(constants.ROLE_PLANT_ADMIN)
    body = validation.get_body()
    bed_code = validation.req_str(body, "bed_code")
    steam_zone_id = validation.req_id(body, "steam_zone_id")
    bed_type = validation.req_enum(body, "bed_type", constants.BED_TYPES)
    length_ft = validation.req_number(body, "length_ft", exclusive_min=0)
    max_force = validation.req_number(body, "max_strand_force_kips", exclusive_min=0)
    buffer_hours = validation.req_int(body, "turnaround_buffer_hours", minimum=0)
    status = validation.opt_enum(body, "status", constants.BED_STATUSES, "AVAILABLE")
    lookup.steam_zone(steam_zone_id)
    for existing in db.store.casting_beds.values():
        if existing["bed_code"] == bed_code:
            errors.fail(errors.ERR_DUPLICATE_RESOURCE_CODE,
                        "bed_code %s is already registered." % bed_code)
    row = db.new_row(db.store.casting_beds, {
        "bed_code": bed_code,
        "steam_zone_id": steam_zone_id,
        "bed_type": bed_type,
        "length_ft": length_ft,
        "max_strand_force_kips": max_force,
        "turnaround_buffer_hours": buffer_hours,
        "status": status,
    })
    db.mark_fresh(row)
    return response.object_response(serialize.casting_bed(row), 201)


@bp.get("/casting-beds/<bed_id>")
def get_casting_bed(bed_id):
    auth.require_any()
    row = lookup.casting_bed(bed_id)
    return response.object_response(serialize.casting_bed(row), 200)


# ---------------------------------------------------------------------------
# YardSlot (PRD 3.7)
# ---------------------------------------------------------------------------
@bp.post("/yard-slots")
def create_yard_slot():
    auth.require(constants.ROLE_PLANT_ADMIN)
    body = validation.get_body()
    slot_code = validation.req_str(body, "slot_code")
    bay_code = validation.req_str(body, "bay_code")
    capacity = validation.req_number(body, "capacity_weight_lb", exclusive_min=0)
    max_stack = validation.req_int(body, "max_stack_count", minimum=1)
    status = validation.opt_enum(body, "status", constants.YARD_SLOT_STATUSES, "EMPTY")
    for existing in db.store.yard_slots.values():
        if existing["slot_code"] == slot_code:
            errors.fail(errors.ERR_DUPLICATE_RESOURCE_CODE,
                        "slot_code %s is already registered." % slot_code)
    row = db.new_row(db.store.yard_slots, {
        "slot_code": slot_code,
        "bay_code": bay_code,
        "capacity_weight_lb": capacity,
        "max_stack_count": max_stack,
        "seeded_blocked": status == "BLOCKED",
    })
    row["status"] = calc.slot_status(row)
    db.mark_fresh(row)
    return response.object_response(serialize.yard_slot(row), 201)


@bp.get("/yard-slots/<slot_id>")
def get_yard_slot(slot_id):
    auth.require_any()
    row = lookup.yard_slot(slot_id)
    return response.object_response(serialize.yard_slot(row), 200)


@bp.get("/yard-slots/<slot_id>/yard-placements")
def list_slot_placements(slot_id):
    auth.require_any()
    lookup.yard_slot(slot_id)
    status = validation.query_filter("status")
    rows = [p for p in db.store.yard_placements.values()
            if p["yard_slot_id"] == slot_id
            and (status is None or p["status"] == status)]
    return listing.list_response(rows, serialize.yard_placement)
