"""Fueling station endpoints (PRD sections 2.7, 3.3)."""

from flask import Blueprint

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import (
    ApiError, ERR_INDOOR_DISPENSING_NOT_APPROVED, ERR_INDOOR_STORAGE_EXCEEDED,
    ERR_INVALID_DATE_RANGE, ERR_INVALID_STATE,
)

bp = Blueprint("stations", __name__)

READ_ROLES = ("SiteManager", "SafetyOfficer", "ComplianceOfficer")
LOCATION_TYPES = ("INDOOR", "OUTDOOR")
INDOOR_STORAGE_MAX_KG = 200

_UPDATABLE = ("station_code", "location_type", "capacity_kg_per_day",
              "storage_capacity_kg", "construction_start", "construction_end")


def _check_indoor(location_type, storage_capacity_kg):
    if location_type == "INDOOR" and storage_capacity_kg > INDOOR_STORAGE_MAX_KG:
        raise ApiError(ERR_INDOOR_STORAGE_EXCEEDED, 422,
                       "INDOOR station storage_capacity_kg exceeds the "
                       "200 kg fire-code maximum")


@bp.post("/api/sites/<site_id>/stations")
@require_roles("SiteManager")
def create_station(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    code = v.str_value(v.req(data, "station_code"), "station_code", 1, 40)
    loc = v.enum_value(v.req(data, "location_type"), "location_type",
                       LOCATION_TYPES)
    cap = v.number_value(v.req(data, "capacity_kg_per_day"),
                         "capacity_kg_per_day", gt=0)
    storage = v.number_value(v.req(data, "storage_capacity_kg"),
                             "storage_capacity_kg", gt=0)
    cs = v.date_value(v.req(data, "construction_start"), "construction_start")
    ce = v.date_value(v.req(data, "construction_end"), "construction_end")
    if v.parse_date(ce) < v.parse_date(cs):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "construction_end must be on or after construction_start")
    _check_indoor(loc, storage)
    st = helpers.create_rec(db.stations, {
        "site_id": site_id,
        "station_code": code,
        "location_type": loc,
        "capacity_kg_per_day": cap,
        "storage_capacity_kg": storage,
        "construction_start": cs,
        "construction_end": ce,
        "construction_status": "PLANNED",
        "commissioned_at": None,
    })
    return envelope.ok(st, 201)


@bp.get("/api/sites/<site_id>/stations")
@require_roles(*READ_ROLES)
def list_stations(site_id):
    helpers.get_site(site_id)
    items = [s for s in db.stations.values() if s["site_id"] == site_id]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/stations/<sid>")
@require_roles(*READ_ROLES)
def get_station(sid):
    return envelope.ok(helpers.get_or_404(db.stations, sid, "station"), 200)


@bp.put("/api/stations/<sid>")
@require_roles("SiteManager")
def update_station(sid):
    st = helpers.get_or_404(db.stations, sid, "station")
    if st["construction_status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "station can only be updated while PLANNED")
    site = helpers.get_site(st["site_id"])
    helpers.ensure_site_open(site)
    data = v.body()
    merged = dict(st)
    if "station_code" in data:
        merged["station_code"] = v.str_value(data["station_code"],
                                             "station_code", 1, 40)
    if "location_type" in data:
        merged["location_type"] = v.enum_value(data["location_type"],
                                               "location_type", LOCATION_TYPES)
    if "capacity_kg_per_day" in data:
        merged["capacity_kg_per_day"] = v.number_value(
            data["capacity_kg_per_day"], "capacity_kg_per_day", gt=0)
    if "storage_capacity_kg" in data:
        merged["storage_capacity_kg"] = v.number_value(
            data["storage_capacity_kg"], "storage_capacity_kg", gt=0)
    if "construction_start" in data:
        merged["construction_start"] = v.date_value(
            data["construction_start"], "construction_start")
    if "construction_end" in data:
        merged["construction_end"] = v.date_value(
            data["construction_end"], "construction_end")
    if (v.parse_date(merged["construction_end"])
            < v.parse_date(merged["construction_start"])):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "construction_end must be on or after construction_start")
    _check_indoor(merged["location_type"], merged["storage_capacity_kg"])
    for key in _UPDATABLE:
        st[key] = merged[key]
    helpers.touch(st)
    return envelope.ok(st, 200)


@bp.post("/api/stations/<sid>/start-construction")
@require_roles("SiteManager")
def start_construction(sid):
    st = helpers.get_or_404(db.stations, sid, "station")
    if st["construction_status"] != "PERMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "station must be PERMITTED to start construction")
    site = helpers.get_site(st["site_id"])
    helpers.ensure_site_open(site)
    if db.current_date() < v.parse_date(st["construction_start"]):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "construction cannot start before construction_start")
    st["construction_status"] = "CONSTRUCTION"
    helpers.touch(st)
    return envelope.ok(st, 200)


@bp.post("/api/stations/<sid>/commission")
@require_roles("ComplianceOfficer")
def commission_station(sid):
    st = helpers.get_or_404(db.stations, sid, "station")
    if st["construction_status"] != "CONSTRUCTION":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "station must be in CONSTRUCTION to commission")
    site = helpers.get_site(st["site_id"])
    helpers.ensure_site_open(site)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "site must be ACTIVE to commission a station")
    if st["location_type"] == "INDOOR":
        approved = any(
            p["station_id"] == sid and p["permit_type"] == "DISPENSING_INDOOR"
            and p["status"] == "ISSUED"
            for p in db.permits.values())
        if not approved:
            raise ApiError(ERR_INDOOR_DISPENSING_NOT_APPROVED, 422,
                           "INDOOR station requires an ISSUED "
                           "DISPENSING_INDOOR permit to commission")
    st["construction_status"] = "COMMISSIONED"
    st["commissioned_at"] = db.clock_stamp()
    helpers.touch(st)
    return envelope.ok(st, 200)
