"""Calculation rules (SCAFFOLD §1.3 / PRD §2.9, §2.10, §3.x).

All money math is Decimal-based with round-half-up; never float.
"""
from datetime import timedelta
from decimal import Decimal

from store import db, touch
from util import round_half_up_int

# --- contract_price_quote constants ---
TIER1_MAX_KG = Decimal("50")
TIER1_RATE = 600000
TIER2_MAX_KG = Decimal("200")
TIER2_RATE = 500000
TIER3_RATE = 425000

# --- integration_fee_ledger constants ---
INTEGRATION_RATE_CENTS_PER_KG = Decimal("12000")
INTERFACE_FACTOR = {
    "RING_15": Decimal("1.0"),
    "RING_24": Decimal("1.25"),
    "CUBESAT": Decimal("0.8"),
}

# --- license_composite_score constants ---
GRANT_THRESHOLD = 70

# --- range_slot_overlap constants ---
TURNAROUND_MINUTES = 45

# --- separation_sequence constants ---
BASE_GAP_S = 30
SAME_INTERFACE_EXTRA_GAP_S = 15

LIVE_ASSIGNMENT_STATUSES = {"PROVISIONAL", "CONFIRMED", "INTEGRATED"}


def quote_price_cents(pricing_mode, payloads):
    """Tiered per-kg price over ALL payloads of the contract (any status)."""
    total = sum((p["mass_kg"] for p in payloads), Decimal("0"))
    if pricing_mode == "MARGINAL":
        t1_kg = min(total, TIER1_MAX_KG)
        t1 = round_half_up_int(t1_kg * TIER1_RATE)
        t2_kg = min(max(total - TIER1_MAX_KG, Decimal("0")), TIER2_MAX_KG - TIER1_MAX_KG)
        t2 = round_half_up_int(t2_kg * TIER2_RATE)
        t3_kg = max(total - TIER2_MAX_KG, Decimal("0"))
        t3 = round_half_up_int(t3_kg * TIER3_RATE)
        return t1 + t2 + t3
    # FLAT: entire mass at the rate of the highest tier reached
    if total <= TIER1_MAX_KG:
        rate = TIER1_RATE
    elif total <= TIER2_MAX_KG:
        rate = TIER2_RATE
    else:
        rate = TIER3_RATE
    return round_half_up_int(total * rate)


def integration_fee_unrounded(payload):
    return (
        payload["mass_kg"]
        * INTEGRATION_RATE_CENTS_PER_KG
        * INTERFACE_FACTOR[payload["interface_class"]]
    )


def integration_fee_cents(payload):
    """Per-line fee: round half up at creation, before any summation."""
    return round_half_up_int(integration_fee_unrounded(payload))


def composite_score(debris, spectrum, history):
    """round_half_up(0.5*d + 0.3*s + 0.2*h) == round_half_up((5d+3s+2h)/10)."""
    return round_half_up_int(
        (Decimal(5) * debris + Decimal(3) * spectrum + Decimal(2) * history)
        / Decimal(10)
    )


def recompute_commitment(mission):
    """manifest_commitment: TOTAL over {PROVISIONAL, CONFIRMED, INTEGRATED},
    FIRM over {CONFIRMED, INTEGRATED}. Derived refresh: updates updated_at,
    never bumps version."""
    total_mass = Decimal("0")
    total_vol = Decimal("0")
    firm_mass = Decimal("0")
    for a in db["assignments"].values():
        if a["mission_id"] != mission["id"]:
            continue
        if a["status"] not in LIVE_ASSIGNMENT_STATUSES:
            continue
        p = db["payloads"][a["payload_id"]]
        total_mass += p["mass_kg"]
        total_vol += p["volume_m3"]
        if a["status"] in ("CONFIRMED", "INTEGRATED"):
            firm_mass += p["mass_kg"]
    mission["committed_mass_kg"] = total_mass
    mission["committed_volume_m3"] = total_vol
    mission["firm_mass_kg"] = firm_mass
    touch(mission)


def range_slot_conflicts(slot):
    """45-minute turnaround buffer vs RESERVED/CONFIRMED slots on the same range.

    A gap of AT LEAST 45 minutes on one side passes; exactly 45 is allowed.
    """
    buf = timedelta(minutes=TURNAROUND_MINUTES)
    for e in db["range_slots"].values():
        if e["id"] == slot["id"]:
            continue
        if e["range_code"] != slot["range_code"]:
            continue
        if e["status"] not in ("RESERVED", "CONFIRMED"):
            continue
        clear = (
            slot["window_close_utc"] + buf <= e["window_open_utc"]
            or e["window_close_utc"] + buf <= slot["window_open_utc"]
        )
        if not clear:
            return True
    return False


def weather_blocked(range_code, t):
    """WEATHER instant membership, half-open: start_utc <= t < end_utc."""
    for w in db["exclusion_windows"].values():
        if w["kind"] != "WEATHER":
            continue
        if w["scope_type"] != "RANGE" or w["scope_value"] != range_code:
            continue
        if w["start_utc"] <= t < w["end_utc"]:
            return True
    return False


def cola_blocked(orbit, slot):
    """COLA window intersection, half-open: touching intervals do not conflict."""
    for w in db["exclusion_windows"].values():
        if w["kind"] != "COLA":
            continue
        if w["scope_type"] != "ORBIT" or w["scope_value"] != orbit:
            continue
        if slot["window_open_utc"] < w["end_utc"] and w["start_utc"] < slot["window_close_utc"]:
            return True
    return False


def separation_order(mission):
    """INTEGRATED assignments ordered by port stack_position DESC, tie-break
    assignment created_at ASC (ids never used for ordering)."""
    cands = [
        a
        for a in db["assignments"].values()
        if a["mission_id"] == mission["id"] and a["status"] == "INTEGRATED"
    ]
    cands.sort(
        key=lambda a: (
            -db["dispenser_ports"][a["dispenser_port_id"]]["stack_position"],
            a["created_at"],
            a["_seq"],
        )
    )
    return cands
