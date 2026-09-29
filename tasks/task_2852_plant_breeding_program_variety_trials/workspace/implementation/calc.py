"""Exact-decimal calculations (PRD 2.6 and scaffold 1.3).

Every arithmetic rule is performed on exact decimals; rounding is ROUND_HALF_UP
at the decimal place the rule names.  Binary floating point is never used.
"""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, getcontext

getcontext().prec = 60

# ---- constants -------------------------------------------------------------
MIN_VALID_REPS = 3
HA_PER_PLOT_FACTOR = Decimal(800)          # 10000 m2 / 12.5 m2

STABLE_B_MIN = Decimal("0.80")
STABLE_B_MAX = Decimal("1.20")

YIELD_COMPONENT_CAP = Decimal(120)
QUALITY_MISS_PENALTY = Decimal(15)
IMPUTED_COMPONENT_VALUE = Decimal(60)
STAGE_CONFIDENCE = {
    "NURSERY": Decimal("0.90"),
    "STAGE_1": Decimal("0.95"),
    "STAGE_2": Decimal("1.00"),
    "STAGE_3": Decimal("1.00"),
    "PRE_COMMERCIAL": Decimal("1.00"),
}

MGMT_TIER_1_CEILING = Decimal("10000.00")
MGMT_TIER_2_CEILING = Decimal("50000.00")
MGMT_RATE_TIER_1 = Decimal("0.12")
MGMT_RATE_TIER_2 = Decimal("0.09")
MGMT_RATE_TIER_3 = Decimal("0.07")

BAG_SIZE_KG = Decimal(25)
SEED_LOSS_PCT = Decimal("0.08")
FIELD_MULTIPLICATION_FACTOR = 40

MIN_ADVANCE_SEED_G = 250

MAS_BONUS_PCT = Decimal("2.5")
RECOVERY_CAP_PCT = Decimal("99.900")
CONVERSION_THRESHOLD_PCT = Decimal("99.0")
CONVERTED_TRAIT_SCORE = 8

RESTRICTED_RATIO_NUM = 85          # utilisation >= 0.85
RESTRICTED_RATIO_DEN = 100


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rhu(value, places):
    """Round half up at `places` decimals."""
    exp = Decimal(1).scaleb(-places)
    return dec(value).quantize(exp, rounding=ROUND_HALF_UP)


