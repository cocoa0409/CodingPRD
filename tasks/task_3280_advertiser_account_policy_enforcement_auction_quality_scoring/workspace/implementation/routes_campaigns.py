"""Routes: campaigns, ad groups."""
from flask import Blueprint, request
from core import (DB, CLOCK, ok, paginate, err, new_record, touch, authenticate,
                  require_role, check_ownership, parse_date)
from services import serialize, lazy_campaign

bp = Blueprint("campaigns", __name__)


def get_campaign_or_404(campaign_id):
    c = DB.campaigns.get(campaign_id)
    if c is None:
        err("ERR_NOT_FOUND", "Campaign not found")
    return c


def _valid_date(s):
    if not isinstance(s, str):
        return False
    try:
        parse_date(s)
        return True
    except Exception:
        return False


@bp.post("/campaigns")
def create_campaign():
    caller = authenticate()
    require_role(caller, "Advertiser")
    body = request.get_json(silent=True) or {}
    account_id = body.get("account_id")
    name = body.get("name")
    budget = body.get("daily_budget_cents")
    start = body.get("start_date")
    end = body.get("end_date")
    if not isinstance(account_id, str) or not account_id:
        err("ERR_VALIDATION", "account_id required")
    if not isinstance(name, str) or not name:
        err("ERR_VALIDATION", "name required")
    if not isinstance(budget, int) or isinstance(budget, bool):
        err("ERR_VALIDATION", "daily_budget_cents must be an integer")
    if not _valid_date(start):
        err("ERR_VALIDATION", "start_date must be YYYY-MM-DD")
    if not _valid_date(end):
        err("ERR_VALIDATION", "end_date must be YYYY-MM-DD")
    account = DB.accounts.get(account_id)
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    check_ownership(caller, account_id)
    # fiscal rules
    if budget < 100:
        err("ERR_BUDGET_BELOW_MINIMUM", "daily_budget_cents must be >= 100")
    if parse_date(end) < parse_date(start):
        err("ERR_CAMPAIGN_DATE_RANGE_INVALID", "end_date must be >= start_date")
    campaign = new_record({
        "account_id": account_id,
        "name": name,
        "daily_budget_cents": budget,
        "start_date": start,
        "end_date": end,
        "eligible_ad_count": 0,
        "status": "DRAFT",
        "pause_origin": "NONE",
        "served_lifetime_cents": 0,
        "click_count_lifetime": 0,
        "current_month_served_cents": 0,
        "overdelivery_credit_cents": 0,
        "monthly_cap_provisional_cents": budget * 304 // 10,
        "last_closed_month_cap_cents": None,
        "last_closed_month_credit_cents": None,
        # budget history: list of [date_str, budget]; entry takes effect the day it is set
        "_budget_history": [[CLOCK.today().strftime("%Y-%m-%d"), budget]],
    })
    DB.campaigns[campaign["id"]] = campaign
    return ok(serialize("campaign", campaign), 201)


@bp.get("/campaigns")
def list_campaigns():
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    account_id_filter = request.args.get("account_id")
    status_filter = request.args.get("status")
    items = list(DB.campaigns.values())
    for c in items:
        lazy_campaign(c)
    if account_id_filter is not None:
        items = [c for c in items if c["account_id"] == account_id_filter]
    if status_filter is not None:
        items = [c for c in items if c["status"] == status_filter]
    if caller.role == "Advertiser":
        items = [c for c in items if c["account_id"] == caller.user_id]
    items.sort(key=lambda c: (c["created_at"], c.get("_seq", 0), c["id"]))
    page, meta = paginate(items)
    return ok([serialize("campaign", c) for c in page], 200, meta)


