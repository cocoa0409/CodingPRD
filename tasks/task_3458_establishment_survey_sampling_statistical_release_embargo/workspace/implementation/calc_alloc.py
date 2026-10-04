"""Neyman stratum allocation (frame freeze) and base sampling weight."""
from decimal import Decimal
from fractions import Fraction

from errors import raise_err, ERR_SAMPLE_BUDGET_INFEASIBLE
from store import (
    DB, SIZE_DISPERSION, MIN_STRATUM_SAMPLE, INDUSTRIES, SIZE_CLASSES, round6,
)


def _tie_index(stratum):
    return (
        INDUSTRIES.index(stratum["industry_code"]),
        SIZE_CLASSES.index(stratum["size_class"]),
    )


def neyman_allocate(strata, budget_n):
    """Compute per-stratum allocations exactly per PRD 3.1.

    raw_h = N * (n_h * s_h) / SUM(n_j * s_j); floor, clamp at the minimum of 2
    (clamping consumes budget first); reconcile to exactly N by repeatedly
    adding to the unclamped stratum with the largest fractional part or
    subtracting from the stratum with the smallest fractional part whose
    allocation still exceeds the minimum; ties by industry_code ASC then
    size_class ASC (SMALL < MEDIUM < LARGE). Raw shares are never rounded.
    """
    denom = sum(s["frame_unit_count"] * SIZE_DISPERSION[s["size_class"]] for s in strata)
    raws = [
        Fraction(budget_n * s["frame_unit_count"] * SIZE_DISPERSION[s["size_class"]], denom)
        for s in strata
    ]
    floors = [r.numerator // r.denominator for r in raws]  # non-negative: exact floor
    allocs = [max(MIN_STRATUM_SAMPLE, f) for f in floors]
    clamped = [f < MIN_STRATUM_SAMPLE for f in floors]
    fracs = [r - f for r, f in zip(raws, floors)]

    diff = budget_n - sum(allocs)
    while diff > 0:
        candidates = [i for i in range(len(strata)) if not clamped[i]]
        if not candidates:
            raise_err(ERR_SAMPLE_BUDGET_INFEASIBLE,
                      "sample budget cannot be reconciled across strata")
        i = min(candidates, key=lambda j: (-fracs[j], _tie_index(strata[j])))
        allocs[i] += 1
        diff -= 1
    while diff < 0:
        candidates = [i for i in range(len(strata)) if allocs[i] > MIN_STRATUM_SAMPLE]
        if not candidates:
            raise_err(ERR_SAMPLE_BUDGET_INFEASIBLE,
                      "sample budget infeasible: all strata at minimum allocation")
        i = min(candidates, key=lambda j: (fracs[j], _tie_index(strata[j])))
        allocs[i] -= 1
        diff += 1
    return allocs


def latest_frozen_frame(program_code):
    """The program's latest FROZEN, non-superseded frame by frozen_at."""
    candidates = [
        f for f in DB["frames"].values()
        if f["program_code"] == program_code and f["frame_status"] == "FROZEN"
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda f: (f["frozen_at"], f["_seq"]))


def base_weight_for(frame, industry_code, size_class):
    """round_half_up(frame_unit_count / allocated_sample_size, 6) for the
    matching stratum of the given FROZEN frame."""
    for s in frame["strata"]:
        if s["industry_code"] == industry_code and s["size_class"] == size_class:
            return round6(
                Decimal(s["frame_unit_count"]) / Decimal(s["allocated_sample_size"])
            )
    return None
