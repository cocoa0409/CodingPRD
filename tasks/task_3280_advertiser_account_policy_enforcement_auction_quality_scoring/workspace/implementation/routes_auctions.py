"""Routes: auctions and invalid-click flagging."""
from flask import Blueprint, request
from core import (DB, CLOCK, ok, err, new_record, touch, authenticate,
                  require_role, normalize_text, parse_date)
from services import (serialize, lazy_campaign, lazy_account, keyword_matches,
                      quality_score_centi, charge_click, profile_for_account,
                      AD_RANK_RESERVE, RESERVE_CPC_CENTS)

bp = Blueprint("auctions", __name__)


def _match(kw_norm, match_type, query_norm):
    if match_type == "EXACT":
        return kw_norm == query_norm
    if match_type == "PHRASE":
        return kw_norm in query_norm
    qtokens = set(query_norm.split())
    return all(t in qtokens for t in kw_norm.split())


@bp.post("/auctions")
def run_auction():
    caller = authenticate()
    require_role(caller, "PlatformAdmin")
    body = request.get_json(silent=True) or {}
    query_text = body.get("query_text")
    clicked = body.get("clicked", False)
    is_invalid = body.get("is_invalid_click", False)
    if not isinstance(query_text, str) or not query_text:
        err("ERR_VALIDATION", "query_text required")
    if not isinstance(clicked, bool) or not isinstance(is_invalid, bool):
        err("ERR_VALIDATION", "clicked and is_invalid_click must be booleans")
    query_norm = normalize_text(query_text)
    today = CLOCK.today()

    candidates = []
    for ad in DB.ads.values():
        if ad["status"] != "ELIGIBLE":
            continue
        ag = DB.ad_groups.get(ad["ad_group_id"])
        if ag is None:
            continue
        campaign = DB.campaigns.get(ag["campaign_id"])
        if campaign is None:
            continue
        lazy_campaign(campaign)
        if campaign["status"] != "ACTIVE":
            continue
        if today < parse_date(campaign["start_date"]) or today > parse_date(campaign["end_date"]):
            continue
        account = DB.accounts.get(campaign["account_id"])
        if account is None:
            continue
        lazy_account(account)
        if account["status"] != "ACTIVE":
            continue
        # negative block: any negative keyword of the ad group matching the query blocks all
        group_kws = [k for k in DB.keywords.values() if k["ad_group_id"] == ag["id"]]
        blocked = any(k["is_negative"] and _match(k["normalized_text"], k["match_type"], query_norm)
                      for k in group_kws)
        if blocked:
            continue
        # bid: highest max_cpc among matching non-negative keywords; tie -> earliest created_at
        matching = [k for k in group_kws if not k["is_negative"]
                    and _match(k["normalized_text"], k["match_type"], query_norm)]
        if not matching:
            continue
        best_bid = max(k["max_cpc_cents"] for k in matching)
        winners = [k for k in matching if k["max_cpc_cents"] == best_bid]
        winners.sort(key=lambda k: (k["created_at"], k.get("_seq", 0), k["id"]))
        bid = winners[0]["max_cpc_cents"]
        qscore = quality_score_centi(ad)
        rank = bid * qscore
        if rank < AD_RANK_RESERVE:
            continue
        candidates.append((ad, campaign, account, bid, qscore, rank))

    if not candidates:
        err("ERR_NO_ELIGIBLE_AD", "No eligible ad for the query")

    # winner: highest rank; tie -> earliest ad created_at
    candidates.sort(key=lambda c: (-c[5], c[0]["created_at"], c[0].get("_seq", 0), c[0]["id"]))
    winner_ad, winner_campaign, winner_account, winner_bid, winner_qscore, winner_rank = candidates[0]
    runner_up_rank = candidates[1][5] if len(candidates) > 1 else None

    # actual CPC
    if runner_up_rank is not None:
        raw = runner_up_rank // winner_qscore  # floor BEFORE +1
        price = raw + 1
        actual_cpc = min(winner_bid, price)
    else:
        actual_cpc = min(winner_bid, RESERVE_CPC_CENTS)

    clicked_flag = bool(clicked)
    invalid_flag = bool(is_invalid)
    charged = actual_cpc if clicked_flag else 0

    # pacing check (valid click only)
    if clicked_flag and not invalid_flag:
        day_key = (winner_campaign["id"], today.strftime("%Y-%m-%d"))
        day = DB.daily_spend_records.get(day_key)
        current_served = day["served_cents"] if day else 0
        new_served = current_served + charged
        if new_served > 2 * winner_campaign["daily_budget_cents"]:
            # record event with no-charge semantics, then 422
            ev = new_record({
                "query_text": query_text,
                "clicked": False,
                "is_invalid_click": False,
                "occurred_date": today.strftime("%Y-%m-%d"),
                "winner_ad_id": winner_ad["id"],
                "winner_campaign_id": winner_campaign["id"],
                "winner_ad_rank": winner_rank,
                "runner_up_ad_rank": runner_up_rank,
                "quality_score_final_centi": winner_qscore,
                "charged_cents": 0,
                "_billed": True,
                "_orig_charge": 0,
            })
            DB.auction_events[ev["id"]] = ev
            err("ERR_DAILY_OVERDELIVERY_LIMIT", "Click would exceed 2x daily budget")

    ev = new_record({
        "query_text": query_text,
        "clicked": clicked_flag,
        "is_invalid_click": invalid_flag,
        "occurred_date": today.strftime("%Y-%m-%d"),
        "winner_ad_id": winner_ad["id"],
        "winner_campaign_id": winner_campaign["id"],
        "winner_ad_rank": winner_rank,
        "runner_up_ad_rank": runner_up_rank,
        "quality_score_final_centi": winner_qscore,
        "charged_cents": 0 if invalid_flag else charged,
        "_billed": False,
        "_orig_charge": 0 if invalid_flag else charged,
    })
    DB.auction_events[ev["id"]] = ev

    if clicked_flag and not invalid_flag and charged > 0:
        charge_click(winner_account, winner_campaign, charged)

    return ok(serialize("auction_event", ev), 201)


