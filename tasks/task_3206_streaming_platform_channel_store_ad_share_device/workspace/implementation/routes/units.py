"""Device units routes."""

from flask import Blueprint, request

import errors as E
from db import store
from middleware import (
    get_json_body,
    parse_pagination,
    require_int,
    require_positive_int,
    require_nonnegative_int,
    require_roles,
    require_str,
)
from response import created, list_response, ok
from services.common import (
    device_unit_view,
    floor_div,
    round_half_up_cents,
    MONETIZATION_RECOVERY_BPS,
    STRAIGHT_LINE_MONTHS,
)

bp = Blueprint("units", __name__)


def get_unit_or_404(uid):
    u = store.device_units.get(uid)
    if u is None:
        E.not_found("DeviceUnit not found")
    return u


def _recompute_outstanding(u):
    u["subsidy_outstanding_cents"] = (
        u["subsidy_cents"] - u["subsidy_recovered_cents"] - u["subsidy_written_off_cents"]
    )


def _activation_gates(model):
    """Pinned referential sub-order: (1) CERTIFIED, (2) != OVERDUE, (3) LICENSED."""
    if model["cert_status"] != "CERTIFIED":
        E.raise_err(E.ERR_MODEL_NOT_CERTIFIED, "Device model must be CERTIFIED")
    if model["update_compliance"] == "OVERDUE":
        E.raise_err(E.ERR_UPDATE_OVERDUE, "Device model update_compliance is OVERDUE")
    mfr = store.manufacturers.get(model["manufacturer_id"])
    if mfr is None or mfr["license_status"] != "LICENSED":
        E.raise_err(E.ERR_MANUFACTURER_NOT_LICENSED,
                    "Manufacturer license must be LICENSED")


@bp.post("/device-units")
def create_unit():
    user_id, role = require_roles("TvManufacturer")
    body = get_json_body()
    device_model_id = require_str(body, "device_model_id")
    serial = require_str(body, "serial_number")
    cost = require_positive_int(body, "hardware_cost_cents")
    price = require_nonnegative_int(body, "sale_price_cents")
    model = store.device_models.get(device_model_id)
    if model is None:
        E.not_found("DeviceModel not found")
    if model["manufacturer_id"] != user_id:
        E.forbidden("TvManufacturer caller does not own this model")
    _activation_gates(model)
    for u in store.device_units.values():
        if u["serial_number"] == serial:
            E.raise_err(E.ERR_DUPLICATE_SERIAL, "serial_number already exists")
    u = store.new_entity()
    subsidy = max(0, cost - price)
    u.update({
        "device_model_id": device_model_id,
        "viewer_id": None,
        "serial_number": serial,
        "hardware_cost_cents": cost,
        "sale_price_cents": price,
        "subsidy_cents": subsidy,
        "subsidy_recovered_cents": 0,
        "subsidy_written_off_cents": 0,
        "subsidy_outstanding_cents": subsidy,
        "os_version_tag": "BASE",
        "status": "MANUFACTURED",
    })
    store.device_units[u["id"]] = u
    return created(device_unit_view(u))


@bp.get("/device-units")
def list_units():
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer", "Viewer")
    limit, offset = parse_pagination()
    dmid = request.args.get("device_model_id")
    vid = request.args.get("viewer_id")
    status = request.args.get("status")
    items = sorted(store.device_units.values(), key=lambda x: x["_seq"])
    if dmid is not None:
        items = [u for u in items if u["device_model_id"] == dmid]
    if vid is not None:
        items = [u for u in items if u.get("viewer_id") == vid]
    if status is not None:
        items = [u for u in items if u["status"] == status]
    return list_response([device_unit_view(u) for u in items], limit, offset, len(items))


@bp.get("/device-units/<uid>")
def get_unit(uid):
    require_roles("PlatformAdmin", "AdOps", "TvManufacturer", "Viewer")
    return ok(device_unit_view(get_unit_or_404(uid)))


@bp.post("/device-units/<uid>/sell")
def sell_unit(uid):
    require_roles("PlatformAdmin")
    u = get_unit_or_404(uid)
    if u["status"] != "MANUFACTURED":
        E.invalid_state("Unit must be MANUFACTURED to sell")
    u["status"] = "SOLD"
    store.touch(u)
    return ok(device_unit_view(u))


