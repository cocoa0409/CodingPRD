"""Treatment facility endpoints (PRD 3.1)."""

from flask import Blueprint

import store
from auth import roles
from derive import facility_view, storage_projection
from envelope import object_response
from errors import fail
from listing import emit_list
from store import now_iso, r2
from validate import get_body, qenum, vint, vnum, vstr

bp = Blueprint("facilities", __name__, url_prefix="/api/v1/treatment-facilities")

POSTURES = ("OPEN", "RESTRICTED", "FROZEN")
ALL_ROLES = ("FacilityOperator", "ComplianceOfficer", "Agronomist", "LabAnalyst",
             "PublicLiaison", "Farmer")
READ_ROLES = ("FacilityOperator", "ComplianceOfficer", "Agronomist", "LabAnalyst",
              "PublicLiaison")


def get_facility(facility_id):
    facility = store.facilities.get(facility_id)
    if facility is None:
        fail("ERR_FACILITY_NOT_FOUND", "Facility %s does not exist." % facility_id)
    return facility


@bp.post("")
@roles("FacilityOperator", "ComplianceOfficer")
def create_facility():
    body = get_body()
    name = vstr(body, "name", required=True, min_len=1, max_len=120)
    npdes = vstr(body, "npdes_permit_number", required=True, min_len=1)
    capacity = vnum(body, "storage_capacity_wet_tons", required=True, gt=0)
    daily = vnum(body, "daily_production_wet_tons", required=True, ge=0)
    bays = vint(body, "loadout_bay_count", required=True, ge=1)
    for existing in store.facilities.values():
        if existing["npdes_permit_number"] == npdes:
            fail("ERR_DUPLICATE_RESOURCE",
                 "npdes_permit_number %s is already registered." % npdes)
    facility = store.new_record({
        "name": name,
        "npdes_permit_number": npdes,
        "storage_capacity_wet_tons": r2(capacity),
        "daily_production_wet_tons": daily,
        "loadout_bay_count": bays,
        "storage_used_wet_tons": r2(0),
        "storage_utilization_pct": r2(0),
        "open_ceiling_exceedance_count": 0,
        "substantiated_complaint_count_30d": 0,
        "days_of_capacity": 9999,
        "posture": "OPEN",
        "updated_at": now_iso(),
        "version": 1,
    })
    store.facilities[facility["id"]] = facility
    return object_response(facility_view(facility), 201)


@bp.get("/<facility_id>")
@roles(*READ_ROLES)
def read_facility(facility_id):
    facility = get_facility(facility_id)
    return object_response(facility_view(facility))


@bp.get("")
@roles(*READ_ROLES)
def list_facilities():
    posture = qenum("posture", POSTURES)
    rows = [f for f in store.facilities.values()
            if posture is None or f["posture"] == posture]
    return emit_list(rows, ("created_at",), view=facility_view)


@bp.get("/<facility_id>/storage-projection")
@roles("FacilityOperator", "ComplianceOfficer", "Agronomist")
def read_storage_projection(facility_id):
    facility = get_facility(facility_id)
    return object_response(storage_projection(facility))