@bp.get("/auction-events/<event_id>")
def get_auction_event(event_id):
    caller = authenticate()
    require_role(caller, "PlatformAdmin", "Advertiser")
    ev = DB.auction_events.get(event_id)
    if ev is None:
        err("ERR_NOT_FOUND", "AuctionEvent not found")
    if caller.role == "Advertiser":
        ad = DB.ads.get(ev["winner_ad_id"])
        ag = DB.ad_groups.get(ad["ad_group_id"]) if ad else None
        campaign = DB.campaigns.get(ag["campaign_id"]) if ag else None
        if campaign is None or campaign["account_id"] != caller.user_id:
            err("ERR_FORBIDDEN", "Advertiser may only read its own auction events")
    return ok(serialize("auction_event", ev), 200)


@bp.post("/auction-events/<event_id>/flag-invalid")
def flag_invalid(event_id):
    caller = authenticate()
    require_role(caller, "BillingAdmin")
    ev = DB.auction_events.get(event_id)
    if ev is None:
        err("ERR_NOT_FOUND", "AuctionEvent not found")
    if not ev["clicked"]:
        err("ERR_AUCTION_NOT_CLICKED", "Auction event was not clicked")
    if ev["is_invalid_click"]:
        err("ERR_CLICK_ALREADY_INVALID", "Click already flagged invalid")
    c = ev["charged_cents"]
    ev["is_invalid_click"] = True
    ev["charged_cents"] = 0
    touch(ev)
    if c > 0:
        campaign = DB.campaigns.get(ev["winner_campaign_id"])
        account = DB.accounts.get(campaign["account_id"]) if campaign else None
        day_key = (ev["winner_campaign_id"], ev["occurred_date"])
        day = DB.daily_spend_records.get(day_key)
        if day is not None:
            day["served_cents"] -= c
            day["click_count"] -= 1
            touch(day)
        if campaign is not None:
            campaign["served_lifetime_cents"] -= c
            campaign["click_count_lifetime"] -= 1
            touch(campaign)
        if account is not None:
            account["lifetime_valid_served_cents"] -= c
            account["lifetime_invalid_click_credit_cents"] = \
                account.get("lifetime_invalid_click_credit_cents", 0) + c
            touch(account)
        profile = profile_for_account(ev_account_id(ev)) if campaign else None
        if profile is not None:
            if not ev.get("_billed"):
                profile["unbilled_cost_cents"] -= c
            else:
                # apply to oldest unpaid invoice (created_at ASC)
                unpaid = [i for i in DB.invoices.values()
                          if i["billing_profile_id"] == profile["id"]
                          and i["status"] in ("ISSUED", "PARTIALLY_PAID", "OVERDUE")]
                unpaid.sort(key=lambda i: (i["created_at"], i.get("_seq", 0), i["id"]))
                remaining = c
                if unpaid:
                    target = unpaid[0]
                    headroom = target["amount_cents"] - target["paid_cents"]
                    applied = min(remaining, headroom)
                    if applied > 0:
                        target["amount_cents"] -= applied
                        target["invalid_click_credit_cents"] += applied
                        touch(target)
                        remaining -= applied
                if remaining > 0:
                    profile["pending_credit_cents"] += remaining
            touch(profile)
    return ok(serialize("auction_event", ev), 200)


def ev_account_id(ev):
    campaign = DB.campaigns.get(ev["winner_campaign_id"])
    return campaign["account_id"] if campaign else None
