"""Calculation rules (SCAFFOLD 1.3 / PRD 3). Pinned rounding orders are
normative: computing at full precision and rounding only at the end is the
rejected variant and yields different last-digit results."""
from decimal import Decimal

from constants import (
    BASE_PRICE_CENTS_PER_M2,
    BONUS_CAP_FRACTION,
    CARBON_NEGATIVE_BUFFER_KGCO2E,
    EOL_MAX_CREDIT_KGCO2E_PER_M2,
    GRADE_RATE_CENTS_PER_M2,
    OTHER_LOT_FACTOR,
    PATHWAY_BONUS_CENTS_PER_KG,
    TILE_MASS_KG_PER_M2,
    TRANSPORT_KGCO2E_PER_M2,
)
from util import q0, q2, q3, q4

ZERO = Decimal("0")


def recompute_batch(store, batch):
    """batch_recycled_content + batch_embodied_carbon + allocated_mass_kg.
    Triggered on every allocate/deallocate and re-validated at release."""
    mix = batch["feedstock_mix"]
    total = sum((e["quantity_kg"] for e in mix), ZERO)
    batch["allocated_mass_kg"] = total
    if total == 0:
        # Undefined (null) while the mix mass is zero.
        batch["recycled_content_pct"] = None
    else:
        recycled = sum(
            (
                e["quantity_kg"]
                for e in mix
                if store.lots[e["lot_id"]]["source_type"] != "VIRGIN"
            ),
            ZERO,
        )
        batch["recycled_content_pct"] = q2(Decimal("100") * recycled / total)
    feedstock = sum(
        (
            e["quantity_kg"] * store.lots[e["lot_id"]]["carbon_factor_kgco2e_per_kg"]
            for e in mix
        ),
        ZERO,
    )
    # PINNED: feedstock component rounded to 4dp before combining.
    component = q4(feedstock / batch["produced_m2"])
    batch["embodied_carbon_kg_per_m2"] = q3(component + batch["mfg_intensity_kgco2e_per_m2"])


def pcf_input_set(store, report):
    """Batches of the report's collection with production_date in the half-open
    [period_start, period_end) and status RELEASED or EXHAUSTED."""
    return [
        b
        for b in store.batches.values()
        if b["collection_id"] == report["collection_id"]
        and b["status"] in ("RELEASED", "EXHAUSTED")
        and report["period_start"] <= b["production_date"] < report["period_end"]
    ]


def pcf_footprint(store, report):
    """Both variants computed from identical inputs at submit (PRD 3.6)."""
    batches = pcf_input_set(store, report)
    total_m2 = sum((b["produced_m2"] for b in batches), ZERO)
    # PINNED: each batch contributes its stored 3dp embodied value; never
    # recomputed from the mix at full precision.
    weighted = sum(
        (b["embodied_carbon_kg_per_m2"] * b["produced_m2"] for b in batches), ZERO
    )
    operational = q3(weighted / total_m2)
    credited = [
        t
        for t in store.takebacks.values()
        if t["collection_id"] == report["collection_id"]
        and t["status"] == "CREDITED"
        and t["credited_at"] is not None
        and report["period_start"] <= t["credited_at"] < report["period_end"]
    ]
    # PINNED: each take-back's recovered area is rounded to 2dp before summing.
    recovered_m2 = sum(
        (q2(t["collected_kg"] / TILE_MASS_KG_PER_M2) for t in credited), ZERO
    )
    recovery_share = recovered_m2 / total_m2
    if recovery_share > 1:
        recovery_share = Decimal("1")
    # PINNED: end-of-life credit at 4dp before subtraction.
    eol_credit = q4(EOL_MAX_CREDIT_KGCO2E_PER_M2 * recovery_share)
    lifecycle = q3(operational + TRANSPORT_KGCO2E_PER_M2 - eol_credit)
    return operational, lifecycle


def takeback_credit(collection, tb):
    """Returns (credit_variant, credit_cents). Variant selected by the declared
    collection's claim_intent: NONE -> STANDARD, else CIRCULAR (PRD 3.5)."""
    # PINNED: recovered m2 rounded to 2dp before any money is computed.
    recovered_m2 = q2(tb["collected_kg"] / TILE_MASS_KG_PER_M2)
    base_cents = recovered_m2 * GRADE_RATE_CENTS_PER_M2[tb["condition_grade"]]
    if collection["claim_intent"] == "NONE":
        return "STANDARD", int(q0(base_cents))
    bonus_raw = (
        tb["reuse_kg"] * PATHWAY_BONUS_CENTS_PER_KG["REUSE"]
        + tb["depolymerize_kg"] * PATHWAY_BONUS_CENTS_PER_KG["DEPOLYMERIZE"]
        + tb["downcycle_kg"] * PATHWAY_BONUS_CENTS_PER_KG["DOWNCYCLE"]
        + tb["landfill_kg"] * PATHWAY_BONUS_CENTS_PER_KG["LANDFILL"]
    )
    cap = q2(BONUS_CAP_FRACTION * base_cents)
    bonus = cap if cap < bonus_raw else bonus_raw
    return "CIRCULAR", int(q0(base_cents + bonus))


