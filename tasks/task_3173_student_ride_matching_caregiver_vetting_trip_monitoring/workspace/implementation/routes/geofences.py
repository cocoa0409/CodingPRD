"""Geofence endpoints."""

import db
import models
import services
import validators as v
from errors import not_found
from flask import Blueprint, request
from middleware import requires
from response import array_response, object_response, paginate

bp = Blueprint("geofences", __name__)

GEOFENCE_INPUT = ("district_id", "label", "center_lat", "center_lon", "radius_miles")


def load_geofence(geofence_id):
    fence = db.get("geofences", geofence_id)
    if fence is None:
        raise not_found("The addressed geofence does not exist.")
    return fence


@bp.post("/student-rides/geofences")
@requires("DistrictAdmin", "PlatformAdmin")
def create_geofence():
    data = v.body()
    v.reject_unknown(data, GEOFENCE_INPUT)
    district_id = v.as_string(data, "district_id")
    if db.get("districts", district_id) is None:
        raise not_found("The addressed district does not exist.")

    fence = db.new_record({
        "district_id": district_id,
        "label": v.as_string(data, "label"),
        "center_lat": services.num_or_none(v.as_number(data, "center_lat", required_field=True)),
        "center_lon": services.num_or_none(v.as_number(data, "center_lon", required_field=True)),
        "radius_miles": services.num_or_none(v.as_number(data, "radius_miles", required_field=True)),
        "registered_on": None,
    })
    fence["registered_on"] = fence["created_at"][:10]
    db.save("geofences", fence)
    return object_response(models.geofence_out(fence), 201)


@bp.get("/student-rides/geofences/<geofence_id>")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def get_geofence(geofence_id):
    return object_response(models.geofence_out(load_geofence(geofence_id)))


@bp.get("/student-rides/geofences/<geofence_id>/checks")
@requires("DistrictAdmin", "PlatformAdmin", "SupportCenterAgent")
def list_geofence_checks(geofence_id):
    load_geofence(geofence_id)
    rows = [c for c in db.all_of("geofence_checks") if c["geofence_id"] == geofence_id]
    page, limit, offset, total = paginate(rows, request.args)
    return array_response(models.serialise_all("geofence_checks", page), limit, offset, total)