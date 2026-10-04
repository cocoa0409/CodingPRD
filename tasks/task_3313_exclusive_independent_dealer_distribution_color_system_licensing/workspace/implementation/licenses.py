"""Color licenses."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import services
from errors import (
    err_not_found, err_invalid_request, err_invalid_state,
    err_reference_inactive,
)
from response import (
    body, get_auth, require_roles, success_obj, paginate, req_string,
)

bp = Blueprint("licenses", __name__)

READ = ["PlatformAdmin", "RegionManager", "ChannelDirector", "EquipmentTech", "DealerPrincipal"]


def _serialize(l):
    return dict(l)


@bp.post("/licenses")
def create_license():
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    data = body()
    dealer_id = req_string(data, "dealer_id")
    cs_id = req_string(data, "colorant_system_id")
    if dealer_id not in db.dealers:
        raise err_not_found("dealer_id not found")
    cs = db.colorant_systems.get(cs_id)
    if cs is None:
        raise err_not_found("colorant_system_id not found")
    if cs["status"] == "RETIRED":
        raise err_reference_inactive("colorant system is RETIRED")
    rec = db.new_common()
    rec.update({
        "dealer_id": dealer_id,
        "colorant_system_id": cs_id,
        "started_on": None,
        "expires_on": None,
        "fee_basis": None,
        "fee_charged_cents": 0,
        "status": "PENDING",
    })
    db.licenses[rec["id"]] = rec
    return success_obj(_serialize(rec), 201)


@bp.get("/licenses")
def list_licenses():
    get_auth()
    items = list(db.licenses.values())
    services.sweep_licenses(items)
    dealer_id = request.args.get("dealer_id")
    cs_id = request.args.get("colorant_system_id")
    if dealer_id is not None:
        items = [l for l in items if l["dealer_id"] == dealer_id]
    if cs_id is not None:
        items = [l for l in items if l["colorant_system_id"] == cs_id]
    return paginate([_serialize(l) for l in items])


@bp.get("/licenses/<lid>")
def get_license(lid):
    get_auth()
    l = db.licenses.get(lid)
    if l is None:
        raise err_not_found("license not found")
    services.sweep_licenses([l])
    return success_obj(_serialize(l))


@bp.post("/licenses/<lid>/renew")
def renew_license(lid):
    _, role = get_auth()
    require_roles(role, ["RegionManager"])
    l = db.licenses.get(lid)
    if l is None:
        raise err_not_found("license not found")
    services.sweep_licenses([l])
    if l["status"] not in ("ACTIVE", "EXPIRED"):
        raise err_invalid_state("license is not ACTIVE or EXPIRED")
    dealer = db.dealers.get(l["dealer_id"])
    if dealer is None or dealer["status"] not in ("ONBOARDING", "ACTIVE", "SUSPENDED"):
        raise err_invalid_state("dealer status does not permit renewal")
    cs = db.colorant_systems.get(l["colorant_system_id"])
    annual = cs["annual_license_fee_cents"] if cs else 0
    now = db.now()
    if l["status"] == "ACTIVE":
        fee_basis = "FULL"
        fee = annual
    else:  # EXPIRED revival
        old_exp = db.parse_ts(l["expires_on"])
        days_remaining = max(0, (old_exp - now).days) if old_exp else 0
        fee_basis = "PRORATED"
        fee = services.round_half_up_int(Decimal(annual) * Decimal(days_remaining) / Decimal(365))
    l["status"] = "ACTIVE"
    l["expires_on"] = db.fmt_ts(now + timedelta(days=db.LICENSE_TERM_DAYS))
    if l.get("started_on") is None:
        l["started_on"] = db.fmt_ts(now)
    l["fee_basis"] = fee_basis
    l["fee_charged_cents"] = fee
    db.touch(l)
    return success_obj(_serialize(l))


@bp.post("/licenses/<lid>/revoke")
def revoke_license(lid):
    _, role = get_auth()
    require_roles(role, ["ChannelDirector"])
    l = db.licenses.get(lid)
    if l is None:
        raise err_not_found("license not found")
    services.sweep_licenses([l])
    if l["status"] not in ("PENDING", "ACTIVE", "EXPIRED", "SUSPENDED"):
        raise err_invalid_state("license cannot be revoked from its current state")
    l["status"] = "REVOKED"
    db.touch(l)
    return success_obj(_serialize(l))
