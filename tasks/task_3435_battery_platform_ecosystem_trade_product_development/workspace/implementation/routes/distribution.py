"""Channel partners and distribution listings: creation with OCC and
supersession, and the activation/relist/ending transitions with their gates."""
from flask import Blueprint, request

import db
from constants import (
    API_PREFIX,
    CHANNEL_TYPES,
    HOME_CENTER_ALLOCATION_CAP,
    INDUSTRIAL_ALLOCATION_CAP,
    LISTING_STATUSES,
    PRO_PACK_CAPACITY_THRESHOLD_WH,
    ROLES,
)
from errors import fail
from helpers import (
    authorize,
    body,
    check_enum,
    check_int,
    ok_list,
    ok_object,
    pagination,
    page_window,
    req_field,
    req_int,
    req_str,
)
from services import (
    bump,
    make_entity,
    partner_active_allocation,
    partner_has_suspended,
    supersede_prior_listing,
)
from views import view_listing, view_partner

bp = Blueprint("distribution", __name__)

_PRODUCT_FIELDS = ("tool_model_id", "battery_pack_id", "charger_id")
_PRODUCT_STORES = {"tool_model_id": "tools", "battery_pack_id": "packs", "charger_id": "chargers"}
_CAPS = {"HOME_CENTER": HOME_CENTER_ALLOCATION_CAP,
         "INDUSTRIAL_DISTRIBUTOR": INDUSTRIAL_ALLOCATION_CAP}

# Manual listing edges (ACTIVE -> SUSPENDED is system-only; ENDED is terminal).
LISTING_EDGES = {
    "PROPOSED": {"ACTIVE", "ENDED"},
    "ACTIVE": {"ENDED"},
    "SUSPENDED": {"ACTIVE", "ENDED"},
    "ENDED": set(),
}


@bp.route(f"{API_PREFIX}/channel-partners", methods=["POST"])
def create_partner():
    authorize(["PlatformAdmin"])
    data = body()
    name = req_str(data, "name")
    channel_type = check_enum(req_field(data, "channel_type"), "channel_type", CHANNEL_TYPES)
    region = req_str(data, "region")
    partner = make_entity({"name": name, "channel_type": channel_type, "region": region})
    db.STORE["partners"][partner["id"]] = partner
    return ok_object(view_partner(partner), 201)


def _get_listing_or_404(listing_id):
    listing = db.STORE["listings"].get(listing_id)
    if listing is None:
        fail("ERR_NOT_FOUND", "Distribution listing not found")
    return listing


@bp.route(f"{API_PREFIX}/listings", methods=["POST"])
def create_listing():
    user_id, _ = authorize(["ChannelManager"])
    data = body()
    # Priority 4: partner existence, then Priority 3 ownership.
    partner_id = req_field(data, "channel_partner_id")
    partner = db.STORE["partners"].get(partner_id)
    if partner is None:
        fail("ERR_NOT_FOUND", "channel_partner_id does not reference an existing partner")
    if user_id != partner_id:
        fail("ERR_FORBIDDEN", "X-User-ID does not match channel_partner_id")
    # Priority 4: existence of provided product FKs, left to right
    provided = {f: data.get(f) for f in _PRODUCT_FIELDS if data.get(f) is not None}
    for f in _PRODUCT_FIELDS:
        if f in provided and db.STORE[_PRODUCT_STORES[f]].get(provided[f]) is None:
            fail("ERR_NOT_FOUND", f"{f} does not reference an existing resource")
    # Priority 5: exactly one product FK; ranges; OCC field required
    if len(provided) != 1:
        fail("ERR_VALIDATION",
             "Exactly one of tool_model_id, battery_pack_id, charger_id must be set")
    wholesale_price_cents = req_int(data, "wholesale_price_cents", minimum=0)
    allocation_qty = req_int(data, "allocation_qty", minimum=1)
    expected = check_int(req_field(data, "expected_channel_partner_version"),
                         "expected_channel_partner_version")
    # Priority 8: optimistic concurrency on the partner's version
    if expected != partner["version"]:
        fail("ERR_STALE_VERSION", "expected_channel_partner_version does not match")
    # Priority 16: partner suspension gate
    if partner_has_suspended(partner_id):
        fail("ERR_PARTNER_HAS_SUSPENDED_LISTINGS",
             "Partner has SUSPENDED listings; re-list or end them first")
    product_field, product_id = next(iter(provided.items()))
    fields = {
        "channel_partner_id": partner_id,
        "tool_model_id": None,
        "battery_pack_id": None,
        "charger_id": None,
        "wholesale_price_cents": wholesale_price_cents,
        "allocation_qty": allocation_qty,
        "status": "PROPOSED",
        "requires_relist_ack": False,
        "superseded_by_listing_id": None,
    }
    fields[product_field] = product_id
    listing = make_entity(fields)
    db.STORE["listings"][listing["id"]] = listing
    supersede_prior_listing(partner_id, product_field, product_id, listing)
    bump(partner)  # listing creation advances the partner's version
    return ok_object(view_listing(listing), 201)


