"""Ward registration, listing and operational-status changes (PRD section 3.1)."""

from flask import Blueprint

import api
import serialize
import store
from errors import ApiError

bp = Blueprint("wards", __name__, url_prefix="/nutrition/wards")

WARD_STATUSES = ("ACTIVE", "SUSPENDED")


@bp.post("")
@api.require("NutritionManager")
def create_ward():
    body = api.body()
    name = api.req_str(body, "name")
    code = api.req_str(body, "code", min_len=2, max_len=8)
    capacity = api.req_int(body, "tray_line_capacity_per_window", lo=1)
    lead = api.req_int(body, "delivery_lead_minutes", lo=0)
    probe_required = api.opt_bool(body, "temperature_probe_required", True)

    if any(w["code"] == code for w in store.wards.values()):
        raise ApiError("ERR_DUPLICATE_WARD_CODE",
                       "A ward with code '%s' already exists." % code)

    ward = {
        "name": name,
        "code": code,
        "tray_line_capacity_per_window": capacity,
        "delivery_lead_minutes": lead,
        "temperature_probe_required": probe_required,
        "status": "ACTIVE",
    }
    store.stamp_new(ward)
    store.wards[ward["id"]] = ward
    return api.created(serialize.ward(ward))


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_wards():
    status = api.q_enum("status", WARD_STATUSES)
    rows = api.filtered(list(store.wards.values()), [(status, "status")])
    return api.paged(rows, serialize.ward)


@bp.get("/<ward_id>")
@api.require(*api.ALL_ROLES)
def read_ward(ward_id):
    return api.ok(serialize.ward(store.get_ward(ward_id)))


@bp.patch("/<ward_id>")
@api.require("NutritionManager")
def update_ward(ward_id):
    ward = store.get_ward(ward_id)
    body = api.body()
    status = api.opt_enum(body, "status", WARD_STATUSES)
    capacity = api.opt_int(body, "tray_line_capacity_per_window", lo=1)
    lead = api.opt_int(body, "delivery_lead_minutes", lo=0)
    probe_required = api.opt_bool(body, "temperature_probe_required")

    if status is not None and status == ward["status"]:
        raise ApiError("ERR_INVALID_STATE",
                       "The ward is already %s." % ward["status"])

    if status is not None:
        ward["status"] = status
    if capacity is not None:
        ward["tray_line_capacity_per_window"] = capacity
    if lead is not None:
        ward["delivery_lead_minutes"] = lead
    if probe_required is not None:
        ward["temperature_probe_required"] = probe_required
    store.touch(ward)
    return api.ok(serialize.ward(ward))