@bp.get("/campaigns/<campaign_id>")
def get_campaign(campaign_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    c = get_campaign_or_404(campaign_id)
    check_ownership(caller, c["account_id"])
    lazy_campaign(c)
    return ok(serialize("campaign", c), 200)


@bp.put("/campaigns/<campaign_id>")
def update_campaign(campaign_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    c = get_campaign_or_404(campaign_id)
    check_ownership(caller, c["account_id"])
    body = request.get_json(silent=True) or {}
    expected = body.get("expected_campaign_version")
    new_budget = body.get("daily_budget_cents", None)
    new_end = body.get("end_date", None)
    if expected is None or not isinstance(expected, int) or isinstance(expected, bool):
        err("ERR_VALIDATION", "expected_campaign_version required")
    if new_budget is not None and (not isinstance(new_budget, int) or isinstance(new_budget, bool)):
        err("ERR_VALIDATION", "daily_budget_cents must be an integer")
    if new_end is not None and not _valid_date(new_end):
        err("ERR_VALIDATION", "end_date must be YYYY-MM-DD")
    # OCC (priority 5)
    if expected != c["version"]:
        err("ERR_STALE_VERSION", "expected_campaign_version mismatch")
    # fiscal
    if new_budget is not None and new_budget < 100:
        err("ERR_BUDGET_BELOW_MINIMUM", "daily_budget_cents must be >= 100")
    end_to_use = new_end if new_end is not None else c["end_date"]
    if parse_date(end_to_use) < parse_date(c["start_date"]):
        err("ERR_CAMPAIGN_DATE_RANGE_INVALID", "end_date must be >= start_date")
    if new_budget is not None:
        c["daily_budget_cents"] = new_budget
        # budget change takes effect for the current logical day
        hist = c.setdefault("_budget_history", [])
        today_s = CLOCK.today().strftime("%Y-%m-%d")
        if hist and hist[-1][0] == today_s:
            hist[-1][1] = new_budget
        else:
            hist.append([today_s, new_budget])
    if new_end is not None:
        c["end_date"] = new_end
    touch(c)
    return ok(serialize("campaign", c), 200)


def _check_activation_gates(c):
    account = DB.accounts.get(c["account_id"])
    today = CLOCK.today()
    if today < parse_date(c["start_date"]) or today > parse_date(c["end_date"]):
        err("ERR_CAMPAIGN_OUTSIDE_FLIGHT_WINDOW", "Logical date outside flight window")
    if account is None:
        err("ERR_NOT_FOUND", "AdvertiserAccount not found")
    if account["status"] == "PENDING_VERIFICATION":
        err("ERR_VERIFICATION_REQUIRED", "Account is PENDING_VERIFICATION")
    if account["status"] in ("SUSPENDED", "APPEAL_PENDING", "SUSPENDED_FINAL"):
        err("ERR_ACCOUNT_SUSPENDED", "Account is suspended")
    # else ACTIVE ok


@bp.post("/campaigns/<campaign_id>/activate")
def activate_campaign(campaign_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    c = get_campaign_or_404(campaign_id)
    check_ownership(caller, c["account_id"])
    lazy_campaign(c)
    if c["status"] not in ("DRAFT", "PAUSED"):
        err("ERR_INVALID_STATE", "Campaign cannot be activated from current state")
    _check_activation_gates(c)
    c["status"] = "ACTIVE"
    c["pause_origin"] = "NONE"
    touch(c)
    return ok(serialize("campaign", c), 200)


@bp.post("/campaigns/<campaign_id>/pause")
def pause_campaign(campaign_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    c = get_campaign_or_404(campaign_id)
    check_ownership(caller, c["account_id"])
    lazy_campaign(c)
    if c["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "Only an ACTIVE campaign can be paused")
    c["status"] = "PAUSED"
    c["pause_origin"] = "ADVERTISER"
    touch(c)
    return ok(serialize("campaign", c), 200)


@bp.get("/campaigns/<campaign_id>/daily-spend-records")
def list_daily_spend(campaign_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    c = get_campaign_or_404(campaign_id)
    check_ownership(caller, c["account_id"])
    items = [d for d in DB.daily_spend_records.values() if d["campaign_id"] == campaign_id]
    items.sort(key=lambda d: (d["created_at"], d.get("_seq", 0), d["id"]))
    page, meta = paginate(items)
    return ok([serialize("daily_spend_record", d) for d in page], 200, meta)


@bp.post("/campaigns/<campaign_id>/ad-groups")
def create_ad_group(campaign_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    c = get_campaign_or_404(campaign_id)
    check_ownership(caller, c["account_id"])
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    if not isinstance(name, str) or not name:
        err("ERR_VALIDATION", "name required")
    ag = new_record({"campaign_id": campaign_id, "name": name})
    DB.ad_groups[ag["id"]] = ag
    return ok(serialize("ad_group", ag), 201)


@bp.get("/campaigns/<campaign_id>/ad-groups")
def list_ad_groups(campaign_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    c = get_campaign_or_404(campaign_id)
    check_ownership(caller, c["account_id"])
    items = [a for a in DB.ad_groups.values() if a["campaign_id"] == campaign_id]
    items.sort(key=lambda a: (a["created_at"], a.get("_seq", 0), a["id"]))
    page, meta = paginate(items)
    return ok([serialize("ad_group", a) for a in page], 200, meta)


@bp.get("/ad-groups/<ad_group_id>")
def get_ad_group(ad_group_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    ag = DB.ad_groups.get(ad_group_id)
    if ag is None:
        err("ERR_NOT_FOUND", "AdGroup not found")
    c = DB.campaigns.get(ag["campaign_id"])
    check_ownership(caller, c["account_id"] if c else None)
    return ok(serialize("ad_group", ag), 200)
