"""Routes: advertising — accounts, campaigns, impressions, call events, reports."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, fmt_ts, parse_ts, parse_date
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, stamp_event, touch, get_body, req_str, req_int, req_bool,
    req_enum, req_date, lazy_reset_spend, pub,
    CALL_MIN_DURATION_S, ATT_WINDOW_DAYS,
)
from routes_pages import get_page

bp = Blueprint("ads", __name__)

AD_ROLES = ("PlatformOps", "Advertiser", "SupportAdmin")


def get_account(account_id):
    a = store.ad_accounts.get(account_id)
    if a is None:
        raise not_found("ad account not found")
    lazy_reset_spend(a)
    return a


def get_campaign(campaign_id):
    c = store.campaigns.get(campaign_id)
    if c is None:
        raise not_found("ad campaign not found")
    return c


@bp.post("/platform/business-pages/<pageId>/ad-account")
@require_roles("BusinessOwner")
def create_ad_account(pageId, _actor_id, _actor_role):
    page = get_page(pageId)
    body = get_body()
    budget = req_int(body, "daily_budget_cents", lo=0)
    if page["claimed_by_user_id"] is None or page["claimed_by_user_id"] != _actor_id:
        raise err("ERR_AD_ACCOUNT_CONFLICT",
                  "page must be claimed by the caller")
    if page.get("ad_account_id"):
        raise err("ERR_AD_ACCOUNT_CONFLICT", "page already has an ad account")
    acct = stamp_common({
        "page_id": pageId,
        "owner_user_id": _actor_id,
        "daily_budget_cents": budget,
        "spent_today_cents": 0,
        "status": "ACTIVE",
        "_spent_date": store.now.date(),
    })
    store.ad_accounts[acct["id"]] = acct
    page["ad_account_id"] = acct["id"]
    touch(page)
    return ok(pub(acct), status=201)


@bp.get("/platform/ad-accounts")
@require_roles(*AD_ROLES)
def list_ad_accounts(_actor_id, _actor_role):
    items = list(store.ad_accounts.values())
    for f in ("owner_user_id", "page_id"):
        v = request.args.get(f)
        if v is not None:
            items = [a for a in items if a.get(f) == v]
    for a in items:
        lazy_reset_spend(a)
    items, limit, offset, total = paginate([pub(a) for a in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/ad-accounts/<accountId>")
@require_roles(*AD_ROLES)
def get_one_account(accountId, _actor_id, _actor_role):
    return ok(pub(get_account(accountId)))


@bp.post("/platform/ad-accounts/<accountId>/suspend")
@require_roles("SupportAdmin")
def suspend_account(accountId, _actor_id, _actor_role):
    acct = get_account(accountId)
    if acct["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "account is not ACTIVE")
    acct["status"] = "SUSPENDED"
    touch(acct)
    for camp in store.campaigns.values():
        if camp["ad_account_id"] == accountId and camp["status"] == "ACTIVE":
            camp["status"] = "PAUSED"
            touch(camp)
    return ok(pub(acct))


@bp.post("/platform/ad-accounts/<accountId>/reactivate")
@require_roles("Advertiser")
def reactivate_account(accountId, _actor_id, _actor_role):
    acct = get_account(accountId)
    if acct["status"] != "SUSPENDED":
        raise err("ERR_INVALID_STATE", "account is not SUSPENDED")
    if acct["owner_user_id"] != _actor_id:
        raise err("ERR_FORBIDDEN", "only the account owner may reactivate")
    page = store.pages.get(acct["page_id"])
    if page is None or page["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "page is not ACTIVE")
    acct["status"] = "ACTIVE"
    touch(acct)
    return ok(pub(acct))


@bp.post("/platform/ad-accounts/<accountId>/close")
@require_roles("Advertiser")
def close_account(accountId, _actor_id, _actor_role):
    acct = get_account(accountId)
    if acct["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err("ERR_INVALID_STATE", "account is not ACTIVE or SUSPENDED")
    if acct["owner_user_id"] != _actor_id:
        raise err("ERR_FORBIDDEN", "only the account owner may close the account")
    acct["status"] = "CLOSED"
    touch(acct)
    for camp in store.campaigns.values():
        if (camp["ad_account_id"] == accountId
                and camp["status"] in ("DRAFT", "ACTIVE", "PAUSED")):
            camp["status"] = "CANCELLED"
            touch(camp)
    return ok(pub(acct))


# ---- campaigns ----

@bp.post("/platform/ad-accounts/<accountId>/campaigns")
@require_roles("Advertiser")
def create_campaign(accountId, _actor_id, _actor_role):
    acct = get_account(accountId)
    body = get_body()
    kind = req_enum(body, "kind", ("SPONSORED_PLACEMENT", "CALL_TRACKING"))
    bid = req_int(body, "bid_cents", lo=1)
    starts_on = req_date(body, "starts_on")
    ends_on = req_date(body, "ends_on")
    cte = req_bool(body, "call_tracking_enabled", default=False)
    if parse_date(ends_on) < parse_date(starts_on):
        raise err("ERR_INVALID_REQUEST", "ends_on must not precede starts_on")
    if acct["owner_user_id"] != _actor_id:
        raise err("ERR_FORBIDDEN", "only the account owner may create campaigns")
    if kind == "CALL_TRACKING" and cte is not True:
        raise err("ERR_CAMPAIGN_CONFIG",
                  "CALL_TRACKING requires call_tracking_enabled true")
    if kind == "SPONSORED_PLACEMENT" and cte is not False:
        raise err("ERR_CAMPAIGN_CONFIG",
                  "SPONSORED_PLACEMENT requires call_tracking_enabled false")
    camp = stamp_common({
        "ad_account_id": accountId,
        "kind": kind,
        "bid_cents": bid,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "call_tracking_enabled": cte,
        "status": "DRAFT",
    })
    store.campaigns[camp["id"]] = camp
    return ok(pub(camp), status=201)


@bp.get("/platform/ad-campaigns")
@require_roles(*AD_ROLES)
def list_campaigns(_actor_id, _actor_role):
    items = list(store.campaigns.values())
    v = request.args.get("ad_account_id")
    if v is not None:
        items = [c for c in items if c["ad_account_id"] == v]
    items, limit, offset, total = paginate([pub(c) for c in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/ad-accounts/<accountId>/campaigns")
@require_roles(*AD_ROLES)
def list_account_campaigns(accountId, _actor_id, _actor_role):
    get_account(accountId)
    items = [pub(c) for c in store.campaigns.values()
             if c["ad_account_id"] == accountId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/ad-campaigns/<campaignId>")
@require_roles(*AD_ROLES)
def get_one_campaign(campaignId, _actor_id, _actor_role):
    return ok(pub(get_campaign(campaignId)))


@bp.post("/platform/ad-campaigns/<campaignId>/activate")
@require_roles("Advertiser")
def activate_campaign(campaignId, _actor_id, _actor_role):
    camp = get_campaign(campaignId)
    acct = store.ad_accounts[camp["ad_account_id"]]
    if camp["status"] not in ("DRAFT", "PAUSED"):
        raise err("ERR_INVALID_STATE", "campaign is not DRAFT or PAUSED")
    if acct["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "ad account is not ACTIVE")
    if camp["status"] == "DRAFT" and acct["owner_user_id"] != _actor_id:
        raise err("ERR_FORBIDDEN", "only the account owner may activate")
    today = store.now.date()
    if camp["status"] == "DRAFT":
        if not (parse_date(camp["starts_on"]) <= today <= parse_date(camp["ends_on"])):
            raise err("ERR_CAMPAIGN_OUT_OF_WINDOW",
                      "current date outside campaign window")
    else:  # resume from PAUSED
        if today > parse_date(camp["ends_on"]):
            raise err("ERR_CAMPAIGN_OUT_OF_WINDOW", "campaign window has ended")
    camp["status"] = "ACTIVE"
    touch(camp)
    return ok(pub(camp))


@bp.post("/platform/ad-campaigns/<campaignId>/pause")
@require_roles("Advertiser")
def pause_campaign(campaignId, _actor_id, _actor_role):
    camp = get_campaign(campaignId)
    if camp["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "campaign is not ACTIVE")
    acct = store.ad_accounts[camp["ad_account_id"]]
    if acct["owner_user_id"] != _actor_id:
        raise err("ERR_FORBIDDEN", "only the account owner may pause")
    camp["status"] = "PAUSED"
    touch(camp)
    return ok(pub(camp))


@bp.post("/platform/ad-campaigns/<campaignId>/cancel")
@require_roles("Advertiser")
def cancel_campaign(campaignId, _actor_id, _actor_role):
    camp = get_campaign(campaignId)
    if camp["status"] not in ("DRAFT", "ACTIVE", "PAUSED"):
        raise err("ERR_INVALID_STATE", "campaign cannot be cancelled from this state")
    camp["status"] = "CANCELLED"
    touch(camp)
    return ok(pub(camp))
