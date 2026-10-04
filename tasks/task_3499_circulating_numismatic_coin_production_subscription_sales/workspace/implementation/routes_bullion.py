"""Bullion issues, authorized purchasers, and allocation settlement
(PRD §3.8)."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import serialize
import store
from helpers import (auth, bad_request, body, envelope, err, list_response,
                     need_enum, need_int, need_num, need_str, no_undeclared,
                     not_found)

bp = Blueprint("bullion", __name__)

METALS = {"GOLD", "SILVER", "PLATINUM"}
TIERS = {"T1", "T2", "T3"}
TIER_BPS = {"T1": 300, "T2": 450, "T3": 625}


def _bracket_bps(total_oz):
    if total_oz < 100:
        return 200
    if total_oz < 500:
        return 100
    return 0


def _refresh_issue_status(issue):
    """ACTIVE -> SOLD_OUT when the pool is empty and nothing is OFFERED.
    (The reverse flip on expiry is handled by the clock sweep.)"""
    if issue["status"] == "ACTIVE" and issue["remaining_pool_units"] == 0:
        offered = any(a["status"] == "OFFERED" and a["bullion_issue_id"] == issue["id"]
                      for a in store.db["allocations"].values())
        if not offered:
            issue["status"] = "SOLD_OUT"
            store.bump(issue)


# ---------------------------------------------------------------------------
# Bullion issues
# ---------------------------------------------------------------------------
@bp.route("/mint/bullion-issues", methods=["POST"])
def create_issue():
    auth("ProgramManager")
    b = body()
    no_undeclared(b, {"name", "metal", "unit_weight_oz", "total_pool_units",
                      "offer_window_hours"})
    name = need_str(b, "name")
    metal = need_enum(b, "metal", METALS)
    weight = need_num(b, "unit_weight_oz")
    if weight <= 0:
        bad_request("unit_weight_oz must be strictly positive")
    pool = need_int(b, "total_pool_units")
    if pool <= 0:
        bad_request("total_pool_units must be strictly positive")
    window = need_int(b, "offer_window_hours")
    if window <= 0:
        bad_request("offer_window_hours must be strictly positive")
    issue = store.mint_entity({
        "name": name,
        "metal": metal,
        "unit_weight_oz": weight,
        "total_pool_units": pool,
        "remaining_pool_units": pool,
        "offer_window_hours": window,
        "status": "ACTIVE",
    })
    store.db["bullion_issues"][issue["id"]] = issue
    return envelope(serialize.bullion_issue(issue), status=201)


def _get_issue_or_404(iid):
    issue = store.db["bullion_issues"].get(iid)
    if issue is None:
        not_found("Bullion issue not found")
    return issue


@bp.route("/mint/bullion-issues/<iid>", methods=["GET"])
def get_issue(iid):
    auth("ProgramManager", "BullionDealer", "FinanceOfficer", "MintDirector",
         "PlatformAdmin")
    return envelope(serialize.bullion_issue(_get_issue_or_404(iid)))


# ---------------------------------------------------------------------------
# Authorized purchasers
# ---------------------------------------------------------------------------
@bp.route("/mint/authorized-purchasers", methods=["POST"])
def create_ap():
    auth("PlatformAdmin")
    b = body()
    no_undeclared(b, {"name", "tier"})
    name = need_str(b, "name")
    tier = need_enum(b, "tier", TIERS)
    ap = store.mint_entity({"name": name, "tier": tier, "status": "APPROVED"})
    store.db["authorized_purchasers"][ap["id"]] = ap
    return envelope(serialize.authorized_purchaser(ap), status=201)


AP_TRANSITIONS = {
    ("APPROVED", "SUSPENDED"),
    ("SUSPENDED", "APPROVED"),
    ("APPROVED", "TERMINATED"),
    ("SUSPENDED", "TERMINATED"),
}


@bp.route("/mint/authorized-purchasers/<aid>/set-status", methods=["POST"])
def set_ap_status(aid):
    auth("MintDirector")
    ap = store.db["authorized_purchasers"].get(aid)
    if ap is None:
        not_found("Authorized purchaser not found")
    b = body()
    to_status = b.get("to_status")
    if to_status is None:
        bad_request("Missing required field: to_status")
    # Any requested transition outside the declared set falls back to the
    # generic state error.
    if (ap["status"], to_status) not in AP_TRANSITIONS:
        err("ERR_INVALID_STATE_TRANSITION", 422,
            "No declared transition from %s to %s" % (ap["status"], to_status))
    no_undeclared(b, {"to_status"})
    ap["status"] = to_status
    store.bump(ap)
    return envelope(serialize.authorized_purchaser(ap))


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------
@bp.route("/mint/bullion-issues/<iid>/allocations", methods=["POST"])
def offer_allocation(iid):
    uid, _ = auth("ProgramManager")
    issue = _get_issue_or_404(iid)
    b = body()
    # Rung 5: OCC against the parent issue's version.
    expected = b.get("expected_bullion_issue_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool) \
                or expected != issue["version"]:
            err("ERR_STALE_VERSION", 412,
                "expected_bullion_issue_version does not match the current version")
    # Rung 6: the authorized purchaser must exist and be APPROVED.
    ap = None
    if isinstance(b.get("authorized_purchaser_id"), str):
        ap = store.db["authorized_purchasers"].get(b["authorized_purchaser_id"])
        if ap is None or ap["status"] != "APPROVED":
            err("ERR_AP_NOT_APPROVED", 422,
                "Authorized purchaser does not exist or is not APPROVED")
    # Rung 9: shape.
    no_undeclared(b, {"authorized_purchaser_id", "quantity_units",
                      "expected_bullion_issue_version"})
    if expected is None:
        bad_request("Missing required field: expected_bullion_issue_version")
    apid = need_str(b, "authorized_purchaser_id")
    if ap is None:
        ap = store.db["authorized_purchasers"].get(apid)
        if ap is None or ap["status"] != "APPROVED":
            err("ERR_AP_NOT_APPROVED", 422,
                "Authorized purchaser does not exist or is not APPROVED")
    qty = need_int(b, "quantity_units")
    if qty < 1:
        err("ERR_QUANTITY_INVALID", 400, "quantity_units must be at least 1")
    # Rung 10: pool sufficiency (a SOLD_OUT issue's remaining pool is zero,
    # so offers against it fail here).
    if qty > issue["remaining_pool_units"]:
        err("ERR_POOL_INSUFFICIENT", 422,
            "quantity_units exceeds the issue's remaining pool")
    expires_dt = store.now_dt() + timedelta(hours=issue["offer_window_hours"])
    a = store.mint_entity({
        "bullion_issue_id": issue["id"],
        "authorized_purchaser_id": apid,
        "quantity_units": qty,
        "offered_by_user_id": uid,
        "offer_expires_at": store.render_like_clock(expires_dt),
        "_expires_dt": expires_dt,
        "total_price_cents": None,
        "status": "OFFERED",
    })
    store.db["allocations"][a["id"]] = a
    issue["remaining_pool_units"] -= qty
    store.bump(issue)
    _refresh_issue_status(issue)
    return envelope(serialize.allocation(a), status=201)


@bp.route("/mint/allocations", methods=["GET"])
def list_allocations():
    auth("ProgramManager", "BullionDealer", "FinanceOfficer", "MintDirector",
         "PlatformAdmin")
    items = list(store.db["allocations"].values())
    for param in ("bullion_issue_id", "authorized_purchaser_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[param] == v]
    return list_response(items, serialize.allocation)


def _get_allocation_or_404(aid):
    a = store.db["allocations"].get(aid)
    if a is None:
        not_found("Allocation not found")
    return a


@bp.route("/mint/allocations/<aid>", methods=["GET"])
def get_allocation(aid):
    auth("ProgramManager", "BullionDealer", "FinanceOfficer", "MintDirector",
         "PlatformAdmin")
    return envelope(serialize.allocation(_get_allocation_or_404(aid)))


@bp.route("/mint/allocations/<aid>/confirm", methods=["POST"])
def confirm_allocation(aid):
    uid, _ = auth("BullionDealer")
    a = _get_allocation_or_404(aid)
    # Rung 3: the dealer confirms only its own allocations.
    if a["authorized_purchaser_id"] != uid:
        err("ERR_FORBIDDEN_OWNERSHIP", 403,
            "Allocation was offered to another authorized purchaser")
    # Rung 5: only an OFFERED allocation confirms. A lapsed offer is already
    # EXPIRED (the clock sweep expires offers eagerly), so it fails here.
    if a["status"] != "OFFERED":
        err("ERR_ALLOCATION_NOT_CONFIRMABLE", 422,
            "Only an OFFERED allocation may be confirmed")
    # Rung 6: firm still APPROVED, and a current spot price for the metal.
    ap = store.db["authorized_purchasers"].get(a["authorized_purchaser_id"])
    if ap is None or ap["status"] != "APPROVED":
        err("ERR_AP_NOT_APPROVED", 422,
            "Authorized purchaser does not exist or is not APPROVED")
    issue = store.db["bullion_issues"][a["bullion_issue_id"]]
    spot = store.db["spot_prices"].get(issue["metal"])
    if spot is None:
        err("ERR_SPOT_PRICE_MISSING", 422,
            "No current spot price established for %s" % issue["metal"])
    # Rung 9: shape.
    no_undeclared(body(), set())
    # Spot plus premium: tier component plus a size bracket on total weight;
    # a single round-half-up to whole cents at the very end.
    total_oz = Decimal(a["quantity_units"]) * issue["unit_weight_oz"]
    premium_bps = TIER_BPS[ap["tier"]] + _bracket_bps(total_oz)
    price = (total_oz * Decimal(spot)
             * (Decimal(1) + Decimal(premium_bps) / Decimal(10000)))
    a["total_price_cents"] = int(price.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    a["status"] = "CONFIRMED"
    store.bump(a)
    _refresh_issue_status(issue)
    return envelope(serialize.allocation(a))


@bp.route("/mint/allocations/<aid>/settle", methods=["POST"])
def settle_allocation(aid):
    uid, _ = auth("FinanceOfficer")
    a = _get_allocation_or_404(aid)
    if a["status"] != "CONFIRMED":
        err("ERR_ALLOCATION_NOT_SETTLABLE", 422,
            "Only a CONFIRMED allocation may be settled")
    if uid == a["offered_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 422,
            "The settler must differ from the offering manager")
    no_undeclared(body(), set())
    a["status"] = "SETTLED"
    store.bump(a)
    issue = store.db["bullion_issues"].get(a["bullion_issue_id"])
    if issue is not None:
        _refresh_issue_status(issue)
    return envelope(serialize.allocation(a))
