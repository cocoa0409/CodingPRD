"""Domain constants and the pure calculation rules of PRD §2.8 / §3."""

from decimal import Decimal, ROUND_HALF_UP

# --- roles (PRD §2.1) --------------------------------------------------------
ROLES = ("PlatformAdmin", "StoreManager", "VeterinaryStaff", "GroomingStaff",
         "VaccinationStaff", "ComplianceOfficer", "PharmacyStaff", "TrainingStaff",
         "Any")

PROFILE_ROLES = tuple(r for r in ROLES if r != "Any")

# --- calculations constants --------------------------------------------------
HIGH_RISK_THRESHOLD = 70
SENSITIVE_THRESHOLD = 40
WEIGHT_BAND_LARGE_KG = Decimal("40.0")
WEIGHT_BAND_MEDIUM_KG = Decimal("25.0")
WEIGHT_BAND_LARGE_POINTS = 10
WEIGHT_BAND_MEDIUM_POINTS = 5
CONDITION_POINTS = {"CARDIAC": 30, "EPILEPSY": 25, "DIABETES": 20,
                    "ORTHOPEDIC": 15, "SKIN_INFECTION": 10}
PET_RISK_CAP = 100
BREED_RISK_SOFT_CEILING = 25
SCORE_CAP = 160
SCREENING_VALIDITY_DAYS = 30

TIER_INCLUSIONS = {
    "ESSENTIAL": {"grooming": 1, "vet": 0, "vaccine": 1},
    "PLUS": {"grooming": 2, "vet": 1, "vaccine": 1},
    "UNLIMITED": {"grooming": 6, "vet": 2, "vaccine": 2},
}
TIER_HARD_CAP = {"ESSENTIAL": 4, "PLUS": 8, "UNLIMITED": 12}
DEFAULT_MONTHLY_FEE_CENTS = {"ESSENTIAL": 3999, "PLUS": 6999, "UNLIMITED": 11999}
# Per-visit credits and the overage credit, taken literally from PRD §3.8.
GROOMING_VISIT_CREDIT_CENTS = 2500
VET_VISIT_CREDIT_CENTS = 4000
VACCINE_VISIT_CREDIT_CENTS = 1500
OVERAGE_CREDIT_CENTS = 500

STATE_DEFAULT_DAYS = {"CA": 1095, "TX": 365, "NY": 365, "FL": 1095}
BOOSTER_CAP_DAYS = 365
REPORTING_STATES = {"CA": True, "TX": True, "NY": True, "FL": False}

EXAM_CHARGE_CENTS = 8500
ITEM_WINDOW_DAYS = {"MEDICATION": 30, "DIET": 90, "TREATMENT": 60}

SURGE_FREEZE_PCT = Decimal("0.90")
RESTRICT_FREEZE_PCT = Decimal("0.80")
HYSTERESIS_RELEASE_PCT = Decimal("0.70")

PET_BUFFER_MINUTES = 15
NO_SHOW_GRACE_MINUTES = 30
PHARMACY_HOLD_HOURS = 72

CROSS_SELL_CREDIT_RATE = Decimal("0.10")

SEVERITY_POINTS = {"MINOR": 10, "MODERATE": 25, "SEVERE": 40}

INCIDENT_CLAIM_CAP = {"CA": 250000, "TX": 150000, "NY": 200000, "FL": 100000}

TERMINAL_BOOKING_STATES = ("COMPLETED", "CANCELLED", "NO_SHOW")
LIVE_BOOKING_STATES = ("REQUESTED", "SCREENED", "BAY_CONFIRMED", "IN_SERVICE")

ENCOUNTER_OCCUPANCY_STATES = ("SCHEDULED", "CHECKED_IN", "IN_EXAM")
ENCOUNTER_OCCUPIED_STATES = ("CHECKED_IN", "IN_EXAM")

VACCINE_TYPES = ("RABIES", "BORDETELLA", "DHPP", "FVRCP")
REPORTABLE_VACCINE_TYPES = ("RABIES",)


def round_half_up(value, places="0.01"):
    """ROUND_HALF_UP to the given quantum, returned as a Decimal."""
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


def cents(value):
    """Round to whole cents and return an int."""
    return int(round_half_up(value))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def json_number(value):
    """Decimal -> int when integral, float otherwise (JSON-safe)."""
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    return value


def screening_score(pet_risk_points, breed_risk_points, weight_kg,
                    health_condition_points):
    """PRD §3.2 weighted screening score, clamped to [0, 160]."""
    breed_ceiling = 0 if breed_risk_points <= BREED_RISK_SOFT_CEILING else BREED_RISK_SOFT_CEILING
    weight = dec(weight_kg)
    if weight >= WEIGHT_BAND_LARGE_KG:
        weight_points = WEIGHT_BAND_LARGE_POINTS
    elif weight >= WEIGHT_BAND_MEDIUM_KG:
        weight_points = WEIGHT_BAND_MEDIUM_POINTS
    else:
        weight_points = 0
    raw = (min(pet_risk_points, PET_RISK_CAP)
           + min(breed_risk_points, breed_ceiling)
           + weight_points + health_condition_points)
    return max(0, min(raw, SCORE_CAP))


def handling_level(score, breed_tier):
    """PRD §3.2 handling level: the breed tier is a floor, not a ceiling."""
    tier = breed_tier or "STANDARD"
    if tier == "HIGH_RISK" or score >= HIGH_RISK_THRESHOLD:
        return "HIGH_RISK"
    if tier == "SENSITIVE" or score >= SENSITIVE_THRESHOLD:
        return "SENSITIVE"
    return "STANDARD"


def monthly_total_cents(effective_fee_cents, tax_rate):
    """PRD §2.8: "a package's monthly total is the package's `monthly_fee_cents`
    multiplied by one plus the package's `state_sales_tax_rate`, rounded half-up
    to whole cents." The same sentence pins the rounding order for
    `total_price_cents`; the result is rounded to two decimal places so that
    `total_price_cents` carries the stated figure for six- and twelve-cycle
    packages rather than an integer-truncated one.
    """
    return round_half_up(dec(effective_fee_cents) * (Decimal(1) + dec(tax_rate)))


def cycle_totals(pre_tax_cents, overage_credit_cents, tax_rate):
    """Returns (cycle_total_cents, tax_cents). PRD §2.8 / §3.8."""
    rate = dec(tax_rate)
    total = round_half_up((dec(pre_tax_cents) - dec(overage_credit_cents))
                          * (Decimal(1) + rate))
    tax = round_half_up(total * rate / (Decimal(1) + rate))
    return total, tax


def posture_next(current_posture, occupied, capacity):
    """PRD §2.7 posture ladder with hysteresis and single-step release."""
    if current_posture == "FROZEN":
        return "OPEN" if occupied == 0 else "FROZEN"
    ratio = Decimal(occupied) / Decimal(capacity)
    if ratio >= SURGE_FREEZE_PCT:
        return "FROZEN"
    if ratio >= RESTRICT_FREEZE_PCT:
        return "RESTRICTED"
    if ratio <= HYSTERESIS_RELEASE_PCT:
        return "OPEN"
    return current_posture