@bp.post("/device-units/<uid>/activate")
def activate_unit(uid):
    user_id, role = require_roles("Viewer")
    u = get_unit_or_404(uid)
    viewer = store.viewer_accounts.get(user_id)
    if viewer is None:
        E.not_found("ViewerAccount not found")
    if u["status"] != "SOLD":
        E.invalid_state("Unit must be SOLD to activate")
    if viewer["status"] != "ACTIVE":
        E.invalid_state("ViewerAccount must be ACTIVE to activate a unit")
    model = store.device_models.get(u["device_model_id"])
    if model is None:
        E.not_found("DeviceModel not found")
    _activation_gates(model)
    u["status"] = "ACTIVATED"
    u["viewer_id"] = user_id
    store.touch(u)
    return ok(device_unit_view(u))


@bp.post("/device-units/<uid>/deactivate")
def deactivate_unit(uid):
    user_id, role = require_roles("Viewer")
    u = get_unit_or_404(uid)
    if u.get("viewer_id") != user_id:
        E.forbidden("Viewer may only deactivate own unit")
    if u["status"] != "ACTIVATED":
        E.invalid_state("Unit must be ACTIVATED to deactivate")
    u["subsidy_written_off_cents"] += u["subsidy_outstanding_cents"]
    u["subsidy_outstanding_cents"] = 0
    u["status"] = "DEACTIVATED"
    store.touch(u)
    return ok(device_unit_view(u))


@bp.post("/device-units/<uid>/apply-os-update")
def apply_os_update(uid):
    user_id, role = require_roles("Viewer")
    u = get_unit_or_404(uid)
    if u.get("viewer_id") != user_id:
        E.forbidden("Viewer may only update own unit")
    body = get_json_body()
    os_update_id = require_str(body, "os_update_id")
    upd = store.os_updates.get(os_update_id)
    if upd is None:
        E.not_found("OsUpdate not found")
    if u["status"] != "ACTIVATED":
        E.invalid_state("Unit must be ACTIVATED to apply an OS update")
    if upd["status"] != "ROLLING" or u["os_version_tag"] == upd["version_tag"]:
        E.raise_err(E.ERR_UPDATE_NOT_APPLICABLE,
                    "OS update not ROLLING or unit already on that version")
    u["os_version_tag"] = upd["version_tag"]
    store.touch(u)
    return ok(device_unit_view(u))


@bp.post("/device-units/<uid>/record-ad-revenue")
def record_ad_revenue(uid):
    require_roles("AdOps")
    u = get_unit_or_404(uid)
    body = get_json_body()
    revenue = body.get("revenue_cents")
    if revenue is None or isinstance(revenue, bool) or not isinstance(revenue, int) or revenue < 0:
        E.invalid_request("revenue_cents must be a non-negative integer")
    model = store.device_models.get(u["device_model_id"])
    if model is None:
        E.not_found("DeviceModel not found")
    if model["recovery_policy"] != "MONETIZATION":
        E.raise_err(E.ERR_RECOVERY_POLICY_MISMATCH,
                    "record-ad-revenue requires a MONETIZATION model")
    outstanding = (u["subsidy_cents"] - u["subsidy_recovered_cents"]
                   - u["subsidy_written_off_cents"])
    recovered = round_half_up_cents(revenue * MONETIZATION_RECOVERY_BPS, 10000)
    recovered = min(recovered, outstanding)
    u["subsidy_recovered_cents"] += recovered
    _recompute_outstanding(u)
    store.touch(u)
    return ok(device_unit_view(u))


@bp.post("/device-units/<uid>/accrue-straight-line")
def accrue_straight_line(uid):
    require_roles("AdOps")
    u = get_unit_or_404(uid)
    model = store.device_models.get(u["device_model_id"])
    if model is None:
        E.not_found("DeviceModel not found")
    if model["recovery_policy"] != "STRAIGHT_LINE":
        E.raise_err(E.ERR_RECOVERY_POLICY_MISMATCH,
                    "accrue-straight-line requires a STRAIGHT_LINE model")
    outstanding = (u["subsidy_cents"] - u["subsidy_recovered_cents"]
                   - u["subsidy_written_off_cents"])
    monthly = floor_div(u["subsidy_cents"], STRAIGHT_LINE_MONTHS)
    recovered = min(outstanding, monthly)
    u["subsidy_recovered_cents"] += recovered
    _recompute_outstanding(u)
    store.touch(u)
    return ok(device_unit_view(u))
