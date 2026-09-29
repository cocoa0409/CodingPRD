"""ServiceSite endpoints."""
from flask import Blueprint

from auth import ALL_ROLES, endpoint
import constants as C
from db import db, insert, ordered, serialize
from responses import created, ok
from routes.common import list_response, resolve
import services
import validation as V

bp = Blueprint("sites", __name__)


@bp.post("/service-sites")
@endpoint(["SalesRep", "PlatformAdmin"])
def create_site():
    body = V.body()
    account_id = V.str_field(body, "account_id", 1)
    site_label = V.str_field(body, "site_label", 1, 120)
    jurisdiction_code = V.str_field(body, "jurisdiction_code", 2, 24)
    access_class = V.enum_field(body, "access_class", C.ACCESS_CLASSES)
    right_of_way_required = V.bool_field(body, "right_of_way_required",
                                         required=False, default=False)
    gate_open_minute = V.int_field(body, "gate_open_minute", 0, 1439,
                                   required=False, default=0)
    gate_close_minute = V.int_field(body, "gate_close_minute", 1, 1440,
                                    required=False, default=1440)
    max_truck_length_ft = V.int_field(body, "max_truck_length_ft", 8, 60,
                                      required=False, default=24)
    V.ordering(gate_open_minute, gate_close_minute,
               "gate_open_minute", "gate_close_minute", strict=True)

    account = resolve("rental_accounts", account_id)

    row = insert("service_sites", {
        "account_id": account["id"],
        "site_label": site_label,
        "jurisdiction_code": jurisdiction_code,
        "right_of_way_required": right_of_way_required,
        "access_class": access_class,
        "gate_open_minute": gate_open_minute,
        "gate_close_minute": gate_close_minute,
        "max_truck_length_ft": max_truck_length_ft,
        "permit_status": "NONE",
        "site_posture": "RESTRICTED",
        "deployed_unit_count": 0,
    })
    services.recompute_site_posture(row)
    return created(serialize(row))


@bp.get("/service-sites/<site_id>")
@endpoint(ALL_ROLES)
def read_site(site_id):
    site = resolve("service_sites", site_id)
    return ok(serialize(site))


@bp.get("/service-sites/<site_id>/permits")
@endpoint(ALL_ROLES)
def list_site_permits(site_id):
    limit, offset = V.pagination()
    permit_kind = V.q_enum("permit_kind", C.PERMIT_KINDS)
    status = V.q_enum("status", C.PERMIT_STATUSES)
    site = resolve("service_sites", site_id)
    rows = [p for p in ordered(db.placement_permits.values())
            if p["site_id"] == site["id"]]
    if permit_kind is not None:
        rows = [p for p in rows if p["permit_kind"] == permit_kind]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return list_response(rows, limit, offset)
