"""Reference data owned by PlatformAdmin (yard assets, disposal facilities)
and by DispatchPlanner (routes)."""
from flask import Blueprint

from auth import ALL_ROLES, endpoint
import constants as C
from db import insert, serialize
from responses import created, ok
from routes.common import resolve
import services
import validation as V

bp = Blueprint("refdata", __name__)


# --------------------------------------------------------------- asset units

@bp.post("/asset-units")
@endpoint(["PlatformAdmin"])
def create_asset_unit():
    body = V.body()
    asset_tag = V.str_field(body, "asset_tag", 1, 32)
    unit_class = V.enum_field(body, "unit_class", C.UNIT_CLASSES)
    yard_code = V.str_field(body, "yard_code", 2, 16)
    tare_length_ft = V.int_field(body, "tare_length_ft", 4, 60)
    V.unique_field("asset_units", "asset_tag", asset_tag)

    row = insert("asset_units", {
        "asset_tag": asset_tag,
        "unit_class": unit_class,
        "yard_code": yard_code,
        "tare_length_ft": tare_length_ft,
        "status": "IN_YARD",
        "damage_strikes": 0,
        "tip_over_count": 0,
    })
    return created(serialize(row))


@bp.get("/asset-units/<unit_id>")
@endpoint(ALL_ROLES)
def read_asset_unit(unit_id):
    return ok(serialize(resolve("asset_units", unit_id)))


# ------------------------------------------------------------ disposal sites

@bp.post("/disposal-sites")
@endpoint(["PlatformAdmin"])
def create_disposal_site():
    body = V.body()
    site_code = V.str_field(body, "site_code", 1, 24)
    daily_gallon_cap = V.int_field(body, "daily_gallon_cap", 100, 500000)
    accepted = V.enum_array_field(body, "accepted_waste_classes", C.WASTE_CLASSES)
    status = V.enum_field(body, "status", C.DISPOSAL_STATUSES,
                          required=False, default="ACCEPTING")
    V.unique_field("disposal_sites", "site_code", site_code)

    row = insert("disposal_sites", {
        "site_code": site_code,
        "daily_gallon_cap": daily_gallon_cap,
        "accepted_waste_classes": accepted,
        "status": status,
        "committed_gallons_today": 0,
    })
    return created(services.disposal_view(row))


@bp.get("/disposal-sites/<disposal_site_id>")
@endpoint(ALL_ROLES)
def read_disposal_site(disposal_site_id):
    return ok(services.disposal_view(resolve("disposal_sites", disposal_site_id)))


# -------------------------------------------------------------------- routes

@bp.post("/routes")
@endpoint(["DispatchPlanner"])
def create_route():
    body = V.body()
    route_code = V.str_field(body, "route_code", 1, 24)
    service_day = V.enum_field(body, "service_day", C.SERVICE_DAYS)
    truck_capacity_units = V.int_field(body, "truck_capacity_units", 1, 400)
    waste_capacity_gallons = V.int_field(body, "waste_capacity_gallons", 100, 6000)
    status = V.enum_field(body, "status", C.ROUTE_STATUSES,
                          required=False, default="ACTIVE")
    V.unique_field("routes", "route_code", route_code)

    row = insert("routes", {
        "route_code": route_code,
        "service_day": service_day,
        "truck_capacity_units": truck_capacity_units,
        "waste_capacity_gallons": waste_capacity_gallons,
        "status": status,
        "committed_units": 0,
        "density_planned_pct": 0,
        "density_realized_pct": 0,
        "last_run_date": None,
    })
    return created(serialize(row))


@bp.get("/routes/<route_id>")
@endpoint(ALL_ROLES)
def read_route(route_id):
    return ok(serialize(resolve("routes", route_id)))
