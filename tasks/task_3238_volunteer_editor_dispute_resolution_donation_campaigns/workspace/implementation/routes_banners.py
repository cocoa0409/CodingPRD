"""Campaign banner and impression routes."""
from flask import Blueprint, request

from db import db
from errors import (ApiError, ERR_BANNER_FREQUENCY_CAP, ERR_BANNER_GEO_MISMATCH,
                    ERR_INVALID_REQUEST)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch)
from middleware import require_roles
from response import success_object
from services import conversion_rate_bp_truncated

bp = Blueprint("banners", __name__)


def _banner_view(banner):
    """Banner detail read includes truncated conversion_rate_bp (PRD 3.8)."""
    out = dict(banner)
    out["conversion_rate_bp"] = conversion_rate_bp_truncated(banner)
    return out


@bp.post("/wiki/campaigns/<campaignId>/banners")
def create_banner(campaignId):
    require_roles("FundraisingManager")
    campaign = lookup(db.campaigns, campaignId, "Campaign")
    body = get_body()
    require_fields(body, ["message_variant", "geo_target", "frequency_cap"])
    try:
        freq = int(body["frequency_cap"])
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST,
                       "frequency_cap must be an integer", 400)
    if freq < 1:
        raise ApiError(ERR_INVALID_REQUEST,
                       "frequency_cap must be at least 1", 400)
    try:
        weight = int(body.get("priority_weight", 1))
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST,
                       "priority_weight must be an integer", 400)
    b = base_entity(has_version=False)
    b.update({
        "campaign_id": campaign["id"],
        "message_variant": body["message_variant"],
        "geo_target": body["geo_target"],
        "frequency_cap": freq,
        "priority_weight": weight,
        "status": "ACTIVE",
        "impression_count": 0,
        "click_count": 0,
        "conversion_count": 0,
    })
    db.banners[b["id"]] = b
    return success_object(_banner_view(b), status=201)


@bp.get("/wiki/banners")
def list_banners():
    require_roles("FundraisingManager", "PlatformAdmin")
    return list_response(db.banners, filters={
        "campaign_id": request.args.get("campaign_id"),
        "status": request.args.get("status"),
    })


@bp.get("/wiki/banners/<bannerId>")
def get_banner(bannerId):
    require_roles("FundraisingManager")
    banner = lookup(db.banners, bannerId, "Banner")
    return success_object(_banner_view(banner))


@bp.post("/wiki/banners/<bannerId>/impressions")
def record_impression(bannerId):
    require_roles("Anonymous", "PlatformAdmin")
    banner = lookup(db.banners, bannerId, "Banner")
    body = get_body()
    require_fields(body, ["viewer_key", "country_code"])
    if banner["geo_target"] != "GLOBAL" and \
            banner["geo_target"] != body["country_code"]:
        raise ApiError(ERR_BANNER_GEO_MISMATCH,
                       "Banner geo_target does not cover viewer country", 409)
    day_bucket = db.now().strftime("%Y-%m-%d")
    served_today = sum(
        1 for e in db.impressions.values()
        if e["banner_id"] == banner["id"]
        and e["viewer_key"] == body["viewer_key"]
        and e["day_bucket"] == day_bucket)
    if served_today >= banner["frequency_cap"]:
        raise ApiError(ERR_BANNER_FREQUENCY_CAP,
                       "User has exceeded daily impression cap for this banner",
                       409)
    clicked = bool(body.get("clicked", False))
    imp = base_entity(has_version=False)
    imp.update({
        "banner_id": banner["id"],
        "viewer_key": body["viewer_key"],
        "country_code": body["country_code"],
        "served_at": db.now_iso(),
        "day_bucket": day_bucket,
        "clicked": clicked,
    })
    db.impressions[imp["id"]] = imp
    banner["impression_count"] += 1
    if clicked:
        banner["click_count"] += 1
    touch(banner, bump_version=False)
    return success_object(imp, status=201)


@bp.get("/wiki/impressions")
def list_impressions():
    require_roles("FundraisingManager", "PlatformAdmin")
    return list_response(db.impressions, filters={
        "banner_id": request.args.get("banner_id"),
        "viewer_key": request.args.get("viewer_key"),
        "day_bucket": request.args.get("day_bucket"),
    })


@bp.get("/wiki/impressions/<impressionId>")
def get_impression(impressionId):
    require_roles("FundraisingManager", "PlatformAdmin")
    return success_object(lookup(db.impressions, impressionId, "Impression"))
