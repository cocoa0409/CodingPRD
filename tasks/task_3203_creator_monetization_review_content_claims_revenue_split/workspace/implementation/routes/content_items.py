"""Content items: upload, review request, classification and settlement."""

from flask import Blueprint, request

import db
from errors import raise_error
from middleware import require_creator_owns, require_role
from response import ok
from routes.common import body, get_content_item, paginated, resolve_channel_item, sort_by_created_at
from routes.serializers import content_item_view
from services import channel as channel_svc
from services import content as content_svc
from services import revenue as revenue_svc

bp = Blueprint("content_items", __name__, url_prefix="/api")


@bp.post("/channels/<channel_id>/content-items")
def upload_content_item(channel_id):
    require_role("Creator", "PlatformAdmin")
    channel = db.get("channels", channel_id)
    if channel is None:
        raise_error("ERR_CHANNEL_NOT_FOUND")
    require_creator_owns(channel_id)

    payload = body()
    if not payload.get("title"):
        raise_error("ERR_INVALID_STATE", "title is required.")

    item = db.common_fields(
        {
            "channel_id": channel["id"],
            "title": payload["title"],
            "duration_seconds": int(payload.get("duration_seconds") or 0),
            "category_code": payload.get("category_code"),
            "self_declared_mature": bool(payload.get("self_declared_mature") or False),
            "upload_status": "UPLOADED",
            "ad_suitability": None,
            "limited_ads_reasons": [],
            "gross_revenue_cents": 0,
            "routed_revenue_cents": 0,
            "holds_revenue": False,
            "takedown_flag": False,
        }
    )
    db.insert("content_items", item)
    return ok(content_item_view(item), 201)


@bp.get("/channels/<channel_id>/content-items")
def list_channel_content_items(channel_id):
    require_role("Any")
    channel = db.get("channels", channel_id)
    if channel is None:
        raise_error("ERR_CHANNEL_NOT_FOUND")
    rows = [i for i in db.all_of("content_items") if i["channel_id"] == channel["id"]]
    return paginated([content_item_view(i) for i in sort_by_created_at(rows)])


@bp.get("/content-items")
def list_content_items():
    require_role("Any")
    channel_filter = request.args.get("channel_id")
    rows = db.all_of("content_items")
    if channel_filter:
        rows = [i for i in rows if i["channel_id"] == channel_filter]
    return paginated([content_item_view(i) for i in sort_by_created_at(rows)])


@bp.get("/content-items/<item_id>")
def get_one_content_item(item_id):
    require_role("Any")
    return ok(content_item_view(get_content_item(item_id)))


@bp.post("/channels/<channel_id>/content-items/<item_id>/requests-review")
def request_review(channel_id, item_id):
    require_role("Creator")
    channel, item = resolve_channel_item(channel_id, item_id)
    require_creator_owns(channel_id)

    if item["upload_status"] != "UPLOADED":
        raise_error("ERR_INVALID_STATE")
    if channel.get("monetization_posture") == "FROZEN":
        raise_error("ERR_POSTURE_FROZEN")

    # Drive UPLOADED -> CLASSIFYING; no AdReview yet and ad_suitability stays null.
    item["upload_status"] = "CLASSIFYING"

    # The classification pass runs over the item's own category_code.
    submitted = [item["category_code"]] if item.get("category_code") else []
    like_count = int(body().get("like_count") or 0)
    comment_count = int(body().get("comment_count") or 0)
    outcome, matched, reason_codes = content_svc.classify(submitted, like_count, comment_count)
    content_svc.create_ad_review(item, outcome, matched, reason_codes, like_count, comment_count)

    # The rights scan then resolves the item to CLASSIFIED or CLAIM_SCAN_COMPLETE.
    content_svc.run_rights_scan(item)
    db.touch(item)
    return ok(content_item_view(item))


@bp.post("/channels/<channel_id>/content-items/<item_id>/classification-appeals")
def classification_appeal(channel_id, item_id):
    require_role("MonetizationReviewer")
    channel, item = resolve_channel_item(channel_id, item_id)

    if item["upload_status"] != "CLASSIFIED":
        raise_error("ERR_INVALID_STATE")
    if item.get("ad_suitability") not in ("LIMITED_ADS", "NO_ADS"):
        raise_error("ERR_INVALID_STATE")
    if channel.get("monetization_posture") == "FROZEN":
        raise_error("ERR_POSTURE_FROZEN")
    if channel.get("monetization_posture") == "RESTRICTED":
        raise_error("ERR_POSTURE_RESTRICTED")

    review = content_svc.latest_ad_review(item["id"])
    if review is not None:
        review["appeal_outcome"] = "UPHELD"

    # The self-loop leaves ad_suitability and limited_ads_reasons unchanged.
    db.touch(item)
    return ok(content_item_view(item))


@bp.post("/content-items/<item_id>/classifications")
def reclassify(item_id):
    require_role("Reviewer", "MonetizationReviewer")
    item = get_content_item(item_id)

    # Re-classification is available from either settling resting state.
    if item["upload_status"] not in ("CLASSIFIED", "CLAIM_SCAN_COMPLETE"):
        raise_error("ERR_INVALID_STATE")

    payload = body()
    categories = payload.get("category_codes") or []
    if not isinstance(categories, list):
        raise_error("ERR_INVALID_CATEGORY_CODE")
    content_svc.validate_categories(categories)

    like_count = int(payload.get("like_count") or 0)
    comment_count = int(payload.get("comment_count") or 0)
    outcome, matched, reason_codes = content_svc.classify(categories, like_count, comment_count)
    content_svc.create_ad_review(item, outcome, matched, reason_codes, like_count, comment_count)

    if outcome == "NO_ADS":
        content_svc.take_down_item_claims(item)

    db.touch(item)
    return ok(content_item_view(item))


@bp.post("/content-items/<item_id>/settle")
def settle(item_id):
    require_role("PlatformAdmin")
    item = get_content_item(item_id)
    revenue_svc.settle_item(item)
    return ok(content_item_view(item))


@bp.patch("/content-items/<item_id>/revenue-lock")
def revenue_lock(item_id):
    require_role("PlatformAdmin")
    item = get_content_item(item_id)

    payload = body()
    locked = bool(payload.get("locked"))
    if locked:
        content_svc.lock_item_revenue(item, payload.get("reason_code"))
    else:
        content_svc.release_item_revenue(item)
    db.touch(item)
    return ok(content_item_view(item))


# --- reverse reachability ----------------------------------------------------

@bp.get("/content-items/<item_id>/ad-reviews")
def list_ad_reviews(item_id):
    require_role("Any")
    item = get_content_item(item_id)
    rows = [r for r in db.all_of("ad_reviews") if r["content_item_id"] == item["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])


@bp.get("/content-items/<item_id>/copyright-strikes")
def list_item_copyright_strikes(item_id):
    require_role("Any")
    item = get_content_item(item_id)
    rows = [s for s in db.all_of("copyright_strikes") if s["content_item_id"] == item["id"]]
    return paginated([dict(r) for r in sort_by_created_at(rows)])