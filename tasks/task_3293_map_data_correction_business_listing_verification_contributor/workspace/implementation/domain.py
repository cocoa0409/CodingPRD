"""Domain helpers: recomputes, serializers, shared business rules."""
import uuid
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

import clock
import store
from errors import raise_err

LEVEL_WEIGHTS = {"NEWCOMER": 0.5, "REGULAR": 1.0, "TRUSTED": 1.5,
                 "EXPERT": 2.0, "MASTER": 2.5}

PROHIBITED_CATEGORIES = {"ESCORT", "WEAPONS", "ADULT"}
LISTING_CATEGORIES = {"RESTAURANT", "RETAIL", "SERVICE", "LODGING", "HEALTH"}

SERVICE_KEYWORDS = {
    "BEST", "CHEAP", "PIZZA", "NEAR", "ME", "TOP", "FREE", "DEAL", "DEALS",
    "DISCOUNT", "CHEAPEST", "GREATEST", "FINEST", "LOWEST", "HOTTEST",
    "OFFERS", "SALE", "DELIVERY", "OPEN", "NOW", "RESTAURANT", "SERVICE",
    "SERVICES", "SHOP", "STORE", "HOTEL", "REPAIR", "24/7",
}


def new_id():
    return str(uuid.uuid4())


def touch(rec, bump_version=True):
    rec["updated_at"] = clock.iso(clock.now())
    if bump_version and "version" in rec:
        rec["version"] += 1


# ---------------------------------------------------------------- keyword stuffing
def is_keyword_stuffed(name):
    """2+ consecutive uppercase keyword tokens from the service-keyword list."""
    if not isinstance(name, str):
        return False
    run = 0
    for tok in name.split():
        clean = "".join(ch for ch in tok if ch.isalpha())
        if clean and clean == clean.upper() and clean.upper() in SERVICE_KEYWORDS \
                and any(ch.isalpha() for ch in clean) and len(clean) >= 2:
            run += 1
            if run >= 2:
                return True
        else:
            run = 0
    return False


