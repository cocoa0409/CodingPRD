"""Listing endpoints: create/list/get/activate/status + status-change listing
+ flat list/read routes."""

from datetime import timedelta

from flask import Blueprint, request

import calcs
import services
from auth import require_roles, require_member_actor
from db import store, now, _parse_iso
from errors import (raise_err, ERR_INVALID_REQUEST, ERR_DUPLICATE_RESOURCE,
                    ERR_INVALID_STATE, ERR_MEMBER_SUSPENDED,
                    ERR_COMP_DISPLAY_PROHIBITED, ERR_LISTING_FLAGGED,
                    ERR_POLICY_REVISION_MISSING,
                    ERR_CROSS_ASSOCIATION_REFERENCE)
from helpers import (body, mint_common, touch, now_iso_str, get_association,
                     get_member, get_office, get_listing, get_status_change,
                     page, parse_dt)
from response import success_object, success_list
from routes.members import check_not_merged

bp = Blueprint("listings", __name__)

LISTING_STATUSES = ("DRAFT", "ACTIVE", "PENDING", "SOLD", "WITHDRAWN",
                    "EXPIRED", "CANCELLED")
# Member-action status machine edges (from_status -> allowed to_status).
ALLOWED_STATUS_EDGES = {
    "ACTIVE": {"PENDING", "SOLD", "WITHDRAWN", "CANCELLED"},
    "PENDING": {"SOLD"},
}


def _check_listing_member_standing(listing):
    member = store.members.get(listing["listing_member_id"])
    if member is None or member["membership_state"] != "ACTIVE" \
       or member["mls_access_state"] != "ENABLED":
        raise_err(ERR_MEMBER_SUSPENDED,
                  "Listing member is SUSPENDED or mls_access DISABLED")


def _select_governing_revision(assoc_id, at_instant):
    """ACTIVE PolicyRevision with max effective_at <= at_instant."""
    candidates = [r for r in store.policy_revisions.values()
                  if r["association_id"] == assoc_id and r["status"] == "ACTIVE"
                  and _parse_iso(r["effective_at"]) <= at_instant]
    if not candidates:
        raise_err(ERR_POLICY_REVISION_MISSING,
                  "No ACTIVE PolicyRevision with effective_at <= activation instant")
    return max(candidates, key=lambda r: _parse_iso(r["effective_at"]))


@bp.route("/mls/associations/<assoc_id>/offices/<office_id>/listings",
          methods=["POST"])
