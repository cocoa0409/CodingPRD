"""Quality-side calculations (PRD 3.4, 3.6, 3.7; SCAFFOLD 1.3).

batch_yield (provisional/final variants), excursion_evaluation (SCREENING and
MKT variants), comparability_equivalence (pinned compute-once/exclude-once
order). All statistical quantities use Decimal with the PRD's rounding.
"""
import math
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP

import store
from errors import err
from constants import (
    ABS_MARGIN,
    DESIGN_TITER_G_PER_L,
    EXCLUSION_SIGMA,
    FREEZE_ALLOWANCE_C,
    KINETIC_RATIO,
    MKT_ALLOWANCE_C,
    PROVISIONAL_RECOVERY_FACTOR,
    REL_MARGIN,
    SCREENING_MAX_EXCURSION_COUNT,
    SPIKE_ALLOWANCE_C,
    UNITS_PER_GRAM,
)


def _dec(v):
    return Decimal(str(v))


def _round(value, places):
    return value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def provisional_yield(capacity_liters):
    raw = _dec(capacity_liters) * DESIGN_TITER_G_PER_L * UNITS_PER_GRAM \
        * PROVISIONAL_RECOVERY_FACTOR
    return int(raw.to_integral_value(rounding=ROUND_FLOOR))


def final_yield(batch):
    """Final variant: mean of VERIFIED DOWNSTREAM TITER results (4dp half-up);
    design titer when none exist; floor of avg * capacity * UNITS_PER_GRAM."""
    campaign = store.get("campaigns", batch["campaign_id"])
    train = store.get("trains", campaign["train_id"])
    titers = [
        _dec(t["measured_value"]) for t in store.all_recs("tests")
        if t["batch_lot_id"] == batch["id"] and t["status"] == "VERIFIED"
        and t["test_type"] == "TITER" and t["phase"] == "DOWNSTREAM"
    ]
    if titers:
        avg = _round(sum(titers) / Decimal(len(titers)), 4)
    else:
        avg = DESIGN_TITER_G_PER_L
    raw = avg * _dec(train["capacity_liters"]) * UNITS_PER_GRAM
    return int(raw.to_integral_value(rounding=ROUND_FLOOR))


def excursion_verdict(shipment, product, readings):
    """Returns (verdict, variant): ACCEPTABLE/UNACCEPTABLE, SCREENING/MKT."""
    if shipment["market_type"] == "CLINICAL":
        lo, hi = _dec(product["min_storage_temp_c"]), _dec(product["max_storage_temp_c"])
        in_band = all(lo <= _dec(r["temperature_c"]) <= hi for r in readings)
        over = sum(1 for r in readings if _dec(r["temperature_c"]) > hi)
        ok = in_band and over <= SCREENING_MAX_EXCURSION_COUNT
        return ("ACCEPTABLE" if ok else "UNACCEPTABLE"), "SCREENING"
    # MKT variant (COMMERCIAL)
    temps = [float(r["temperature_c"]) for r in readings]
    mean_exp = sum(math.exp(-KINETIC_RATIO / (t + 273.15)) for t in temps) / len(temps)
    mkt_k = -KINETIC_RATIO / math.log(mean_exp)
    mkt_c = _round(Decimal(str(mkt_k - 273.15)), 3)
    hi = _dec(product["max_storage_temp_c"])
    lo = _dec(product["min_storage_temp_c"])
    ok = (
        mkt_c <= hi + MKT_ALLOWANCE_C
        and _dec(max(temps)) <= hi + SPIKE_ALLOWANCE_C
        and _dec(min(temps)) >= lo - FREEZE_ALLOWANCE_C
    )
    return ("ACCEPTABLE" if ok else "UNACCEPTABLE"), "MKT"


def comparability_assessment(study):
    """Returns (baseline_mean, equivalence_margin, comparable_bool, error).

    Pinned order: full-baseline stats -> single exclusion pass -> mu1 rounded
    once -> margin -> candidate values -> verdict band. Raises
    ERR_STUDY_DATA_MISSING via err() when a candidate lacks data.
    """
    values = [_dec(v) for v in study["baseline_attribute_values"]]
    n = Decimal(len(values))
    mu0 = sum(values) / n
    var = sum((v - mu0) ** 2 for v in values) / n
    sd0 = var.sqrt()
    lo = mu0 - EXCLUSION_SIGMA * sd0
    hi = mu0 + EXCLUSION_SIGMA * sd0
    survivors = [v for v in values if lo <= v <= hi]
    mu1 = _round(sum(survivors) / Decimal(len(survivors)), 4)
    margin = _round(max(ABS_MARGIN, REL_MARGIN * mu1), 4)
    candidates = []
    for bid in study["candidate_batch_ids"]:
        tests = [t for t in store.all_recs("tests")
                 if t["batch_lot_id"] == bid and t["status"] == "VERIFIED"
                 and t["test_type"] == "PURITY" and t["phase"] == "DOWNSTREAM"]
        if not tests:
            err("ERR_STUDY_DATA_MISSING",
                f"Candidate batch {bid} lacks a VERIFIED DOWNSTREAM PURITY test")
        latest = max(tests, key=lambda t: (t["created_at"], t["_seq"]))
        candidates.append(_dec(latest["measured_value"]))
    comparable = all(mu1 - margin <= v <= mu1 + margin for v in candidates)
    return mu1, margin, comparable