def ceil_int(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# entry_yield_rollup
# ---------------------------------------------------------------------------
def entry_yield_rollup(values):
    """values: the ACCEPTED, non-outlier YIELD_KG_PLOT observation values."""
    n = len(values)
    total = sum((dec(v) for v in values), Decimal(0))
    plot_mean = rhu(total / Decimal(n), 3)
    per_ha = rhu(plot_mean * HA_PER_PLOT_FACTOR, 2)
    return plot_mean, per_ha


# ---------------------------------------------------------------------------
# trial_series_cost_allocation
# ---------------------------------------------------------------------------
def series_cost(pairs):
    """pairs: iterable of (plot_count, plot_cost_usd)."""
    subtotal_raw = sum((dec(pc) * dec(cost) for pc, cost in pairs), Decimal(0))
    subtotal = rhu(subtotal_raw, 2)
    if subtotal < MGMT_TIER_1_CEILING:
        rate = MGMT_RATE_TIER_1
    elif subtotal < MGMT_TIER_2_CEILING:
        rate = MGMT_RATE_TIER_2
    else:
        rate = MGMT_RATE_TIER_3
    fee = rhu(subtotal * rate, 2)
    total = rhu(subtotal + fee, 2)
    return subtotal, fee, total


# ---------------------------------------------------------------------------
# seed_increase_volume_plan
# ---------------------------------------------------------------------------
def volume_plan(demands):
    """demands: iterable of demand_kg values. Ceil per allocation, THEN sum."""
    bags = 0
    for d in demands:
        bags += ceil_int((dec(d) * (Decimal(1) + SEED_LOSS_PCT)) / BAG_SIZE_KG)
    allocated = ceil_int(
        (Decimal(bags) * BAG_SIZE_KG * Decimal(1000)) / Decimal(FIELD_MULTIPLICATION_FACTOR)
    )
    return bags, allocated


# ---------------------------------------------------------------------------
# marker_recovery_pct
# ---------------------------------------------------------------------------
def marker_recovery_pct(bc_generation, marker_assisted, target_marker_present):
    base = Decimal(100) * (Decimal(1) - (Decimal("0.5") ** (int(bc_generation) + 1)))
    bonus = MAS_BONUS_PCT if (marker_assisted and target_marker_present) else Decimal(0)
    value = rhu(base + bonus, 3)
    if value > RECOVERY_CAP_PCT:
        value = RECOVERY_CAP_PCT
    return value


# ---------------------------------------------------------------------------
# site capacity posture
# ---------------------------------------------------------------------------
def capacity_posture(peak, capacity):
    if capacity <= 0:
        return "FROZEN"
    if peak * 1 >= capacity:                      # utilisation >= 1.00
        return "FROZEN"
    if peak * RESTRICTED_RATIO_DEN >= capacity * RESTRICTED_RATIO_NUM:
        return "RESTRICTED"
    return "OPEN"


# ---------------------------------------------------------------------------
# Finlay-Wilkinson stability regression
# ---------------------------------------------------------------------------
def stability(points):
    """points: list of (x=site index_kg_per_ha, y=entry yield_kg_per_ha),
    both already-rounded two-decimal stored values."""
    n = len(points)
    if n < 2:
        return None, None, "UNCLASSIFIED"
    xs = [dec(p[0]) for p in points]
    ys = [dec(p[1]) for p in points]
    mean_x = sum(xs, Decimal(0)) / Decimal(n)
    mean_y = sum(ys, Decimal(0)) / Decimal(n)
    denom = sum(((x - mean_x) ** 2 for x in xs), Decimal(0))
    if denom == 0:
        return None, None, "UNCLASSIFIED"
    num = sum(((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)), Decimal(0))
    b_raw = num / denom
    b = rhu(b_raw, 4)
    mse = None
    if n >= 3:
        ss = Decimal(0)
        for x, y in zip(xs, ys):
            resid = y - (mean_y + b_raw * (x - mean_x))
            ss += resid * resid
        mse = rhu(ss / Decimal(n - 2), 2)
    if STABLE_B_MIN <= b <= STABLE_B_MAX:
        cls = "STABLE"
    elif b > STABLE_B_MAX:
        cls = "RESPONSIVE"
    else:
        cls = "BUFFERED"
    return b, mse, cls


# ---------------------------------------------------------------------------
# line_advancement_index (PRD 3.8)
# ---------------------------------------------------------------------------
_MIN_SPEC_TRAIT = {
    "TEST_WEIGHT_MIN": "TEST_WEIGHT",
    "PROTEIN_MIN": "PROTEIN",
    "OIL_MIN": "OIL",
}


def index_components(objective, line, source_mean):
    """Returns (yield_component, disease_component, quality_component) where a
    MISSING component is None."""
    # --- yield ---
    if source_mean is None:
        yield_c = None
    else:
        raw = rhu(Decimal(100) * dec(source_mean) / dec(objective["target_yield_kg_per_ha"]), 2)
        yield_c = raw if raw < YIELD_COMPONENT_CAP else YIELD_COMPONENT_CAP

    # --- disease ---
    scores = line.get("disease_resistance_scores") or {}
    if not scores:
        disease_c = None
    else:
        req = objective.get("required_disease_resistances") or []
        if len(req) == 0:
            disease_c = Decimal("100.00")
        else:
            min_score = dec(objective["min_resistance_score"])
            matched = 0
            for trait in req:
                if trait in scores and dec(scores[trait]) >= min_score:
                    matched += 1
            disease_c = rhu(Decimal(100) * Decimal(matched) / Decimal(len(req)), 2)

    # --- quality ---
    values = line.get("quality_trait_values") or {}
    if not values:
        quality_c = None
    else:
        specs = objective.get("quality_trait_specs") or {}
        miss = 0
        for spec_code, threshold in specs.items():
            if spec_code == "MOISTURE_MAX":
                trait = "MOISTURE"
                if trait not in values or dec(values[trait]) > dec(threshold):
                    miss += 1
            else:
                trait = _MIN_SPEC_TRAIT.get(spec_code)
                if trait is None:
                    continue
                if trait not in values or dec(values[trait]) < dec(threshold):
                    miss += 1
        raw = Decimal(100) - QUALITY_MISS_PENALTY * Decimal(miss)
        quality_c = raw if raw > 0 else Decimal(0)
        quality_c = rhu(quality_c, 2)
    return yield_c, disease_c, quality_c


def weighted_base(objective, yield_c, disease_c, quality_c):
    total = (dec(objective["yield_weight"]) * dec(yield_c)
             + dec(objective["disease_weight"]) * dec(disease_c)
             + dec(objective["quality_weight"]) * dec(quality_c))
    return rhu(total, 2)


def provisional_index(objective, line, source_mean):
    y, d, q = index_components(objective, line, source_mean)
    if y is None and d is None and q is None:
        return None
    imp = IMPUTED_COMPONENT_VALUE
    return weighted_base(objective, y if y is not None else imp,
                         d if d is not None else imp,
                         q if q is not None else imp)


def cumulative_index(objective, line, source_mean):
    y, d, q = index_components(objective, line, source_mean)
    zero = Decimal("0.00")
    base = weighted_base(objective, y if y is not None else zero,
                         d if d is not None else zero,
                         q if q is not None else zero)
    factor = STAGE_CONFIDENCE.get(line.get("pipeline_stage"), Decimal("1.00"))
    return rhu(base * factor, 2)
