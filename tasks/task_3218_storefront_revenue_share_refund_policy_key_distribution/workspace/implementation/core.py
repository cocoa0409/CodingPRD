"""Core shared state, logical clock, helpers, and business-rule services for
the Storefront Revenue Share / Refund / Key Distribution API (task 3218).

Storage is in-memory only: plain dicts keyed by id, fresh on every boot.
"""

import math
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps

from flask import g, request


# ==========================================================================
# In-memory store — fresh per process; no persistence by design.
# ==========================================================================
STORE = {
    "developer_accounts": {},
    "titles": {},
    "store_page_reviews": {},
    "regional_prices": {},
    "key_batches": {},
    "keys": {},
    "user_accounts": {},
    "purchases": {},
    "refund_requests": {},
    "reviews": {},
    "review_bomb_windows": {},
    "workshop_items": {},
    "workshop_sales": {},
}

_SEQ = [0]
_CLOCK = {"now": datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)}

# ==========================================================================
# Constants (PRD §3 / scaffold §1.3)
# ==========================================================================
FX = {
    "EUR": Decimal("0.92"),
    "GBP": Decimal("0.79"),
    "JPY": Decimal("149.50"),
    "BRL": Decimal("5.05"),
}
PPP = {
    "EUR": Decimal("0.90"),
    "GBP": Decimal("0.95"),
    "JPY": Decimal("0.70"),
    "BRL": Decimal("0.50"),
}
OVERRIDE_CURRENCIES = ("EUR", "GBP", "JPY", "BRL")
PURCHASE_CURRENCIES = ("USD", "EUR", "GBP", "JPY", "BRL")
TIER_RATES = {1: Decimal("0.30"), 2: Decimal("0.25"), 3: Decimal("0.20")}
TIER2_THRESHOLD = 1_000_000_000   # $10,000,000 in cents
TIER3_THRESHOLD = 5_000_000_000   # $50,000,000 in cents
MAX_DEVIATION_BPS = 2500
FREE_KEY_BASE = 5000
PLAYTIME_LIMIT = 120
PURCHASE_AGE_LIMIT = timedelta(days=14)
ABUSE_WINDOW = timedelta(days=60)
RESTRICT_THRESHOLD = 3
OVER_LIMIT_PENALTY = 3
BOMB_MIN_COUNT = 10
BOMB_WINDOW = timedelta(days=7)
DETECTION_WINDOW = timedelta(hours=24)
RECENT_WINDOW = timedelta(days=30)
REDEEM_ACCOUNT_LIMIT = 3
REDEEM_GLOBAL_LIMIT = 50
REDEEM_WINDOW = timedelta(minutes=60)

VALID_ROLES = ("PlatformOps", "Developer", "StoreReviewer", "TrustSafety", "User", "Anonymous")


# ==========================================================================
# Errors
# ==========================================================================
class ApiError(Exception):
    def __init__(self, error_id, status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.status = status
        self.message = message or error_id


def err_unauthenticated(msg="Missing or malformed X-User-ID / X-User-Role"):
    raise ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg="Role not permitted for endpoint"):
    raise ApiError("ERR_FORBIDDEN", 403, msg)


def err_not_found(msg="Referenced id does not exist"):
    raise ApiError("ERR_NOT_FOUND", 404, msg)


def err_not_owner(msg="Caller does not own the target resource"):
    raise ApiError("ERR_NOT_OWNER", 403, msg)


def err_invalid_state(msg="Transition not defined from current state"):
    raise ApiError("ERR_INVALID_STATE", 409, msg)


def err_stale_version(msg="expected_title_version mismatch"):
    raise ApiError("ERR_STALE_VERSION", 412, msg)


def err_invalid_request(msg="Missing/invalid required field"):
    raise ApiError("ERR_INVALID_REQUEST", 400, msg)


# ==========================================================================
# Logical clock
# ==========================================================================
def get_now():
    return _CLOCK["now"]


def set_now(dt):
    _CLOCK["now"] = dt


