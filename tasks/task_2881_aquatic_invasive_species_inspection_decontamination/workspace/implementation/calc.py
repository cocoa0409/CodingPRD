"""Program constants and the calculation rules of PRD section 3."""

import math
from decimal import Decimal, ROUND_HALF_UP

# --- roles / program identity ----------------------------------------------
PROGRAM_STATE_CODE = "MT"

# --- certification ---------------------------------------------------------
CERT_LEVEL1_HOURS = Decimal("8")
CERT_LEVEL2_HOURS = Decimal("40")
CERT_VALID_HOURS = 8760
CERTIFIED_INSPECTOR_DECON_THRESHOLD = 2

# --- reciprocity -----------------------------------------------------------
RECIPROCITY_CREDIT_POINTS = 20

# --- risk score ------------------------------------------------------------
RISK_TIER_POINTS = {"HIGH": 40, "MODERATE": 20, "LOW": 5}
INFESTATION_POINTS = {"CONFIRMED_INFESTED": 30, "SUSPECT": 15, "CLEAN": 0}
RESIDUAL_WATER_BASE_POINTS = 20
RESIDUAL_WATER_ML_DIVISOR = 100
RESIDUAL_WATER_ML_CAP_POINTS = 15
DRY_CREDIT_POINTS_PER_DAY = 5
DRY_CREDIT_CAP_POINTS = 25
VESSEL_FACTOR_ELEVATED = Decimal("1.25")
VESSEL_FACTOR_STANDARD = Decimal("1.00")
ELEVATED_VESSEL_TYPES = ("PONTOON_MULTI_CHAMBER", "BALLASTED_WAKEBOAT")
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100
BAND_MODERATE_MIN = 25
BAND_HIGH_MIN = 50
BAND_EXTREME_MIN = 75

# --- decontamination -------------------------------------------------------
MIN_TREATMENT_TEMP_F = Decimal("120")
HIGH_TREATMENT_TEMP_F = Decimal("140")
MIN_TREATMENT_PSI = Decimal("1500")
HIGH_TREATMENT_PSI = Decimal("3000")
REQUIRED_DWELL_SECONDS = {"LOW": 30, "MODERATE": 60, "HIGH": 120, "EXTREME": 180}
BASE_DRY_HOURS = {"LOW": 12, "MODERATE": 36, "HIGH": 72, "EXTREME": 120}
MAX_CREDIT_FRACTION = Decimal("0.75")
MIN_DRY_HOURS = 6
BAY_BUFFER_MINUTES = 30
MAX_DECON_ATTEMPTS = 3

# --- fees ------------------------------------------------------------------
BASE_INSPECTION_FEE_CENTS = 2500
DECON_RATE_CENTS_PER_MINUTE = 450
SURCHARGE_TIER_1_THRESHOLD_CENTS = 10000
SURCHARGE_TIER_2_THRESHOLD_CENTS = 25000

# --- quarantine ------------------------------------------------------------
BASE_HOLD_HOURS = {"LOW": 24, "MODERATE": 48, "HIGH": 72, "EXTREME": 120}
REJECTION_EXTENSION_HOURS = 24
REJECTED_RELEASE_REFERRAL_THRESHOLD = 2
WATCHLIST_STRIKE_THRESHOLD = 2

# --- enforcement ----------------------------------------------------------
PENALTY_BASE_CENTS = 15000
PENALTY_STRIKE_STEP_CENTS = 7500

# --- detection ------------------------------------------------------------
INFESTATION_CONFIRM_LIVE_THRESHOLD = 2
INFESTATION_SUSPECT_DETECTION_THRESHOLD = 1

# --- campaigns ------------------------------------------------------------
CAMPAIGN_BUDGET_CAP_CENTS = 5000000
CAMPAIGN_IMPRESSIONS_BONUS_DIVISOR = 5000
CAMPAIGN_IMPRESSIONS_BONUS_CAP = 10


