"""Shrink apportionment and the cooperative patronage waterfall."""

from fractions import Fraction

import domain
from constants import (AUDITED_TIER_RELIEF_BP, DAMAGE_BP, LATE_DELIVERY_BP,
                       PATRONAGE_CAP_BP, PRODUCER_FAULT_CAP_BP, SHORT_COUNT_BP,
                       SPEC_MISMATCH_BP, TEMP_ABUSE_EXCURSION_BP,
                       TEMP_ABUSE_NO_EXCURSION_BP)
from store import apply_bp, db, round_half_up_div, sorted_records, touch


# ---------------------------------------------------------------------------
# calculations.rejection_shrink_allocation
# ---------------------------------------------------------------------------

def _base_fault_bp(reason_code, temp_excursion):
    if reason_code == "TEMP_ABUSE":
        # inverts on the cold-chain evidence the hub itself recorded at staging
        return TEMP_ABUSE_EXCURSION_BP if temp_excursion else TEMP_ABUSE_NO_EXCURSION_BP
    if reason_code == "DAMAGE":
        return DAMAGE_BP
    if reason_code == "SPEC_MISMATCH":
        return SPEC_MISMATCH_BP
    if reason_code == "SHORT_COUNT":
        return SHORT_COUNT_BP
    return LATE_DELIVERY_BP


def compute_shrink(claim, allocation, producer):
    delivered = allocation["delivered_quantity"]
    buyer_credit = round_half_up_div(
        allocation["buyer_amount_cents"] * claim["quantity_rejected"], delivered)

    base_bp = _base_fault_bp(claim["reason_code"], allocation["temp_excursion"])

    tier = domain.food_safety_tier(producer) if producer is not None else "TIER_NONE"
    if tier == "TIER_AUDITED":
        relieved_bp = max(0, base_bp - AUDITED_TIER_RELIEF_BP)
    else:
        relieved_bp = base_bp
    # relief is applied BEFORE the cap
    producer_fault_bp = min(relieved_bp, PRODUCER_FAULT_CAP_BP)

    producer_charge = apply_bp(buyer_credit, producer_fault_bp)
    hub_absorbed = buyer_credit - producer_charge
    return {
        "producer_fault_bp": producer_fault_bp,
        "buyer_credit_cents": buyer_credit,
        "producer_charge_cents": producer_charge,
        "hub_absorbed_cents": hub_absorbed,
    }


# ---------------------------------------------------------------------------
# calculations.patronage_basis_valuation
# ---------------------------------------------------------------------------

def net_basis(producer):
    return max(0, producer["patronage_volume_cents"] - producer["shrink_charge_cents"])


def eligible_producers():
    out = []
    for producer in sorted_records(list(db.producers.values())):
        if producer["onboarding_status"] != "ACTIVE":
            continue
        if not domain.compliance_ok(producer):
            continue
        if net_basis(producer) <= 0:
            continue
        out.append(producer)
    return out


def build_snapshot():
    members = []
    total = 0
    for producer in eligible_producers():
        basis = net_basis(producer)
        members.append({
            "producer_id": producer["id"],
            "net": basis,
            "created_at": producer["created_at"],
            "seq": producer["_seq"],
        })
        total += basis
    return members, total


# ---------------------------------------------------------------------------
# calculations.patronage_distribution_waterfall
# ---------------------------------------------------------------------------

def distribute(cycle):
    pool = cycle["distributable_pool_cents"]
    total = cycle["basis_snapshot_total_cents"]
    members = cycle.get("_snapshot") or []
    if total <= 0 or not members:
        cycle["distributed_total_cents"] = 0
        cycle["remainder_cents"] = pool
        return

    cap_cents = (pool * PATRONAGE_CAP_BP) // 10000

    rows = []
    for member in members:
        raw = Fraction(pool * member["net"], total)
        base = min(raw.numerator // raw.denominator, cap_cents)
        rows.append({
            "producer_id": member["producer_id"],
            "net": member["net"],
            "created_at": member["created_at"],
            "seq": member["seq"],
            "raw": raw,
            "frac": raw - (raw.numerator // raw.denominator),
            "base": base,
            "headroom": cap_cents - base,
        })

    leftover = pool - sum(r["base"] for r in rows)

    walk_order = sorted(
        rows,
        key=lambda r: (-r["frac"], -r["net"], r["created_at"], r["seq"]),
    )

    while leftover > 0 and any(r["headroom"] > 0 for r in walk_order):
        progressed = False
        for row in walk_order:
            if leftover <= 0:
                break
            if row["headroom"] <= 0:
                continue
            row["base"] += 1
            row["headroom"] -= 1
            leftover -= 1
            progressed = True
        if not progressed:
            break

    distributed = 0
    for row in rows:
        producer = db.producers.get(row["producer_id"])
        if producer is not None and row["base"] > 0:
            producer["retained_patronage_cents"] += row["base"]
            touch(producer)
        distributed += row["base"]

    cycle["distributed_total_cents"] = distributed
    cycle["remainder_cents"] = pool - distributed
