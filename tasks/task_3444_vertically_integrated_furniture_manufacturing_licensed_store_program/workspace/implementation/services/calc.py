"""Pure calculation rules (PRD §2.6, §3.1, §3.3-§3.7) — no route logic here."""
from decimal import Decimal, ROUND_HALF_UP

from constants import (
    CALL_OUT_CENTS, CHARGEBACK_RATE, CLEARANCE_MARKDOWN_KEEP, CREW_CENTS,
    LICENSEE_UNIT_FACTOR, OVERAGE_BLOCK_MINUTES, OVERAGE_CENTS,
    PREFERRED_STANDING_SCORE, STAIRS_CENTS, STAIRS_FREE_FLIGHTS,
    TIER1_FACTOR, TIER1_QTY, TIER2_FACTOR, TIER2_QTY, TIER3_FACTOR, TIER3_QTY,
    ZONE_CENTS,
)
from db import store


def rhu_cents(value):
    """round_half_up to integer cents."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round2(value):
    """round_half_up to 2 decimal places (performance scores)."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# order_pricing (PRD §3.5): round the UNIT first, then multiply by quantity.
# ---------------------------------------------------------------------------

def clearance_price_cents(price_point_cents):
    return rhu_cents(Decimal(price_point_cents) * CLEARANCE_MARKDOWN_KEEP)


def base_price_cents(line):
    """Orderable base for the line's current lifecycle; None if not orderable."""
    if line["lifecycle"] == "ACTIVE":
        return line["price_point_cents"]
    if line["lifecycle"] == "CLEARANCE":
        return line["clearance_price_cents"]
    return None  # CONCEPT / RETIRED not orderable


def unit_price_cents(buyer_type, quantity, line):
    base = base_price_cents(line)
    if base is None:
        return None
    if buyer_type == "LICENSEE":
        return rhu_cents(Decimal(base) * LICENSEE_UNIT_FACTOR)
    if quantity >= TIER3_QTY:
        factor = TIER3_FACTOR
    elif quantity >= TIER2_QTY:
        factor = TIER2_FACTOR
    elif quantity >= TIER1_QTY:
        factor = TIER1_FACTOR
    else:
        factor = Decimal("1")
    return rhu_cents(Decimal(base) * factor)


def price_order(order, line):
    """Fill unit_price_cents + provisional_total_cents off the line's CURRENT lifecycle."""
    unit = unit_price_cents(order["buyer_type"], order["quantity"], line)
    order["unit_price_cents"] = unit
    order["provisional_total_cents"] = unit * order["quantity"] if unit is not None else None
    order["_priced_lifecycle"] = line["lifecycle"]


def final_total_cents(order, line):
    """Final lock: quantity re-priced with the line's current lifecycle."""
    unit = unit_price_cents(order["buyer_type"], order["quantity"], line)
    return unit * order["quantity"] if unit is not None else None


# ---------------------------------------------------------------------------
# royalty_accrual (PRD §3.7): round per line, then sum. Rate read at delivery.
# ---------------------------------------------------------------------------

def royalty_for(final_total, royalty_rate):
    return rhu_cents(Decimal(final_total) * Decimal(str(royalty_rate)))


def chargeback_for(final_total):
    return rhu_cents(Decimal(final_total) * CHARGEBACK_RATE)


def recompute_ledger(lic):
    """Returns True when a stored ledger field changed."""
    accrued = 0
    for o in store.orders.values():
        if o.get("licensee_id") == lic["id"] and o["fulfillment_state"] == "DELIVERED":
            if o.get("_royalty_cents") is not None:
                accrued += o["_royalty_cents"]
    chargeback = 0
    for c in store.claims.values():
        if (c.get("licensee_id") == lic["id"] and c["decision"] == "APPROVED"
                and c["claim_type"] == "DAMAGE_IN_TRANSIT"
                and c["chargeback_cents"] is not None):
            chargeback += c["chargeback_cents"]
    changed = (lic["royalty_accrued_cents"] != accrued
               or lic["chargeback_cents"] != chargeback)
    lic["royalty_accrued_cents"] = accrued
    lic["chargeback_cents"] = chargeback
    lic["net_royalty_cents"] = accrued - chargeback
    return changed


# ---------------------------------------------------------------------------
# credit_exposure (PRD §3.3)
# ---------------------------------------------------------------------------

