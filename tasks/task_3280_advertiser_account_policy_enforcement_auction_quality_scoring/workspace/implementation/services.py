"""Shared business logic: lazy evaluation, cascades, billing, auction math."""
from datetime import timedelta
from core import DB, CLOCK, touch, new_record, fmt_ts, req_ts, normalize_text

AD_RANK_RESERVE = 20000
RESERVE_CPC_CENTS = 5
THRESHOLD_LADDER = [50000, 150000, 300000, 500000]
RESTRICTED_CATEGORIES = {"ALCOHOL", "GAMBLING", "HEALTHCARE", "FINANCIAL"}


# ---------------------------------------------------------------------------
# Lazy state finalization (PRD 2.6)
# ---------------------------------------------------------------------------

def lazy_account(account):
    if account is None:
        return
    if account["status"] == "SUSPENDED" and account.get("suspended_at"):
        from core import _parse_iso
        susp = _parse_iso(account["suspended_at"])
        if CLOCK.now() >= susp + timedelta(days=30):
            open_appeal = any(
                a for a in DB.appeals.values()
                if a["account_id"] == account["id"] and a["status"] in ("SUBMITTED", "UNDER_REVIEW")
            )
            if not open_appeal:
                account["status"] = "SUSPENDED_FINAL"
                touch(account)


def lazy_campaign(campaign):
    if campaign is None:
        return
    if campaign["status"] in ("DRAFT", "ACTIVE", "PAUSED"):
        from core import parse_date
        if CLOCK.today() > parse_date(campaign["end_date"]):
            campaign["status"] = "ENDED"
            touch(campaign)


def lazy_invoice(invoice):
    if invoice is None:
        return
    if invoice["status"] in ("ISSUED", "PARTIALLY_PAID"):
        from core import parse_date
        if CLOCK.today() > parse_date(invoice["due_date"]):
            invoice["status"] = "OVERDUE"
            touch(invoice)


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

def campaign_account(campaign):
    return DB.accounts.get(campaign["account_id"])

def ad_campaign(ad):
    ag = DB.ad_groups.get(ad["ad_group_id"])
    return DB.campaigns.get(ag["campaign_id"]) if ag else None

def ad_account(ad):
    c = ad_campaign(ad)
    return DB.accounts.get(c["account_id"]) if c else None

def adgroup_campaign(ag):
    return DB.campaigns.get(ag["campaign_id"])

def adgroup_account(ag):
    c = adgroup_campaign(ag)
    return DB.accounts.get(c["account_id"]) if c else None

def profile_account(profile):
    return DB.accounts.get(profile["account_id"])

def invoice_profile(invoice):
    return DB.billing_profiles.get(invoice["billing_profile_id"])

def invoice_account(invoice):
    p = invoice_profile(invoice)
    return DB.accounts.get(p["account_id"]) if p else None

def review_account(review):
    ad = DB.ads.get(review["ad_id"])
    return ad_account(ad) if ad else None

def event_account(event):
    ad = DB.ads.get(event["winner_ad_id"])
    return ad_account(ad) if ad else None

def account_of_campaign_id(campaign_id):
    c = DB.campaigns.get(campaign_id)
    return DB.accounts.get(c["account_id"]) if c else None


# ---------------------------------------------------------------------------
# Quality score
# ---------------------------------------------------------------------------

def quality_score_centi(ad):
    return 50 * ad["quality_ectr_score"] + 30 * ad["quality_relevance_score"] + 20 * ad["quality_lp_score"]


# ---------------------------------------------------------------------------
# eligible_ad_count recompute + cascades
# ---------------------------------------------------------------------------

def recompute_eligible_ad_count(campaign):
    count = 0
    for ad in DB.ads.values():
        ag = DB.ad_groups.get(ad["ad_group_id"])
        if ag and ag["campaign_id"] == campaign["id"] and ad["status"] == "ELIGIBLE":
            count += 1
    campaign["eligible_ad_count"] = count
    return count


def on_ad_became_eligible(ad):
    """Snapshot freeze + count recompute + bubble-up resume."""
    ad["quality_score_snapshot_centi"] = quality_score_centi(ad)
    campaign = ad_campaign(ad)
    if campaign is None:
        return
    recompute_eligible_ad_count(campaign)
    touch(campaign)
    if (campaign["status"] == "PAUSED"
            and campaign["pause_origin"] == "NO_ELIGIBLE_ADS"
            and campaign["eligible_ad_count"] > 0):
        account = campaign_account(campaign)
        if account and account["status"] == "ACTIVE":
            campaign["status"] = "ACTIVE"
            campaign["pause_origin"] = "NONE"
            touch(campaign)