def rhu(value, places):
    """Round half up to the given number of decimal places."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_int(value):
    return int(rhu(value, 0))


def as_float(value, places):
    if value is None:
        return None
    return float(rhu(value, places))


# ---------------------------------------------------------------------------
# inspector_certification_level
# ---------------------------------------------------------------------------
def certification_level_for(hours_total, decon_endorsement):
    if hours_total < CERT_LEVEL1_HOURS:
        return "TRAINEE"
    if hours_total < CERT_LEVEL2_HOURS:
        return "LEVEL_1"
    if not decon_endorsement:
        return "LEVEL_2"
    return "DECON_CERTIFIED"


# ---------------------------------------------------------------------------
# watercraft_risk_score
# ---------------------------------------------------------------------------
def dry_credit_points(last_removed_at, basis_instant):
    """Standing-time credit, floored to whole days and capped."""
    if last_removed_at is None or basis_instant is None:
        standing_hours = 0
    else:
        delta = (basis_instant - last_removed_at).total_seconds()
        standing_hours = max(0, math.floor(delta / 3600.0))
    return min(DRY_CREDIT_CAP_POINTS,
               (standing_hours // 24) * DRY_CREDIT_POINTS_PER_DAY)


def risk_score(water_body, watercraft, residual_water_present, standing_water_ml,
               reciprocity_honored, last_removed_at, basis_instant):
    """Returns (score, dry_credit_points) for one basis instant."""
    tier_points = RISK_TIER_POINTS[water_body["risk_tier"]]
    infestation_points = INFESTATION_POINTS[water_body["infestation_status"]]

    water_points = 0
    if residual_water_present:
        water_points = RESIDUAL_WATER_BASE_POINTS + min(
            RESIDUAL_WATER_ML_CAP_POINTS,
            (standing_water_ml or 0) // RESIDUAL_WATER_ML_DIVISOR,
        )

    dry_credit = dry_credit_points(last_removed_at, basis_instant)
    recip_credit = RECIPROCITY_CREDIT_POINTS if reciprocity_honored else 0

    factor = (VESSEL_FACTOR_ELEVATED
              if watercraft["vessel_type"] in ELEVATED_VESSEL_TYPES
              else VESSEL_FACTOR_STANDARD)

    # PINNED ORDER: sum the point terms, multiply by the vessel factor, round
    # exactly once, then clamp.
    raw = Decimal(tier_points + infestation_points + water_points
                  - dry_credit - recip_credit) * factor
    score = min(RISK_SCORE_MAX, max(RISK_SCORE_MIN, rhu_int(raw)))
    return score, dry_credit


def risk_band_for(score):
    if score < BAND_MODERATE_MIN:
        return "LOW"
    if score < BAND_HIGH_MIN:
        return "MODERATE"
    if score < BAND_EXTREME_MIN:
        return "HIGH"
    return "EXTREME"


# ---------------------------------------------------------------------------
# decon_treatment_effectiveness / decon_required_dry_hours
# ---------------------------------------------------------------------------
def treatment_effectiveness_pct(water_temp_f, pressure_psi, dwell_seconds, band):
    temp_factor = Decimal("0.5") if Decimal(str(water_temp_f)) < HIGH_TREATMENT_TEMP_F else Decimal("1.0")
    psi_factor = Decimal("0.6") if Decimal(str(pressure_psi)) < HIGH_TREATMENT_PSI else Decimal("1.0")
    required = Decimal(REQUIRED_DWELL_SECONDS[band])
    dwell_factor = Decimal(dwell_seconds) / required
    if dwell_factor > Decimal("1.0"):
        dwell_factor = Decimal("1.0")
    return rhu(temp_factor * psi_factor * dwell_factor * Decimal(100), 2)


def required_dry_hours(band, effectiveness_pct):
    base = BASE_DRY_HOURS[band]
    credit = int(math.floor(
        (Decimal(base) * (Decimal(str(effectiveness_pct)) / Decimal(100)) * MAX_CREDIT_FRACTION)
    ))
    return base, max(MIN_DRY_HOURS, base - credit)


# ---------------------------------------------------------------------------
# inspection_total_fee_cents
# ---------------------------------------------------------------------------
def decon_fee_for_dwell(dwell_seconds):
    minutes = int(math.ceil(Decimal(dwell_seconds) / Decimal(60)))
    return DECON_RATE_CENTS_PER_MINUTE * minutes


def surcharge_for_subtotal(subtotal_cents):
    if subtotal_cents < SURCHARGE_TIER_1_THRESHOLD_CENTS:
        rate = Decimal("0.00")
    elif subtotal_cents < SURCHARGE_TIER_2_THRESHOLD_CENTS:
        rate = Decimal("0.05")
    else:
        rate = Decimal("0.10")
    return rhu_int(Decimal(subtotal_cents) * rate)


# ---------------------------------------------------------------------------
# quarantine_hold_hours / enforcement_penalty_cents
# ---------------------------------------------------------------------------
def hold_hours_for(band, rejected_release_count):
    return BASE_HOLD_HOURS[band] + REJECTION_EXTENSION_HOURS * rejected_release_count


def penalty_for(compliance_strikes):
    prior = max(0, compliance_strikes - 1)
    return PENALTY_BASE_CENTS + PENALTY_STRIKE_STEP_CENTS * prior


# ---------------------------------------------------------------------------
# campaign_effectiveness_score
# ---------------------------------------------------------------------------
def impressions_bonus(impressions):
    return min(CAMPAIGN_IMPRESSIONS_BONUS_CAP,
               (impressions or 0) // CAMPAIGN_IMPRESSIONS_BONUS_DIVISOR)


def effectiveness_score(window_rate, baseline_rate, bonus):
    raw = (Decimal(50)
           + (window_rate - rhu(baseline_rate, 4)) * Decimal(100)
           + Decimal(bonus))
    score = rhu(raw, 2)
    if score < Decimal("0.00"):
        score = Decimal("0.00")
    if score > Decimal("100.00"):
        score = Decimal("100.00")
    return score
