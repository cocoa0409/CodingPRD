"""Routes: ad charging — impressions, call events, attribution reports."""
from datetime import timedelta
from flask import Blueprint, request

from db import store, fmt_ts, parse_ts, parse_date
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_event, touch, get_body, req_str, req_int, req_enum, req_date,
    lazy_reset_spend, pub,
    CALL_MIN_DURATION_S, ATT_WINDOW_DAYS,
)
from routes_ads import AD_ROLES, get_account, get_campaign

bp = Blueprint("ad_events", __name__)

CHARGE_ROLES = ("Advertiser", "PlatformOps")


def _charge(acct, cost):
    """Pinned budget check: reject when spent + cost > budget (equality allowed)."""
    if acct["spent_today_cents"] + cost > acct["daily_budget_cents"]:
        raise err("ERR_BUDGET_EXCEEDED", "charge would exceed the daily budget")
    acct["spent_today_cents"] += cost
    touch(acct)


@bp.post("/platform/ad-accounts/<accountId>/impressions")
@require_roles(*CHARGE_ROLES)
def create_impression(accountId, _actor_id, _actor_role):
    acct = get_account(accountId)
    body = get_body()
    campaign_id = req_str(body, "campaign_id")
    idem = req_str(body, "idempotency_key")
    camp = store.campaigns.get(campaign_id)
    if camp is None or camp["ad_account_id"] != accountId:
        raise not_found("campaign not found on this account")
    # idempotency: same key + same campaign -> original event; same key + different campaign -> conflict
    for ev in store.impressions.values():
        if ev["ad_account_id"] == accountId and ev["idempotency_key"] == idem:
            if ev["campaign_id"] == campaign_id:
                return ok(pub(ev), status=201)
            raise err("ERR_IDEMPOTENCY_CONFLICT",
                      "idempotency_key reused with a different campaign_id")
    if camp["kind"] != "SPONSORED_PLACEMENT" or camp["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE",
                  "impressions require an ACTIVE SPONSORED_PLACEMENT campaign")
    if acct["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "ad account is not ACTIVE")
    _charge(acct, camp["bid_cents"])
    ev = stamp_event({
        "ad_account_id": accountId,
        "campaign_id": campaign_id,
        "idempotency_key": idem,
        "cost_cents": camp["bid_cents"],
        "served_on": store.now.date().isoformat(),
    })
    store.impressions[ev["id"]] = ev
    return ok(pub(ev), status=201)


@bp.get("/platform/ad-accounts/<accountId>/impressions")
@require_roles(*AD_ROLES)
def list_account_impressions(accountId, _actor_id, _actor_role):
    get_account(accountId)
    items = [pub(e) for e in store.impressions.values()
             if e["ad_account_id"] == accountId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/ad-impression-events")
@require_roles(*AD_ROLES)
def list_impressions(_actor_id, _actor_role):
    items = list(store.impressions.values())
    for f in ("campaign_id", "ad_account_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    items, limit, offset, total = paginate([pub(e) for e in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/ad-impression-events/<eventId>")
@require_roles(*AD_ROLES)
def get_impression(eventId, _actor_id, _actor_role):
    ev = store.impressions.get(eventId)
    if ev is None:
        raise not_found("impression event not found")
    return ok(pub(ev))


@bp.post("/platform/ad-accounts/<accountId>/call-events")
@require_roles(*CHARGE_ROLES)
def create_call_event(accountId, _actor_id, _actor_role):
    acct = get_account(accountId)
    body = get_body()
    campaign_id = req_str(body, "campaign_id")
    caller_number = req_str(body, "caller_number")
    called_at = body.get("called_at")
    duration = req_int(body, "duration_seconds", lo=0)
    if not isinstance(called_at, str):
        raise err("ERR_INVALID_REQUEST", "called_at is required")
    try:
        called_dt = parse_ts(called_at)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", "called_at must be an ISO 8601 timestamp")
    camp = store.campaigns.get(campaign_id)
    if camp is None or camp["ad_account_id"] != accountId:
        raise not_found("campaign not found on this account")
    if camp["kind"] != "CALL_TRACKING" or camp["status"] != "ACTIVE":
        raise err("ERR_CAMPAIGN_NOT_CALL_TRACKING",
                  "call events require an ACTIVE CALL_TRACKING campaign")
    called_date = called_dt.date()
    if not (parse_date(camp["starts_on"]) <= called_date <= parse_date(camp["ends_on"])):
        raise err("ERR_ATTRIBUTION_WINDOW",
                  "called_at outside the campaign window")
    qualified = duration >= CALL_MIN_DURATION_S
    cost = camp["bid_cents"] if qualified else 0
    if qualified:
        if acct["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "ad account is not ACTIVE")
        _charge(acct, cost)
    ev = stamp_event({
        "ad_account_id": accountId,
        "campaign_id": campaign_id,
        "caller_number": caller_number,
        "called_at": called_at,
        "duration_seconds": duration,
        "qualified": qualified,
        "cost_cents": cost,
        "attribution_window_days": ATT_WINDOW_DAYS,
    })
    store.call_events[ev["id"]] = ev
    return ok(pub(ev), status=201)


@bp.get("/platform/ad-accounts/<accountId>/call-events")
@require_roles(*AD_ROLES)
def list_account_call_events(accountId, _actor_id, _actor_role):
    get_account(accountId)
    items = [pub(e) for e in store.call_events.values()
             if e["ad_account_id"] == accountId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/call-track-events")
@require_roles(*AD_ROLES)
def list_call_events(_actor_id, _actor_role):
    items = list(store.call_events.values())
    for f in ("campaign_id", "ad_account_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    items, limit, offset, total = paginate([pub(e) for e in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/call-track-events/<eventId>")
@require_roles(*AD_ROLES)
def get_call_event(eventId, _actor_id, _actor_role):
    ev = store.call_events.get(eventId)
    if ev is None:
        raise not_found("call track event not found")
    return ok(pub(ev))


@bp.post("/platform/ad-accounts/<accountId>/attribution-reports")
@require_roles(*CHARGE_ROLES)
def create_report(accountId, _actor_id, _actor_role):
    acct = get_account(accountId)
    body = get_body()
    campaign_id = req_str(body, "campaign_id")
    period_start = req_date(body, "period_start")
    period_end = req_date(body, "period_end")
    variant = req_enum(body, "variant", ("STRICT", "EXTENDED"))
    if parse_date(period_end) < parse_date(period_start):
        raise err("ERR_INVALID_REQUEST", "period_end must not precede period_start")
    camp = store.campaigns.get(campaign_id)
    if camp is None or camp["ad_account_id"] != accountId:
        raise not_found("campaign not found on this account")
    ps = parse_date(period_start)
    pe = parse_date(period_end)
    impressions = 0
    imp_spend = 0
    for ev in store.impressions.values():
        if ev["campaign_id"] != campaign_id:
            continue
        d = parse_date(ev["served_on"])
        if ps <= d <= pe:
            impressions += 1
            imp_spend += ev["cost_cents"]
    if variant == "EXTENDED":
        call_start = ps - timedelta(days=ATT_WINDOW_DAYS)
    else:
        call_start = ps
    qualified_calls = 0
    call_spend = 0
    for ev in store.call_events.values():
        if ev["campaign_id"] != campaign_id or not ev["qualified"]:
            continue
        d = parse_ts(ev["called_at"]).date()
        if call_start <= d <= pe:
            qualified_calls += 1
            call_spend += ev["cost_cents"]
    rep = stamp_event({
        "ad_account_id": accountId,
        "campaign_id": campaign_id,
        "period_start": period_start,
        "period_end": period_end,
        "variant": variant,
        "impressions": impressions,
        "qualified_calls": qualified_calls,
        "spend_cents": imp_spend + call_spend,
    })
    store.reports[rep["id"]] = rep
    return ok(pub(rep), status=201)


@bp.get("/platform/ad-accounts/<accountId>/attribution-reports")
@require_roles(*AD_ROLES)
def list_account_reports(accountId, _actor_id, _actor_role):
    get_account(accountId)
    items = [pub(r) for r in store.reports.values()
             if r["ad_account_id"] == accountId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/attribution-reports")
@require_roles(*AD_ROLES)
def list_reports(_actor_id, _actor_role):
    items = list(store.reports.values())
    for f in ("campaign_id", "ad_account_id"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    items, limit, offset, total = paginate([pub(r) for r in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/attribution-reports/<reportId>")
@require_roles(*AD_ROLES)
def get_report(reportId, _actor_id, _actor_role):
    rep = store.reports.get(reportId)
    if rep is None:
        raise not_found("attribution report not found")
    return ok(pub(rep))
