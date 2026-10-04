"""Routes: ads, policy reviews, keywords."""
from flask import Blueprint, request
from core import (DB, ok, paginate, err, new_record, touch, authenticate,
                  require_role, check_ownership, normalize_text)
from services import (serialize, RESTRICTED_CATEGORIES, recompute_eligible_ad_count,
                      on_ad_became_eligible, on_ad_disapproved)

bp = Blueprint("ads", __name__)

CATEGORIES = {"GENERAL", "ALCOHOL", "GAMBLING", "HEALTHCARE", "FINANCIAL"}
MATCH_TYPES = {"EXACT", "PHRASE", "BROAD"}


def get_adgroup_or_404(ag_id):
    ag = DB.ad_groups.get(ag_id)
    if ag is None:
        err("ERR_NOT_FOUND", "AdGroup not found")
    return ag


def get_ad_or_404(ad_id):
    a = DB.ads.get(ad_id)
    if a is None:
        err("ERR_NOT_FOUND", "Ad not found")
    return a


def get_review_or_404(r_id):
    r = DB.policy_reviews.get(r_id)
    if r is None:
        err("ERR_NOT_FOUND", "PolicyReview not found")
    return r


def account_id_for_adgroup(ag):
    c = DB.campaigns.get(ag["campaign_id"])
    return c["account_id"] if c else None


def account_id_for_ad(ad):
    ag = DB.ad_groups.get(ad["ad_group_id"])
    return account_id_for_adgroup(ag) if ag else None