def iso(dt):
    """ISO 8601 UTC with three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 datetime; raise ValueError on malformed input."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ==========================================================================
# Numeric helpers
# ==========================================================================
def rhu(dec):
    """Round-half-up a Decimal to an integer minor unit."""
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def recommended_price_cents(base_usd_cents, currency):
    return rhu(Decimal(base_usd_cents) * FX[currency] * PPP[currency])


# ==========================================================================
# Record plumbing
# ==========================================================================
def next_seq():
    _SEQ[0] += 1
    return _SEQ[0]


def new_id():
    return uuid.uuid4().hex


def new_req_id():
    return "req_" + uuid.uuid4().hex[:22]


def new_record(coll, fields):
    now = iso(get_now())
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }
    rec.update(fields)
    STORE[coll][rec["id"]] = rec
    return rec


def touch(rec):
    rec["updated_at"] = iso(get_now())
    rec["version"] += 1


def pub(rec):
    """Public view: strip internal keys."""
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def get_or_404(coll, rec_id, msg="Referenced id does not exist"):
    if not isinstance(rec_id, str):
        err_not_found(msg)
    rec = STORE[coll].get(rec_id)
    if rec is None:
        err_not_found(msg)
    return rec


# ==========================================================================
# Auth / roles
# ==========================================================================
def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or not isinstance(uid, str) or not uid.strip():
        err_unauthenticated()
    if role is None or role not in VALID_ROLES:
        err_unauthenticated()
    g.user_id = uid
    g.role = role


def roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.role not in allowed:
                err_forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco


def check_dev_owner(dev_account_id):
    """Ownership for entity-backed Developer callers (priority 4)."""
    if g.role == "Developer" and g.user_id != dev_account_id:
        err_not_owner()


def check_user_owner(user_account_id):
    """Ownership for entity-backed User callers (priority 4)."""
    if g.role == "User" and g.user_id != user_account_id:
        err_not_owner()


# ==========================================================================
# Request body / pagination helpers
# ==========================================================================
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err_invalid_request("Request body must be a JSON object")
    return data


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        err_invalid_request("Field '%s' is required and must be a non-empty string" % field)
    return v


def pagination_params():
    raw_limit = request.args.get("limit", "10")
    raw_offset = request.args.get("offset", "0")
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        err_invalid_request("Invalid pagination parameters")
    if str(raw_limit).strip() != str(limit) or str(raw_offset).strip() != str(offset):
        # reject things like "1.5" that int() would not accept anyway; keep simple
        pass
    if limit < 1 or limit > 100 or offset < 0:
        err_invalid_request("Pagination out of range (limit 1..100, offset >= 0)")
    return limit, offset


def parse_bool_param(name):
    v = request.args.get(name)
    if v is None:
        return None
    if v == "true":
        return True
    if v == "false":
        return False
    err_invalid_request("Invalid boolean query parameter '%s'" % name)


def list_page(items):
    """Sort by insertion order (created_at ascending), paginate, return page+meta."""
    items = sorted(items, key=lambda r: r["_seq"])
    limit, offset = pagination_params()
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


# ==========================================================================
# Entity graph helpers
# ==========================================================================
def developer_of_title(title):
    return STORE["developer_accounts"].get(title["developer_account_id"])


def title_of_key(key):
    batch = STORE["key_batches"].get(key["batch_id"])
    if batch is None:
        return None
    return STORE["titles"].get(batch["title_id"])


def maybe_auto_release(title):
    """Lazy auto-release: a RELEASE_SCHEDULED title whose instant has been
    reached releases on any read/action."""
    if title["status"] == "RELEASE_SCHEDULED" and title["scheduled_release_at"]:
        if parse_dt(title["scheduled_release_at"]) <= get_now():
            title["status"] = "RELEASED"
            title["released_at"] = title["scheduled_release_at"]
            touch(title)


# ==========================================================================
# Revenue share / ledger recomputes
# ==========================================================================
def recompute_tier(title):
    r = title["lifetime_recognized_revenue_usd_cents"]
    if r >= TIER3_THRESHOLD:
        title["current_tier"] = 3
    elif r >= TIER2_THRESHOLD:
        title["current_tier"] = 2
    else:
        title["current_tier"] = 1


def completed_sales_count(title_id):
    return sum(
        1
        for p in STORE["purchases"].values()
        if p["title_id"] == title_id and p["status"] in ("COMPLETED", "PARTIALLY_REFUNDED")
    )


def recompute_refund_abuse_flag(title):
    sales = completed_sales_count(title["id"])
    events = title["lifetime_refund_events"]
    title["refund_abuse_flag"] = events > 0 and events * 10 > 3 * sales


# ==========================================================================
# Review scoring / bomb windows
# ==========================================================================
def review_weight(review):
    return max(1, math.isqrt(max(0, review["author_playtime_minutes"])))


def reviews_of_title(title_id):
    return [r for r in STORE["reviews"].values() if r["title_id"] == title_id]


def active_windows_of_title(title_id):
    return [
        w for w in STORE["review_bomb_windows"].values()
        if w["title_id"] == title_id and w["status"] == "ACTIVE"
    ]


def window_covers(window, dt):
    return parse_dt(window["start_at"]) <= dt < parse_dt(window["end_at"])


def window_covers_review(window, review):
    """Coverage at the PRD's tie-aware granularity: created_at within
    [start_at, end_at), and — when the review shares start_at's instant —
    not created strictly before the review that defines start_at (PRD §3.7
    "earliest first on ties" is read in creation order)."""
    created = parse_dt(review["created_at"])
    if not window_covers(window, created):
        return False
    boundary = window.get("_start_seq")
    if boundary is not None and created == parse_dt(window["start_at"]):
        return review["_seq"] >= boundary
    return True


def refresh_bomb_flag(title):
    now = get_now()
    title["review_bomb_flag"] = any(
        window_covers(w, now) for w in active_windows_of_title(title["id"])
    )


def refresh_off_topic(title):
    """off_topic == review created inside any ACTIVE window's coverage."""
    windows = active_windows_of_title(title["id"])
    for r in reviews_of_title(title["id"]):
        r["off_topic"] = any(window_covers_review(w, r) for w in windows)


