"""ReplacementOrder endpoints (PRD 3.4): create-with-supersede (OCC on the
site), dye-lot match, completion, cancellation."""
from flask import Blueprint, request

from auth import authenticate, authorize, forbid
from calcs import dye_lot_match, replacement_quote, zone_code_in_use
from constants import ALL_ROLES, ORDER_REASONS
from envelope import list_endpoint, success
from errors import ApiError
from serialize import serialize_order
from store import STORE, new_common, touch
from util import get_body, is_int, req_enum, req_str

bp = Blueprint("orders", __name__)

NON_TERMINAL_ORDER_STATES = ("DRAFT", "MATCHED", "MATCH_FAILED")


def release_reservation(store, order):
    """MATCHED cancellation side effect: the reserved area returns to the
    matched batch; a batch at EXHAUSTED reverts to RELEASED as availability
    returns."""
    if order["status"] == "MATCHED" and order["matched_batch_id"]:
        batch = store.batches.get(order["matched_batch_id"])
        zone = store.zones.get(order["zone_id"])
        if batch is not None and zone is not None:
            batch["available_m2"] += zone["area_m2"]
            if batch["status"] == "EXHAUSTED" and batch["available_m2"] > 0:
                batch["status"] = "RELEASED"
            touch(store, batch)


def cancel_order(store, order):
    """Shared by the cancel endpoint, order supersession, and the site
    decommission cascade."""
    release_reservation(store, order)
    order["status"] = "CANCELLED"
    touch(store, order)


def _installer_order(order_id, uid):
    """Priority 3 ownership via the order's site, then priority 4."""
    o = STORE.orders.get(order_id)
    if o is not None:
        site = STORE.sites.get(o["site_id"])
        if site is not None and uid != site["contractor_name"]:
            forbid("X-User-ID must equal the site's contractor_name")
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Replacement order does not exist")
    return o


@bp.route("/carpetloop/replacement-orders", methods=["POST"])
def create_order():
    uid, role = authenticate()
    authorize(role, {"Specifier"})
    body = get_body()
    # Priority 4, canonical order: site before zone.
    site = None
    if body.get("site_id") is not None:
        site = STORE.sites.get(body["site_id"])
        if site is None:
            raise ApiError("ERR_SITE_NOT_FOUND", 404, "Site does not exist")
    zone = None
    if body.get("zone_id") is not None:
        zone = STORE.zones.get(body["zone_id"])
        if zone is None:
            raise ApiError("ERR_ZONE_NOT_FOUND", 404, "Zone does not exist")
    # Priority 6: the zone must be IN_SERVICE.
    if zone is not None and zone["status"] != "IN_SERVICE":
        raise ApiError("ERR_ZONE_NOT_IN_SERVICE", 409, "Zone is not IN_SERVICE")
    # Priority 7: OCC — expected_site_version equals the site's current version.
    esv = body.get("expected_site_version")
    if is_int(esv) and site is not None and esv != site["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_site_version does not match the site's version"
        )
    # Priority 9: the zone must belong to the named site.
    if zone is not None and site is not None and zone["site_id"] != site["id"]:
        raise ApiError(
            "ERR_ZONE_SITE_MISMATCH", 422, "zone_id belongs to a different site than site_id"
        )
    # Priority 11: request shape (expected_site_version is non-optional, PRD 2.7).
    req_str(body, "site_id")
    req_str(body, "zone_id")
    reason = req_enum(body, "reason", ORDER_REASONS)
    new_zone_code = req_str(body, "new_zone_code")
    if not is_int(esv):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "expected_site_version is required and must be an integer"
        )
    # Supersede: an existing non-terminal order on the same zone is cancelled,
    # releasing any reservation per the cancellation side effects.
    for o in list(STORE.orders.values()):
        if o["zone_id"] == zone["id"] and o["status"] in NON_TERMINAL_ORDER_STATES:
            cancel_order(STORE, o)
    # The create advances the site's version.
    touch(STORE, site)
    o = new_common(STORE)
    o.update(
        {
            "site_id": site["id"],
            "zone_id": zone["id"],
            "reason": reason,
            "new_zone_code": new_zone_code,
            "matched_batch_id": None,
            "quoted_cost_cents": None,
            "status": "DRAFT",
            "created_by": uid,
        }
    )
    STORE.orders[o["id"]] = o
    return success(serialize_order(o), 201)


