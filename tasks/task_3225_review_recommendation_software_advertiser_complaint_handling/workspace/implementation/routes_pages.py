"""Routes: business pages."""
from flask import Blueprint, request

from db import store
from errors import not_found, err
from middleware import require_roles
from response import ok, ok_list, paginate
from services import (
    stamp_common, touch, get_body, req_str, pub,
)
from routes_core import ALL_ROLES

bp = Blueprint("pages", __name__)


def get_page(page_id):
    p = store.pages.get(page_id)
    if p is None:
        raise not_found("business page not found")
    return p


@bp.post("/platform/business-pages")
@require_roles("PlatformOps")
def create_page(_actor_id, _actor_role):
    body = get_body()
    page = stamp_common({
        "name": req_str(body, "name"),
        "address_line": req_str(body, "address_line"),
        "city": req_str(body, "city"),
        "category": req_str(body, "category"),
        "website": req_str(body, "website"),
        "claimed_by_user_id": None,
        "merged_into_id": None,
        "displayed_review_count": 0,
        "displayed_rating_avg_x100": 0,
        "ad_account_id": None,
        "status": "ACTIVE",
    })
    store.pages[page["id"]] = page
    return ok(pub(page), status=201)


@bp.get("/platform/business-pages")
@require_roles(*ALL_ROLES)
def list_pages(_actor_id, _actor_role):
    items = list(store.pages.values())
    for f in ("claimed_by_user_id", "merged_into_id", "ad_account_id"):
        v = request.args.get(f)
        if v is not None:
            items = [p for p in items if p.get(f) == v]
    items, limit, offset, total = paginate([pub(p) for p in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/business-pages/<pageId>")
@require_roles(*ALL_ROLES)
def get_one_page(pageId, _actor_id, _actor_role):
    return ok(pub(get_page(pageId)))


@bp.patch("/platform/business-pages/<pageId>")
@require_roles("BusinessOwner")
def update_page(pageId, _actor_id, _actor_role):
    page = get_page(pageId)
    body = get_body()
    # OCC field required
    epv = body.get("expected_page_version")
    if epv is None:
        raise err("ERR_INVALID_REQUEST", "expected_page_version is required")
    if not isinstance(epv, int) or isinstance(epv, bool):
        raise err("ERR_INVALID_REQUEST", "expected_page_version must be an integer")
    # owner-only info update
    if page["claimed_by_user_id"] != _actor_id:
        raise err("ERR_FORBIDDEN", "only the claimed owner may update page info")
    if epv != page["version"]:
        raise err("ERR_STALE_VERSION", "expected_page_version does not match current version")
    for f in ("name", "website", "category", "address_line", "city"):
        if f in body:
            v = body[f]
            if not isinstance(v, str):
                raise err("ERR_INVALID_REQUEST", f"{f} must be a string")
            page[f] = v
    touch(page)
    return ok(pub(page))


@bp.post("/platform/business-pages/<pageId>/close")
@require_roles("SupportAdmin")
def close_page(pageId, _actor_id, _actor_role):
    page = get_page(pageId)
    if page["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "page is not ACTIVE")
    page["status"] = "CLOSED"
    touch(page)
    # cascade: ad account suspended + active campaigns paused
    if page.get("ad_account_id"):
        acct = store.ad_accounts.get(page["ad_account_id"])
        if acct is not None and acct["status"] == "ACTIVE":
            acct["status"] = "SUSPENDED"
            touch(acct)
            for camp in store.campaigns.values():
                if camp["ad_account_id"] == acct["id"] and camp["status"] == "ACTIVE":
                    camp["status"] = "PAUSED"
                    touch(camp)
    # cascade: SUBMITTED/VERIFIED claims -> EXPIRED
    for claim in store.claims.values():
        if claim["page_id"] == pageId and claim["status"] in ("SUBMITTED", "VERIFIED"):
            claim["status"] = "EXPIRED"
            touch(claim)
    return ok(pub(page))


@bp.get("/platform/business-pages/<pageId>/reviews")
@require_roles(*ALL_ROLES)
def list_page_reviews(pageId, _actor_id, _actor_role):
    get_page(pageId)
    items = [r for r in store.reviews.values() if r["page_id"] == pageId]
    state = request.args.get("recommendation_state")
    if state is not None:
        items = [r for r in items if r["recommendation_state"] == state]
    items, limit, offset, total = paginate([pub(r) for r in items], request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/business-pages/<pageId>/claims")
@require_roles("PlatformOps", "SupportAdmin", "BusinessOwner")
def list_page_claims(pageId, _actor_id, _actor_role):
    get_page(pageId)
    items = [pub(c) for c in store.claims.values() if c["page_id"] == pageId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/business-pages/<pageId>/complaints")
@require_roles("PlatformOps", "ContentModerator", "SupportAdmin", "BusinessOwner")
def list_page_complaints(pageId, _actor_id, _actor_role):
    get_page(pageId)
    items = [pub(c) for c in store.complaints.values() if c["page_id"] == pageId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/business-pages/<pageId>/solicitation-cases")
@require_roles("PlatformOps", "TrustInvestigator", "SupportAdmin")
def list_page_cases(pageId, _actor_id, _actor_role):
    get_page(pageId)
    items = [pub(c) for c in store.cases.values() if c["page_id"] == pageId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)


@bp.get("/platform/business-pages/<pageId>/consumer-alerts")
@require_roles(*ALL_ROLES)
def list_page_alerts(pageId, _actor_id, _actor_role):
    get_page(pageId)
    items = [pub(a) for a in store.alerts.values() if a["page_id"] == pageId]
    items, limit, offset, total = paginate(items, request.args)
    return ok_list(items, limit, offset, total)
