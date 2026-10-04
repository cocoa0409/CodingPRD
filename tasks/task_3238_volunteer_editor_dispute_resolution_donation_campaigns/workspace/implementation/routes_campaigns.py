"""Donation campaign lifecycle routes."""
from flask import Blueprint, request

from db import db
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch, check_occ, parse_datetime_field, iso)
from middleware import require_roles
from response import success_object
from services import net_revenue_allocation

bp = Blueprint("campaigns", __name__)


@bp.post("/wiki/campaigns")
def create_campaign():
    require_roles("FundraisingManager")
    body = get_body()
    require_fields(body, ["name", "start_at", "end_at", "target_amount_cents"])
    start = parse_datetime_field(body["start_at"], "start_at")
    end = parse_datetime_field(body["end_at"], "end_at")
    try:
        target = int(body["target_amount_cents"])
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST,
                       "target_amount_cents must be an integer", 400)
    c = base_entity()
    c.update({
        "name": body["name"],
        "start_at": iso(start),
        "end_at": iso(end),
        "target_amount_cents": target,
        "status": "DRAFT",
        "raised_cents": 0,
    })
    db.campaigns[c["id"]] = c
    return success_object(c, status=201)


@bp.get("/wiki/campaigns")
def list_campaigns():
    require_roles("FundraisingManager", "Anonymous", "PlatformAdmin")
    return list_response(db.campaigns,
                         filters={"status": request.args.get("status")})


@bp.get("/wiki/campaigns/<campaignId>")
def get_campaign(campaignId):
    require_roles("FundraisingManager", "Anonymous")
    return success_object(lookup(db.campaigns, campaignId, "Campaign"))


def _set_banners(campaign, status):
    for b in db.banners.values():
        if b["campaign_id"] == campaign["id"] and b["status"] != "RETIRED":
            b["status"] = status
            touch(b, bump_version=False)


@bp.post("/wiki/campaigns/<campaignId>/activate")
def activate_campaign(campaignId):
    require_roles("FundraisingManager")
    c = lookup(db.campaigns, campaignId, "Campaign")
    body = get_body()
    check_occ(body, "expected_campaign_version", c)
    now = db.now()
    if c["status"] == "DRAFT":
        from db import _parse_iso
        if not (_parse_iso(c["start_at"]) <= now <= _parse_iso(c["end_at"])):
            raise ApiError(ERR_INVALID_STATE,
                           "Current time must fall within the campaign window",
                           409)
        active_banners = [b for b in db.banners.values()
                          if b["campaign_id"] == c["id"] and b["status"] == "ACTIVE"]
        if not active_banners:
            raise ApiError(ERR_INVALID_STATE,
                           "At least one ACTIVE banner must be configured", 409)
        c["status"] = "ACTIVE"
    elif c["status"] == "PAUSED":
        from db import _parse_iso
        if now > _parse_iso(c["end_at"]):
            raise ApiError(ERR_INVALID_STATE,
                           "Cannot reactivate a campaign past its end_at", 409)
        c["status"] = "ACTIVE"
        _set_banners(c, "ACTIVE")
    else:
        raise ApiError(ERR_INVALID_STATE,
                       "Only a DRAFT or PAUSED campaign can be activated", 409)
    touch(c)
    return success_object(c)


@bp.post("/wiki/campaigns/<campaignId>/pause")
def pause_campaign(campaignId):
    require_roles("FundraisingManager")
    c = lookup(db.campaigns, campaignId, "Campaign")
    body = get_body()
    check_occ(body, "expected_campaign_version", c)
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an ACTIVE campaign can be paused", 409)
    c["status"] = "PAUSED"
    _set_banners(c, "PAUSED")
    touch(c)
    return success_object(c)


@bp.post("/wiki/campaigns/<campaignId>/complete")
def complete_campaign(campaignId):
    require_roles("FundraisingManager")
    c = lookup(db.campaigns, campaignId, "Campaign")
    body = get_body()
    check_occ(body, "expected_campaign_version", c)
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an ACTIVE campaign can be completed", 409)
    from db import _parse_iso
    if not (db.now() > _parse_iso(c["end_at"])
            or c["raised_cents"] >= c["target_amount_cents"]):
        raise ApiError(ERR_INVALID_STATE,
                       "Campaign can complete only after end_at or once the "
                       "target amount is reached", 409)
    c["status"] = "COMPLETED"
    _set_banners(c, "RETIRED")
    per_banner, total_net = net_revenue_allocation(c["id"])
    c["net_revenue_allocation"] = {
        "banners": per_banner,
        "total_net_cents": total_net,
    }
    touch(c)
    return success_object(c)


@bp.post("/wiki/campaigns/<campaignId>/cancel")
def cancel_campaign(campaignId):
    require_roles("FundraisingManager")
    c = lookup(db.campaigns, campaignId, "Campaign")
    body = get_body()
    check_occ(body, "expected_campaign_version", c)
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE,
                       "Only an ACTIVE campaign can be cancelled", 409)
    c["status"] = "CANCELLED"
    _set_banners(c, "RETIRED")
    for d in db.donations.values():
        if d["campaign_id"] == c["id"] and d["status"] == "PLEDGED":
            d["status"] = "FAILED"
            touch(d, bump_version=False)
    touch(c)
    return success_object(c)