def _valid_score(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 10


# ---------------------------------------------------------------------------
# Ads
# ---------------------------------------------------------------------------

@bp.post("/ad-groups/<ad_group_id>/ads")
def create_ad(ad_group_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    ag = get_adgroup_or_404(ad_group_id)
    check_ownership(caller, account_id_for_adgroup(ag))
    body = request.get_json(silent=True) or {}
    headline = body.get("headline")
    final_url = body.get("final_url")
    category = body.get("category")
    certified = body.get("restricted_category_certified", False)
    ectr = body.get("quality_ectr_score")
    rel = body.get("quality_relevance_score")
    lp = body.get("quality_lp_score")
    if not isinstance(headline, str) or not headline:
        err("ERR_VALIDATION", "headline required")
    if not isinstance(final_url, str) or not final_url:
        err("ERR_VALIDATION", "final_url required")
    if category not in CATEGORIES:
        err("ERR_VALIDATION", "category invalid")
    if not isinstance(certified, bool):
        err("ERR_VALIDATION", "restricted_category_certified must be boolean")
    if not _valid_score(ectr) or not _valid_score(rel) or not _valid_score(lp):
        err("ERR_VALIDATION", "quality scores must be integers 1..10")
    # restricted-category certification (priority 7)
    if category in RESTRICTED_CATEGORIES and not certified:
        err("ERR_RESTRICTED_CATEGORY_UNCERTIFIED", "Restricted category ad requires certification")
    # headline uniqueness (case-insensitive) (priority 8)
    for a in DB.ads.values():
        if a["ad_group_id"] == ad_group_id and a["headline"].lower() == headline.lower():
            err("ERR_DUPLICATE_AD_HEADLINE", "Headline already exists in this ad group")
    ad = new_record({
        "ad_group_id": ad_group_id,
        "headline": headline,
        "final_url": final_url,
        "category": category,
        "restricted_category_certified": certified,
        "quality_ectr_score": ectr,
        "quality_relevance_score": rel,
        "quality_lp_score": lp,
        "quality_score_snapshot_centi": None,
        "status": "DRAFT",
        "review_round": 0,
    })
    DB.ads[ad["id"]] = ad
    return ok(serialize("ad", ad), 201)


@bp.get("/ad-groups/<ad_group_id>/ads")
def list_ads(ad_group_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PolicyReviewer", "PlatformAdmin")
    ag = get_adgroup_or_404(ad_group_id)
    check_ownership(caller, account_id_for_adgroup(ag))
    items = [a for a in DB.ads.values() if a["ad_group_id"] == ad_group_id]
    items.sort(key=lambda a: (a["created_at"], a.get("_seq", 0), a["id"]))
    page, meta = paginate(items)
    return ok([serialize("ad", a) for a in page], 200, meta)


@bp.get("/ads/<ad_id>")
def get_ad(ad_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PolicyReviewer", "PlatformAdmin")
    ad = get_ad_or_404(ad_id)
    check_ownership(caller, account_id_for_ad(ad))
    return ok(serialize("ad", ad), 200)


@bp.put("/ads/<ad_id>")
def update_ad(ad_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    ad = get_ad_or_404(ad_id)
    check_ownership(caller, account_id_for_ad(ad))
    body = request.get_json(silent=True) or {}
    new_headline = body.get("headline", None)
    new_url = body.get("final_url", None)
    new_ectr = body.get("quality_ectr_score", None)
    new_rel = body.get("quality_relevance_score", None)
    new_lp = body.get("quality_lp_score", None)
    if new_headline is not None and (not isinstance(new_headline, str) or not new_headline):
        err("ERR_VALIDATION", "headline must be a non-empty string")
    if new_url is not None and (not isinstance(new_url, str) or not new_url):
        err("ERR_VALIDATION", "final_url must be a non-empty string")
    for v in (new_ectr, new_rel, new_lp):
        if v is not None and not _valid_score(v):
            err("ERR_VALIDATION", "quality scores must be integers 1..10")
    content_changed = False
    if new_headline is not None and new_headline != ad["headline"]:
        # uniqueness check
        for a in DB.ads.values():
            if (a["ad_group_id"] == ad["ad_group_id"] and a["id"] != ad["id"]
                    and a["headline"].lower() == new_headline.lower()):
                err("ERR_DUPLICATE_AD_HEADLINE", "Headline already exists in this ad group")
        ad["headline"] = new_headline
        content_changed = True
    if new_url is not None and new_url != ad["final_url"]:
        ad["final_url"] = new_url
        content_changed = True
    if new_ectr is not None:
        ad["quality_ectr_score"] = new_ectr
    if new_rel is not None:
        ad["quality_relevance_score"] = new_rel
    if new_lp is not None:
        ad["quality_lp_score"] = new_lp
    if content_changed and ad["status"] in ("ELIGIBLE", "DISAPPROVED"):
        was_eligible = ad["status"] == "ELIGIBLE"
        ad["status"] = "DRAFT"
        if was_eligible:
            campaign = None
            ag = DB.ad_groups.get(ad["ad_group_id"])
            if ag:
                campaign = DB.campaigns.get(ag["campaign_id"])
            if campaign is not None:
                recompute_eligible_ad_count(campaign)
                touch(campaign)
    touch(ad)
    return ok(serialize("ad", ad), 200)


@bp.post("/ads/<ad_id>/submit-review")
def submit_review(ad_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    ad = get_ad_or_404(ad_id)
    check_ownership(caller, account_id_for_ad(ad))
    if ad["status"] != "DRAFT":
        err("ERR_INVALID_STATE", "Only a DRAFT ad can be submitted for review")
    ad["status"] = "UNDER_REVIEW"
    ad["review_round"] = ad.get("review_round", 0) + 1
    touch(ad)
    automated = "CLEAN" if ad["category"] == "GENERAL" else "FLAGGED_RESTRICTED"
    outcome = "AUTO_APPROVED" if automated == "CLEAN" else "NEEDS_HUMAN"
    review = new_record({
        "ad_id": ad["id"],
        "round": ad["review_round"],
        "automated_verdict": automated,
        "outcome": outcome,
        "reviewer_note": None,
    })
    DB.policy_reviews[review["id"]] = review
    if automated == "CLEAN":
        ad["status"] = "ELIGIBLE"
        touch(ad)
        on_ad_became_eligible(ad)
    return ok(serialize("policy_review", review), 200)


@bp.get("/ads/<ad_id>/policy-reviews")
def list_reviews(ad_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PolicyReviewer", "PlatformAdmin")
    ad = get_ad_or_404(ad_id)
    check_ownership(caller, account_id_for_ad(ad))
    items = [r for r in DB.policy_reviews.values() if r["ad_id"] == ad_id]
    items.sort(key=lambda r: (r["created_at"], r.get("_seq", 0), r["id"]))
    page, meta = paginate(items)
    return ok([serialize("policy_review", r) for r in page], 200, meta)


@bp.get("/ads/<ad_id>/auction-events")
def list_ad_auction_events(ad_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    ad = get_ad_or_404(ad_id)
    check_ownership(caller, account_id_for_ad(ad))
    items = [e for e in DB.auction_events.values() if e["winner_ad_id"] == ad_id]
    items.sort(key=lambda e: (e["created_at"], e.get("_seq", 0), e["id"]))
    page, meta = paginate(items)
    return ok([serialize("auction_event", e) for e in page], 200, meta)


@bp.post("/policy-reviews/<review_id>/decide")
def decide_review(review_id):
    caller = authenticate()
    require_role(caller, "PolicyReviewer")
    review = get_review_or_404(review_id)
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    note = body.get("reviewer_note")
    if outcome not in ("HUMAN_APPROVED", "HUMAN_VIOLATION"):
        err("ERR_VALIDATION", "outcome must be HUMAN_APPROVED or HUMAN_VIOLATION")
    if review["outcome"] != "NEEDS_HUMAN":
        err("ERR_INVALID_STATE", "Review already decided or not awaiting human")
    ad = DB.ads.get(review["ad_id"])
    if outcome == "HUMAN_APPROVED":
        if ad is not None and ad["category"] in RESTRICTED_CATEGORIES \
                and not ad.get("restricted_category_certified", False):
            err("ERR_RESTRICTED_CATEGORY_UNCERTIFIED",
                "Restricted category ad requires certification for approval")
        review["outcome"] = "HUMAN_APPROVED"
        if isinstance(note, str):
            review["reviewer_note"] = note
        touch(review)
        if ad is not None:
            ad["status"] = "ELIGIBLE"
            touch(ad)
            on_ad_became_eligible(ad)
    else:
        review["outcome"] = "HUMAN_VIOLATION"
        if isinstance(note, str):
            review["reviewer_note"] = note
        touch(review)
        if ad is not None:
            ad["status"] = "DISAPPROVED"
            touch(ad)
            on_ad_disapproved(ad)
    return ok(serialize("policy_review", review), 200)


# ---------------------------------------------------------------------------
# Keywords
# ---------------------------------------------------------------------------

def _match(kw_norm, match_type, query_norm):
    if match_type == "EXACT":
        return kw_norm == query_norm
    if match_type == "PHRASE":
        return kw_norm in query_norm
    qtokens = set(query_norm.split())
    return all(t in qtokens for t in kw_norm.split())


@bp.post("/ad-groups/<ad_group_id>/keywords")
def create_keyword(ad_group_id):
    caller = authenticate()
    require_role(caller, "Advertiser")
    ag = get_adgroup_or_404(ad_group_id)
    check_ownership(caller, account_id_for_adgroup(ag))
    body = request.get_json(silent=True) or {}
    text = body.get("text")
    match_type = body.get("match_type")
    is_negative = body.get("is_negative", False)
    max_cpc = body.get("max_cpc_cents", None)
    if not isinstance(text, str) or not text:
        err("ERR_VALIDATION", "text required")
    if match_type not in MATCH_TYPES:
        err("ERR_VALIDATION", "match_type invalid")
    if not isinstance(is_negative, bool):
        err("ERR_VALIDATION", "is_negative must be boolean")
    if is_negative:
        if max_cpc is not None:
            err("ERR_VALIDATION", "negative keyword must not carry max_cpc_cents")
    else:
        if not isinstance(max_cpc, int) or isinstance(max_cpc, bool) or max_cpc <= 0:
            err("ERR_VALIDATION", "max_cpc_cents required and must be > 0 for non-negative keywords")
    norm = normalize_text(text)
    # uniqueness
    for k in DB.keywords.values():
        if (k["ad_group_id"] == ad_group_id and k["normalized_text"] == norm
                and k["match_type"] == match_type and k["is_negative"] == is_negative):
            err("ERR_DUPLICATE_KEYWORD", "Keyword already exists")
    # negative-keyword conflict: the negative keyword must not block the canonical
    # query of any keyword in the same ad group (existing or the new one itself).
    group_kws = [k for k in DB.keywords.values() if k["ad_group_id"] == ad_group_id]
    if is_negative:
        for k in group_kws:
            if not k["is_negative"]:
                if _match(norm, match_type, k["normalized_text"]):
                    err("ERR_NEGATIVE_KEYWORD_CONFLICT",
                        "Negative keyword blocks an existing keyword's canonical query")
    else:
        for k in group_kws:
            if k["is_negative"]:
                if _match(k["normalized_text"], k["match_type"], norm):
                    err("ERR_NEGATIVE_KEYWORD_CONFLICT",
                        "A negative keyword already blocks this keyword's canonical query")
    kw = new_record({
        "ad_group_id": ad_group_id,
        "text": text,
        "normalized_text": norm,
        "match_type": match_type,
        "is_negative": is_negative,
        "max_cpc_cents": max_cpc if not is_negative else None,
    })
    DB.keywords[kw["id"]] = kw
    return ok(serialize("keyword", kw), 201)


@bp.get("/ad-groups/<ad_group_id>/keywords")
def list_keywords(ad_group_id):
    caller = authenticate()
    require_role(caller, "Advertiser", "PlatformAdmin")
    ag = get_adgroup_or_404(ad_group_id)
    check_ownership(caller, account_id_for_adgroup(ag))
    items = [k for k in DB.keywords.values() if k["ad_group_id"] == ad_group_id]
    neg_filter = request.args.get("is_negative")
    if neg_filter is not None:
        if neg_filter.lower() == "true":
            items = [k for k in items if k["is_negative"]]
        elif neg_filter.lower() == "false":
            items = [k for k in items if not k["is_negative"]]
    items.sort(key=lambda k: (k["created_at"], k.get("_seq", 0), k["id"]))
    page, meta = paginate(items)
    return ok([serialize("keyword", k) for k in page], 200, meta)
