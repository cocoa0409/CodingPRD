"""Routes: logical clock + users."""
from flask import Blueprint, request

from db import store, parse_ts
from errors import not_found, invalid_request
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_str, req_int, clamp,
    apply_lazy_time_effects, set_review_state, recompute_page_aggregates, pub,
)

bp = Blueprint("core", __name__)

ALL_ROLES = ("PlatformOps", "Reviewer", "BusinessOwner", "Advertiser",
             "ContentModerator", "TrustInvestigator", "SupportAdmin",
             "LegalOps", "Reporter")


@bp.post("/platform/_clock/set_current_utc")
@require_roles("PlatformOps")
def set_clock(_actor_id, _actor_role):
    body = get_body()
    target = body.get("to_iso8601")
    if not isinstance(target, str):
        raise invalid_request("to_iso8601 is required")
    try:
        dt = parse_ts(target)
    except (ValueError, TypeError):
        raise invalid_request("to_iso8601 must be an ISO 8601 timestamp")
    store.now = dt
    apply_lazy_time_effects()
    return ok({"now": store.now_iso()})


@bp.post("/platform/users")
@require_roles("PlatformOps")
def create_user(_actor_id, _actor_role):
    body = get_body()
    email = req_str(body, "email")
    display_name = req_str(body, "display_name")
    home_region = req_str(body, "home_region")
    user = stamp_common({
        "email": email,
        "display_name": display_name,
        "home_region": home_region,
        "trust_score": 50,
        "strike_count": 0,
        "status": "ACTIVE",
    })
    store.users[user["id"]] = user
    return ok(pub(user), status=201)


@bp.get("/platform/users")
@require_roles("PlatformOps", "ContentModerator", "TrustInvestigator",
               "SupportAdmin", "LegalOps")
def list_users(_actor_id, _actor_role):
    items, limit, offset, total = paginate([pub(u) for u in store.users.values()],
                                           request.args)
    return ok_list(items, limit, offset, total)


def _get_user(user_id):
    u = store.users.get(user_id)
    if u is None:
        raise not_found("user not found")
    return u


@bp.get("/platform/users/<userId>")
@require_roles(*ALL_ROLES)
def get_user(userId, _actor_id, _actor_role):
    return ok(pub(_get_user(userId)))


@bp.get("/platform/users/<userId>/reviews")
@require_roles(*ALL_ROLES)
def list_user_reviews(userId, _actor_id, _actor_role):
    _get_user(userId)
    items = [pub(r) for r in store.reviews.values() if r["author_user_id"] == userId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.post("/platform/users/<userId>/suspend")
@require_roles("PlatformOps")
def suspend_user(userId, _actor_id, _actor_role):
    u = _get_user(userId)
    u["status"] = "SUSPENDED"
    touch(u)
    return ok(pub(u))


@bp.post("/platform/users/<userId>/purge")
@require_roles("PlatformOps")
def purge_user(userId, _actor_id, _actor_role):
    u = _get_user(userId)
    u["status"] = "PURGED"
    touch(u)
    affected_pages = set()
    for r in store.reviews.values():
        if r["author_user_id"] == userId and r["recommendation_state"] != "REMOVED":
            set_review_state(r, "REMOVED")
            affected_pages.add(r["page_id"])
    for pid in affected_pages:
        page = store.pages.get(pid)
        if page is not None:
            recompute_page_aggregates(page)
            touch(page)
    return ok(pub(u))


@bp.post("/platform/users/<userId>/trust-adjustments")
@require_roles("PlatformOps")
def trust_adjust(userId, _actor_id, _actor_role):
    u = _get_user(userId)
    body = get_body()
    ts = req_int(body, "trust_score")
    u["trust_score"] = clamp(ts, 0, 100)
    touch(u)
    return ok(pub(u))
