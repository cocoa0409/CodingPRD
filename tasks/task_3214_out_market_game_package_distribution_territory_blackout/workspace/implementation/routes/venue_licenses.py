"""Venue licenses: apply, list, get, certify, recertify, suspend, reinstate, revoke."""
from flask import Blueprint, request

from db import db
from errors import (
    err_account_kind_mismatch, err_already_terminal, err_invalid_state,
)
from middleware import require_roles
from paginate import parse_pagination, paginate
from response import success
from services import (
    new_resource, touch, get_or_404, venue_fee, enforce_occupancy_cap,
)
from validate import body_json, req_string, req_zip, req_int

bp = Blueprint("venue_licenses", __name__)


@bp.post("/venue-licenses")
@require_roles("VenueManager")
def create_venue_license(auth):
    body = body_json()
    account_id = req_string(body, "account_id")
    account = get_or_404(db.accounts, account_id)
    venue_name = req_string(body, "venue_name")
    venue_zip = req_zip(body, "venue_zip")
    fire_code_occupancy = req_int(body, "fire_code_occupancy")
    if account["account_kind"] != "COMMERCIAL":
        raise err_account_kind_mismatch()
    enforce_occupancy_cap(fire_code_occupancy, account)

    lic = new_resource()
    lic.update({
        "account_id": account_id,
        "venue_name": venue_name,
        "venue_zip": venue_zip,
        "fire_code_occupancy": fire_code_occupancy,
        "occupancy_tier": None,
        "annual_fee_cents": None,
        "status": "PENDING",
    })
    db.venue_licenses[lic["id"]] = lic
    return success(lic, status=201)


@bp.get("/venue-licenses")
@require_roles("ComplianceAuditor", "PlatformAdmin", "SupportAgent", "VenueManager")
def list_venue_licenses(auth):
    limit, offset = parse_pagination()
    account_id = request.args.get("account_id")
    status = request.args.get("status")
    occupancy_tier = request.args.get("occupancy_tier")
    items = sorted(db.venue_licenses.values(), key=lambda r: r["created_at"])
    if account_id is not None:
        items = [l for l in items if l["account_id"] == account_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    if occupancy_tier is not None:
        items = [l for l in items if l["occupancy_tier"] == occupancy_tier]
    window, page = paginate(items, limit, offset)
    return success(window, pagination=page)


@bp.get("/venue-licenses/<lid>")
@require_roles("ComplianceAuditor", "PlatformAdmin", "SupportAgent", "VenueManager")
def get_venue_license(lid, auth):
    lic = get_or_404(db.venue_licenses, lid)
    return success(lic)


@bp.post("/venue-licenses/<lid>/certify")
@require_roles("ComplianceAuditor")
def certify_venue_license(lid, auth):
    lic = get_or_404(db.venue_licenses, lid)
    if lic["status"] == "REVOKED":
        raise err_already_terminal()
    if lic["status"] != "PENDING":
        raise err_invalid_state()
    account = db.accounts.get(lic["account_id"])
    enforce_occupancy_cap(lic["fire_code_occupancy"], account)
    tier, fee = venue_fee(lic["fire_code_occupancy"])
    lic["occupancy_tier"] = tier
    lic["annual_fee_cents"] = fee
    lic["status"] = "CERTIFIED"
    touch(lic)
    return success(lic)


@bp.post("/venue-licenses/<lid>/recertify")
@require_roles("ComplianceAuditor")
def recertify_venue_license(lid, auth):
    lic = get_or_404(db.venue_licenses, lid)
    if lic["status"] == "REVOKED":
        raise err_already_terminal()
    if lic["status"] != "CERTIFIED":
        raise err_invalid_state()
    body = body_json()
    new_occupancy = req_int(body, "fire_code_occupancy")
    account = db.accounts.get(lic["account_id"])
    enforce_occupancy_cap(new_occupancy, account)
    lic["fire_code_occupancy"] = new_occupancy
    tier, fee = venue_fee(new_occupancy)
    lic["occupancy_tier"] = tier
    lic["annual_fee_cents"] = fee
    touch(lic)
    return success(lic)


@bp.post("/venue-licenses/<lid>/suspend")
@require_roles("ComplianceAuditor")
def suspend_venue_license(lid, auth):
    lic = get_or_404(db.venue_licenses, lid)
    if lic["status"] == "REVOKED":
        raise err_already_terminal()
    if lic["status"] not in ("PENDING", "CERTIFIED"):
        raise err_invalid_state()
    lic["status"] = "SUSPENDED"
    touch(lic)
    return success(lic)


@bp.post("/venue-licenses/<lid>/reinstate")
@require_roles("ComplianceAuditor")
def reinstate_venue_license(lid, auth):
    lic = get_or_404(db.venue_licenses, lid)
    if lic["status"] == "REVOKED":
        raise err_already_terminal()
    if lic["status"] != "SUSPENDED":
        raise err_invalid_state()
    tier, fee = venue_fee(lic["fire_code_occupancy"])
    lic["occupancy_tier"] = tier
    lic["annual_fee_cents"] = fee
    lic["status"] = "CERTIFIED"
    touch(lic)
    return success(lic)


@bp.post("/venue-licenses/<lid>/revoke")
@require_roles("ComplianceAuditor")
def revoke_venue_license(lid, auth):
    lic = get_or_404(db.venue_licenses, lid)
    if lic["status"] == "REVOKED":
        raise err_already_terminal()
    lic["status"] = "REVOKED"
    touch(lic)
    return success(lic)
