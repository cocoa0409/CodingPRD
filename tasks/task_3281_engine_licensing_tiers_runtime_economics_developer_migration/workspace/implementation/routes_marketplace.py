"""Asset marketplace routes: listings, purchases, refunds."""
from flask import Blueprint, request
from decimal import Decimal, ROUND_HALF_UP
from datetime import timedelta

from db import db
from errors import (
    raise_err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_TIER_FEATURE_NOT_ALLOWED, ERR_ORG_SUSPENDED, ERR_BUYER_IS_CREATOR,
    ERR_REFUND_WINDOW_EXPIRED,
)
from helpers import ok, ok_list, body, new_common, new_id, now_iso, touch, current_date
from middleware import authenticate, authorize, ERR_FORBIDDEN_ORG, get_org_or_404
from services_calc import (
    active_tier_config, compute_standing, SHARE_BOUNDARY_CENTS,
    SHARE_LOW_PCT, SHARE_HIGH_PCT,
)
from routes_orgs import _is_migrated

bp = Blueprint("marketplace", __name__)

READ_ROLES = {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor", "ReviewBoard"}


def _check_listing_owner(role, uid, listing):
    if role == "OrgOwner" and uid != listing["creator_org_id"]:
        raise_err(ERR_FORBIDDEN_ORG, "Not your listing")


@bp.route("/orgs/<oid>/asset-listings", methods=["POST"])
def create_listing(oid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    if oid not in db.orgs:
        raise_err(ERR_NOT_FOUND, "Organization not found")
    if uid != oid:
        raise_err(ERR_FORBIDDEN_ORG, "Not your org")
    org = get_org_or_404(oid)
    if _is_migrated(oid) or org["org_standing"] == "SUSPENDED":
        raise_err(ERR_ORG_SUSPENDED, "Org suspended or migrated")
    b = body()
    title = b.get("title")
    price = b.get("price_cents")
    if not isinstance(title, str):
        raise_err(ERR_VALIDATION, "title is required")
    if not isinstance(price, int) or isinstance(price, bool) or price < 0:
        raise_err(ERR_VALIDATION, "price_cents must be a non-negative integer")
    ent = new_common()
    ent.update({
        "creator_org_id": oid,
        "title": title,
        "price_cents": price,
        "listing_status": "DRAFT",
        "review_rounds": 0,
    })
    db.asset_listings[ent["id"]] = ent
    return ok(ent, 201)


@bp.route("/orgs/<oid>/asset-listings", methods=["GET"])
def list_org_listings(oid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    if role == "OrgOwner" and uid != oid:
        raise_err(ERR_FORBIDDEN_ORG, "Not your org")
    get_org_or_404(oid)
    items = [l for l in db.asset_listings.values() if l["creator_org_id"] == oid]
    items.sort(key=lambda l: l["created_at"])
    ls = request.args.get("listing_status")
    if ls:
        items = [l for l in items if l["listing_status"] == ls]
    return ok_list(items)


@bp.route("/asset-listings/<lid>", methods=["GET"])
def get_listing(lid):
    uid, role = authenticate()
    authorize(role, READ_ROLES)
    l = db.asset_listings.get(lid)
    if l is None:
        raise_err(ERR_NOT_FOUND, "Listing not found")
    _check_listing_owner(role, uid, l)
    return ok(l)


@bp.route("/asset-listings/<lid>/submit-review", methods=["POST"])
def submit_review(lid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    l = db.asset_listings.get(lid)
    if l is None:
        raise_err(ERR_NOT_FOUND, "Listing not found")
    _check_listing_owner(role, uid, l)
    if l["listing_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only DRAFT listings may be submitted")
    org = get_org_or_404(l["creator_org_id"])
    compute_standing(org)
    if org["org_standing"] != "GOOD":
        raise_err(ERR_ORG_SUSPENDED, "Org standing must be GOOD")
    if l["price_cents"] < 0:
        raise_err(ERR_VALIDATION, "price_cents must be non-negative")
    cfg = active_tier_config(org["effective_tier_code"])
    if cfg is None or not cfg.get("marketplace_sell_allowed"):
        raise_err(ERR_TIER_FEATURE_NOT_ALLOWED, "Tier does not allow marketplace selling")
    l["listing_status"] = "PENDING_REVIEW"
    l["review_rounds"] = l.get("review_rounds", 0) + 1
    touch(l)
    return ok(l)


@bp.route("/asset-listings/<lid>/review", methods=["POST"])
def review_listing(lid):
    uid, role = authenticate()
    authorize(role, {"ReviewBoard"})
    l = db.asset_listings.get(lid)
    if l is None:
        raise_err(ERR_NOT_FOUND, "Listing not found")
    if l["listing_status"] != "PENDING_REVIEW":
        raise_err(ERR_INVALID_STATE, "Listing must be PENDING_REVIEW")
    b = body()
    action = b.get("action")
    if action not in ("APPROVE", "REJECT"):
        raise_err(ERR_VALIDATION, "action must be APPROVE or REJECT")
    l["listing_status"] = "APPROVED" if action == "APPROVE" else "REJECTED"
    touch(l)
    return ok(l)


@bp.route("/asset-listings/<lid>/revise", methods=["POST"])
def revise_listing(lid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    l = db.asset_listings.get(lid)
    if l is None:
        raise_err(ERR_NOT_FOUND, "Listing not found")
    _check_listing_owner(role, uid, l)
    if l["listing_status"] not in ("REJECTED", "DELISTED"):
        raise_err(ERR_INVALID_STATE, "Only REJECTED or DELISTED listings may be revised")
    b = body()
    if "title" in b:
        if not isinstance(b["title"], str):
            raise_err(ERR_VALIDATION, "title must be a string")
        l["title"] = b["title"]
    if "price_cents" in b:
        price = b["price_cents"]
        if not isinstance(price, int) or isinstance(price, bool) or price < 0:
            raise_err(ERR_VALIDATION, "price_cents must be a non-negative integer")
        l["price_cents"] = price
    l["listing_status"] = "DRAFT"
    touch(l)
    return ok(l)


@bp.route("/asset-listings/<lid>/delist", methods=["POST"])
def delist_listing(lid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    l = db.asset_listings.get(lid)
    if l is None:
        raise_err(ERR_NOT_FOUND, "Listing not found")
    _check_listing_owner(role, uid, l)
    if l["listing_status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Only APPROVED listings may be delisted")
    l["listing_status"] = "DELISTED"
    touch(l)
    return ok(l)


@bp.route("/asset-listings/<lid>/purchase", methods=["POST"])
def purchase_listing(lid):
    uid, role = authenticate()
    authorize(role, {"OrgOwner"})
    l = db.asset_listings.get(lid)
    if l is None:
        raise_err(ERR_NOT_FOUND, "Listing not found")
    # Buyer org is the caller identity
    buyer = db.orgs.get(uid)
    if buyer is None:
        raise_err(ERR_NOT_FOUND, "Buyer org not found")
    compute_standing(buyer)
    if buyer["org_standing"] == "SUSPENDED" or _is_migrated(uid):
        raise_err(ERR_ORG_SUSPENDED, "Buyer org suspended or migrated")
    if l["listing_status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Listing must be APPROVED")
    if uid == l["creator_org_id"]:
        raise_err(ERR_BUYER_IS_CREATOR, "Org may not purchase its own listing")
    creator = get_org_or_404(l["creator_org_id"])
    gross = l["price_cents"]
    lifetime_gross = sum(
        p["gross_cents"] for p in db.asset_purchases.values()
        if p["listing_id"] in {
            x["id"] for x in db.asset_listings.values() if x["creator_org_id"] == creator["id"]
        } and p["purchase_status"] == "COMPLETED"
    )
    pct = SHARE_HIGH_PCT if lifetime_gross >= SHARE_BOUNDARY_CENTS else SHARE_LOW_PCT
    platform_share = int((Decimal(gross) * pct).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    creator_share = gross - platform_share
    ent = {
        "id": new_id(),
        "created_at": now_iso(),
        "listing_id": lid,
        "buyer_org_id": uid,
        "gross_cents": gross,
        "platform_share_cents": platform_share,
        "creator_share_cents": creator_share,
        "purchase_status": "COMPLETED",
        "purchased_at": now_iso(),
    }
    db.asset_purchases[ent["id"]] = ent
    creator["marketplace_credit_cents"] = creator.get("marketplace_credit_cents", 0) + creator_share
    touch(creator)
    return ok(ent, 201)


@bp.route("/asset-purchases", methods=["GET"])
def list_purchases():
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"})
    items = sorted(db.asset_purchases.values(), key=lambda p: p["created_at"])
    li = request.args.get("listing_id")
    bo = request.args.get("buyer_org_id")
    if li:
        items = [p for p in items if p["listing_id"] == li]
    if bo:
        items = [p for p in items if p["buyer_org_id"] == bo]
    if role == "OrgOwner":
        own_listings = {l["id"] for l in db.asset_listings.values() if l["creator_org_id"] == uid}
        items = [p for p in items if p["buyer_org_id"] == uid or p["listing_id"] in own_listings]
    return ok_list(items)


@bp.route("/asset-purchases/<pid>", methods=["GET"])
def get_purchase(pid):
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "OrgOwner", "FinanceOps", "Auditor"})
    p = db.asset_purchases.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Purchase not found")
    if role == "OrgOwner":
        listing = db.asset_listings.get(p["listing_id"])
        if uid != p["buyer_org_id"] and (listing is None or listing["creator_org_id"] != uid):
            raise_err(ERR_FORBIDDEN_ORG, "Not your purchase")
    return ok(p)


@bp.route("/asset-purchases/<pid>/refund", methods=["POST"])
def refund_purchase(pid):
    from helpers import parse_iso_datetime
    uid, role = authenticate()
    authorize(role, {"PlatformAdmin", "FinanceOps"})
    p = db.asset_purchases.get(pid)
    if p is None:
        raise_err(ERR_NOT_FOUND, "Purchase not found")
    if p["purchase_status"] == "REFUNDED":
        raise_err(ERR_REFUND_WINDOW_EXPIRED, "Purchase already refunded")
    purchased = parse_iso_datetime(p["purchased_at"])
    from db import db as _db
    if purchased is not None and _db.clock > purchased + timedelta(days=14):
        raise_err(ERR_REFUND_WINDOW_EXPIRED, "Refund window expired")
    p["purchase_status"] = "REFUNDED"
    listing = db.asset_listings.get(p["listing_id"])
    if listing is not None:
        creator = db.orgs.get(listing["creator_org_id"])
        if creator is not None:
            creator["marketplace_credit_cents"] = max(
                0, creator.get("marketplace_credit_cents", 0) - p["creator_share_cents"]
            )
            touch(creator)
    return ok(p)
