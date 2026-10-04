"""Business listing endpoints."""
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from services_listings import (NONTERMINAL_EDIT_STATES, suspend_listing,
                               do_require_reverify)
from validation import (require_fields, require_enum, require_number,
                        get_or_404)

bp = Blueprint("listings", __name__)

READ_ROLES = {"PlatformAdmin", "Contributor", "BusinessOwner", "Moderator", "PolicyAnalyst"}
VIOLATION_TYPES = {"KEYWORD_STUFFING", "FAKE_ADDRESS", "PROHIBITED_CATEGORY",
                   "FAKE_REVIEWS", "IMPERSONATION"}


def _check_geo(region, lat, lng):
    if lat < region["geo_min_lat"] or lat > region["geo_max_lat"] \
            or lng < region["geo_min_lng"] or lng > region["geo_max_lng"]:
        raise_err("ERR_GEO_OUT_OF_REGION", "coordinates outside region bounding box")


def screen_name_for_stuffing(listing, name):
    """Reject keyword-stuffed names; strike persists on listing even when the
    write fails. At creation (listing is None) there is no strike target."""
    if domain.is_keyword_stuffed(name):
        if listing is not None:
            listing["keyword_stuffing_strikes"] += 1
            domain.touch(listing)
        raise_err("ERR_KEYWORD_STUFFING", "name contains keyword-stuffing pattern")


@bp.post("/v1/business-listings")
def create_listing():
    require_roles({"PlatformAdmin", "BusinessOwner"})
    data = body()
    require_fields(data, ["region_id", "name", "category", "address_text",
                          "geo_lat", "geo_lng"])
    region = store.regions.get(data["region_id"])
    if region is None:
        raise_err("ERR_NOT_FOUND", "region not found")
    category = data["category"]
    if category in domain.PROHIBITED_CATEGORIES:
        raise_err("ERR_PROHIBITED_CATEGORY", "prohibited category")
    if category not in domain.LISTING_CATEGORIES:
        raise_err("ERR_INVALID_REQUEST", "unknown category")
    screen_name_for_stuffing(None, data["name"])
    lat = require_number(data, "geo_lat")
    lng = require_number(data, "geo_lng")
    _check_geo(region, lat, lng)
    now = clock.iso(clock.now())
    rec = {
        "id": domain.new_id(),
        "region_id": region["id"],
        "name": data["name"],
        "category": category,
        "address_text": data["address_text"],
        "geo_lat": lat,
        "geo_lng": lng,
        "owner_contributor_id": None,
        "status": "UNCLAIMED",
        "visibility": "PUBLIC",
        "health_score": 50.0,
        "moderation_health_score": 50.0,
        "review_count": 0,
        "rating_avg": 0.0,
        "accepted_edit_count": 0,
        "keyword_stuffing_strikes": 0,
        "verification_method": None,
        "verified_at": None,
        "reverify_due_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.listings[rec["id"]] = rec
    domain.recompute_listing(rec)
    return envelope(domain.listing_view(rec), status=201)


@bp.get("/v1/business-listings")
def list_listings():
    require_roles(READ_ROLES)
    status_filter = request.args.get("status")
    items = []
    for l in store.listings.values():
        domain.recompute_listing(l)
        if status_filter is None and l["status"] == "PERMANENTLY_CLOSED":
            continue
        items.append(l)
    for f in ("region_id", "owner_contributor_id", "status", "visibility", "category"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain._clean(l) for l in page], response_type="array", pagination=pg)


@bp.get("/v1/business-listings/<lid>")
def get_listing(lid):
    require_roles(READ_ROLES)
    l = get_or_404(store.listings, lid)
    return envelope(domain.listing_view(l))


@bp.patch("/v1/business-listings/<lid>")
def patch_listing(lid):
    role, uid = require_roles({"BusinessOwner", "PlatformAdmin"})
    l = get_or_404(store.listings, lid)
    data = body()
    if role == "BusinessOwner" and l.get("owner_contributor_id") != uid:
        raise_err("ERR_NOT_LISTING_OWNER", "only the listing owner may update it")
    if "name" in data and data["name"] is not None:
        screen_name_for_stuffing(l, data["name"])
        l["name"] = data["name"]
    if "address_text" in data and data["address_text"] is not None:
        l["address_text"] = data["address_text"]
    new_lat = l["geo_lat"]
    new_lng = l["geo_lng"]
    if "geo_lat" in data and data["geo_lat"] is not None:
        new_lat = require_number(data, "geo_lat")
    if "geo_lng" in data and data["geo_lng"] is not None:
        new_lng = require_number(data, "geo_lng")
    if new_lat != l["geo_lat"] or new_lng != l["geo_lng"]:
        region = store.regions.get(l["region_id"])
        _check_geo(region, new_lat, new_lng)
        l["geo_lat"] = new_lat
        l["geo_lng"] = new_lng
    domain.recompute_listing(l)
    domain.touch(l)
    return envelope(domain.listing_view(l))


