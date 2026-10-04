"""Shared business logic: derived quantities, calculations, cascades."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional, Tuple

from db import db, parse_ts


GRADE_B_FACTOR = Decimal("0.8")
GRADE_C_FACTOR = Decimal("0.6")
MIN_ANCHOR_PREMIUM_PCT = 20
TIER_DISCOUNT_PCT = {"BRONZE": 5, "SILVER": 10, "GOLD": 15}
TIER_RANK = {"BRONZE": 0, "SILVER": 1, "GOLD": 2}
PACE_WINDOW_DAYS = 7
MIN_SELLING_DAYS = 3
REFUND_WINDOW_DAYS = 14
STORE_TIER_RANK = {"TIER_1": 0, "TIER_2": 1, "TIER_3": 2}

# Monotonic creation sequence, used as a stable tiebreaker where the spec
# orders by created_at (the logical clock can tie across creations).
_seq_counter = {"n": 0}


def next_seq() -> int:
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def round_half_up_int(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def touch(entity: dict) -> None:
    """Stamp updated_at from the logical clock and bump version (PRD §2.4)."""
    entity["updated_at"] = db.now_iso()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# BuyLot derived quantities (PRD §2.9 unit conservation)
# ---------------------------------------------------------------------------

def lot_allocations(lot_id: str):
    return [a for a in db.allocations.values() if a["lot_id"] == lot_id]


def lot_purchases(lot_id: str):
    return [p for p in db.purchases.values() if p["lot_id"] == lot_id]


def qty_allocated_outstanding(lot_id: str) -> int:
    total = 0
    for a in lot_allocations(lot_id):
        if a["status"] in ("CONFIRMED", "SHIPPED"):
            total += a["qty_granted"]
        elif a["status"] == "RECEIVED":
            total += a["store_on_hand_qty"]
    return total


def qty_sold(lot_id: str) -> int:
    return sum(p["qty"] for p in lot_purchases(lot_id) if p["status"] == "COMPLETED")


def qty_pool(lot_id: str) -> int:
    lot = db.lots[lot_id]
    return (
        lot["quantity_total"]
        - qty_allocated_outstanding(lot_id)
        - qty_sold(lot_id)
        - lot["qty_liquidated"]
        - lot["qty_scrapped"]
    )


def pace_window_units_sold(lot_id: str) -> int:
    """Units sold within the current trailing 7-day window [now-7d, now)."""
    now = db.now()
    lo = now - timedelta(days=PACE_WINDOW_DAYS)
    total = 0
    for p in lot_purchases(lot_id):
        if p["status"] != "COMPLETED":
            continue
        created = parse_ts(p["created_at"])
        if created is not None and lo <= created < now:
            total += p["qty"]
    return total


# ---------------------------------------------------------------------------
# Landed unit cost (PRD §3.5, dual variant)
# ---------------------------------------------------------------------------

def landed_cost_provisional(lot: dict) -> int:
    return round_half_up_int(
        Decimal(lot["total_cost_cents"]) / Decimal(lot["est_sellable_qty"])
    )


def landed_cost_final(lot: dict, screening: dict) -> int:
    effective = (
        Decimal(screening["qty_grade_a"])
        + GRADE_B_FACTOR * Decimal(screening["qty_grade_b"])
        + GRADE_C_FACTOR * Decimal(screening["qty_grade_c"])
    )
    return round_half_up_int(Decimal(lot["total_cost_cents"]) / effective)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------

def _base(e: dict) -> dict:
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def serialize_vendor(v: dict) -> dict:
    d = _base(v)
    d.update({"name": v["name"], "vendor_code": v["vendor_code"]})
    return d


def serialize_jurisdiction(j: dict) -> dict:
    d = _base(j)
    d.update({
        "jurisdiction_code": j["jurisdiction_code"],
        "comparison_rule": j["comparison_rule"],
        "window_days": j["window_days"],
        "required_offer_days": j["required_offer_days"],
        "max_advertised_discount_pct": j["max_advertised_discount_pct"],
        "member_discount_cap_pct": j["member_discount_cap_pct"],
    })
    return d


def serialize_store(s: dict) -> dict:
    d = _base(s)
    d.update({
        "name": s["name"],
        "store_code": s["store_code"],
        "jurisdiction_id": s["jurisdiction_id"],
        "performance_tier": s["performance_tier"],
        "status": s["status"],
    })
    return d


def serialize_lot(lot: dict) -> dict:
    d = _base(lot)
    d.update({
        "vendor_id": lot["vendor_id"],
        "home_jurisdiction_id": lot["home_jurisdiction_id"],
        "title": lot["title"],
        "source_type": lot["source_type"],
        "condition_grade": lot["condition_grade"],
        "quantity_total": lot["quantity_total"],
        "total_cost_cents": lot["total_cost_cents"],
        "est_sellable_qty": lot["est_sellable_qty"],
        "comparison_price_cents": lot["comparison_price_cents"],
        "vendor_msrp_cents": lot["vendor_msrp_cents"],
        "pace_target_units_per_week": lot["pace_target_units_per_week"],
        "created_by_user_id": lot["created_by_user_id"],
        "safety_status": lot["safety_status"],
        "commercial_status": lot["commercial_status"],
        "retail_price_cents": lot["retail_price_cents"],
        "advertises_comparison": lot["advertises_comparison"],
        "sellable_qty_confirmed": lot["sellable_qty_confirmed"],
        "landed_unit_cost_cents": lot["landed_unit_cost_cents"],
        "markdown_rounds": lot["markdown_rounds"],
        "on_sale_since": lot["on_sale_since"],
        "qty_pool": qty_pool(lot["id"]),
        "qty_allocated_outstanding": qty_allocated_outstanding(lot["id"]),
        "qty_sold": qty_sold(lot["id"]),
        "qty_liquidated": lot["qty_liquidated"],
        "qty_scrapped": lot["qty_scrapped"],
    })
    return d


def serialize_screening(s: dict) -> dict:
    d = _base(s)
    d.update({
        "lot_id": s["lot_id"],
        "round_number": s["round_number"],
        "screener_user_id": s["screener_user_id"],
        "status": s["status"],
        "recall_check": s["recall_check"],
        "expiration_check": s["expiration_check"],
        "condition_verified": s["condition_verified"],
        "qty_grade_a": s["qty_grade_a"],
        "qty_grade_b": s["qty_grade_b"],
        "qty_grade_c": s["qty_grade_c"],
        "result": s["result"],
        "notes": s["notes"],
        "completed_at": s["completed_at"],
    })
    return d


def serialize_allocation(a: dict) -> dict:
    d = _base(a)
    d.update({
        "lot_id": a["lot_id"],
        "store_id": a["store_id"],
        "qty_requested": a["qty_requested"],
        "qty_granted": a["qty_granted"],
        "store_on_hand_qty": a["store_on_hand_qty"],
        "status": a["status"],
    })
    return d


def serialize_assignment(a: dict) -> dict:
    d = _base(a)
    d.update({
        "store_id": a["store_id"],
        "lot_id": a["lot_id"],
        "aisle_code": a["aisle_code"],
        "daily_unit_limit": a["daily_unit_limit"],
        "valid_from": a["valid_from"],
        "valid_to": a["valid_to"],
        "status": a["status"],
    })
    return d


def serialize_member(m: dict) -> dict:
    d = _base(m)
    d.update({
        "member_code": m["member_code"],
        "tier": m["tier"],
        "home_store_id": m["home_store_id"],
        "status": m["status"],
    })
    return d


def serialize_event(e: dict) -> dict:
    d = _base(e)
    d.update({
        "lot_id": e["lot_id"],
        "starts_at": e["starts_at"],
        "ends_at": e["ends_at"],
        "min_tier": e["min_tier"],
        "extra_discount_pct": e["extra_discount_pct"],
        "status": e["status"],
    })
    return d


def serialize_purchase(p: dict) -> dict:
    d = _base(p)
    d.update({
        "store_id": p["store_id"],
        "lot_id": p["lot_id"],
        "member_id": p["member_id"],
        "qty": p["qty"],
        "pricing_variant": p["pricing_variant"],
        "discount_pct_applied": p["discount_pct_applied"],
        "unit_price_cents": p["unit_price_cents"],
        "line_total_cents": p["line_total_cents"],
        "status": p["status"],
        "refunded_at": p["refunded_at"],
    })
    return d


def serialize_disposition(d0: dict) -> dict:
    d = _base(d0)
    d.update({
        "lot_id": d0["lot_id"],
        "action": d0["action"],
        "markdown_pct": d0["markdown_pct"],
        "liquidator_ref": d0["liquidator_ref"],
        "recovery_cents": d0["recovery_cents"],
        "status": d0["status"],
        "applied_at": d0["applied_at"],
    })
    return d


def sort_by_created(items):
    return sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))


# ---------------------------------------------------------------------------
# Cascades (PRD §3.3 blocked lot, §3.7 liquidated lot)
# ---------------------------------------------------------------------------

def cascade_lot_blocked(lot: dict) -> None:
    """Link 1: cancel PROPOSED/CONFIRMED allocations (CONFIRMED returns its
    qty_granted to the pool — automatic because qty_pool is derived).
    Link 2: supersede ACTIVE aisle assignments of affected stores for this lot."""
    now_iso = db.now_iso()
    affected_store_ids = set()
    for a in lot_allocations(lot["id"]):
        if a["status"] in ("PROPOSED", "CONFIRMED"):
            if a["status"] == "CONFIRMED":
                affected_store_ids.add(a["store_id"])
            a["status"] = "CANCELLED"
            touch(a)
    # Link 2 applies to stores whose allocation was cancelled by link 1.
    # PROPOSED allocations hold no units; only CONFIRMED cancellations count.
    for asn in db.aisle_assignments.values():
        if (
            asn["lot_id"] == lot["id"]
            and asn["status"] == "ACTIVE"
            and asn["store_id"] in affected_store_ids
        ):
            asn["status"] = "SUPERSEDED"
            asn["valid_to"] = now_iso
            touch(asn)


def cascade_lot_closed_liquidated(lot: dict) -> None:
    """Every ACTIVE aisle assignment referencing the lot -> SUPERSEDED with
    valid_to := close timestamp; every SCHEDULED/ACTIVE event -> CANCELLED."""
    now_iso = db.now_iso()
    for asn in db.aisle_assignments.values():
        if asn["lot_id"] == lot["id"] and asn["status"] == "ACTIVE":
            asn["status"] = "SUPERSEDED"
            asn["valid_to"] = now_iso
            touch(asn)
    for ev in db.events.values():
        if ev["lot_id"] == lot["id"] and ev["status"] in ("SCHEDULED", "ACTIVE"):
            ev["status"] = "CANCELLED"
            touch(ev)


def maybe_close_sold_out(lot: dict) -> None:
    """ON_SALE -> CLOSED_SOLD_OUT when the pipeline is empty (PRD §3.6)."""
    if lot["commercial_status"] != "ON_SALE":
        return
    if (
        qty_pool(lot["id"]) == 0
        and qty_allocated_outstanding(lot["id"]) == 0
        and lot["qty_liquidated"] == 0
        and lot["qty_scrapped"] == 0
    ):
        lot["commercial_status"] = "CLOSED_SOLD_OUT"
        touch(lot)


# ---------------------------------------------------------------------------
# Event coverage (half-open [starts_at, ends_at), PRD §3.9 / member_price)
# ---------------------------------------------------------------------------

def event_covers_now(ev: dict) -> bool:
    if ev["status"] in ("ENDED", "CANCELLED"):
        return False
    now = db.now()
    starts = parse_ts(ev["starts_at"])
    ends = parse_ts(ev["ends_at"])
    if starts is None or ends is None:
        return False
    return starts <= now < ends


def active_events_for_lot(lot_id: str):
    return [e for e in db.events.values() if e["lot_id"] == lot_id and event_covers_now(e)]


# ---------------------------------------------------------------------------
# Advertised price legality (PRD §3.5)
# ---------------------------------------------------------------------------

def check_price_legality(lot: dict, retail_price_cents: int, advertises_comparison: bool) -> Optional[Tuple[str, str, int]]:
    """Returns (error_id, message, http_status) or None if legal."""
    jr = db.jurisdiction_rules[lot["home_jurisdiction_id"]]
    rule = jr["comparison_rule"]
    if rule == "COMPARISON_PROHIBITED":
        if advertises_comparison:
            return (
                "ERR_COMPARISON_ADVERTISING_PROHIBITED",
                "Comparison advertising is prohibited in the lot's home jurisdiction",
                422,
            )
        return None
    if rule == "MSRP_REFERENCE":
        if lot["comparison_price_cents"] != lot["vendor_msrp_cents"]:
            return (
                "ERR_COMPARISON_NOT_MSRP",
                "comparison_price_cents must equal vendor_msrp_cents under MSRP_REFERENCE",
                422,
            )
        if retail_price_cents > lot["comparison_price_cents"]:
            return (
                "ERR_ADVERTISED_DISCOUNT_TOO_DEEP",
                "retail_price_cents must not exceed the comparison price",
                422,
            )
        return None
    # WAS_NOW_WINDOW
    anchor = round_half_up_int(
        Decimal(retail_price_cents) * Decimal(100 + MIN_ANCHOR_PREMIUM_PCT) / Decimal(100)
    )
    if lot["comparison_price_cents"] < anchor:
        return (
            "ERR_ANCHOR_PREMIUM_INSUFFICIENT",
            "comparison_price_cents must be at least the retail price marked up by 20 percent",
            422,
        )
    discount_pct = (
        Decimal(lot["comparison_price_cents"] - retail_price_cents)
        * Decimal(100)
        / Decimal(lot["comparison_price_cents"])
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    if discount_pct > Decimal(jr["max_advertised_discount_pct"]):
        return (
            "ERR_ADVERTISED_DISCOUNT_TOO_DEEP",
            "Advertised discount percent exceeds the jurisdictional maximum",
            422,
        )
    return None


# ---------------------------------------------------------------------------
# Clock advance side effects (PRD §2.5, §3.7)
# ---------------------------------------------------------------------------

def run_clock_side_effects() -> None:
    now = db.now()
    # Early-access event transitions.
    for ev in db.events.values():
        starts = parse_ts(ev["starts_at"])
        ends = parse_ts(ev["ends_at"])
        if starts is None or ends is None:
            continue
        if ev["status"] == "SCHEDULED" and starts <= now < ends:
            ev["status"] = "ACTIVE"
            touch(ev)
        elif ev["status"] == "ACTIVE" and now >= ends:
            ev["status"] = "ENDED"
            touch(ev)
    # Sell-through pacing evaluation (after event transitions).
    for lot in db.lots.values():
        if lot["commercial_status"] != "ON_SALE" or not lot["on_sale_since"]:
            continue
        on_sale_since = parse_ts(lot["on_sale_since"])
        if on_sale_since is None:
            continue
        selling_days = int((now - on_sale_since).total_seconds() // 86400)
        if selling_days < MIN_SELLING_DAYS:
            continue
        if pace_window_units_sold(lot["id"]) * 2 < lot["pace_target_units_per_week"]:
            lot["commercial_status"] = "DISPOSITION_REVIEW"
            touch(lot)
