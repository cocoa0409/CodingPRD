"""Every calculation rule of the service, with the pinned rounding orders."""

from decimal import Decimal, ROUND_HALF_UP

# --------------------------------------------------------------------------
# Rounding primitives
# --------------------------------------------------------------------------

ZERO = Decimal("0")


def D(value):
    """Convert to Decimal without ever going through binary float arithmetic."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if value is None:
        return None
    return Decimal(str(value))


def rhu(value, places):
    """round_half_up to `places` decimals -- a midpoint always rounds away from zero."""
    if value is None:
        return None
    quant = Decimal(1).scaleb(-places)
    return D(value).quantize(quant, rounding=ROUND_HALF_UP)


def out_num(value):
    """Render a Decimal for JSON without losing its declared scale semantics."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


# --------------------------------------------------------------------------
# supplier_qualification_score
# --------------------------------------------------------------------------

AUDIT_WEIGHT = Decimal("0.40")
PPM_WEIGHT = Decimal("0.35")
CAPA_WEIGHT = Decimal("0.25")
PPM_DIVISOR = Decimal("50")
CAPA_PENALTY = Decimal("12.5")
QUALIFIED_SCORE_FLOOR = Decimal("85.00")
CONDITIONAL_SCORE_FLOOR = Decimal("70.00")


def supplier_qualification_score(audit_score, defect_ppm, open_capa_count):
    audit_component = D(audit_score)
    ppm_component = max(ZERO, Decimal(100) - D(defect_ppm) / PPM_DIVISOR)
    capa_component = max(ZERO, Decimal(100) - D(open_capa_count) * CAPA_PENALTY)
    total = (
        AUDIT_WEIGHT * audit_component
        + PPM_WEIGHT * ppm_component
        + CAPA_WEIGHT * capa_component
    )
    return rhu(total, 2)


def supplier_band(score):
    """Band selection uses the ROUNDED score. None means below the floor."""
    if score >= QUALIFIED_SCORE_FLOOR:
        return "QUALIFIED"
    if score >= CONDITIONAL_SCORE_FLOOR:
        return "CONDITIONAL"
    return None


# --------------------------------------------------------------------------
# lot_holiday_density
# --------------------------------------------------------------------------

MIN_SAMPLE_SIZE = 3
MAX_HOLIDAYS_PER_TANK = Decimal("0.50")
MAX_ADHESION_CLASS = 2