def create_listing(assoc_id, office_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    office = get_office(office_id, assoc_id)
    check_not_merged(assoc)
    data = body()
    for f in ("listing_member_id", "mls_number", "property_address",
              "list_price_cents"):
        if data.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field '%s'" % f)
    listing_member_id = data["listing_member_id"]
    member = store.members.get(listing_member_id)
    if member is None or member["association_id"] != assoc_id:
        raise_err(ERR_CROSS_ASSOCIATION_REFERENCE,
                  "listing_member_id must belong to the office's association")
    # The actor must be the listing member (entity-backed ownership).
    require_member_actor(user_id, listing_member_id)
    # listing agent: office broker or any ACTIVE member of that office
    if member["membership_state"] != "ACTIVE" and \
       office["broker_member_id"] != listing_member_id:
        raise_err(ERR_MEMBER_SUSPENDED,
                  "listing member must be ACTIVE (or the office broker)")
    price = data["list_price_cents"]
    if isinstance(price, bool) or not isinstance(price, int) or price <= 0:
        raise_err(ERR_INVALID_REQUEST, "list_price_cents must be an integer > 0")
    for l in store.listings.values():
        if l["mls_number"] == data["mls_number"]:
            raise_err(ERR_DUPLICATE_RESOURCE,
                      "mls_number '%s' already exists" % data["mls_number"])
    offer_comp = data.get("offer_comp_cents", 0)
    if isinstance(offer_comp, bool) or not isinstance(offer_comp, int) or offer_comp < 0:
        raise_err(ERR_INVALID_REQUEST, "offer_comp_cents must be an integer >= 0")
    public_marketing_at = data.get("public_marketing_at")
    if public_marketing_at is not None:
        parse_dt(public_marketing_at, "public_marketing_at")
    # When the CURRENTLY governing revision suppresses comp display, reject a
    # positive offer at creation.
    gov = calcs.governing_revision(assoc_id)
    if gov is not None and gov["comp_display_mode"] == "COMP_DISPLAY_OFF" \
       and offer_comp > 0:
        raise_err(ERR_COMP_DISPLAY_PROHIBITED,
                  "offer_comp_cents > 0 while governing revision is COMP_DISPLAY_OFF")
    if gov is not None and gov["comp_display_mode"] == "COMP_DISPLAY_OFF":
        offer_comp = 0
    listing = {
        "office_id": office_id,
        "listing_member_id": listing_member_id,
        "mls_number": data["mls_number"],
        "property_address": data["property_address"],
        "list_price_cents": price,
        "public_marketing_at": public_marketing_at,
        "status": "DRAFT",
        "accuracy_flag": "CLEAN",
        "policy_revision_id": None,
        "offer_comp_cents": offer_comp,
        "activated_at": None,
        "status_changed_at": None,
    }
    mint_common(listing)
    store.listings[listing["id"]] = listing
    return success_object(listing, 201)


@bp.route("/mls/associations/<assoc_id>/offices/<office_id>/listings/<listing_id>",
          methods=["GET"])
def get_listing_route(assoc_id, office_id, listing_id):
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    get_association(assoc_id)
    get_office(office_id, assoc_id)
    return success_object(get_listing(listing_id, office_id))


@bp.route("/mls/associations/<assoc_id>/offices/<office_id>/listings/<listing_id>/activate",
          methods=["POST"])
def activate_listing(assoc_id, office_id, listing_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    office = get_office(office_id, assoc_id)
    listing = get_listing(listing_id, office_id)
    check_not_merged(assoc)
    if listing["status"] not in ("DRAFT", "WITHDRAWN"):
        raise_err(ERR_INVALID_STATE,
                  "Only a DRAFT or WITHDRAWN listing may be activated")
    require_member_actor(user_id, listing["listing_member_id"])
    _check_listing_member_standing(listing)
    if office["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Office must be ACTIVE to activate a listing")

    activated_at = now()
    revision = _select_governing_revision(assoc_id, activated_at)
    # comp gate: reject (validation, not clamp) positive offer under OFF mode
    if revision["comp_display_mode"] == "COMP_DISPLAY_OFF" and \
       listing["offer_comp_cents"] > 0:
        raise_err(ERR_COMP_DISPLAY_PROHIBITED,
                  "offer_comp_cents > 0 while governing revision is COMP_DISPLAY_OFF")

    reactivation = listing["status"] == "WITHDRAWN"
    from_status = listing["status"]
    # Clear-coop audit only on first activation (public_marketing_at consumed).
    # Create the auto-citation BEFORE mutating the listing so a missing fine
    # schedule rejects the activation without leaving partial state.
    clear_coop_citation = None
    if not reactivation and listing.get("public_marketing_at"):
        if calcs.clear_coop_is_late(listing["public_marketing_at"], activated_at):
            clear_coop_citation = services.create_citation(
                assoc_id, listing["listing_member_id"],
                "CLEAR_COOP", "AUTO_LATE_LISTING", listing_id=listing["id"])
    listing["status"] = "ACTIVE"
    listing["activated_at"] = now_iso_str()
    listing["status_changed_at"] = now_iso_str()
    listing["policy_revision_id"] = revision["id"]
    services.record_status_change(listing, from_status, "ACTIVE",
                                  business_effective_at=now_iso_str(),
                                  audit=False)
    touch(listing)
    return success_object(listing)


@bp.route("/mls/associations/<assoc_id>/offices/<office_id>/listings/<listing_id>/status",
          methods=["POST"])
def change_listing_status(assoc_id, office_id, listing_id):
    user_id, _ = require_roles("Member")
    assoc = get_association(assoc_id)
    office = get_office(office_id, assoc_id)
    listing = get_listing(listing_id, office_id)
    check_not_merged(assoc)
    data = body()
    to_status = data.get("to_status")
    if to_status not in LISTING_STATUSES:
        raise_err(ERR_INVALID_REQUEST, "to_status must be a valid listing status")
    business_effective_at = data.get("business_effective_at")
    if business_effective_at is None:
        raise_err(ERR_INVALID_REQUEST,
                  "Missing required field 'business_effective_at'")
    parse_dt(business_effective_at, "business_effective_at")

    allowed = ALLOWED_STATUS_EDGES.get(listing["status"], set())
    if to_status not in allowed:
        raise_err(ERR_INVALID_STATE,
                  "Listing in status %s cannot transition to %s"
                  % (listing["status"], to_status))
    require_member_actor(user_id, listing["listing_member_id"])
    _check_listing_member_standing(listing)
    if to_status in ("WITHDRAWN", "CANCELLED") and \
       listing["accuracy_flag"] == "FLAGGED":
        raise_err(ERR_LISTING_FLAGGED,
                  "WITHDRAWN/CANCELLED attempted on a FLAGGED listing")

    from_status = listing["status"]
    audit = to_status in ("PENDING", "SOLD")
    services.record_status_change(listing, from_status, to_status,
                                  business_effective_at=business_effective_at,
                                  audit=audit)
    listing["status"] = to_status
    listing["status_changed_at"] = now_iso_str()
    touch(listing)
    return success_object(listing)


@bp.route("/mls/associations/<assoc_id>/offices/<office_id>/listings/<listing_id>/status-changes",
          methods=["GET"])
def list_status_changes(assoc_id, office_id, listing_id):
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    get_association(assoc_id)
    get_office(office_id, assoc_id)
    listing = get_listing(listing_id, office_id)
    items = [s for s in store.status_changes.values()
             if s["listing_id"] == listing["id"]]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


# ------------------------- association-scoped list -------------------------

@bp.route("/mls/associations/<assoc_id>/listings", methods=["GET"])
def list_assoc_listings(assoc_id):
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    get_association(assoc_id)
    office_ids = {o["id"] for o in store.offices.values()
                  if o["association_id"] == assoc_id}
    items = [l for l in store.listings.values() if l["office_id"] in office_ids]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    office_id = request.args.get("office_id")
    if office_id is not None:
        items = [l for l in items if l["office_id"] == office_id]
    member_id = request.args.get("listing_member_id")
    if member_id is not None:
        items = [l for l in items if l["listing_member_id"] == member_id]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


# ------------------------------ flat routes --------------------------------

def _flat_list_listings():
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    items = list(store.listings.values())
    office_id = request.args.get("office_id")
    if office_id is not None:
        items = [l for l in items if l["office_id"] == office_id]
    member_id = request.args.get("listing_member_id")
    if member_id is not None:
        items = [l for l in items if l["listing_member_id"] == member_id]
    status = request.args.get("status")
    if status is not None:
        items = [l for l in items if l["status"] == status]
    rev_id = request.args.get("policy_revision_id")
    if rev_id is not None:
        items = [l for l in items if l.get("policy_revision_id") == rev_id]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


# Registered twice (two scaffold rows with different documented filter sets);
# Flask dedupes identical rules, so one function suffices.
bp.add_url_rule("/mls/listings", "flat_list_listings", _flat_list_listings,
                methods=["GET"])


@bp.route("/mls/listings/<listing_id>", methods=["GET"])
def flat_get_listing(listing_id):
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    return success_object(get_listing(listing_id))


def _flat_list_status_changes():
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    items = list(store.status_changes.values())
    listing_id = request.args.get("listing_id")
    if listing_id is not None:
        items = [s for s in items if s["listing_id"] == listing_id]
    auto_cit = request.args.get("auto_citation_id")
    if auto_cit is not None:
        items = [s for s in items if s.get("auto_citation_id") == auto_cit]
    items, limit, offset, total = page(items)
    return success_list(items, limit, offset, total)


bp.add_url_rule("/mls/status-changes", "flat_list_status_changes",
                _flat_list_status_changes, methods=["GET"])


@bp.route("/mls/status-changes/<sc_id>", methods=["GET"])
def flat_get_status_change(sc_id):
    require_roles("AssociationStaff", "Member", "HearingPanelist")
    return success_object(get_status_change(sc_id))
