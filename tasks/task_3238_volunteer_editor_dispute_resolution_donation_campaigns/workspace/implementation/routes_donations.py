"""Donation routes: pledge, process, fail, refund."""
from datetime import timedelta

from flask import Blueprint, request

from db import db, _parse_iso
from errors import (ApiError, ERR_CAMPAIGN_INACTIVE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_REFUND_WINDOW_EXPIRED)
from helpers import (base_entity, get_body, require_fields, list_response,
                     lookup, touch)
from middleware import require_roles
from response import success_object

bp = Blueprint("donations", __name__)


@bp.post("/wiki/campaigns/<campaignId>/donations")
def create_donation(campaignId):
    require_roles("Anonymous")
    campaign = lookup(db.campaigns, campaignId, "Campaign")
    body = get_body()
    require_fields(body, ["banner_id", "donor_email_hash", "amount_cents",
                          "currency"])
    banner = lookup(db.banners, body["banner_id"], "Banner")
    if banner["campaign_id"] != campaign["id"]:
        from errors import ERR_NOT_FOUND
        raise ApiError(ERR_NOT_FOUND,
                       "Banner does not belong to this campaign", 404)
    try:
        amount = int(body["amount_cents"])
    except (TypeError, ValueError):
        raise ApiError(ERR_INVALID_REQUEST,
                       "amount_cents must be an integer", 400)
    if amount <= 0:
        raise ApiError(ERR_INVALID_REQUEST,
                       "amount_cents must be positive", 400)
    d = base_entity(has_version=False)
    d.update({
        "campaign_id": campaign["id"],
        "banner_id": banner["id"],
        "donor_email_hash": body["donor_email_hash"],
        "amount_cents": amount,
        "currency": body["currency"],
        "status": "PLEDGED",
        "processed_at": None,
    })
    db.donations[d["id"]] = d
    return success_object(d, status=201)


@bp.get("/wiki/donations")
def list_donations():
    require_roles("FundraisingManager", "PaymentProcessor", "PlatformAdmin")
    return list_response(db.donations, filters={
        "campaign_id": request.args.get("campaign_id"),
        "banner_id": request.args.get("banner_id"),
        "status": request.args.get("status"),
    })


@bp.get("/wiki/donations/<donationId>")
def get_donation(donationId):
    require_roles("FundraisingManager", "PaymentProcessor")
    return success_object(lookup(db.donations, donationId, "Donation"))


@bp.post("/wiki/donations/<donationId>/process")
def process_donation(donationId):
    require_roles("PaymentProcessor")
    d = lookup(db.donations, donationId, "Donation")
    if d["status"] != "PLEDGED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a PLEDGED donation can be processed", 409)
    campaign = db.campaigns.get(d["campaign_id"])
    banner = db.banners.get(d["banner_id"])
    if (campaign is None or campaign["status"] != "ACTIVE"
            or banner is None or banner["status"] != "ACTIVE"):
        raise ApiError(ERR_CAMPAIGN_INACTIVE,
                       "Campaign or banner not ACTIVE for donation processing",
                       409)
    d["status"] = "COMPLETED"
    d["processed_at"] = db.now_iso()
    touch(d, bump_version=False)
    campaign["raised_cents"] += d["amount_cents"]
    touch(campaign)
    banner["conversion_count"] += 1
    touch(banner, bump_version=False)
    return success_object(d)


@bp.post("/wiki/donations/<donationId>/fail")
def fail_donation(donationId):
    require_roles("PaymentProcessor")
    d = lookup(db.donations, donationId, "Donation")
    if d["status"] != "PLEDGED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a PLEDGED donation can be failed", 409)
    d["status"] = "FAILED"
    touch(d, bump_version=False)
    return success_object(d)


@bp.post("/wiki/donations/<donationId>/refund")
def refund_donation(donationId):
    require_roles("FundraisingManager")
    d = lookup(db.donations, donationId, "Donation")
    if d["status"] != "COMPLETED":
        raise ApiError(ERR_INVALID_STATE,
                       "Only a COMPLETED donation can be refunded", 409)
    if db.now() - _parse_iso(d["processed_at"]) > timedelta(days=90):
        raise ApiError(ERR_REFUND_WINDOW_EXPIRED,
                       "More than 90 days since donation processed", 409)
    d["status"] = "REFUNDED"
    touch(d, bump_version=False)
    campaign = db.campaigns.get(d["campaign_id"])
    if campaign is not None:
        campaign["raised_cents"] -= d["amount_cents"]
        touch(campaign)
    banner = db.banners.get(d["banner_id"])
    if banner is not None:
        banner["conversion_count"] -= 1
        touch(banner, bump_version=False)
    return success_object(d)