@bp.post("/v1/business-listings/<lid>/claim")
def claim_listing(lid):
    role, uid = require_roles({"BusinessOwner"})
    l = get_or_404(store.listings, lid)
    data = body()
    require_fields(data, ["expected_listing_version"])
    # OCC runs before the already-claimed state check: per PRD §2.5, a claim
    # built on an outdated snapshot — e.g. taken before another claim mutated
    # the listing — is rejected with ERR_STALE_VERSION.
    if data["expected_listing_version"] != l["version"]:
        raise_err("ERR_STALE_VERSION", "listing version advanced")
    if l.get("owner_contributor_id") is not None:
        raise_err("ERR_LISTING_ALREADY_CLAIMED", "listing already claimed")
    contributor = store.contributors.get(uid)
    if contributor is None or contributor["status"] != "ACTIVE":
        raise_err("ERR_CONTRIBUTOR_RESTRICTED", "claiming contributor not ACTIVE")
    l["owner_contributor_id"] = uid
    l["status"] = "CLAIM_PENDING"
    domain.recompute_listing(l)
    domain.touch(l)
    return envelope(domain.listing_view(l))


@bp.post("/v1/business-listings/<lid>/suspend")
def suspend(lid):
    role, uid = require_roles({"PolicyAnalyst"})
    l = get_or_404(store.listings, lid)
    data = body()
    require_fields(data, ["violation_type", "evidence_notes"])
    violation = require_enum(data, "violation_type", VIOLATION_TYPES)
    if l["status"] not in ("CLAIM_PENDING", "VERIFIED", "REVERIFY_REQUIRED"):
        raise_err("ERR_INVALID_STATE", "listing not suspendable from %s" % l["status"])
    case = suspend_listing(l, violation, data["evidence_notes"], uid)
    return envelope(domain.case_view(case))


@bp.post("/v1/business-listings/<lid>/require-reverify")
def require_reverify(lid):
    require_roles({"PolicyAnalyst"})
    l = get_or_404(store.listings, lid)
    if l["status"] != "VERIFIED":
        raise_err("ERR_INVALID_STATE", "listing not VERIFIED")
    do_require_reverify(l)
    return envelope(domain.listing_view(l))


@bp.get("/v1/business-listings/<lid>/map-edits")
def list_listing_edits(lid):
    require_roles(READ_ROLES)
    get_or_404(store.listings, lid)
    items = [e for e in store.edits.values() if e["listing_id"] == lid]
    status = request.args.get("status")
    if status is not None:
        items = [e for e in items if e["status"] == status]
    page, pg = paginate(items, request.args)
    return envelope([domain.edit_view(e) for e in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/business-listings/<lid>/reviews")
def list_listing_reviews(lid):
    require_roles(READ_ROLES)
    get_or_404(store.listings, lid)
    items = [r for r in store.reviews.values() if r["listing_id"] == lid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pg = paginate(items, request.args)
    return envelope([domain.review_view(r) for r in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/business-listings/<lid>/hours-observations")
def list_listing_hours(lid):
    require_roles(READ_ROLES)
    get_or_404(store.listings, lid)
    items = [h for h in store.hours.values() if h["listing_id"] == lid]
    dm = request.args.get("day_mask")
    if dm is not None:
        items = [h for h in items if h["day_mask"] == dm]
    page, pg = paginate(items, request.args)
    return envelope([domain.hours_view(h) for h in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/business-listings/<lid>/suspension-cases")
def list_listing_cases(lid):
    require_roles({"PlatformAdmin", "PolicyAnalyst", "Moderator", "BusinessOwner"})
    get_or_404(store.listings, lid)
    items = [c for c in store.cases.values() if c["listing_id"] == lid]
    page, pg = paginate(items, request.args)
    return envelope([domain.case_view(c) for c in page],
                    response_type="array", pagination=pg)


@bp.post("/v1/business-listings/<lid>/hours/resolve")
def resolve_hours(lid):
    require_roles({"PlatformAdmin", "Moderator"})
    l = get_or_404(store.listings, lid)
    data = body()
    require_fields(data, ["day_mask"])
    from services_hours import resolve as hours_resolve
    result = hours_resolve(l, data["day_mask"])
    return envelope(result)
