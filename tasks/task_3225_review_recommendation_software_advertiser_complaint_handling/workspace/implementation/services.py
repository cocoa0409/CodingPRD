"""Shared helpers: entity construction, serializers, scoring, aggregates,
lazy clock effects, and payload validation."""
import re
import uuid
from datetime import timedelta

from db import store, fmt_ts, parse_date
from errors import invalid_request

REC_THRESHOLD = 700
TRUST_WEIGHT = 4
SUSPENDED_PENALTY = 200
EDIT_PENALTY = 50
AGE_DECAY_PER_DAY = 2
AGE_DECAY_CAP_DAYS = 100
STRIKE_TRUST_PENALTY = 15
REMOVAL_TRUST_PENALTY = 5
STRIKE_ESCALATION = 2
CALL_MIN_DURATION_S = 30
ATT_WINDOW_DAYS = 30
EDIT_WINDOW_H = 72
VERIFY_TTL_D = 7
NOTICE_PERIOD_D = 14
ALERT_COOLDOWN_D = 30

# Fields for common ("first-class") resources: id, created_at, updated_at, version
# Event-like resources (impressions, call events, attribution reports) have
# only id + created_at.


def new_id():
    return str(uuid.uuid4())


def stamp_common(obj):
    ts = fmt_ts(store.now)
    obj["id"] = new_id()
    obj["created_at"] = ts
    obj["updated_at"] = ts
    obj["version"] = 1
    return obj


def stamp_event(obj):
    obj["id"] = new_id()
    obj["created_at"] = fmt_ts(store.now)
    return obj


def touch(obj):
    obj["updated_at"] = fmt_ts(store.now)
    obj["version"] = obj.get("version", 1) + 1


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


# ---- payload validation helpers ----

def get_body():
    from flask import request
    if not request.is_json:
        raise invalid_request("request body must be JSON")
    body = request.get_json(silent=True)
    if body is None or not isinstance(body, dict):
        raise invalid_request("request body must be a JSON object")
    return body


def req_str(body, field, min_len=None):
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be a string")
    if min_len is not None and len(v) < min_len:
        raise invalid_request(f"{field} must be at least {min_len} characters")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if v not in allowed:
        raise invalid_request(f"{field} must be one of {sorted(allowed)}")
    return v


def req_int(body, field, lo=None, hi=None):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise invalid_request(f"{field} is required and must be an integer")
    if lo is not None and v < lo:
        raise invalid_request(f"{field} must be >= {lo}")
    if hi is not None and v > hi:
        raise invalid_request(f"{field} must be <= {hi}")
    return v


def req_bool(body, field, default=None):
    v = body.get(field)
    if v is None:
        if default is None:
            raise invalid_request(f"{field} is required and must be a boolean")
        return default
    if not isinstance(v, bool):
        raise invalid_request(f"{field} must be a boolean")
    return v


def req_date(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        raise invalid_request(f"{field} is required and must be a YYYY-MM-DD date")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
        raise invalid_request(f"{field} must be a YYYY-MM-DD date")
    try:
        parse_date(v)
    except ValueError:
        raise invalid_request(f"{field} must be a valid YYYY-MM-DD date")
    return v


# ---- recommendation scoring ----

def compute_score(review, author):
    base = 300 + TRUST_WEIGHT * clamp(author["trust_score"], 0, 100)
    if author["status"] == "SUSPENDED":
        base -= SUSPENDED_PENALTY
    if review.get("edited_flag"):
        base -= EDIT_PENALTY
    age_seconds = (store.now - review["_submitted_dt"]).total_seconds()
    age_days = int(age_seconds // 86400)
    if age_days < 0:
        age_days = 0
    base -= AGE_DECAY_PER_DAY * min(age_days, AGE_DECAY_CAP_DAYS)
    return clamp(base, 0, 1000)


def recompute_page_aggregates(page):
    displayed = [r for r in store.reviews.values()
                 if r["page_id"] == page["id"] and r["recommendation_state"] == "DISPLAYED"]
    n = len(displayed)
    page["displayed_review_count"] = n
    if n == 0:
        page["displayed_rating_avg_x100"] = 0
    else:
        total = sum(r["rating"] for r in displayed)
        # round half-up at the final division only
        num = 100 * total
        page["displayed_rating_avg_x100"] = (2 * num + n) // (2 * n)


def set_review_state(review, new_state):
    """Transition helper: maintains page aggregates around DISPLAYED entry/exit."""
    old = review["recommendation_state"]
    if old == new_state:
        return
    review["recommendation_state"] = new_state
    touch(review)
    page = store.pages.get(review["page_id"])
    if page is None:
        return
    if old == "DISPLAYED" or new_state == "DISPLAYED":
        recompute_page_aggregates(page)
        touch(page)


# ---- lazy clock effects ----

def apply_lazy_time_effects():
    """Apply claim expiry, campaign completion, and ad-account daily spend reset."""
    for claim in store.claims.values():
        if claim["status"] == "SUBMITTED":
            if store.now > claim["_created_dt"] + timedelta(days=VERIFY_TTL_D):
                claim["status"] = "EXPIRED"
                touch(claim)
    today = store.now.date()
    for camp in store.campaigns.values():
        if camp["status"] in ("ACTIVE", "PAUSED"):
            if parse_date(camp["ends_on"]) < today:
                camp["status"] = "COMPLETED"
                touch(camp)
    for acct in store.ad_accounts.values():
        if acct.get("_spent_date") is not None and acct["_spent_date"] < today:
            acct["spent_today_cents"] = 0
            acct["_spent_date"] = today
            touch(acct)
        elif acct.get("_spent_date") is None:
            acct["_spent_date"] = today


def lazy_reset_spend(acct):
    today = store.now.date()
    if acct.get("_spent_date") != today:
        acct["spent_today_cents"] = 0
        acct["_spent_date"] = today
        touch(acct)


# ---- serializers (strip private _ keys) ----

def pub(obj):
    return {k: v for k, v in obj.items() if not k.startswith("_")}
