"""Sponsor and campaign routes."""

from flask import Blueprint, request

from db import DB
from common import base_resource, touch, paginate, parse_dt
from middleware import require_role
from errors import not_found, invalid_state, stale_version, campaign_overlap
from response import success_object, success_list
import calc
import services

bp = Blueprint("sponsors", __name__)


def sponsor_view(s):
    return dict(s)


def campaign_view(c):
    return dict(c)


@bp.post("/venue/sponsors")
def create_sponsor():
    require_role("SponsorshipManager")
    body = request.get_json(silent=True) or {}
    s = base_resource()
    s.update({
        "name": body.get("name"),
        "brand_tier": body.get("brand_tier"),
        "active_campaign_count": 0,
    })
    DB.sponsors[s["id"]] = s
    return success_object(sponsor_view(s), 201)


@bp.get("/venue/sponsors")
def list_sponsors():
    require_role("SponsorshipManager", "ProductionDirector")
    items = sorted(DB.sponsors.values(), key=lambda x: x["created_at"])
    tier = request.args.get("brand_tier")
    if tier:
        items = [s for s in items if s["brand_tier"] == tier]
    page, limit, offset, total = paginate([sponsor_view(s) for s in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue/sponsors/<sid>")
def get_sponsor(sid):
    require_role("SponsorshipManager")
    s = DB.sponsors.get(sid)
    if not s:
        raise not_found()
    return success_object(sponsor_view(s))


@bp.post("/venue/campaigns")
def create_campaign():
    require_role("SponsorshipManager")
    body = request.get_json(silent=True) or {}
    sponsor = DB.sponsors.get(body.get("sponsor_id"))
    if not sponsor:
        raise not_found("sponsor_id does not exist")
    c = base_resource()
    c.update({
        "sponsor_id": body.get("sponsor_id"),
        "start_time": body.get("start_time"),
        "end_time": body.get("end_time"),
        "exterior_slots": body.get("exterior_slots"),
        "spot_seconds": body.get("spot_seconds"),
        "contracted_impressions": body.get("contracted_impressions"),
        "delivered_impressions": 0,
        "under_delivery": 0,
        "make_good_credits": 0,
        "status": "DRAFT",
    })
    DB.campaigns[c["id"]] = c
    return success_object(campaign_view(c), 201)


@bp.get("/venue/campaigns")
def list_campaigns():
    require_role("SponsorshipManager")
    items = sorted(DB.campaigns.values(), key=lambda x: x["created_at"])
    sid = request.args.get("sponsor_id")
    status = request.args.get("status")
    if sid:
        items = [c for c in items if c["sponsor_id"] == sid]
    if status:
        items = [c for c in items if c["status"] == status]
    page, limit, offset, total = paginate([campaign_view(c) for c in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue/campaigns/<cid>")
def get_campaign(cid):
    require_role("SponsorshipManager")
    c = DB.campaigns.get(cid)
    if not c:
        raise not_found()
    return success_object(campaign_view(c))


@bp.post("/venue/campaigns/<cid>/activate")
def activate_campaign(cid):
    require_role("SponsorshipManager")
    c = DB.campaigns.get(cid)
    if not c:
        raise not_found()
    if c["status"] not in ("DRAFT", "PAUSED"):
        raise invalid_state()
    sponsor = DB.sponsors.get(c["sponsor_id"])
    if not sponsor:
        raise not_found()
    now = DB.clock
    if not (parse_dt(c["start_time"]) <= now < parse_dt(c["end_time"])):
        raise invalid_state("Campaign flight window not open")
    # sponsor overlap check: no two ACTIVE campaigns of same sponsor with overlapping flights
    for other in DB.campaigns.values():
        if other["id"] == cid or other["sponsor_id"] != sponsor["id"]:
            continue
        if other["status"] != "ACTIVE":
            continue
        if calc.windows_overlap(parse_dt(c["start_time"]), parse_dt(c["end_time"]),
                                parse_dt(other["start_time"]), parse_dt(other["end_time"])):
            raise campaign_overlap()
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_sponsor_version")
    if expected is not None and expected != sponsor["version"]:
        raise stale_version()
    c["status"] = "ACTIVE"
    touch(c)
    sponsor["active_campaign_count"] += 1
    touch(sponsor)
    return success_object(campaign_view(c))


@bp.post("/venue/campaigns/<cid>/pause")
def pause_campaign(cid):
    require_role("SponsorshipManager")
    c = DB.campaigns.get(cid)
    if not c:
        raise not_found()
    if c["status"] != "ACTIVE":
        raise invalid_state()
    c["status"] = "PAUSED"
    touch(c)
    sponsor = DB.sponsors.get(c["sponsor_id"])
    if sponsor:
        sponsor["active_campaign_count"] = max(0, sponsor["active_campaign_count"] - 1)
        touch(sponsor)
    return success_object(campaign_view(c))


@bp.post("/venue/campaigns/<cid>/cancel")
def cancel_campaign(cid):
    require_role("SponsorshipManager")
    c = DB.campaigns.get(cid)
    if not c:
        raise not_found()
    if c["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise invalid_state()
    was_active = c["status"] == "ACTIVE"
    c["status"] = "CANCELLED"
    touch(c)
    if was_active:
        sponsor = DB.sponsors.get(c["sponsor_id"])
        if sponsor:
            sponsor["active_campaign_count"] = max(0, sponsor["active_campaign_count"] - 1)
            touch(sponsor)
    return success_object(campaign_view(c))