def required_sample_size(planned_quantity):
    """max(3, ceil(planned_quantity * 0.05)) computed with exact integer arithmetic."""
    ceil_five_percent = -((-int(planned_quantity) * 5) // 100)
    return max(MIN_SAMPLE_SIZE, ceil_five_percent)


def holiday_density(holiday_count, sample_size):
    return rhu(D(holiday_count) / D(sample_size), 4)


def holiday_verdict(density):
    return "FAIL" if density > MAX_HOLIDAYS_PER_TANK else "PASS"


def adhesion_verdict(adhesion_class):
    return "FAIL" if int(adhesion_class) > MAX_ADHESION_CLASS else "PASS"


# --------------------------------------------------------------------------
# insulation_r_value_achieved
# --------------------------------------------------------------------------

R_VALUE_PER_MM = Decimal("0.4")
MIN_FOAM_THICKNESS_MM = 40


def achieved_r_value(foam_thickness_mm):
    return rhu(D(foam_thickness_mm) * R_VALUE_PER_MM, 1)


# --------------------------------------------------------------------------
# uef_compliance_margin / rating_floor_check
# --------------------------------------------------------------------------

SMALL_CAPACITY_MAX_GALLONS = 55
FEDERAL_MIN_UEF = {
    "GAS": {"small": Decimal("0.58"), "large": Decimal("0.55")},
    "ELECTRIC": {"small": Decimal("0.92"), "large": Decimal("1.90")},
    "HEAT_PUMP": {"small": Decimal("2.20"), "large": Decimal("2.90")},
}
SAMPLE_DERATE = {1: Decimal("0.02"), 2: Decimal("0.01"), 3: Decimal("0.00")}
R_VALUE_CREDIT_BASE = Decimal("16")
R_VALUE_CREDIT_PER_POINT = Decimal("0.005")
R_VALUE_CREDIT_MAX = Decimal("0.03")
RATING_FLOOR = {
    "FIRST_HOUR_RATING": Decimal("30.0"),
    "RECOVERY": Decimal("10.0"),
}


def uef_effective_minimum(fuel_type, nominal_capacity_gallons, insulation_r_value,
                         sample_size):
    tier = "small" if int(nominal_capacity_gallons) <= SMALL_CAPACITY_MAX_GALLONS else "large"
    base_min = FEDERAL_MIN_UEF[fuel_type][tier]
    derate = SAMPLE_DERATE[min(int(sample_size), 3)]
    credit = min(
        R_VALUE_CREDIT_MAX,
        max(ZERO, D(insulation_r_value) - R_VALUE_CREDIT_BASE) * R_VALUE_CREDIT_PER_POINT,
    )
    return rhu(base_min + derate - credit, 4)


def test_margin(measured_value, effective_minimum):
    return rhu(D(measured_value) - D(effective_minimum), 4)


def test_status(margin):
    return "PASSED" if margin >= 0 else "FAILED"


# --------------------------------------------------------------------------
# certified_rating_rounding -- per-test rounding first, then the mean
# --------------------------------------------------------------------------

def mean_of_rounded(values, places):
    if not values:
        return None
    total = ZERO
    for value in values:
        total += rhu(value, places)
    return rhu(total / Decimal(len(values)), places)


# --------------------------------------------------------------------------
# unit_serial_assignment
# --------------------------------------------------------------------------

SERIAL_SEQ_WIDTH = 5


def serial_number(prefix, production_period, seq):
    compact = production_period.replace("-", "")
    return "%s-%s-%s" % (prefix, compact, str(seq).zfill(SERIAL_SEQ_WIDTH))


# --------------------------------------------------------------------------
# water_hardness_band_factor
# --------------------------------------------------------------------------

HARDNESS_FACTOR = {
    "SOFT": Decimal("0.80"),
    "MODERATE": Decimal("1.00"),
    "HARD": Decimal("1.35"),
    "VERY_HARD": Decimal("1.80"),
}


def hardness_band(gpg):
    value = D(gpg)
    if value < Decimal("3.5"):
        return "SOFT"
    if value <= Decimal("7.0"):
        return "MODERATE"
    if value <= Decimal("10.5"):
        return "HARD"
    return "VERY_HARD"


# --------------------------------------------------------------------------
# unit_months_in_service
# --------------------------------------------------------------------------

SERVICE_MONTH_DAYS = 30


def months_in_service(shipped_at, now):
    if shipped_at is None:
        return None
    seconds = (now - shipped_at).total_seconds()
    period = SERVICE_MONTH_DAYS * 86400
    return int(seconds // period)


# --------------------------------------------------------------------------
# warranty_reserve_ledger
# --------------------------------------------------------------------------

WARRANTY_ACCRUAL_CENTS_PER_UNIT = {"GAS": 42000, "ELECTRIC": 31000, "HEAT_PUMP": 98000}


# --------------------------------------------------------------------------
# warranty_payout_proration
# --------------------------------------------------------------------------

TANK_FULL_COVERAGE_MONTHS = 72
TANK_HALF_COVERAGE_MONTHS = 96
COMPONENT_COVERAGE_MONTHS = 12
TANK_LIST_CENTS = 41500
COMPONENT_LIST_CENTS = {"THERMOSTAT": 4200, "GAS_VALVE": 8200, "COMPRESSOR": 52000}
LABOR_ALLOWANCE_CENTS = 12525
FREIGHT_ALLOWANCE_CENTS = 3325


def warranty_coverage(failure_mode, months):
    """Returns (coverage_pct as Decimal with two decimals, part_cents)."""
    m = int(months)
    if failure_mode in ("TANK_LEAK", "ANODE_DEPLETION"):
        if m <= TANK_FULL_COVERAGE_MONTHS:
            pct = Decimal("1.00")
        elif m <= TANK_HALF_COVERAGE_MONTHS:
            pct = Decimal("0.50")
        else:
            pct = Decimal("0.00")
        return pct, TANK_LIST_CENTS
    if failure_mode in COMPONENT_LIST_CENTS:
        pct = Decimal("1.00") if m <= COMPONENT_COVERAGE_MONTHS else Decimal("0.00")
        return pct, COMPONENT_LIST_CENTS[failure_mode]
    return Decimal("0.00"), 0


def warranty_payout(part_cents, coverage_pct):
    """Prorate and round EACH of the three lines, then sum."""
    line_part = rhu(D(part_cents) * coverage_pct, 0)
    line_labor = rhu(D(LABOR_ALLOWANCE_CENTS) * coverage_pct, 0)
    line_freight = rhu(D(FREIGHT_ALLOWANCE_CENTS) * coverage_pct, 0)
    return int(line_part + line_labor + line_freight)


# --------------------------------------------------------------------------
# tank_failure_rate_by_period
# --------------------------------------------------------------------------

PPM_SCALE = Decimal("1000000")


def weighted_exposure(pairs):
    """pairs = iterable of (months_in_service, hardness_factor)."""
    total = ZERO
    for months, factor in pairs:
        if months is None or factor is None:
            continue
        total += D(months) * D(factor)
    return rhu(total, 2)


def failure_rate_ppm(numerator, denominator):
    if denominator is None or D(denominator) == 0:
        return Decimal("0.0")
    return rhu(D(numerator) / D(denominator) * PPM_SCALE, 1)


# --------------------------------------------------------------------------
# recall_remedy_cost
# --------------------------------------------------------------------------

REMEDY_PARTS_CENTS = {
    "TANK_REPLACEMENT": 41500,
    "GAS_VALVE_KIT": 8200,
    "TP_VALVE_KIT": 3100,
    "FULL_UNIT_REPLACEMENT": 68000,
}
REMEDY_HOURS = {
    "TANK_REPLACEMENT": Decimal("3.5"),
    "GAS_VALVE_KIT": Decimal("1.0"),
    "TP_VALVE_KIT": Decimal("0.5"),
    "FULL_UNIT_REPLACEMENT": Decimal("4.0"),
}
REMEDY_LABOR_RATE_CENTS_PER_HOUR = Decimal("9800")
ADMIN_TIER_1_MAX_CENTS = 20000
ADMIN_TIER_2_MAX_CENTS = 50000
ADMIN_RATE_TIER_1 = Decimal("0.15")
ADMIN_RATE_TIER_2 = Decimal("0.10")
ADMIN_RATE_TIER_3 = Decimal("0.06")


def per_unit_remedy_cost(remedy_type):
    labor_cents = rhu(REMEDY_LABOR_RATE_CENTS_PER_HOUR * REMEDY_HOURS[remedy_type], 0)
    provisional_total = D(REMEDY_PARTS_CENTS[remedy_type]) + labor_cents
    # The tier is chosen ONCE from the provisional total and never re-selected.
    if provisional_total <= ADMIN_TIER_1_MAX_CENTS:
        admin_rate = ADMIN_RATE_TIER_1
    elif provisional_total <= ADMIN_TIER_2_MAX_CENTS:
        admin_rate = ADMIN_RATE_TIER_2
    else:
        admin_rate = ADMIN_RATE_TIER_3
    admin_fee_cents = rhu(provisional_total * admin_rate, 0)
    return int(provisional_total + admin_fee_cents)


# --------------------------------------------------------------------------
# recall_completion_rate
# --------------------------------------------------------------------------

def completion_pct(remedied_count, denominator):
    if not denominator:
        return Decimal("0.00")
    return rhu(D(remedied_count) / D(denominator) * Decimal(100), 2)