@bp.route(f"{API_PREFIX}/listings/<listing_id>", methods=["GET"])
def get_listing(listing_id):
    authorize(ROLES)
    return ok_object(view_listing(_get_listing_or_404(listing_id)))


@bp.route(f"{API_PREFIX}/listings", methods=["GET"])
def list_listings():
    authorize(ROLES)
    limit, offset = pagination()
    items = list(db.STORE["listings"].values())
    for f in ("channel_partner_id", "tool_model_id", "battery_pack_id", "charger_id",
              "superseded_by_listing_id"):
        v = request.args.get(f)
        if v is not None:
            items = [l for l in items if l.get(f) == v]
    page, total = page_window(items, limit, offset)
    return ok_list([view_listing(l) for l in page], total, limit, offset)


def _activation_gates(listing, partner):
    """Gates for PROPOSED -> ACTIVE and SUSPENDED -> ACTIVE, in priority order."""
    # Priority 6 (product state): tool must be LAUNCHED; a RECALLED pack is a
    # terminal-state lockdown -> ERR_INVALID_STATE.
    pack = None
    if listing.get("tool_model_id") is not None:
        tool = db.STORE["tools"][listing["tool_model_id"]]
        if tool["stage"] != "LAUNCHED":
            fail("ERR_INVALID_STATE", "Tool model is not LAUNCHED")
    elif listing.get("battery_pack_id") is not None:
        pack = db.STORE["packs"][listing["battery_pack_id"]]
        if pack["certification_status"] == "RECALLED":
            fail("ERR_INVALID_STATE", "Battery pack is RECALLED")
    # Priority 9: safety hold
    if pack is not None and pack["safety_hold"]:
        fail("ERR_SAFETY_HOLD", "Battery pack is on safety_hold")
    # Priority 13: pack certification gate
    if pack is not None and pack["certification_status"] != "CERTIFIED":
        fail("ERR_CERTIFICATION_REQUIRED", "Battery pack is not CERTIFIED")
    # Priority 14: channel segmentation (HOME_CENTER only)
    if partner["channel_type"] == "HOME_CENTER":
        if listing.get("tool_model_id") is not None:
            tool = db.STORE["tools"][listing["tool_model_id"]]
            if tool["tier"] == "TRADE_SPECIALIST":
                fail("ERR_SEGMENT_NOT_ALLOWED",
                     "HOME_CENTER may not activate TRADE_SPECIALIST tools")
        if pack is not None and pack["rated_capacity_wh"] > PRO_PACK_CAPACITY_THRESHOLD_WH:
            fail("ERR_SEGMENT_NOT_ALLOWED",
                 "HOME_CENTER may not activate packs above the pro capacity threshold")
    # Priority 23: allocation cap (inclusive)
    cap = _CAPS[partner["channel_type"]]
    if partner_active_allocation(partner["id"]) + listing["allocation_qty"] > cap:
        fail("ERR_ALLOCATION_CAP_EXCEEDED", "Activation would exceed the channel cap")


@bp.route(f"{API_PREFIX}/listings/<listing_id>/transition", methods=["POST"])
def transition_listing(listing_id):
    user_id, _ = authorize(["ChannelManager"])
    listing = _get_listing_or_404(listing_id)
    if user_id != listing["channel_partner_id"]:
        fail("ERR_FORBIDDEN", "X-User-ID does not match the listing's channel_partner_id")
    data = body()
    to_status = check_enum(req_field(data, "to_status"), "to_status", LISTING_STATUSES)
    if to_status not in LISTING_EDGES[listing["status"]]:
        fail("ERR_INVALID_STATE", f"Cannot transition {listing['status']} -> {to_status}")
    if to_status == "ACTIVE":
        partner = db.STORE["partners"][listing["channel_partner_id"]]
        _activation_gates(listing, partner)
    was_suspended = listing["status"] == "SUSPENDED"
    listing["status"] = to_status
    if to_status == "ACTIVE" and was_suspended:
        # Relisting implicitly acknowledges the safety bulletin.
        listing["requires_relist_ack"] = False
    bump(listing)
    return ok_object(view_listing(listing))
