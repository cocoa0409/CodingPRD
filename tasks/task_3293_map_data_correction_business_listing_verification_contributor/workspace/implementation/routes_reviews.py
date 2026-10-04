"""UserReview and ReviewFlag endpoints + fake-probability calculation."""
from datetime import timedelta
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from services_listings import create_grant
from validation import require_fields, require_enum, require_int, require_str, get_or_404

bp = Blueprint("reviews", __name__)

REASONS = {"FAKE", "CONFLICT_OF_INTEREST", "OFF_TOPIC", "HATE", "SPAM"}
READ_ROLES = {"PlatformAdmin", "Contributor", "BusinessOwner", "Moderator", "PolicyAnalyst"}
NONTERMINAL_REVIEW_STATES = {"PUBLISHED", "FLAGGED", "UNDER_MODERATION"}


def compute_fake_probability(review):
    c = store.contributors.get(review["contributor_id"])
    l = store.listings.get(review["listing_id"])
    now = clock.now()
    i1 = 0
    if c is not None:
        domain.recompute_trust(c, demote=False)
        if c["finalized_trust_score"] < 30:
            i1 = 1
    i2 = 0
    if c is not None and l is not None:
        region_id = l["region_id"]
        window_start = now - timedelta(hours=24)
        burst = 0
        for r in store.reviews.values():
            if r["id"] == review["id"]:
                continue
            if r["contributor_id"] != c["id"]:
                continue
            rl = store.listings.get(r["listing_id"])
            if rl is None or rl["region_id"] != region_id:
                continue
            if clock.parse(r["created_at"]) >= window_start:
                burst += 1
        if burst >= 3:
            i2 = 1
    i3 = 1 if len(review["text"]) < 20 else 0
    i4 = 0
    if c is not None:
        if clock.parse(c["created_at"]) > now - timedelta(days=7):
            i4 = 1
    prob = 0.10 * i1 + 0.25 * i2 + 0.30 * i3 + 0.35 * i4
    prob = max(0.0, min(1.0, prob))
    return domain.round_half_up_2(prob)


def auto_flag(review):
    flag = {
        "id": domain.new_id(),
        "review_id": review["id"],
        "reporter_contributor_id": None,
        "reporter_is_owner": False,
        "reason": "FAKE",
        "status": "OPEN",
        "created_at": clock.iso(clock.now()),
    }
    store.flags[flag["id"]] = flag
    if review["status"] == "PUBLISHED":
        review["status"] = "FLAGGED"
    domain.touch(review)
    l = store.listings.get(review["listing_id"])
    if l is not None:
        domain.recompute_listing(l)
    return flag


def recompute_flag_count(review):
    review["flag_count"] = sum(1 for f in store.flags.values()
                               if f["review_id"] == review["id"]
                               and f["status"] == "OPEN")