def on_ad_disapproved(ad):
    """Count recompute + NO_ELIGIBLE_ADS auto-pause cascade."""
    campaign = ad_campaign(ad)
    if campaign is None:
        return
    recompute_eligible_ad_count(campaign)
    touch(campaign)
    if campaign["status"] == "ACTIVE" and campaign["eligible_ad_count"] == 0:
        campaign["status"] = "PAUSED"
        campaign["pause_origin"] = "NO_ELIGIBLE_ADS"
        touch(campaign)


def suspend_account_cascade(account):
    for campaign in DB.campaigns.values():
        if campaign["account_id"] == account["id"] and campaign["status"] == "ACTIVE":
            campaign["status"] = "PAUSED"
            campaign["pause_origin"] = "SUSPENSION"
            recompute_eligible_ad_count(campaign)
            touch(campaign)


def resume_account_cascade(account):
    for campaign in DB.campaigns.values():
        if (campaign["account_id"] == account["id"]
                and campaign["status"] == "PAUSED"
                and campaign["pause_origin"] == "SUSPENSION"):
            campaign["status"] = "ACTIVE"
            campaign["pause_origin"] = "NONE"
            recompute_eligible_ad_count(campaign)
            touch(campaign)


# ---------------------------------------------------------------------------
# Billing helpers
# ---------------------------------------------------------------------------

def profile_for_account(account_id):
    for p in DB.billing_profiles.values():
        if p["account_id"] == account_id:
            return p
    return None


def issue_invoice(profile, kind, gross_amount, overdelivery_credit=0):
    """Issue an invoice, applying pending credits first. Returns invoice or None.

    gross_amount: the unbilled amount being billed (before credits).
    """
    applied_pending = min(profile["pending_credit_cents"], gross_amount)
    profile["pending_credit_cents"] -= applied_pending
    after = gross_amount - applied_pending
    applied_overdelivery = min(overdelivery_credit, after)
    amount = after - applied_overdelivery
    if amount <= 0:
        return None
    now_s = CLOCK.now_iso()
    last_end = profile.get("_last_invoice_end") or profile["created_at"]
    inv = new_record({
        "billing_profile_id": profile["id"],
        "kind": kind,
        "period_start": last_end,
        "period_end": now_s,
        "amount_cents": amount,
        "overdelivery_credit_cents": applied_overdelivery,
        "invalid_click_credit_cents": applied_pending,
        "status": "ISSUED",
        "due_date": (CLOCK.today() + timedelta(days=14)).strftime("%Y-%m-%d"),
        "paid_cents": 0,
    })
    DB.invoices[inv["id"]] = inv
    profile["_last_invoice_end"] = now_s
    # mark all unbilled charged events of this account as billed
    account_id = profile["account_id"]
    for ev in DB.auction_events.values():
        if ev.get("_billed"):
            continue
        if ev["charged_cents"] <= 0:
            continue
        ev_account = event_account(ev)
        if ev_account and ev_account["id"] == account_id:
            ev["_billed"] = True
    return inv


def charge_click(account, campaign, charged):
    """Run the valid-click money pipeline (PRD 3.7). Assumes pacing passed."""
    # daily spend record
    day_key = (campaign["id"], CLOCK.today().strftime("%Y-%m-%d"))
    day = DB.daily_spend_records.get(day_key)
    if day is None:
        day = new_record({
            "campaign_id": campaign["id"],
            "spend_date": CLOCK.today().strftime("%Y-%m-%d"),
            "served_cents": 0,
            "click_count": 0,
        })
        DB.daily_spend_records[day_key] = day
    day["served_cents"] += charged
    day["click_count"] += 1
    touch(day)
    campaign["served_lifetime_cents"] += charged
    campaign["click_count_lifetime"] += 1
    touch(campaign)
    account["lifetime_valid_served_cents"] += charged
    touch(account)
    profile = profile_for_account(account["id"])
    if profile is not None:
        profile["unbilled_cost_cents"] += charged
        if profile["unbilled_cost_cents"] >= profile["billing_threshold_cents"]:
            gross = profile["unbilled_cost_cents"]
            inv = issue_invoice(profile, "THRESHOLD", gross)
            profile["unbilled_cost_cents"] = 0
        touch(profile)


def escalate_threshold(profile):
    ladder = THRESHOLD_LADDER
    cur = profile["billing_threshold_cents"]
    try:
        idx = ladder.index(cur)
    except ValueError:
        idx = -1
    if idx + 1 < len(ladder):
        profile["billing_threshold_cents"] = ladder[idx + 1]
    else:
        profile["billing_threshold_cents"] = ladder[-1]