def recompute_review_stats(title):
    now = get_now()
    included = [
        r for r in reviews_of_title(title["id"])
        if r["status"] == "PUBLISHED" and not r["off_topic"]
    ]
    if included:
        total_w = sum(review_weight(r) for r in included)
        pos_w = sum(review_weight(r) for r in included if r["is_positive"])
        title["review_score_bps"] = rhu(Decimal(10000 * pos_w) / Decimal(total_w))
    else:
        title["review_score_bps"] = None
    window_start = now - RECENT_WINDOW
    recent = [
        r for r in included
        if window_start < parse_dt(r["created_at"]) <= now
    ]
    if recent:
        total_w = sum(review_weight(r) for r in recent)
        pos_w = sum(review_weight(r) for r in recent if r["is_positive"])
        # exact rational comparisons: share >= 0.70 / 0.40
        if pos_w * 100 >= total_w * 70:
            title["recent_review_summary"] = "MOSTLY_POSITIVE"
        elif pos_w * 100 >= total_w * 40:
            title["recent_review_summary"] = "MIXED"
        else:
            title["recent_review_summary"] = "MOSTLY_NEGATIVE"
    else:
        title["recent_review_summary"] = None


def run_bomb_detection(title, triggering_review_id=None):
    """Rolling detection on every review creation (PRD §3.7)."""
    now = get_now()
    window_start = now - DETECTION_WINDOW
    recent_pub = [
        r for r in reviews_of_title(title["id"])
        if r["status"] == "PUBLISHED" and window_start < parse_dt(r["created_at"]) <= now
    ]
    negatives = [r for r in recent_pub if not r["is_positive"]]
    total = len(recent_pub)
    if len(negatives) >= BOMB_MIN_COUNT and len(negatives) * 5 >= total * 4:
        actives = active_windows_of_title(title["id"])
        if actives:
            # second trigger while one is ACTIVE extends the existing window
            w = sorted(actives, key=lambda x: x["_seq"])[0]
            w["end_at"] = iso(now + BOMB_WINDOW)
            touch(w)
            refresh_off_topic(title)
        else:
            oldest = min(negatives, key=lambda r: (parse_dt(r["created_at"]), r["_seq"]))
            win = new_record("review_bomb_windows", {
                "title_id": title["id"],
                "start_at": oldest["created_at"],
                "end_at": iso(now + BOMB_WINDOW),
                "status": "ACTIVE",
                "trigger_review_count": len(negatives),
            })
            win["_start_seq"] = oldest["_seq"]
            refresh_off_topic(title)
    refresh_bomb_flag(title)
    recompute_review_stats(title)