def recompute_credit(account):
    """Sum over RESERVED/ALLOCATED x PENDING/PICKED/SHIPPED; final if ALLOCATED else provisional."""
    used = 0
    for o in store.orders.values():
        if o.get("retail_account_id") != account["id"]:
            continue
        if o["allocation_state"] not in ("RESERVED", "ALLOCATED"):
            continue
        if o["fulfillment_state"] not in ("PENDING", "PICKED", "SHIPPED"):
            continue
        used += o["final_total_cents"] if o["allocation_state"] == "ALLOCATED" else o["provisional_total_cents"]
    changed = account["credit_used_cents"] != used
    account["credit_used_cents"] = used
    return changed


# ---------------------------------------------------------------------------
# AllocationCycle counters (PRD §3.4)
# ---------------------------------------------------------------------------

def recompute_cycle(cycle):
    lic_res = 0
    ws_res = 0
    for o in store.orders.values():
        if o["allocation_cycle_id"] != cycle["id"]:
            continue
        if o["allocation_state"] not in ("RESERVED", "ALLOCATED"):
            continue
        if o["buyer_type"] == "LICENSEE":
            lic_res += o["quantity"]
        else:
            ws_res += o["quantity"]
    available = cycle["capacity_units"] - lic_res - ws_res
    changed = (cycle["licensee_reserved_units"] != lic_res
               or cycle["wholesale_reserved_units"] != ws_res
               or cycle["available_units"] != available)
    cycle["licensee_reserved_units"] = lic_res
    cycle["wholesale_reserved_units"] = ws_res
    cycle["available_units"] = available
    return changed


# ---------------------------------------------------------------------------
# waitlist_ranking (PRD §3.4): (standing_tier ASC, created_at ASC, seq ASC).
# ---------------------------------------------------------------------------

def standing_tier(order):
    if order["buyer_type"] == "LICENSEE":
        lic = store.licensees.get(order.get("licensee_id"))
        if (lic is not None and lic["seasoned_score"] is not None
                and lic["seasoned_score"] >= PREFERRED_STANDING_SCORE):
            return 1
        return 2
    acct = store.retail_accounts.get(order.get("retail_account_id"))
    if acct is not None and acct["credit_used_cents"] * 4 <= acct["credit_limit_cents"]:
        return 1
    return 2


def rank_key(order):
    return (standing_tier(order), order["created_at"], order["_seq"])


# ---------------------------------------------------------------------------
# delivery_fee (PRD §3.6)
# ---------------------------------------------------------------------------

def estimate_fee(zone, crew_units):
    return CALL_OUT_CENTS + ZONE_CENTS[zone] + crew_units * CREW_CENTS


def final_fee(appt):
    window_minutes = int((appt["window_end"] - appt["window_start"]).total_seconds() // 60)
    excess = max(0, appt["actual_duration_minutes"] - window_minutes)
    blocks = (excess + OVERAGE_BLOCK_MINUTES - 1) // OVERAGE_BLOCK_MINUTES  # ceil
    stairs = max(0, appt["stairs_flights"] - STAIRS_FREE_FLIGHTS) * STAIRS_CENTS
    return appt["estimate_fee_cents"] + blocks * OVERAGE_CENTS + stairs


# ---------------------------------------------------------------------------
# delivery_capacity_check (PRD §3.6): aggregate instant-wise overlap, CONFIRMED only.
# ---------------------------------------------------------------------------

def windows_overlap(s1, e1, s2, e2):
    """Half-open overlap: touching windows do NOT overlap."""
    return s1 < e2 and s2 < e1


def capacity_ok(dc, cand_start, cand_end, cand_crew, exclude_id=None):
    confirmed = [
        a for a in store.appointments.values()
        if a["dc_id"] == dc["id"] and a["status"] == "CONFIRMED" and a["id"] != exclude_id
    ]
    points = [cand_start]
    for a in confirmed:
        if (windows_overlap(cand_start, cand_end, a["window_start"], a["window_end"])
                and cand_start <= a["window_start"] < cand_end):
            points.append(a["window_start"])
    for t in points:
        load = sum(
            a["crew_units"] for a in confirmed
            if a["window_start"] <= t < a["window_end"]
        )
        if load + cand_crew > dc["daily_crew_units"]:
            return False
    return True