@bp.post("/v1/reviews")
def create_review():
    role, uid = require_roles({"Contributor", "BusinessOwner"})
    data = body()
    require_fields(data, ["listing_id", "contributor_id", "rating", "text"])
    l = store.listings.get(data["listing_id"])
    if l is None:
        raise_err("ERR_NOT_FOUND", "listing not found")
    c = store.contributors.get(data["contributor_id"])
    if c is None:
        raise_err("ERR_NOT_FOUND", "contributor not found")
    rating = require_int(data, "rating")
    if rating < 1 or rating > 5:
        raise_err("ERR_INVALID_REQUEST", "rating must be 1..5")
    text = require_str(data, "text", min_len=1, max_len=2000)
    if c["status"] != "ACTIVE":
        raise_err("ERR_CONTRIBUTOR_RESTRICTED", "contributor not ACTIVE")
    if l["status"] in ("SUSPENDED", "PERMANENTLY_CLOSED"):
        raise_err("ERR_LISTING_SUSPENDED", "listing not reviewable")
    for r in store.reviews.values():
        if r["listing_id"] == l["id"] and r["contributor_id"] == c["id"] \
                and r["status"] in NONTERMINAL_REVIEW_STATES:
            raise_err("ERR_DUPLICATE_SUBMISSION", "duplicate open review")

    now = clock.iso(clock.now())
    rec = {
        "id": domain.new_id(),
        "listing_id": l["id"],
        "contributor_id": c["id"],
        "rating": rating,
        "text": text,
        "status": "PUBLISHED",
        "fake_probability": 0.0,
        "flag_count": 0,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.reviews[rec["id"]] = rec
    # review grant with level-based multiplier
    domain.recompute_points(c)
    multiplier = domain.LEVEL_WEIGHTS[c["level"]]
    grant = create_grant(c["id"], "REVIEW", rec["id"], 2, multiplier)
    rec["_review_grant_id"] = grant["id"]
    domain.recompute_contributor(c, demote=True)

    prob = compute_fake_probability(rec)
    rec["fake_probability"] = prob
    domain.touch(rec)
    if prob >= 0.80:
        auto_flag(rec)
    domain.recompute_listing(l)
    return envelope(domain.review_view(rec), status=201)


@bp.get("/v1/reviews")
def list_reviews():
    require_roles(READ_ROLES)
    items = list(store.reviews.values())
    for f in ("listing_id", "contributor_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [r for r in items if r.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.review_view(r) for r in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/reviews/<rid>")
def get_review(rid):
    require_roles(READ_ROLES)
    r = get_or_404(store.reviews, rid)
    recompute_flag_count(r)
    return envelope(domain.review_view(r))


@bp.post("/v1/reviews/<rid>/flag")
def flag_review(rid):
    role, uid = require_roles({"Contributor", "BusinessOwner"})
    r = get_or_404(store.reviews, rid)
    data = body()
    reason = require_enum(data, "reason", REASONS)
    recompute_flag_count(r)
    if r["status"] not in ("PUBLISHED", "FLAGGED") or r["flag_count"] >= 5:
        raise_err("ERR_FLAG_LIMIT_REACHED", "review cannot be flagged")
    l = store.listings.get(r["listing_id"])
    reporter_is_owner = bool(l is not None and l.get("owner_contributor_id") == uid)
    flag = {
        "id": domain.new_id(),
        "review_id": r["id"],
        "reporter_contributor_id": uid,
        "reporter_is_owner": reporter_is_owner,
        "reason": reason,
        "status": "OPEN",
        "created_at": clock.iso(clock.now()),
    }
    store.flags[flag["id"]] = flag
    r["status"] = "FLAGGED"
    recompute_flag_count(r)
    domain.touch(r)
    return envelope(domain.flag_view(flag), status=201)


@bp.get("/v1/review-flags")
def list_flags():
    require_roles({"PlatformAdmin", "Moderator", "PolicyAnalyst"})
    items = list(store.flags.values())
    for f in ("review_id", "reporter_contributor_id", "status", "reason"):
        v = request.args.get(f)
        if v is not None:
            items = [fl for fl in items if fl.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.flag_view(f) for f in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/review-flags/<fid>")
def get_flag(fid):
    require_roles({"PlatformAdmin", "Moderator", "PolicyAnalyst"})
    f = get_or_404(store.flags, fid)
    return envelope(domain.flag_view(f))


@bp.get("/v1/review-flags/<fid>/review-tickets")
def flag_tickets(fid):
    require_roles({"PlatformAdmin", "Moderator"})
    get_or_404(store.flags, fid)
    items = [t for t in store.tickets.values() if t.get("review_flag_id") == fid]
    page, pg = paginate(items, request.args)
    return envelope([domain.ticket_view(t) for t in page],
                    response_type="array", pagination=pg)


@bp.post("/v1/review-flags/<fid>/dismiss")
def dismiss_flag(fid):
    require_roles({"Moderator"})
    f = get_or_404(store.flags, fid)
    if f["status"] != "OPEN":
        raise_err("ERR_INVALID_STATE", "flag not OPEN")
    f["status"] = "DISMISSED"
    r = store.reviews.get(f["review_id"])
    if r is not None:
        recompute_flag_count(r)
        if r["flag_count"] == 0 and r["status"] == "FLAGGED":
            r["status"] = "PUBLISHED"
        domain.touch(r)
        l = store.listings.get(r["listing_id"])
        if l is not None:
            domain.recompute_listing(l)
    return envelope(domain.flag_view(f))
