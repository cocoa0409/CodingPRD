"""AisleAssignments, Purchases, Refunds, and the logical clock."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from db import db, parse_ts
from errors import (
    ApiError,
    not_found,
    invalid_request,
    invalid_state,
    stale_version,
    unauthorized,
)
from middleware import (
    require_roles,
    get_json_body,
    check_unknown_fields,
    require_fields,
    check_int_ge,
    check_string,
    check_bool,
)
from response import success_object
from services.core import (
    REFUND_WINDOW_DAYS,
    TIER_DISCOUNT_PCT,
    TIER_RANK,
    active_events_for_lot,
    event_covers_now,
    maybe_close_sold_out,
    next_seq,
    qty_sold,
    round_half_up_int,
    run_clock_side_effects,
    serialize_assignment,
    serialize_purchase,
    touch,
)
from routes.refdata import new_entity, ANY_ROLE

bp = Blueprint("sales", __name__)


def _get_store(store_id: str) -> dict:
    s = db.stores.get(store_id)
    if s is None:
        raise not_found("Store not found: %s" % store_id)
    return s


def _get_lot(lot_id: str) -> dict:
    lot = db.lots.get(lot_id)
    if lot is None:
        raise not_found("BuyLot not found: %s" % lot_id)
    return lot


def _covering_assignment(store_id: str, lot_id: str):
    """ACTIVE assignment covering now: valid_from <= now AND
    (valid_to IS NULL OR now <= valid_to) — PRD §3.6 layout gate."""
    now = db.now()
    for a in db.aisle_assignments.values():
        if a["store_id"] != store_id or a["lot_id"] != lot_id or a["status"] != "ACTIVE":
            continue
        vf = parse_ts(a["valid_from"])
        vt = parse_ts(a["valid_to"]) if a["valid_to"] is not None else None
        if vf is not None and vf <= now and (vt is None or now <= vt):
            return a
    return None


def _received_allocation(store_id: str, lot_id: str):
    for a in db.allocations.values():
        if a["store_id"] == store_id and a["lot_id"] == lot_id and a["status"] == "RECEIVED":
            return a
    return None


def _assignments_conflict(a_store: str, a_code: str, vf, vt) -> list:
    """Closed-interval conflicts: touching endpoints conflict (PRD §3.9).
    Overlap iff vf <= existing.valid_to AND existing.valid_from <= vt,
    with None valid_to treated as open-ended (infinity)."""
    conflicts = []
    for a in db.aisle_assignments.values():
        if a["store_id"] != a_store or a["aisle_code"] != a_code or a["status"] != "ACTIVE":
            continue
        evf = parse_ts(a["valid_from"])
        evt = parse_ts(a["valid_to"]) if a["valid_to"] is not None else None
        if evf is None:
            continue
        new_end_ok = True
        if evt is not None and vf > evt:
            new_end_ok = False  # new starts strictly after existing ends
        old_end_ok = True
        if vt is not None and evf > vt:
            old_end_ok = False  # existing starts strictly after new ends
        if new_end_ok and old_end_ok:
            conflicts.append(a)
    return conflicts


# ---------------------------------------------------------------------------
# AisleAssignments
# ---------------------------------------------------------------------------

@bp.post("/stores/<store_id>/aisle-assignments")
def create_assignment(store_id):
    require_roles(["StoreManager"])
    store = _get_store(store_id)
    body = get_json_body()
    allowed = [
        "lot_id", "aisle_code", "daily_unit_limit", "expected_store_version",
        "valid_from", "valid_to", "supersede",
    ]
    check_unknown_fields(body, allowed)
    require_fields(body, ["lot_id", "aisle_code", "daily_unit_limit", "expected_store_version"])
    check_string(body, "aisle_code")
    check_int_ge(body, "daily_unit_limit", 1)
    if not isinstance(body["expected_store_version"], int) or isinstance(
        body["expected_store_version"], bool
    ):
        raise invalid_request("expected_store_version must be an integer")
    if "supersede" in body:
        check_bool(body, "supersede")
    lot = db.lots.get(body["lot_id"])
    if lot is None:
        raise not_found("BuyLot not found: %s" % body["lot_id"])

    if "valid_from" in body and body["valid_from"] is not None:
        vf = parse_ts(body["valid_from"])
        if vf is None:
            raise invalid_request("valid_from must be an ISO 8601 timestamp")
    else:
        vf = db.now()
    if "valid_to" in body and body["valid_to"] is not None:
        vt = parse_ts(body["valid_to"])
        if vt is None:
            raise invalid_request("valid_to must be an ISO 8601 timestamp")
    else:
        vt = None

    # Safety gate (§2.10) then store standing (§3.1), per validation priority.
    if lot["safety_status"] != "CLEARED":
        raise ApiError("ERR_LOT_SAFETY_BLOCKED", "The lot has not passed safety screening", 409)
    if store["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_SUSPENDED", "The store is suspended", 409)

    supersede = bool(body.get("supersede", False))
    conflicts = _assignments_conflict(store_id, body["aisle_code"], vf, vt)
    if conflicts and not supersede:
        raise ApiError(
            "ERR_AISLE_WINDOW_CONFLICT",
            "An ACTIVE assignment already covers this aisle window",
            409,
        )

    # Advertising-law gate vs store jurisdiction (PRD §3.5).
    jr = db.jurisdiction_rules[store["jurisdiction_id"]]
    if jr["comparison_rule"] == "COMPARISON_PROHIBITED" and lot["advertises_comparison"]:
        raise ApiError(
            "ERR_COMPARISON_ADVERTISING_PROHIBITED",
            "Comparison advertising is prohibited in the store's jurisdiction",
            422,
        )

    # OCC (PRD §2.8) — after auth/existence, as its own step.
    if body["expected_store_version"] != store["version"]:
        raise stale_version("expected_store_version does not match the store's current version")

    from db import format_ts

    if supersede:
        for prior in conflicts:
            prior["status"] = "SUPERSEDED"
            prior["valid_to"] = format_ts(vf - timedelta(seconds=1))
            touch(prior)

    a = new_entity()
    a.update({
        "store_id": store_id,
        "lot_id": body["lot_id"],
        "aisle_code": body["aisle_code"],
        "daily_unit_limit": body["daily_unit_limit"],
        "valid_from": format_ts(vf),
        "valid_to": format_ts(vt) if vt is not None else None,
        "status": "ACTIVE",
    })
    db.aisle_assignments[a["id"]] = a
    touch(store)  # creation bumps the store's version (PRD §3.9)
    return success_object(serialize_assignment(a), 201)


# ---------------------------------------------------------------------------
# Purchases
# ---------------------------------------------------------------------------

@bp.post("/stores/<store_id>/purchases")
def create_purchase(store_id):
    role, user_id = require_roles(["ClubMember", "Anonymous"])
    store = _get_store(store_id)
    body = get_json_body()
    check_unknown_fields(body, ["lot_id", "qty", "member_id"])
    require_fields(body, ["lot_id", "qty"])
    check_int_ge(body, "qty", 1)
    if "member_id" in body and body["member_id"] is not None:
        check_string(body, "member_id")
    member_id = body.get("member_id")

    # Authorization refinements (PRD §2.1).
    if role == "Anonymous" and member_id is not None:
        raise unauthorized("Anonymous callers must not supply member_id")
    if role == "ClubMember" and member_id is not None and user_id != member_id:
        raise unauthorized("A ClubMember may only transact under their own member_id")

    lot = db.lots.get(body["lot_id"])
    if lot is None:
        raise not_found("BuyLot not found: %s" % body["lot_id"])
    member = None
    if member_id is not None:
        member = db.members.get(member_id)
        if member is None:
            raise not_found("LoyaltyMember not found: %s" % member_id)

    # 1. Lifecycle-state gate: ON_SALE / DISPOSITION_REVIEW / BLOCKED pass through.
    if lot["commercial_status"] not in ("ON_SALE", "DISPOSITION_REVIEW", "BLOCKED"):
        raise invalid_state("The lot is not in a sellable state")
    # 2. Safety gate.
    if lot["safety_status"] != "CLEARED":
        raise ApiError("ERR_LOT_SAFETY_BLOCKED", "The lot has not passed safety screening", 409)
    # 3. Store standing.
    if store["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_SUSPENDED", "The store is suspended", 409)
    # 4. Deal-dependent layout gate.
    assignment = _covering_assignment(store_id, lot["id"])
    if assignment is None:
        raise ApiError(
            "ERR_NO_ACTIVE_ASSIGNMENT",
            "No ACTIVE aisle assignment covers now for this store and lot",
            409,
        )
    # 5. Member standing.
    if member is not None and member["status"] != "ACTIVE":
        raise ApiError("ERR_MEMBER_SUSPENDED", "The member is suspended", 409)

    # 6-7. Early-access event gates.
    active_events = active_events_for_lot(lot["id"])
    covering_event = None
    if active_events:
        if member_id is None:
            raise ApiError(
                "ERR_EARLY_ACCESS_MEMBER_ONLY",
                "A member_id is required while an early-access event is active",
                403,
            )
        for ev in active_events:
            if TIER_RANK[member["tier"]] >= TIER_RANK[ev["min_tier"]]:
                covering_event = ev
                break
        if covering_event is None:
            raise ApiError(
                "ERR_MEMBER_TIER_TOO_LOW",
                "The member's tier is below the active event's minimum tier",
                403,
            )

    # Pricing variant and discount percent (pinned order, PRD §3.6).
    if member_id is None:
        pct = 0
        pricing_variant = "GUEST"
    elif covering_event is not None:
        pct = TIER_DISCOUNT_PCT[member["tier"]] + covering_event["extra_discount_pct"]
        pricing_variant = "EVENT"
    else:
        pct = TIER_DISCOUNT_PCT[member["tier"]]
        pricing_variant = "STANDARD"

    # 8. Jurisdictional cap gate (== cap allowed).
    if member_id is not None:
        jr = db.jurisdiction_rules[store["jurisdiction_id"]]
        if pct > jr["member_discount_cap_pct"]:
            raise ApiError(
                "ERR_MEMBER_DISCOUNT_CAP_EXCEEDED",
                "Combined member discount exceeds the jurisdictional cap",
                422,
            )

    # 9. Quantity-limited signage: units already purchased for (store, lot)
    # on the current UTC day by this member (or the shared guest bucket) +
    # qty <= daily_unit_limit.
    now = db.now()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = day_start + timedelta(days=1)
    used = 0
    for p in db.purchases.values():
        if p["store_id"] != store_id or p["lot_id"] != lot["id"]:
            continue
        if p["status"] != "COMPLETED":
            continue
        if p["member_id"] != member_id:
            continue
        created = parse_ts(p["created_at"])
        if created is not None and day_start <= created < day_end:
            used += p["qty"]
    if used + body["qty"] > assignment["daily_unit_limit"]:
        raise ApiError(
            "ERR_SIGNAGE_LIMIT_EXCEEDED",
            "The daily unit limit for this signage would be exceeded",
            409,
        )

    # 10. Store shelf stock.
    allocation = _received_allocation(store_id, lot["id"])
    on_hand = allocation["store_on_hand_qty"] if allocation is not None else 0
    if body["qty"] > on_hand:
        raise ApiError(
            "ERR_INSUFFICIENT_STORE_STOCK",
            "The store does not hold enough on-hand units for this lot",
            409,
        )

    # Pinned rounding: per-unit half-up, then integer line total.
    unit_price_cents = round_half_up_int(
        Decimal(lot["retail_price_cents"]) * Decimal(100 - pct) / Decimal(100)
    )
    line_total_cents = unit_price_cents * body["qty"]

    p = new_entity()
    p.update({
        "store_id": store_id,
        "lot_id": lot["id"],
        "member_id": member_id,
        "qty": body["qty"],
        "pricing_variant": pricing_variant,
        "discount_pct_applied": pct,
        "unit_price_cents": unit_price_cents,
        "line_total_cents": line_total_cents,
        "status": "COMPLETED",
        "refunded_at": None,
        "_allocation_id": allocation["id"] if allocation is not None else None,
    })
    db.purchases[p["id"]] = p
    allocation["store_on_hand_qty"] -= body["qty"]
    touch(allocation)
    maybe_close_sold_out(lot)
    return success_object(serialize_purchase(p), 201)


@bp.get("/purchases/<pid>")
def get_purchase(pid):
    require_roles(ANY_ROLE)
    p = db.purchases.get(pid)
    if p is None:
        raise not_found("Purchase not found: %s" % pid)
    return success_object(serialize_purchase(p))


@bp.post("/purchases/<pid>/refund")
def refund_purchase(pid):
    require_roles(["StoreManager"])
    p = db.purchases.get(pid)
    if p is None:
        raise not_found("Purchase not found: %s" % pid)
    # State gate (PRD §3.6): purchase must be COMPLETED; lot must not be
    # terminally liquidated or scrapped.
    if p["status"] != "COMPLETED":
        raise invalid_state("Only a COMPLETED purchase can be refunded")
    lot = db.lots.get(p["lot_id"])
    if lot is not None and lot["commercial_status"] in ("CLOSED_LIQUIDATED", "CLOSED_SCRAPPED"):
        raise invalid_state("Purchases of a liquidated or scrapped lot cannot be refunded")
    # Refund window: now - created_at <= 14 days; exactly 14 days allowed.
    created = parse_ts(p["created_at"])
    now = db.now()
    if created is not None and (now - created) > timedelta(days=REFUND_WINDOW_DAYS):
        raise ApiError(
            "ERR_REFUND_WINDOW_EXPIRED",
            "Refund attempted more than 14 days after purchase",
            409,
        )
    p["status"] = "REFUNDED"
    p["refunded_at"] = db.now_iso()
    touch(p)
    alloc = db.allocations.get(p.get("_allocation_id") or "")
    if alloc is None:
        alloc = _received_allocation(p["store_id"], p["lot_id"])
    if alloc is not None:
        alloc["store_on_hand_qty"] += p["qty"]
        touch(alloc)
    if lot is not None and lot["commercial_status"] == "CLOSED_SOLD_OUT":
        lot["commercial_status"] = "ON_SALE"
        touch(lot)
    return success_object(serialize_purchase(p))


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles(["Admin"])
    body = get_json_body()
    check_unknown_fields(body, ["to_iso8601"])
    require_fields(body, ["to_iso8601"])
    target = parse_ts(body["to_iso8601"])
    if target is None:
        raise invalid_request("to_iso8601 must be an ISO 8601 timestamp")
    db.clock = target
    run_clock_side_effects()
    return success_object({"current_utc": db.now_iso()})