# ==========================================================================
# Refund abuse scoring
# ==========================================================================
def bump_abuse_score(user, delta):
    user["refund_abuse_score"] = max(0, user["refund_abuse_score"] + delta)
    if user["refund_abuse_score"] > RESTRICT_THRESHOLD and user["status"] == "ACTIVE":
        user["status"] = "RESTRICTED"
        user["refund_restricted"] = True


def recompute_abuse_score(user):
    """Rolling 60-day window recompute (used on unrestrict)."""
    now = get_now()
    start = now - ABUSE_WINDOW
    score = 0
    for rr in STORE["refund_requests"].values():
        if rr["user_account_id"] != user["id"] or rr["status"] != "APPROVED":
            continue
        if rr["decided_at"] is None:
            continue
        decided = parse_dt(rr["decided_at"])
        if not (start <= decided <= now):
            continue
        purchase = STORE["purchases"].get(rr["purchase_id"])
        score += 1
        if purchase is not None and purchase["playtime_minutes"] >= PLAYTIME_LIMIT:
            score += OVER_LIMIT_PENALTY
    for p in STORE["purchases"].values():
        if p["user_account_id"] != user["id"]:
            continue
        purchased = parse_dt(p["purchased_at"])
        if start <= purchased <= now:
            score -= 1
    user["refund_abuse_score"] = max(0, score)


# ==========================================================================
# Refund cascade (shared by auto-approval and manual approve)
# ==========================================================================
def apply_refund_cascade(purchase, approved_amount):
    purchase["refunded_cents"] += approved_amount
    cur = purchase["currency"]
    if cur == "USD":
        usd_delta = approved_amount
    else:
        usd_delta = rhu(Decimal(approved_amount) / FX[cur])
    purchase["refunded_amount_usd_cents"] += usd_delta
    if purchase["refunded_cents"] >= purchase["gross_price_cents"]:
        purchase["status"] = "REFUNDED"
    else:
        purchase["status"] = "PARTIALLY_REFUNDED"
    touch(purchase)

    title = STORE["titles"][purchase["title_id"]]
    title["lifetime_recognized_revenue_usd_cents"] -= usd_delta
    title["lifetime_refund_events"] += 1
    recompute_tier(title)
    recompute_refund_abuse_flag(title)
    touch(title)

    user = STORE["user_accounts"][purchase["user_account_id"]]
    delta = 1 + (OVER_LIMIT_PENALTY if purchase["playtime_minutes"] >= PLAYTIME_LIMIT else 0)
    bump_abuse_score(user, delta)
    touch(user)


# ==========================================================================
# Key cascades
# ==========================================================================
def revoke_unused_keys_for_title(title_id):
    for key in STORE["keys"].values():
        if key["status"] != "UNUSED":
            continue
        t = title_of_key(key)
        if t is not None and t["id"] == title_id:
            key["status"] = "REVOKED"
            touch(key)


def revoke_unused_keys_for_developer(dev_account_id):
    for key in STORE["keys"].values():
        if key["status"] != "UNUSED":
            continue
        t = title_of_key(key)
        if t is not None and t["developer_account_id"] == dev_account_id:
            key["status"] = "REVOKED"
            touch(key)


# ==========================================================================
# Serializers (resolve computed fields on read)
# ==========================================================================
def serialize_title(title):
    maybe_auto_release(title)
    refresh_bomb_flag(title)
    return pub(title)


def serialize(rec):
    return pub(rec)