# ---------------------------------------------------------------- contributor aggregates
def round_half_up_int(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2(x):
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def contributor_grants(cid):
    return [g for g in store.grants.values() if g["contributor_id"] == cid]


def recompute_points(c):
    grants = contributor_grants(c["id"])
    total = sum(g["points"] for g in grants if g["status"] == "POSTED")
    lifetime = sum(g["points"] for g in grants)
    c["total_points"] = total
    c["lifetime_points"] = lifetime
    if total < 50:
        level = "NEWCOMER"
    elif total < 250:
        level = "REGULAR"
    elif total < 1000:
        level = "TRUSTED"
    elif total < 5000:
        level = "EXPERT"
    else:
        level = "MASTER"
    c["level"] = level
    return level


def _trust(c, finalized):
    now = clock.now()
    edits = [e for e in store.edits.values() if e["contributor_id"] == c["id"]]
    if finalized:
        cutoff = now - timedelta(days=7)
        edits = [e for e in edits if clock.parse(e["created_at"]) <= cutoff]
    p = sum(1 for e in edits if e["status"] == "PUBLISHED")
    r = sum(1 for e in edits if e["status"] == "REJECTED")
    v = sum(1 for e in edits if e["status"] == "REVERTED")
    base = 50 + 3 * p - 6 * r - 9 * v
    closed = any(l for l in store.listings.values()
                 if l.get("owner_contributor_id") == c["id"]
                 and l["status"] == "PERMANENTLY_CLOSED")
    if closed:
        base -= 25
    return max(0, min(100, int(base)))


def recompute_trust(c, demote=True):
    c["provisional_trust_score"] = _trust(c, finalized=False)
    c["finalized_trust_score"] = _trust(c, finalized=True)
    if demote and c["finalized_trust_score"] < 20 and c["status"] == "ACTIVE":
        c["status"] = "RESTRICTED"
        touch(c)
    return c


def recompute_contributor(c, demote=True):
    recompute_points(c)
    recompute_trust(c, demote=demote)
    fc = sum(1 for a in store.attempts.values()
             if a["status"] == "FAILED"
             and store.listings.get(a["listing_id"], {}).get("owner_contributor_id") == c["id"])
    c["failed_verification_count"] = fc
    return c


# ---------------------------------------------------------------- listing aggregates
def listing_reviews(lid):
    return [r for r in store.reviews.values() if r["listing_id"] == lid]


def recompute_listing(l):
    lid = l["id"]
    reviews = listing_reviews(lid)
    published = [r for r in reviews if r["status"] == "PUBLISHED"]
    under_mod = [r for r in reviews if r["status"] == "UNDER_MODERATION"]
    l["review_count"] = len(published)
    if published:
        avg = sum(r["rating"] for r in published) / len(published)
        l["rating_avg"] = round_half_up_2(avg)
    else:
        l["rating_avg"] = 0.0

    now = clock.now()
    window_start = now - timedelta(days=30)
    edits = [e for e in store.edits.values() if e["listing_id"] == lid]
    windowed = [e for e in edits if clock.parse(e["created_at"]) >= window_start
                and clock.parse(e["created_at"]) <= now]
    p_w = sum(1 for e in windowed if e["status"] == "PUBLISHED")
    v_w = sum(1 for e in windowed if e["status"] == "REVERTED")
    revert_rate = v_w / max(1, p_w + v_w)

    accepted = sum(1 for e in edits if e["status"] == "PUBLISHED")
    l["accepted_edit_count"] = accepted

    is_suspended = 1 if l["status"] == "SUSPENDED" else 0

    def health(rating_avg_used):
        h = (50 + 4 * rating_avg_used
             + 2 * min(accepted, 10)
             - 40 * revert_rate - 5 * is_suspended)
        h = round_half_up_2(h)
        return max(0.0, min(100.0, h))

    l["health_score"] = health(l["rating_avg"])

    denom = len(published) + 0.5 * len(under_mod)
    if denom > 0:
        numer = sum(r["rating"] for r in published) + 0.5 * sum(r["rating"] for r in under_mod)
        mod_avg = numer / denom
    else:
        mod_avg = 0.0
    l["moderation_health_score"] = health(mod_avg)

    if l["status"] in ("SUSPENDED", "PERMANENTLY_CLOSED"):
        l["visibility"] = "HIDDEN"
    elif l["health_score"] < 30:
        l["visibility"] = "RESTRICTED"
    else:
        l["visibility"] = "PUBLIC"
    return l


# ---------------------------------------------------------------- region posture
def recompute_region(rg):
    tasks = [t for t in store.imagery.values() if t["region_id"] == rg["id"]]
    pending = sum(1 for t in tasks
                  if t["status"] in ("CAPTURED", "BLUR_PENDING", "REPROCESS"))
    rg["privacy_pending_count"] = pending
    if rg.get("frozen"):
        rg["posture"] = "FROZEN"
    elif pending > 0:
        rg["posture"] = "CLEARANCE_PENDING"
    elif any(t.get("capture_media_count", 0) > 0 for t in tasks):
        rg["posture"] = "CLEAR"
    else:
        rg["posture"] = "ACTIVE"
    return rg


# ---------------------------------------------------------------- serializers
def region_view(rg):
    recompute_region(rg)
    return dict(rg)


def contributor_view(c):
    recompute_contributor(c, demote=False)
    return dict(c)


def listing_view(l):
    recompute_listing(l)
    return _clean(l)


def flag_view(f):
    return dict(f)


def grant_view(g):
    return dict(g)


def hours_view(h):
    return _clean(h)


def attempt_view(a):
    return dict(a)


def _clean(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def edit_view(e):
    return _clean(e)


def ticket_view(t):
    return dict(t)


def review_view(r):
    return _clean(r)


def case_view(c):
    return {k: v for k, v in c.items() if k != "suspended_by"}


def imagery_view(t):
    return dict(t)


def routing_view(u):
    return dict(u)