def replacement_quote(zone, zone_batch, matched_batch):
    """zone.area_m2 * 1200 * (1.00 same dye lot else 1.15), half-up to cents."""
    factor = (
        Decimal("1.00")
        if matched_batch["dye_lot_code"] == zone_batch["dye_lot_code"]
        else OTHER_LOT_FACTOR
    )
    return int(q0(zone["area_m2"] * BASE_PRICE_CENTS_PER_M2 * factor))


def dye_lot_match(store, zone, zone_batch):
    """Candidates: same collection as the zone's batch, RELEASED, available_m2
    >= zone.area_m2. Ranked: exact dye lot first, then |delta_e difference|
    ascending, then created_at ascending (earliest first). Resource ids are
    never a tie-breaker; the creation sequence only stabilizes exact-timestamp
    ties, which the clock's stillness can produce."""
    candidates = [
        b
        for b in store.batches.values()
        if b["collection_id"] == zone_batch["collection_id"]
        and b["status"] == "RELEASED"
        and b["available_m2"] >= zone["area_m2"]
    ]
    if not candidates:
        return None
    lot_code = zone_batch["dye_lot_code"]
    z_de = zone_batch["delta_e"]
    candidates.sort(
        key=lambda b: (
            0 if b["dye_lot_code"] == lot_code else 1,
            abs(b["delta_e"] - z_de),
            b["created_at"],
            b["_seq"],
        )
    )
    return candidates[0]


def claim_required_offset(claim, report):
    """Pinned evaluation order: report's stored variant selected by boundary ->
    gross = value * claimed_volume_m2 -> max(0, gross) plus the 500 kg buffer
    only for CARBON_NEGATIVE. Stored at 3dp."""
    if claim["boundary"] == "CRADLE_TO_GRAVE":
        report_value = report["lifecycle_kgco2e_per_m2"]
    else:
        report_value = report["operational_kgco2e_per_m2"]
    gross = report_value * claim["claimed_volume_m2"]
    required = gross if gross > 0 else ZERO
    if claim["claim_type"] == "CARBON_NEGATIVE":
        required = required + CARBON_NEGATIVE_BUFFER_KGCO2E
    return q3(required)


def coverage_of(claim):
    """NONE when retired == 0; FULL when retired >= required; else PARTIAL.
    Exact decimal comparisons on stored values."""
    retired = claim["retired_kgco2e"]
    required = claim["required_offset_kgco2e"]
    if retired == 0:
        return "NONE"
    if required is not None and retired >= required:
        return "FULL"
    return "PARTIAL"


def recompute_target(target):
    """target_posture: current = baseline before any reading, else the reading
    with the greatest period_end (tie: the one recorded later wins). ON_TRACK
    if current <= target_intensity (inclusive), else AT_RISK if current <=
    baseline, else BREACHED."""
    log = target["readings_log"]
    if not log:
        target["current_intensity_kgco2e_per_m2"] = target[
            "baseline_intensity_kgco2e_per_m2"
        ]
    else:
        latest_idx = max(range(len(log)), key=lambda i: (log[i]["period_end"], i))
        target["current_intensity_kgco2e_per_m2"] = log[latest_idx][
            "intensity_kgco2e_per_m2"
        ]
    target_intensity = target["baseline_intensity_kgco2e_per_m2"] * (
        Decimal("1") - target["target_reduction_pct"]
    )
    current = target["current_intensity_kgco2e_per_m2"]
    if current <= target_intensity:
        target["posture"] = "ON_TRACK"
    elif current <= target["baseline_intensity_kgco2e_per_m2"]:
        target["posture"] = "AT_RISK"
    else:
        target["posture"] = "BREACHED"


def supplier_reliability(store, supplier_name):
    """Computed at lot creation over prior decided (QC_PASSED|QC_FAILED) lots
    of the same supplier_name; 100.00 when none. Call before inserting the new
    lot so only strictly-prior lots count."""
    decided = [
        lot
        for lot in store.lots.values()
        if lot["supplier_name"] == supplier_name
        and lot["status"] in ("QC_PASSED", "QC_FAILED")
    ]
    decided.sort(key=lambda lot: (lot["created_at"], lot["_seq"]))
    if not decided:
        return Decimal("100.00")
    passed = sum(
        (lot["quantity_kg"] for lot in decided if lot["status"] == "QC_PASSED"), ZERO
    )
    total = sum((lot["quantity_kg"] for lot in decided), ZERO)
    return q2(Decimal("100") * passed / total)


def zone_code_in_use(store, site_id, zone_code, exclude_zone_id=None):
    """zone_code uniqueness among the site's zones currently IN_SERVICE. The
    zone being replaced is excluded at order completion: it leaves IN_SERVICE
    in the same transition that creates its successor."""
    for z in store.zones.values():
        if (
            z["site_id"] == site_id
            and z["status"] == "IN_SERVICE"
            and z["zone_code"] == zone_code
            and z["id"] != exclude_zone_id
        ):
            return True
    return False


def periods_overlap(s1, e1, s2, e2):
    """Half-open [start, end) overlap; touching endpoints do not overlap."""
    return s1 < e2 and s2 < e1
