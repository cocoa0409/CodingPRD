"""Calculation rules: money/hours rounding, settlement waterfall, labor costs."""
from decimal import Decimal, ROUND_HALF_UP

from constants import UNION_RULES, FAMILY_PACK_SIZE, TRUCKS_PER_DOOR
from db import db
from clock import now
import helpers as H


def round_half_up_cents(x):
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_hours_half(hours):
    return float(Decimal(str(hours)).quantize(Decimal("0.5"), rounding=ROUND_HALF_UP))


# ---------- venue share (dual variant with floor) ----------

def compute_venue_share(engagement, venue, gross):
    if engagement["deal_type"] == "FLAT_RENT":
        return int(engagement["agreed_rent_cents"])
    pct = Decimal(str(venue["percentage_share_pct"]))
    pct_share = round_half_up_cents(Decimal(gross) * pct)
    return max(int(engagement["agreed_rent_cents"]), pct_share)


# ---------- royalty waterfall ----------

def compute_royalty_withheld(tour, gross, reconcile_clock=None):
    ts = reconcile_clock or now()
    active = [l for l in db.license_agreements.values()
              if l["tour_id"] == tour["id"] and l["status"] == "ACTIVE"
              and l["starts_on"] <= ts and ts < l["ends_on"]]
    if not active:
        return 0
    # Event 1: per-agreement percentage pieces, each rounded, then summed.
    pct_part = 0
    for a in active:
        pct_part += round_half_up_cents(Decimal(gross) * Decimal(str(a["royalty_pct"])))
    # Event 2: guarantee proration; each division rounded once, then summed.
    prorate_count = 0
    for e in db.engagements.values():
        if e["tour_id"] == tour["id"] and e["status"] in H.PRORATE_ENGAGEMENT_STATUSES:
            prorate_count += 1
    if prorate_count <= 0:
        prorate_count = 1
    guarantee_part = 0
    for a in active:
        guarantee_part += round_half_up_cents(
            Decimal(a["minimum_guarantee_cents"]) / Decimal(prorate_count))
    uncapped = max(pct_part, guarantee_part)
    # Event 3: reserve cap rounding.
    reserve_pct = Decimal(str(tour.get("royalty_reserve_pct") or 0))
    if reserve_pct > 0:
        cap = round_half_up_cents(Decimal(gross) * reserve_pct)
        return min(uncapped, cap)
    return uncapped


def compute_promoter_net(gross, venue_share, royalty_withheld, labor_total):
    return gross - venue_share - royalty_withheld - labor_total


def compute_labor_total(engagement_id):
    total = 0
    for c in db.labor_calls.values():
        if c["engagement_id"] == engagement_id and c["status"] == "SETTLED":
            total += c.get("final_cost_cents") or 0
    return total


# ---------- labor estimate (per-call, DRAFT -> POSTED) ----------

def labor_rules(venue):
    return UNION_RULES[venue["union_rule_set"]]


def compute_labor_estimate(call, venue):
    rules = labor_rules(venue)
    delta = call["call_end_at"] - call["call_start_at"]
    raw_hours = round_hours_half(delta.total_seconds() / 3600.0)
    effective_hours = max(raw_hours, float(rules["minimum_hours"]))
    straight_hours = min(effective_hours, float(rules["ot_threshold"]))
    overtime_hours = max(0.0, effective_hours - float(rules["ot_threshold"]))
    mult = rules["ot_multiplier"]
    weighted = Decimal(str(straight_hours)) + Decimal(str(overtime_hours)) * mult
    est = round_half_up_cents(
        Decimal(call["headcount"]) * Decimal(call["hourly_rate_cents"]) * weighted)
    return {
        "union_minimum_hours": int(rules["minimum_hours"]),
        "effective_hours": effective_hours,
        "overtime_hours": overtime_hours,
        "estimated_cost_cents": est,
    }


# ---------- labor final (per-worker chronological, FILLED -> SETTLED) ----------

def compute_labor_final(call, venue, punch_records):
    rules = labor_rules(venue)
    pairs = []
    for idx, rec in enumerate(punch_records):
        pin = rec["punch_in_at"]
        pout = rec["punch_out_at"]
        created = rec.get("created_at") or ""
        pairs.append((pin, created, idx, pin, pout))
    pairs.sort(key=lambda t: (t[0], t[1], t[2]))
    total = 0
    for _pin_key, _created, _idx, pin, pout in pairs:
        hours = round_hours_half((pout - pin).total_seconds() / 3600.0)
        effective = max(hours, float(rules["minimum_hours"]))
        straight = min(effective, float(rules["ot_threshold"]))
        ot = max(0.0, effective - float(rules["ot_threshold"]))
        weighted = Decimal(str(straight)) + Decimal(str(ot)) * rules["ot_multiplier"]
        total += round_half_up_cents(Decimal(call["hourly_rate_cents"]) * weighted)
    return total


# ---------- trucks ----------

def compute_dock_doors(truck_count):
    return -(-int(truck_count) // TRUCKS_PER_DOOR)  # ceil


# ---------- family pack ----------

def family_pack_total(base_price_cents, n):
    bundle_count = n // FAMILY_PACK_SIZE
    loose = n - bundle_count * FAMILY_PACK_SIZE
    per_seat = round_half_up_cents(Decimal(base_price_cents) / Decimal(FAMILY_PACK_SIZE))
    return bundle_count * base_price_cents + loose * per_seat


# ---------- market cooldown ----------

def market_overlap(engagement, tour):
    for other in db.engagements.values():
        if other["id"] == engagement["id"]:
            continue
        if other["tour_id"] != tour["id"] or other["venue_id"] != engagement["venue_id"]:
            continue
        if other["status"] not in H.PRORATE_ENGAGEMENT_STATUSES:
            continue
        gap_seconds = abs((engagement["first_show_at"] - other["first_show_at"]).total_seconds())
        gap_days = int(gap_seconds // 86400)
        if gap_days < tour["market_cooldown_days"]:
            return True
    return False
