"""Arithmetic rules of PRD sections 2.5 and 3 - every rounding step is pinned."""

from decimal import Decimal, ROUND_CEILING, ROUND_HALF_UP, getcontext

getcontext().prec = 60

D0 = Decimal(0)

# ---- precision quanta (PRD 2.5) --------------------------------------------
Q_DENSITY = Decimal("0.0001")   # 4 dp, g/cm3
Q_DOSE = Decimal("0.01")        # 2 dp, kGy
Q_MASS = Decimal("0.001")       # 3 dp, kg
Q_MONEY = Decimal("0.01")       # 2 dp, USD

# ---- emission rate schedule (PRD 3.2 / 3.6) --------------------------------
TIER1_MAX_KG = Decimal("50.000")
TIER2_MAX_KG = Decimal("200.000")
TIER1_RATE_USD = Decimal("12.00")
TIER2_RATE_USD = Decimal("18.50")
TIER3_RATE_USD = Decimal("27.00")

# ---- aeration derating (PRD 3.8) -------------------------------------------
DENSITY_BREAK_LOW = Decimal("0.1000")
DENSITY_BREAK_HIGH = Decimal("0.2000")
DENSITY_FACTOR_LOW = Decimal("1.00")
DENSITY_FACTOR_MID = Decimal("1.25")
DENSITY_FACTOR_HIGH = Decimal("1.60")
RETEST_MULTIPLIER_STEP = Decimal("0.5")
MAX_RESIDUAL_RETESTS = 2

# ---- VDmax audit (PRD 3.3) -------------------------------------------------
VDMAX_SAMPLE_SIZE = 100
PASS_INTERVAL_DAYS = 90
CONDITIONAL_INTERVAL_DAYS = 30
MAX_CONSECUTIVE_CONDITIONAL = 2

KG_TO_G = Decimal(1000)
M3_TO_CM3 = Decimal(1000000)


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    if value is None:
        return None
    return Decimal(str(value))


def round_half_up(value, quantum):
    return dec(value).quantize(quantum, rounding=ROUND_HALF_UP)


def round_density(value):
    return round_half_up(value, Q_DENSITY)


def round_dose(value):
    return round_half_up(value, Q_DOSE)


def round_mass(value):
    return round_half_up(value, Q_MASS)


def round_money(value):
    return round_half_up(value, Q_MONEY)


def ceil_hours(value):
    return int(dec(value).to_integral_value(rounding=ROUND_CEILING))


# ---------------------------------------------------------------------------
# cycle_load_density
# ---------------------------------------------------------------------------
def cycle_load_density(rows):
    """rows: iterable of (pallet_count, pallet_mass_kg, pallet_volume_m3).

    Accumulations are never rounded; the quotient is rounded exactly once to
    four decimal places (PRD 3.5).
    """
    total_mass_g = D0
    total_volume_cm3 = D0
    for pallet_count, pallet_mass_kg, pallet_volume_m3 in rows:
        total_mass_g += Decimal(pallet_count) * dec(pallet_mass_kg) * KG_TO_G
        total_volume_cm3 += Decimal(pallet_count) * dec(pallet_volume_m3) * M3_TO_CM3
    if total_volume_cm3 == 0:
        return Decimal("0.0000")
    return round_density(total_mass_g / total_volume_cm3)


# ---------------------------------------------------------------------------
# emission_fee_usd - the six pinned steps of PRD 3.6
# ---------------------------------------------------------------------------
def abated_mass(raw_eto_charge_kg, abatement_efficiency_pct):
    """Step one."""
    survival = Decimal(1) - (dec(abatement_efficiency_pct) / Decimal(100))
    return round_mass(dec(raw_eto_charge_kg) * survival)


def prospective_ytd(consumed_kg_ytd, abated_kg):
    """Step two."""
    return round_mass(dec(consumed_kg_ytd) + dec(abated_kg))


def emission_rate(prospective):
    """Step four - the band is keyed on the POST-charge figure."""
    prospective = dec(prospective)
    if prospective <= TIER1_MAX_KG:
        return TIER1_RATE_USD
    if prospective <= TIER2_MAX_KG:
        return TIER2_RATE_USD
    return TIER3_RATE_USD


def emission_fee(abated_kg, rate):
    """Step five."""
    return round_money(dec(abated_kg) * dec(rate))


# ---------------------------------------------------------------------------
# aeration_required_hours - dual variant (PRD 3.8)
# ---------------------------------------------------------------------------
def density_factor(load_density):
    d = dec(load_density)
    if d < DENSITY_BREAK_LOW:
        return DENSITY_FACTOR_LOW
    if d < DENSITY_BREAK_HIGH:
        return DENSITY_FACTOR_MID
    return DENSITY_FACTOR_HIGH


def required_hours_standard(base_hours, factor):
    return ceil_hours(Decimal(base_hours) * dec(factor))


def required_hours_extended(base_hours, factor, retest_count):
    multiplier = Decimal(1) + RETEST_MULTIPLIER_STEP * Decimal(retest_count)
    return ceil_hours(Decimal(base_hours) * dec(factor) * multiplier)


# ---------------------------------------------------------------------------
# vdmax_audit_verdict (PRD 3.3)
# ---------------------------------------------------------------------------
def vdmax_outcome(positives):
    if positives == 0:
        return "PASS", PASS_INTERVAL_DAYS
    if positives == 1:
        return "CONDITIONAL_PASS", CONDITIONAL_INTERVAL_DAYS
    return "FAIL", 0
