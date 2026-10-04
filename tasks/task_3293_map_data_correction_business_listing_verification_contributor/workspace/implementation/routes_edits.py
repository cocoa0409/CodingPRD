"""MapEdit endpoints: create (auto-validation), supply-info, revert, reads."""
from datetime import timedelta
from flask import Blueprint, request

import clock
import domain
import store
from errors import raise_err
from response import envelope, require_roles, body, paginate
from services_listings import (NONTERMINAL_EDIT_STATES, publish_edit,
                               revert_edit)
from validation import require_fields, require_enum, get_or_404

bp = Blueprint("edits", __name__)

EDIT_TYPES = {"NAME", "CATEGORY", "ADDRESS", "HOURS", "LOCATION", "ATTRIBUTE"}
READ_ROLES = {"PlatformAdmin", "Contributor", "BusinessOwner", "Moderator", "PolicyAnalyst"}


def auto_validation_score(contributor, listing, edit_type, payload):
    trust = contributor["finalized_trust_score"]
    evidence = payload.get("evidence_urls") if isinstance(payload, dict) else None
    ev_count = min(len(evidence), 3) if isinstance(evidence, list) else 0
    if edit_type in ("ADDRESS", "LOCATION"):
        risk = 25
    elif edit_type == "NAME":
        risk = 30 if listing["keyword_stuffing_strikes"] > 0 else 10
    else:
        risk = 5
    score = 40 + 0.4 * trust + 10 * ev_count - risk
    score = max(0.0, min(100.0, score))
    return round(score, 1)