@bp.route("/carpetloop/replacement-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    o = STORE.orders.get(order_id)
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Replacement order does not exist")
    return success(serialize_order(o), 200)


@bp.route("/carpetloop/replacement-orders", methods=["GET"])
def list_orders():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    filters = {}
    for f in ("site_id", "zone_id", "matched_batch_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters[f] = v
    return list_endpoint(STORE.orders.values(), request.args, filters, serialize_order)


@bp.route("/carpetloop/replacement-orders/<order_id>/match", methods=["POST"])
def match_order(order_id):
    uid, role = authenticate()
    authorize(role, {"Installer"})
    o = _installer_order(order_id, uid)
    # Priority 5: match exists from DRAFT and from MATCH_FAILED (re-match).
    if o["status"] not in ("DRAFT", "MATCH_FAILED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be matched from its state")
    zone = STORE.zones.get(o["zone_id"])
    # Priority 6: the zone must still be IN_SERVICE.
    if zone is None or zone["status"] != "IN_SERVICE":
        raise ApiError("ERR_ZONE_NOT_IN_SERVICE", 409, "Zone is not IN_SERVICE")
    zone_batch = STORE.batches.get(zone["batch_id"])
    candidate = dye_lot_match(STORE, zone, zone_batch)
    if candidate is None:
        # Empty-pool fallback: no side effects, matched_batch_id stays null.
        o["status"] = "MATCH_FAILED"
        touch(STORE, o)
        return success(serialize_order(o), 200)
    o["matched_batch_id"] = candidate["id"]
    o["quoted_cost_cents"] = replacement_quote(zone, zone_batch, candidate)
    o["status"] = "MATCHED"
    # Reservation: debit the matched batch; exhaust it if availability hits 0.
    candidate["available_m2"] -= zone["area_m2"]
    if candidate["available_m2"] == 0:
        candidate["status"] = "EXHAUSTED"
    touch(STORE, candidate)
    touch(STORE, o)
    return success(serialize_order(o), 200)


@bp.route("/carpetloop/replacement-orders/<order_id>/complete", methods=["POST"])
def complete_order(order_id):
    uid, role = authenticate()
    authorize(role, {"Installer"})
    o = _installer_order(order_id, uid)
    # Priority 6: the order must be MATCHED, then the zone still IN_SERVICE —
    # the zone check is evaluated before any fiscal check (PRD 3.4).
    if o["status"] != "MATCHED":
        raise ApiError("ERR_ORDER_NOT_MATCHED", 409, "Order is not MATCHED")
    zone = STORE.zones.get(o["zone_id"])
    if zone is None or zone["status"] != "IN_SERVICE":
        raise ApiError("ERR_ZONE_NOT_IN_SERVICE", 409, "Zone is not IN_SERVICE")
    site = STORE.sites.get(o["site_id"])
    # Priority 11: new_zone_code unique among the site's IN_SERVICE zones at
    # completion time (constraint guards precede fiscal guards, PRD 2.8).
    if zone_code_in_use(STORE, site["id"], o["new_zone_code"], exclude_zone_id=zone["id"]):
        raise ApiError(
            "ERR_ZONE_CODE_CONFLICT",
            409,
            "new_zone_code duplicates an IN_SERVICE zone at this site",
        )
    # Priority 12: the site's remaining replacement budget.
    if site["spent_replacement_cents"] + o["quoted_cost_cents"] > site[
        "annual_replacement_budget_cents"
    ]:
        raise ApiError(
            "ERR_REPLACEMENT_BUDGET_EXCEEDED",
            422,
            "Completion exceeds the site's annual replacement budget",
        )
    zone["status"] = "REPLACED"
    touch(STORE, zone)
    new_zone = new_common(STORE)
    new_zone.update(
        {
            "site_id": site["id"],
            "batch_id": o["matched_batch_id"],
            "zone_code": o["new_zone_code"],
            "area_m2": zone["area_m2"],
            "status": "IN_SERVICE",
        }
    )
    STORE.zones[new_zone["id"]] = new_zone
    site["spent_replacement_cents"] += o["quoted_cost_cents"]
    touch(STORE, site)
    # The matched reservation becomes permanent: no availability change, though
    # the batch still moves to EXHAUSTED if its available_m2 stands at zero.
    batch = STORE.batches.get(o["matched_batch_id"])
    if batch is not None and batch["status"] == "RELEASED" and batch["available_m2"] == 0:
        batch["status"] = "EXHAUSTED"
        touch(STORE, batch)
    o["status"] = "COMPLETED"
    touch(STORE, o)
    return success(serialize_order(o), 200)


@bp.route("/carpetloop/replacement-orders/<order_id>/cancel", methods=["POST"])
def cancel_order_endpoint(order_id):
    uid, role = authenticate()
    authorize(role, {"Specifier"})
    o = STORE.orders.get(order_id)
    # Priority 3: Specifier ownership via the order's created_by.
    if o is not None and uid != o["created_by"]:
        forbid("X-User-ID must equal the order's created_by")
    if o is None:
        raise ApiError("ERR_ORDER_NOT_FOUND", 404, "Replacement order does not exist")
    # Priority 5: the cancel endpoint exists from DRAFT and MATCHED.
    if o["status"] not in ("DRAFT", "MATCHED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order cannot be cancelled from its state")
    cancel_order(STORE, o)
    return success(serialize_order(o), 200)