# ---------------------------------------------------------------------------
# Keyword matching
# ---------------------------------------------------------------------------

def keyword_matches(kw, normalized_query):
    text = kw["normalized_text"]
    if kw["match_type"] == "EXACT":
        return text == normalized_query
    if kw["match_type"] == "PHRASE":
        return text in normalized_query
    # BROAD: every token of keyword appears among query tokens
    qtokens = set(normalized_query.split())
    return all(tok in qtokens for tok in text.split())


# ---------------------------------------------------------------------------
# Serializers (compute derived fields, strip internals)
# ---------------------------------------------------------------------------

PUBLIC_FIELDS = {
    "account": ["id", "business_name", "country_code", "status", "suspension_reason_code",
                "suspended_at", "upheld_appeal_count", "verified_business_name", "disclosure_text",
                "lifetime_valid_served_cents", "lifetime_billed_cents",
                "lifetime_overdelivery_credit_cents", "lifetime_invalid_click_credit_cents",
                "created_at", "updated_at", "version"],
    "verification": ["id", "account_id", "legal_business_name", "registration_number",
                     "document_type", "disclosure_consent", "status", "rejection_reason",
                     "supersedes_id", "created_at", "updated_at", "version"],
    "appeal": ["id", "account_id", "argument_text", "challenges_suspended_at", "status",
               "decided_at", "reviewer_note", "created_at", "updated_at", "version"],
    "billing_profile": ["id", "account_id", "payment_method_type", "currency_code",
                        "billing_threshold_cents", "unbilled_cost_cents", "pending_credit_cents",
                        "outstanding_balance_cents", "last_closed_month",
                        "created_at", "updated_at", "version"],
    "campaign": ["id", "account_id", "name", "daily_budget_cents", "start_date", "end_date",
                 "eligible_ad_count", "status", "pause_origin", "served_lifetime_cents",
                 "click_count_lifetime", "current_month_served_cents", "overdelivery_credit_cents",
                 "monthly_cap_provisional_cents", "last_closed_month_cap_cents",
                 "last_closed_month_credit_cents", "created_at", "updated_at", "version"],
    "ad_group": ["id", "campaign_id", "name", "created_at", "updated_at", "version"],
    "ad": ["id", "ad_group_id", "headline", "final_url", "category",
           "restricted_category_certified", "quality_ectr_score", "quality_relevance_score",
           "quality_lp_score", "quality_score_snapshot_centi", "status", "review_round",
           "created_at", "updated_at", "version"],
    "keyword": ["id", "ad_group_id", "text", "normalized_text", "match_type", "is_negative",
                "max_cpc_cents", "created_at", "updated_at", "version"],
    "policy_review": ["id", "ad_id", "round", "automated_verdict", "outcome", "reviewer_note",
                      "created_at", "updated_at", "version"],
    "auction_event": ["id", "query_text", "clicked", "is_invalid_click", "occurred_date",
                      "winner_ad_id", "winner_campaign_id", "winner_ad_rank",
                      "runner_up_ad_rank", "quality_score_final_centi", "charged_cents",
                      "created_at", "updated_at", "version"],
    "daily_spend_record": ["id", "campaign_id", "spend_date", "served_cents", "click_count",
                           "created_at", "updated_at", "version"],
    "invoice": ["id", "billing_profile_id", "kind", "period_start", "period_end", "amount_cents",
                "overdelivery_credit_cents", "invalid_click_credit_cents", "status", "due_date",
                "paid_cents", "created_at", "updated_at", "version"],
}


def serialize(kind, rec):
    out = {}
    if kind == "account":
        # lifetime_billed_cents: sum of current amount_cents over profile invoices
        profile = profile_for_account(rec["id"])
        billed = 0
        if profile:
            billed = sum(i["amount_cents"] for i in DB.invoices.values()
                         if i["billing_profile_id"] == profile["id"])
        rec["lifetime_billed_cents"] = billed
    elif kind == "billing_profile":
        rec["outstanding_balance_cents"] = sum(
            i["amount_cents"] - i["paid_cents"] for i in DB.invoices.values()
            if i["billing_profile_id"] == rec["id"])
    elif kind == "campaign":
        rec["monthly_cap_provisional_cents"] = rec["daily_budget_cents"] * 304 // 10
        month_prefix = CLOCK.today().strftime("%Y-%m")
        rec["current_month_served_cents"] = sum(
            d["served_cents"] for d in DB.daily_spend_records.values()
            if d["campaign_id"] == rec["id"] and d["spend_date"].startswith(month_prefix))
    for f in PUBLIC_FIELDS[kind]:
        out[f] = rec.get(f)
    return out