@bp.post("/v1/map-edits")
def create_edit():
    role, uid = require_roles({"Contributor", "BusinessOwner"})
    data = body()
    require_fields(data, ["listing_id", "contributor_id", "edit_type", "payload",
                          "expected_listing_version"])
    l = store.listings.get(data["listing_id"])
    if l is None:
        raise_err("ERR_NOT_FOUND", "listing not found")
    c = store.contributors.get(data["contributor_id"])
    if c is None:
        raise_err("ERR_NOT_FOUND", "contributor not found")
    edit_type = require_enum(data, "edit_type", EDIT_TYPES)
    payload = data["payload"]
    if not isinstance(payload, dict):
        raise_err("ERR_INVALID_REQUEST", "payload must be an object")
    # content policy screens run before OCC per PRD precedence? PRD: stale-version
    # surfaces before keyword-stuffing, so OCC first.
    if data["expected_listing_version"] != l["version"]:
        raise_err("ERR_STALE_VERSION", "listing version advanced")
    if c["status"] != "ACTIVE":
        raise_err("ERR_CONTRIBUTOR_RESTRICTED", "contributor not ACTIVE")
    if l["status"] in ("SUSPENDED", "PERMANENTLY_CLOSED"):
        raise_err("ERR_LISTING_SUSPENDED", "listing does not admit edits")
    # duplicate screen
    for e in store.edits.values():
        if e["listing_id"] == l["id"] and e["contributor_id"] == c["id"] \
                and e["edit_type"] == edit_type \
                and e["status"] in NONTERMINAL_EDIT_STATES:
            raise_err("ERR_DUPLICATE_SUBMISSION", "duplicate open edit")
    # type-specific content screens
    if edit_type == "NAME" and "name" in payload:
        from routes_listings import screen_name_for_stuffing
        screen_name_for_stuffing(l, payload["name"])
    if edit_type == "CATEGORY" and "category" in payload:
        cat = payload["category"]
        if cat in domain.PROHIBITED_CATEGORIES:
            raise_err("ERR_PROHIBITED_CATEGORY", "prohibited category")
        if cat not in domain.LISTING_CATEGORIES:
            raise_err("ERR_INVALID_REQUEST", "unknown category")
    if edit_type in ("LOCATION", "ADDRESS"):
        region = store.regions.get(l["region_id"])
        lat = payload.get("geo_lat", l["geo_lat"])
        lng = payload.get("geo_lng", l["geo_lng"])
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            if lat < region["geo_min_lat"] or lat > region["geo_max_lat"] \
                    or lng < region["geo_min_lng"] or lng > region["geo_max_lng"]:
                raise_err("ERR_GEO_OUT_OF_REGION", "coordinates outside region")

    domain.recompute_contributor(c, demote=False)
    score = auto_validation_score(c, l, edit_type, payload)
    domain.recompute_points(c)
    quality_weight = domain.LEVEL_WEIGHTS[c["level"]]

    now = clock.iso(clock.now())
    rec = {
        "id": domain.new_id(),
        "listing_id": l["id"],
        "contributor_id": c["id"],
        "edit_type": edit_type,
        "payload": payload,
        "status": "SUBMITTED",
        "auto_score": score,
        "quality_weight": quality_weight,
        "rejection_reason": None,
        "review_ticket_id": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    store.edits[rec["id"]] = rec

    if score >= 85:
        rec["status"] = "AUTO_VALIDATED"
        publish_edit(rec)  # sets PUBLISHED + cascades; touches listing
    elif score >= 50:
        rec["status"] = "QUEUED"
        domain.touch(rec)
    else:
        rec["status"] = "REJECTED"
        rec["rejection_reason"] = "AUTO_LOW_SCORE"
        domain.touch(rec)
        domain.recompute_contributor(c, demote=True)

    # edit creation bumps listing version (OCC contract)
    domain.recompute_listing(l)
    domain.touch(l)
    return envelope(domain.edit_view(rec), status=201)


@bp.get("/v1/map-edits")
def list_edits():
    require_roles(READ_ROLES)
    items = list(store.edits.values())
    for f in ("listing_id", "contributor_id", "status", "edit_type", "review_ticket_id"):
        v = request.args.get(f)
        if v is not None:
            items = [e for e in items if e.get(f) == v]
    page, pg = paginate(items, request.args)
    return envelope([domain.edit_view(e) for e in page],
                    response_type="array", pagination=pg)


@bp.get("/v1/map-edits/<eid>")
def get_edit(eid):
    require_roles(READ_ROLES)
    e = get_or_404(store.edits, eid)
    return envelope(domain.edit_view(e))


@bp.post("/v1/map-edits/<eid>/supply-info")
def supply_info(eid):
    role, uid = require_roles({"Contributor", "BusinessOwner"})
    e = get_or_404(store.edits, eid)
    data = body()
    if e["status"] != "NEEDS_MORE_INFO":
        raise_err("ERR_INVALID_STATE", "edit not awaiting info")
    if e["contributor_id"] != uid:
        raise_err("ERR_NOT_EDIT_AUTHOR", "only the edit author may supply info")
    evidence = data.get("evidence")
    if not evidence or (isinstance(evidence, str) and not evidence.strip()):
        raise_err("ERR_INVALID_REQUEST", "evidence must be non-empty")
    c = store.contributors.get(e["contributor_id"])
    if c is None or c["status"] != "ACTIVE":
        raise_err("ERR_CONTRIBUTOR_RESTRICTED", "contributor not ACTIVE")
    e["status"] = "IN_REVIEW"
    domain.touch(e)
    now = clock.now()
    ticket = {
        "id": domain.new_id(),
        "map_edit_id": e["id"],
        "review_flag_id": None,
        "queue": "EDIT_REVIEW",
        "status": "OPEN",
        "claimed_by": None,
        "priority": "HIGH",
        "resolution": None,
        "sla_due_at": clock.iso(now + timedelta(hours=24)),
        "created_at": clock.iso(now),
        "updated_at": clock.iso(now),
        "version": 1,
    }
    store.tickets[ticket["id"]] = ticket
    return envelope(domain.edit_view(e))


@bp.post("/v1/map-edits/<eid>/revert")
def revert(eid):
    require_roles({"PolicyAnalyst"})
    e = get_or_404(store.edits, eid)
    if e["status"] != "PUBLISHED":
        raise_err("ERR_INVALID_STATE", "only PUBLISHED edits can be reverted")
    revert_edit(e)
    return envelope(domain.edit_view(e))


@bp.get("/v1/map-edits/<eid>/review-tickets")
def edit_tickets(eid):
    require_roles({"PlatformAdmin", "Moderator"})
    get_or_404(store.edits, eid)
    items = [t for t in store.tickets.values() if t.get("map_edit_id") == eid]
    page, pg = paginate(items, request.args)
    return envelope([domain.ticket_view(t) for t in page],
                    response_type="array", pagination=pg)
