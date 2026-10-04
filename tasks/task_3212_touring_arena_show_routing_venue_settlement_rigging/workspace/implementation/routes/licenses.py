"""LicenseAgreement endpoints."""
from flask import Blueprint, request

from clock import now
from constants import ALL_ROLES
from db import db, base_fields, touch
from errors import err
from middleware import require_roles
from response import success, paginate
import helpers as H
import ticks

bp = Blueprint("licenses", __name__)


@bp.route("/tours/<tourId>/license-agreements", methods=["POST"])
@require_roles("LicensingManager")
def create_license(tourId):
    t = H.get_tour(tourId)
    data = H.body()
    H.require_fields(data, ["property_code", "licensor_name", "royalty_pct",
                            "starts_on", "ends_on"])
    l = base_fields()
    l.update({
        "tour_id": t["id"],
        "property_code": H.req_str(data, "property_code"),
        "licensor_name": H.req_str(data, "licensor_name"),
        "royalty_pct": H.opt_num(data, "royalty_pct", None),
        "minimum_guarantee_cents": H.opt_int(data, "minimum_guarantee_cents", 0),
        "starts_on": H.req_dt(data, "starts_on"),
        "ends_on": H.req_dt(data, "ends_on"),
        "status": "DRAFT",
    })
    if l["royalty_pct"] is None:
        raise err("ERR_INVALID_REQUEST", "royalty_pct is required")
    db.license_agreements[l["id"]] = l
    return success(l, 201)


@bp.route("/tours/<tourId>/license-agreements", methods=["GET"])
@require_roles(*ALL_ROLES)
def list_licenses(tourId):
    H.get_tour(tourId)
    items = [l for l in db.license_agreements.values() if l["tour_id"] == tourId]
    for l in items:
        ticks.tick_license(l)
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, meta = paginate(items, request.args)
    return success(page, 200, meta)


@bp.route("/tours/<tourId>/license-agreements/<licId>", methods=["GET"])
@require_roles(*ALL_ROLES)
def get_license(tourId, licId):
    H.get_tour(tourId)
    l = H.get_license(tourId, licId)
    ticks.tick_license(l)
    return success(l)


@bp.route("/tours/<tourId>/license-agreements/<licId>/activate", methods=["POST"])
@require_roles("LicensingManager")
def activate_license(tourId, licId):
    H.get_tour(tourId)
    l = H.get_license(tourId, licId)
    if l["status"] != "DRAFT":
        raise err("ERR_LICENSE_NOT_DRAFT", "LicenseAgreement must be DRAFT to activate")
    ts = now()
    if not (l["starts_on"] <= ts < l["ends_on"]):
        raise err("ERR_INVALID_STATE",
                  "Logical clock must be >= starts_on and < ends_on to activate")
    l["status"] = "ACTIVE"
    touch(l)
    return success(l)


@bp.route("/tours/<tourId>/license-agreements/<licId>/terminate", methods=["POST"])
@require_roles("LicensingManager")
def terminate_license(tourId, licId):
    H.get_tour(tourId)
    l = H.get_license(tourId, licId)
    ticks.tick_license(l)
    if l["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "LicenseAgreement must be ACTIVE to terminate")
    l["status"] = "TERMINATED"
    touch(l)
    return success(l)
