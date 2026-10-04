"""HomeSite endpoints."""

from flask import Blueprint, request

from db import db
from errors import fail
from response import ok, ok_list, paginate
from checks import (
    authenticate, body, require_fields, int_field, string_field, enum_field,
    iso_field, get_community, get_home_site,
)
from services import common, calc

bp = Blueprint("home_sites", __name__)

DETAIL_ROLES = [
    "PlatformAdmin",
    "SalesCounselor",
    "MortgageBanker",
    "ClosingOfficer",
    "ComplianceOfficer",
]
CONSTRUCTION_STAGES = [
    "NOT_STARTED",
    "FOUNDATION",
    "FRAMING",
    "DRYWALL",
    "FINISH",
    "COMPLETE",
]


@bp.post("/housing/communities/<community_id>/home-sites")
def create_home_site(community_id):
    authenticate(["SalesCounselor", "PlatformAdmin"])
    community = get_community(community_id)
    payload = body()
    require_fields(
        payload,
        [
            "lot_number",
            "address",
            "base_price_cents",
            "construction_stage",
            "estimated_completion_iso",
            "advertised_rate_bps",
            "advertised_rate_expires_iso",
        ],
    )
    lot_number = string_field(payload, "lot_number")
    address = string_field(payload, "address")
    base_price = int_field(payload, "base_price_cents", minimum=1)
    stage = enum_field(payload, "construction_stage", CONSTRUCTION_STAGES)
    completion = iso_field(payload, "estimated_completion_iso")
    advertised_rate = int_field(payload, "advertised_rate_bps", minimum=0, maximum=2000)
    advertised_expires = iso_field(payload, "advertised_rate_expires_iso")

    if "community_id" in payload and payload["community_id"] is not None:
        if payload["community_id"] != community_id:
            fail("ERR_RESOURCE_NOT_FOUND", "the body community_id does not match the path")
    for existing in db.home_sites.values():
        if existing.get("community_id") == community_id and existing.get(
            "lot_number"
        ) == lot_number:
            fail("ERR_INVALID_ENUM_VALUE", "lot_number must be unique within its community")

    row = {
        "id": db.new_id(),
        "community_id": community_id,
        "lot_number": lot_number,
        "address": address,
        "base_price_cents": base_price,
        "construction_stage": stage,
        "estimated_completion_iso": completion,
        "advertised_rate_bps": advertised_rate,
        "advertised_rate_expires_iso": advertised_expires,
        "home_site_status": "AVAILABLE",
    }
    common.stamp_new(row)
    db.home_sites[row["id"]] = row
    calc.capture_rate_realization(community)
    common.touch(community)
    return ok(common.dump(row), 201)


@bp.get("/housing/home-sites/<home_site_id>")
def get_home_site_detail(home_site_id):
    authenticate(DETAIL_ROLES)
    home_site = get_home_site(home_site_id)
    return ok(common.dump(home_site), 200)


@bp.post("/housing/communities/<community_id>/home-sites/<home_site_id>/reserve")
def reserve_home_site(community_id, home_site_id):
    authenticate(["SalesCounselor"])
    community = get_community(community_id)
    home_site = get_home_site(home_site_id)
    if home_site.get("community_id") != community_id:
        fail("ERR_RESOURCE_NOT_FOUND", "the home site does not belong to the community")
    if community.get("program_status") not in ("ACTIVE", "RESTRICTED"):
        fail("ERR_INVALID_STATE", "the community does not permit reservations")
    if home_site.get("home_site_status") != "AVAILABLE":
        fail("ERR_INVALID_STATE", "the home site is not AVAILABLE")
    home_site["home_site_status"] = "UNDER_CONTRACT"
    common.touch(home_site)
    calc.capture_rate_realization(community)
    common.touch(community)
    return ok(common.dump(home_site), 200)


@bp.get("/housing/home-sites/<home_site_id>/contracts")
def list_home_site_contracts(home_site_id):
    authenticate(DETAIL_ROLES)
    get_home_site(home_site_id)
    rows = [c for c in db.contracts.values() if c.get("home_site_id") == home_site_id]
    window, pagination = paginate(
        common.sort_rows(rows), request.args.get("limit"), request.args.get("offset")
    )
    return ok_list(common.dump_all(window), 200, pagination)