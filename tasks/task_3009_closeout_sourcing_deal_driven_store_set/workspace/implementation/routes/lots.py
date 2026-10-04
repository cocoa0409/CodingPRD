"""BuyLots: CRUD, screenings, regrade, pricing, allocations, events, dispositions."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from db import db, parse_ts
from errors import ApiError, not_found, invalid_request, invalid_state, stale_version
from middleware import (
    require_roles,
    get_json_body,
    check_unknown_fields,
    require_fields,
    check_enum,
    check_int_range,
    check_int_ge,
    check_string,
    check_bool,
    parse_pagination,
)
from response import success_object, success_list
from services.core import (
    STORE_TIER_RANK,
    cascade_lot_blocked,
    cascade_lot_closed_liquidated,
    check_price_legality,
    landed_cost_final,
    landed_cost_provisional,
    lot_allocations,
    next_seq,
    pace_window_units_sold,
    qty_allocated_outstanding,
    qty_pool,
    qty_sold,
    round_half_up_int,
    serialize_allocation,
    serialize_assignment,
    serialize_disposition,
    serialize_event,
    serialize_lot,
    serialize_purchase,
    serialize_screening,
    sort_by_created,
    touch,
)
from routes.refdata import new_entity, ANY_ROLE

bp = Blueprint("lots", __name__)

SOURCE_TYPES = ["MFR_OVERRUN", "PACKAGE_CHANGE", "INSURANCE_SALVAGE"]
CONDITION_GRADES = ["A", "B", "C", "MIXED"]
COMMERCIAL_STATUSES = [
    "SOURCED", "SCREENING", "CLEARED", "PRICED", "ON_SALE",
    "DISPOSITION_REVIEW", "BLOCKED", "CLOSED_SOLD_OUT",
    "CLOSED_LIQUIDATED", "CLOSED_SCRAPPED",
]
CHECK_PASS_FAIL = ["PASS", "FAIL"]
CHECK_EXPIRATION = ["PASS", "FAIL", "NA"]
MEMBER_TIERS = ["BRONZE", "SILVER", "GOLD"]
DISPOSITION_ACTIONS = ["MARKDOWN", "LIQUIDATE", "SCRAP"]


def _get_lot(lot_id: str) -> dict:
    lot = db.lots.get(lot_id)
    if lot is None:
        raise not_found("BuyLot not found: %s" % lot_id)
    return lot


def _lot_screenings(lot_id: str):
    return [s for s in db.screenings.values() if s["lot_id"] == lot_id]


def _lot_events(lot_id: str):
    return [e for e in db.events.values() if e["lot_id"] == lot_id]


def _lot_dispositions(lot_id: str):
    return [d for d in db.dispositions.values() if d["lot_id"] == lot_id]


# ---------------------------------------------------------------------------
# BuyLot CRUD
# ---------------------------------------------------------------------------

@bp.post("/lots")
def create_lot():
    role, user_id = require_roles(["SourcingBuyer", "Admin"])
    body = get_json_body()
    allowed = [
        "vendor_id", "home_jurisdiction_id", "title", "source_type",
        "condition_grade", "quantity_total", "total_cost_cents",
        "est_sellable_qty", "comparison_price_cents", "vendor_msrp_cents",
        "pace_target_units_per_week",
    ]
    check_unknown_fields(body, allowed)
    require_fields(body, allowed)
    check_string(body, "title")
    check_enum(body, "source_type", SOURCE_TYPES)
    check_enum(body, "condition_grade", CONDITION_GRADES)
    for f in (
        "quantity_total", "total_cost_cents", "est_sellable_qty",
        "comparison_price_cents", "vendor_msrp_cents",
        "pace_target_units_per_week",
    ):
        check_int_ge(body, f, 1)
    _vendor = db.vendors.get(body["vendor_id"])
    if _vendor is None:
        raise not_found("Vendor not found: %s" % body["vendor_id"])
    _jr = db.jurisdiction_rules.get(body["home_jurisdiction_id"])
    if _jr is None:
        raise not_found("JurisdictionRule not found: %s" % body["home_jurisdiction_id"])

    lot = new_entity()
    lot.update({
        "vendor_id": body["vendor_id"],
        "home_jurisdiction_id": body["home_jurisdiction_id"],
        "title": body["title"],
        "source_type": body["source_type"],
        "condition_grade": body["condition_grade"],
        "quantity_total": body["quantity_total"],
        "total_cost_cents": body["total_cost_cents"],
        "est_sellable_qty": body["est_sellable_qty"],
        "comparison_price_cents": body["comparison_price_cents"],
        "vendor_msrp_cents": body["vendor_msrp_cents"],
        "pace_target_units_per_week": body["pace_target_units_per_week"],
        "created_by_user_id": user_id,
        "safety_status": "PENDING_SCREEN",
        "commercial_status": "SOURCED",
        "retail_price_cents": None,
        "advertises_comparison": False,
        "sellable_qty_confirmed": None,
        "markdown_rounds": 0,
        "on_sale_since": None,
        "qty_liquidated": 0,
        "qty_scrapped": 0,
    })
    lot["landed_unit_cost_cents"] = landed_cost_provisional(lot)
    db.lots[lot["id"]] = lot
    return success_object(serialize_lot(lot), 201)


@bp.get("/lots/<lid>")
def get_lot(lid):
    require_roles(ANY_ROLE)
    lot = _get_lot(lid)
    return success_object(serialize_lot(lot))


@bp.get("/lots")
def list_lots():
    require_roles(ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(db.lots.values())
    commercial_status = None
    vendor_id = None
    source_type = None
    from flask import request
    commercial_status = request.args.get("commercial_status")
    vendor_id = request.args.get("vendor_id")
    source_type = request.args.get("source_type")
    if commercial_status is not None:
        items = [l for l in items if l["commercial_status"] == commercial_status]
    if vendor_id is not None:
        items = [l for l in items if l["vendor_id"] == vendor_id]
    if source_type is not None:
        items = [l for l in items if l["source_type"] == source_type]
    items = sort_by_created(items)
    total = len(items)
    return success_list([serialize_lot(l) for l in items[offset:offset + limit]], limit, offset, total)


@bp.get("/lots/<lid>/summary")
def get_lot_summary(lid):
    require_roles(ANY_ROLE)
    lot = _get_lot(lid)
    return success_object({
        "qty_pool": qty_pool(lid),
        "qty_allocated_outstanding": qty_allocated_outstanding(lid),
        "qty_sold": qty_sold(lid),
        "qty_liquidated": lot["qty_liquidated"],
        "qty_scrapped": lot["qty_scrapped"],
        "landed_unit_cost_cents": lot["landed_unit_cost_cents"],
        "markdown_rounds": lot["markdown_rounds"],
        "commercial_status": lot["commercial_status"],
        "safety_status": lot["safety_status"],
        "pace_window_units_sold": pace_window_units_sold(lid),
    })


@bp.post("/lots/<lid>/regrade")
def regrade_lot(lid):
    require_roles(["SourcingBuyer"])
    lot = _get_lot(lid)
    body = get_json_body()
    check_unknown_fields(body, ["condition_grade"])
    require_fields(body, ["condition_grade"])
    check_enum(body, "condition_grade", CONDITION_GRADES)
    # State gate (PRD §3.3): lot must be in SCREENING and the latest COMPLETED
    # screening must have result FAILED_CONDITION.
    if lot["commercial_status"] != "SCREENING":
        raise invalid_state("Regrade requires the lot to be in SCREENING")
    completed = [s for s in _lot_screenings(lid) if s["status"] == "COMPLETED"]
    completed.sort(key=lambda s: s["round_number"])
    if not completed or completed[-1]["result"] != "FAILED_CONDITION":
        raise invalid_state(
            "Regrade requires the latest COMPLETED screening to have result FAILED_CONDITION"
        )
    lot["condition_grade"] = body["condition_grade"]
    lot["safety_status"] = "PENDING_SCREEN"
    lot["commercial_status"] = "SOURCED"
    touch(lot)
    return success_object(serialize_lot(lot))


# ---------------------------------------------------------------------------
# SafetyScreenings
# ---------------------------------------------------------------------------

@bp.post("/lots/<lid>/screenings")
def open_screening(lid):
    role, user_id = require_roles(["SafetyOfficer"])
    lot = _get_lot(lid)
    if lot["commercial_status"] not in ("SOURCED", "ON_SALE", "DISPOSITION_REVIEW"):
        raise invalid_state(
            "Screenings may only be opened on lots in SOURCED, ON_SALE, or DISPOSITION_REVIEW"
        )
    # Segregation of duties (PRD §3.3).
    if user_id == lot["created_by_user_id"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            "The screening officer must differ from the lot's creator",
            422,
        )
    prior = _lot_screenings(lid)
    s = new_entity()
    s.update({
        "lot_id": lid,
        "round_number": len(prior) + 1,
        "screener_user_id": user_id,
        "status": "PENDING",
        "recall_check": None,
        "expiration_check": None,
        "condition_verified": None,
        "qty_grade_a": None,
        "qty_grade_b": None,
        "qty_grade_c": None,
        "result": None,
        "notes": None,
        "completed_at": None,
    })
    db.screenings[s["id"]] = s
    if lot["commercial_status"] == "SOURCED":
        lot["commercial_status"] = "SCREENING"
        touch(lot)
    return success_object(serialize_screening(s), 201)


@bp.get("/lots/<lid>/screenings")
def list_screenings(lid):
    require_roles(ANY_ROLE)
    _get_lot(lid)
    limit, offset = parse_pagination()
    items = sort_by_created(_lot_screenings(lid))
    total = len(items)
    return success_list([serialize_screening(s) for s in items[offset:offset + limit]], limit, offset, total)


@bp.post("/lots/<lid>/screenings/<sid>/complete")
def complete_screening(lid, sid):
    require_roles(["SafetyOfficer"])
    lot = _get_lot(lid)
    s = db.screenings.get(sid)
    if s is None or s["lot_id"] != lid:
        raise not_found("SafetyScreening not found: %s" % sid)
    body = get_json_body()
    allowed = [
        "recall_check", "expiration_check", "condition_verified",
        "qty_grade_a", "qty_grade_b", "qty_grade_c", "notes",
    ]
    check_unknown_fields(body, allowed)
    require_fields(body, [
        "recall_check", "expiration_check", "condition_verified",
        "qty_grade_a", "qty_grade_b", "qty_grade_c",
    ])
    check_enum(body, "recall_check", CHECK_PASS_FAIL)
    check_enum(body, "expiration_check", CHECK_EXPIRATION)
    check_bool(body, "condition_verified")
    check_int_ge(body, "qty_grade_a", 0)
    check_int_ge(body, "qty_grade_b", 0)
    check_int_ge(body, "qty_grade_c", 0)
    if "notes" in body:
        check_string(body, "notes")
    if s["status"] != "PENDING":
        raise invalid_state("Only a PENDING screening can be completed")
    if body["qty_grade_a"] + body["qty_grade_b"] + body["qty_grade_c"] != lot["quantity_total"]:
        raise ApiError(
            "ERR_GRADE_SUM_MISMATCH",
            "Grade counts must sum to lot.quantity_total",
            422,
        )

    s.update({
        "recall_check": body["recall_check"],
        "expiration_check": body["expiration_check"],
        "condition_verified": body["condition_verified"],
        "qty_grade_a": body["qty_grade_a"],
        "qty_grade_b": body["qty_grade_b"],
        "qty_grade_c": body["qty_grade_c"],
        "notes": body.get("notes"),
    })

    # Derive result in fixed order (PRD §3.3).
    if body["recall_check"] == "FAIL":
        result = "FAILED_RECALL"
    elif body["expiration_check"] == "FAIL":
        result = "FAILED_EXPIRATION"
    elif body["condition_verified"] is False:
        result = "FAILED_CONDITION"
    else:
        result = "PASSED"
    s["result"] = result
    s["status"] = "COMPLETED"
    s["completed_at"] = db.now_iso()
    touch(s)

    if result == "PASSED":
        lot["commercial_status"] = "CLEARED"
        lot["safety_status"] = "CLEARED"
        lot["sellable_qty_confirmed"] = (
            body["qty_grade_a"] + body["qty_grade_b"] + body["qty_grade_c"]
        )
        lot["landed_unit_cost_cents"] = landed_cost_final(lot, s)
        touch(lot)
    elif result in ("FAILED_RECALL", "FAILED_EXPIRATION"):
        lot["safety_status"] = "BLOCKED"
        lot["commercial_status"] = "BLOCKED"
        touch(lot)
        cascade_lot_blocked(lot)
    else:  # FAILED_CONDITION: lot stays SCREENING (regrade loop)
        pass
    return success_object(serialize_screening(s))


# ---------------------------------------------------------------------------
# Pricing
# ---------------------------------------------------------------------------

@bp.post("/lots/<lid>/price")
def price_lot(lid):
    require_roles(["PricingLead"])
    lot = _get_lot(lid)
    body = get_json_body()
    check_unknown_fields(body, ["retail_price_cents", "advertises_comparison"])
    require_fields(body, ["retail_price_cents", "advertises_comparison"])
    check_int_ge(body, "retail_price_cents", 1)
    check_bool(body, "advertises_comparison")
    if lot["commercial_status"] != "CLEARED":
        raise invalid_state("Pricing requires the lot to be in CLEARED")
    if lot["safety_status"] != "CLEARED":
        raise invalid_state("Pricing requires safety_status CLEARED")
    err = check_price_legality(lot, body["retail_price_cents"], body["advertises_comparison"])
    if err is not None:
        raise ApiError(err[0], err[1], err[2])
    lot["retail_price_cents"] = body["retail_price_cents"]
    lot["advertises_comparison"] = body["advertises_comparison"]
    lot["commercial_status"] = "PRICED"
    touch(lot)
    return success_object(serialize_lot(lot))


# ---------------------------------------------------------------------------
# Allocations
# ---------------------------------------------------------------------------

@bp.post("/lots/<lid>/allocations")
def propose_allocation(lid):
    require_roles(["AllocationManager"])
    lot = _get_lot(lid)
    body = get_json_body()
    check_unknown_fields(body, ["store_id", "qty_requested"])
    require_fields(body, ["store_id", "qty_requested"])
    check_int_ge(body, "qty_requested", 1)
    store = db.stores.get(body["store_id"])
    if store is None:
        raise not_found("Store not found: %s" % body["store_id"])
    if lot["safety_status"] != "CLEARED":
        raise ApiError("ERR_LOT_SAFETY_BLOCKED", "The lot has not passed safety screening", 409)
    if store["status"] != "ACTIVE":
        raise ApiError("ERR_STORE_SUSPENDED", "The destination store is suspended", 409)
    if body["qty_requested"] > qty_pool(lid):
        raise ApiError(
            "ERR_INSUFFICIENT_LOT_QUANTITY",
            "qty_requested exceeds the lot's unallocated pool",
            409,
        )
    a = new_entity()
    a.update({
        "lot_id": lid,
        "store_id": body["store_id"],
        "qty_requested": body["qty_requested"],
        "qty_granted": 0,
        "store_on_hand_qty": 0,
        "status": "PROPOSED",
    })
    db.allocations[a["id"]] = a
    return success_object(serialize_allocation(a), 201)


@bp.get("/lots/<lid>/allocations")
def list_lot_allocations(lid):
    require_roles(ANY_ROLE)
    _get_lot(lid)
    limit, offset = parse_pagination()
    items = sort_by_created(lot_allocations(lid))
    total = len(items)
    return success_list([serialize_allocation(a) for a in items[offset:offset + limit]], limit, offset, total)


def _get_allocation(lid: str, aid: str) -> dict:
    a = db.allocations.get(aid)
    if a is None or a["lot_id"] != lid:
        raise not_found("Allocation not found: %s" % aid)
    return a


@bp.get("/lots/<lid>/allocations/<aid>")
def get_allocation(lid, aid):
    require_roles(ANY_ROLE)
    _get_lot(lid)
    a = _get_allocation(lid, aid)
    return success_object(serialize_allocation(a))


@bp.post("/lots/<lid>/allocations/commit")
def commit_allocations(lid):
    require_roles(["AllocationManager"])
    lot = _get_lot(lid)
    if lot["commercial_status"] not in ("PRICED", "ON_SALE", "DISPOSITION_REVIEW"):
        raise invalid_state("Allocation commit requires the lot to be PRICED or later sellable")
    candidates = [a for a in lot_allocations(lid) if a["status"] == "PROPOSED"]
    candidates.sort(key=lambda a: (
        STORE_TIER_RANK[db.stores[a["store_id"]]["performance_tier"]],
        a["created_at"],
        a.get("_seq", 0),
    ))
    pool = qty_pool(lid)
    granted_count = 0
    total_granted = 0
    for a in candidates:
        grant = min(a["qty_requested"], pool)
        a["qty_granted"] = grant
        if grant > 0:
            a["status"] = "CONFIRMED"
            pool -= grant
            granted_count += 1
            total_granted += grant
        touch(a)
    if total_granted > 0 and lot["commercial_status"] == "PRICED":
        lot["commercial_status"] = "ON_SALE"
        lot["on_sale_since"] = db.now_iso()
        touch(lot)
    return success_object({
        "granted_count": granted_count,
        "total_granted_qty": total_granted,
    })


@bp.post("/lots/<lid>/allocations/<aid>/ship")
def ship_allocation(lid, aid):
    require_roles(["AllocationManager"])
    _get_lot(lid)
    a = _get_allocation(lid, aid)
    if a["status"] != "CONFIRMED":
        raise invalid_state("Only a CONFIRMED allocation can be shipped")
    a["status"] = "SHIPPED"
    touch(a)
    return success_object(serialize_allocation(a))


@bp.post("/lots/<lid>/allocations/<aid>/receive")
def receive_allocation(lid, aid):
    require_roles(["AllocationManager"])
    _get_lot(lid)
    a = _get_allocation(lid, aid)
    if a["status"] != "SHIPPED":
        raise invalid_state("Only a SHIPPED allocation can be received")
    a["status"] = "RECEIVED"
    a["store_on_hand_qty"] = a["qty_granted"]
    touch(a)
    return success_object(serialize_allocation(a))


@bp.post("/lots/<lid>/allocations/<aid>/recall")
def recall_allocation(lid, aid):
    require_roles(["AllocationManager"])
    _get_lot(lid)
    a = _get_allocation(lid, aid)
    if a["status"] != "SHIPPED":
        raise invalid_state("Only a SHIPPED allocation can be recalled")
    a["status"] = "CONFIRMED"
    touch(a)
    return success_object(serialize_allocation(a))


@bp.post("/lots/<lid>/allocations/<aid>/release")
def release_allocation(lid, aid):
    require_roles(["AllocationManager"])
    _get_lot(lid)
    a = _get_allocation(lid, aid)
    if a["status"] not in ("CONFIRMED", "RECEIVED"):
        raise invalid_state("Only a CONFIRMED or RECEIVED allocation can be released")
    if a["status"] == "CONFIRMED":
        # qty_pool += qty_granted (derived; flipping status out of
        # CONFIRMED/SHIPPED returns the units automatically).
        pass
    else:  # RECEIVED
        a["store_on_hand_qty"] = 0
    a["status"] = "RELEASED"
    touch(a)
    return success_object(serialize_allocation(a))


@bp.post("/lots/<lid>/allocations/<aid>/cancel")
def cancel_allocation(lid, aid):
    require_roles(["AllocationManager"])
    _get_lot(lid)
    a = _get_allocation(lid, aid)
    if a["status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED allocation can be cancelled")
    a["status"] = "CANCELLED"
    touch(a)
    return success_object(serialize_allocation(a))


# ---------------------------------------------------------------------------
# EarlyAccessEvents
# ---------------------------------------------------------------------------

@bp.post("/lots/<lid>/early-access-events")
def create_event(lid):
    require_roles(["PricingLead"])
    lot = _get_lot(lid)
    body = get_json_body()
    check_unknown_fields(body, ["starts_at", "ends_at", "min_tier", "extra_discount_pct"])
    require_fields(body, ["starts_at", "ends_at", "min_tier", "extra_discount_pct"])
    check_enum(body, "min_tier", MEMBER_TIERS)
    check_int_range(body, "extra_discount_pct", 0, 100)
    starts = parse_ts(body.get("starts_at"))
    ends = parse_ts(body.get("ends_at"))
    if starts is None:
        raise invalid_request("starts_at must be an ISO 8601 timestamp")
    if ends is None:
        raise invalid_request("ends_at must be an ISO 8601 timestamp")
    if lot["commercial_status"] not in ("PRICED", "ON_SALE"):
        raise invalid_state("Events may only be scheduled on lots in PRICED or ON_SALE")
    # Half-open overlap check against SCHEDULED/ACTIVE events of the lot;
    # touching endpoints are allowed (PRD §3.9).
    for ev in _lot_events(lid):
        if ev["status"] not in ("SCHEDULED", "ACTIVE"):
            continue
        ev_start = parse_ts(ev["starts_at"])
        ev_end = parse_ts(ev["ends_at"])
        if ev_start is None or ev_end is None:
            continue
        if starts < ev_end and ev_start < ends:
            raise ApiError(
                "ERR_EVENT_WINDOW_OVERLAP",
                "Event window overlaps an existing SCHEDULED or ACTIVE event on the lot",
                409,
            )
    if ends <= starts:
        raise ApiError("ERR_INVALID_EVENT_WINDOW", "ends_at must be strictly after starts_at", 422)
    e = new_entity()
    e.update({
        "lot_id": lid,
        "starts_at": body["starts_at"],
        "ends_at": body["ends_at"],
        "min_tier": body["min_tier"],
        "extra_discount_pct": body["extra_discount_pct"],
        "status": "SCHEDULED",
    })
    db.events[e["id"]] = e
    return success_object(serialize_event(e), 201)


@bp.get("/lots/<lid>/early-access-events")
def list_events(lid):
    require_roles(ANY_ROLE)
    _get_lot(lid)
    limit, offset = parse_pagination()
    items = sort_by_created(_lot_events(lid))
    total = len(items)
    return success_list([serialize_event(e) for e in items[offset:offset + limit]], limit, offset, total)


@bp.post("/lots/<lid>/early-access-events/<eid>/cancel")
def cancel_event(lid, eid):
    require_roles(["PricingLead"])
    _get_lot(lid)
    e = db.events.get(eid)
    if e is None or e["lot_id"] != lid:
        raise not_found("EarlyAccessEvent not found: %s" % eid)
    if e["status"] not in ("SCHEDULED", "ACTIVE"):
        raise invalid_state("Only a SCHEDULED or ACTIVE event can be cancelled")
    e["status"] = "CANCELLED"
    touch(e)
    return success_object(serialize_event(e))


# ---------------------------------------------------------------------------
# Reverse reachability under lots
# ---------------------------------------------------------------------------

@bp.get("/lots/<lid>/purchases")
def list_lot_purchases(lid):
    require_roles(ANY_ROLE)
    _get_lot(lid)
    limit, offset = parse_pagination()
    items = sort_by_created([p for p in db.purchases.values() if p["lot_id"] == lid])
    total = len(items)
    return success_list([serialize_purchase(p) for p in items[offset:offset + limit]], limit, offset, total)


@bp.get("/lots/<lid>/aisle-assignments")
def list_lot_assignments(lid):
    require_roles(ANY_ROLE)
    _get_lot(lid)
    limit, offset = parse_pagination()
    items = sort_by_created([a for a in db.aisle_assignments.values() if a["lot_id"] == lid])
    total = len(items)
    return success_list([serialize_assignment(a) for a in items[offset:offset + limit]], limit, offset, total)


# ---------------------------------------------------------------------------
# Dispositions
# ---------------------------------------------------------------------------

@bp.post("/lots/<lid>/dispositions")
def create_disposition(lid):
    require_roles(["SourcingBuyer"])
    lot = _get_lot(lid)
    body = get_json_body()
    allowed = ["action", "expected_lot_version", "markdown_pct", "liquidator_ref", "recovery_cents"]
    check_unknown_fields(body, allowed)
    require_fields(body, ["action", "expected_lot_version"])
    check_enum(body, "action", DISPOSITION_ACTIONS)
    if not isinstance(body["expected_lot_version"], int) or isinstance(body["expected_lot_version"], bool):
        raise invalid_request("expected_lot_version must be an integer")
    action = body["action"]
    if action == "MARKDOWN":
        require_fields(body, ["markdown_pct"])
        check_int_range(body, "markdown_pct", 1, 50)
    if action == "LIQUIDATE":
        require_fields(body, ["liquidator_ref", "recovery_cents"])
        check_string(body, "liquidator_ref")
        check_int_ge(body, "recovery_cents", 0)
    # Lifecycle-state gate (PRD §3.7): MARKDOWN/LIQUIDATE require ON_SALE or
    # DISPOSITION_REVIEW; SCRAP requires BLOCKED or DISPOSITION_REVIEW.
    if action in ("MARKDOWN", "LIQUIDATE"):
        if lot["commercial_status"] not in ("ON_SALE", "DISPOSITION_REVIEW"):
            raise invalid_state(
                "%s dispositions require the lot to be ON_SALE or DISPOSITION_REVIEW" % action
            )
    else:  # SCRAP
        if lot["commercial_status"] not in ("BLOCKED", "DISPOSITION_REVIEW"):
            raise invalid_state(
                "SCRAP dispositions require the lot to be BLOCKED or DISPOSITION_REVIEW"
            )
    # OCC (PRD §2.8) — after auth/existence, as its own step.
    if body["expected_lot_version"] != lot["version"]:
        raise stale_version("expected_lot_version does not match the lot's current version")
    # Supersede the prior PENDING disposition of the lot.
    for d0 in _lot_dispositions(lid):
        if d0["status"] == "PENDING":
            d0["status"] = "SUPERSEDED"
            touch(d0)
    d = new_entity()
    d.update({
        "lot_id": lid,
        "action": action,
        "markdown_pct": body.get("markdown_pct"),
        "liquidator_ref": body.get("liquidator_ref"),
        "recovery_cents": body.get("recovery_cents"),
        "status": "PENDING",
        "applied_at": None,
    })
    db.dispositions[d["id"]] = d
    touch(lot)  # disposition creation increments BuyLot.version (§1.5)
    return success_object(serialize_disposition(d), 201)


@bp.get("/lots/<lid>/dispositions")
def list_dispositions(lid):
    require_roles(ANY_ROLE)
    _get_lot(lid)
    limit, offset = parse_pagination()
    items = sort_by_created(_lot_dispositions(lid))
    total = len(items)
    return success_list([serialize_disposition(d) for d in items[offset:offset + limit]], limit, offset, total)


@bp.post("/lots/<lid>/dispositions/<did>/apply")
def apply_disposition(lid, did):
    require_roles(["SourcingBuyer"])
    lot = _get_lot(lid)
    d = db.dispositions.get(did)
    if d is None or d["lot_id"] != lid:
        raise not_found("Disposition not found: %s" % did)
    if d["status"] != "PENDING":
        raise invalid_state("Only a PENDING disposition can be applied")
    action = d["action"]

    if action == "MARKDOWN":
        if lot["commercial_status"] != "DISPOSITION_REVIEW":
            raise invalid_state("Applying a MARKDOWN requires the lot to be DISPOSITION_REVIEW")
        lot["retail_price_cents"] = round_half_up_int(
            Decimal(lot["retail_price_cents"]) * Decimal(100 - d["markdown_pct"]) / Decimal(100)
        )
        lot["markdown_rounds"] += 1
        lot["commercial_status"] = "ON_SALE"
    elif action == "LIQUIDATE":
        if lot["commercial_status"] != "DISPOSITION_REVIEW":
            raise invalid_state("Applying a LIQUIDATE requires the lot to be DISPOSITION_REVIEW")
        if qty_allocated_outstanding(lid) != 0 or any(
            a["status"] in ("PROPOSED",) for a in lot_allocations(lid)
        ):
            raise invalid_state(
                "LIQUIDATE requires no allocation in PROPOSED, CONFIRMED, SHIPPED, or RECEIVED"
            )
        lot["qty_liquidated"] = qty_pool(lid)
        lot["commercial_status"] = "CLOSED_LIQUIDATED"
    else:  # SCRAP
        if lot["commercial_status"] not in ("BLOCKED", "DISPOSITION_REVIEW"):
            raise invalid_state("Applying a SCRAP requires the lot to be BLOCKED or DISPOSITION_REVIEW")
        if qty_allocated_outstanding(lid) != 0 or any(
            a["status"] in ("PROPOSED",) for a in lot_allocations(lid)
        ):
            raise invalid_state(
                "SCRAP requires no allocation in PROPOSED, CONFIRMED, SHIPPED, or RECEIVED"
            )
        lot["qty_scrapped"] = qty_pool(lid)
        lot["commercial_status"] = "CLOSED_SCRAPPED"

    d["status"] = "APPLIED"
    d["applied_at"] = db.now_iso()
    touch(d)
    touch(lot)
    if action == "LIQUIDATE":
        cascade_lot_closed_liquidated(lot)
    return success_object(serialize_disposition(d))
