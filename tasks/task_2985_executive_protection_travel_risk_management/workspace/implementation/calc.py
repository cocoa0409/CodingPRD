"""The service's calculations -- PRD 3.2 to 3.9.

Every constant and every ordering below traces to a sentence of the PRD.
"""

from decimal import Decimal

from util import SCORE_CAP, hours_between, age_in_days, round2, round_cents, to_decimal

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

STAFF_ROLES = ("ANALYST", "MANAGER", "DIRECTOR")
TIERS = ("TIER_1", "TIER_2", "TIER_3")
CONSENT_SCOPES = ("NONE", "TRIP_ONLY", "CONTINUOUS")
SURVEY_OUTCOMES = ("COMPLETE", "DEFICIENT")
SIGNAL_TYPES = ("MEDIA_MENTION", "SOCIAL_GEOTAG", "PUBLIC_FILING", "PROTEST_MENTION")
ASSESSMENT_REVIEW_OUTCOMES = ("APPROVE", "RETURN")
POLICY_TYPES = ("MEDICAL_EVAC", "KIDNAP_RANSOM", "TRAVEL_ACCIDENT")
POLICY_VERIFY_OUTCOMES = ("VERIFY", "REJECT")
TRIP_PURPOSES = ("BUSINESS_TRAVEL", "PUBLIC_APPEARANCE", "BOARD_EVENT")
ALLOCATION_METHODS = ("PRORATA", "BUSINESS_ONLY", "EXEC_PERQUISITE")
ADVANCE_ITEMS = (
    "ROUTE_SURVEY",
    "HOTEL_SURVEY",
    "HOSPITAL_SURVEY",
    "COMMS_TEST",
    "LOCAL_LIAISON",
    "CROWD_PLAN",
)
ADVANCE_OUTCOMES = ("COMPLETE", "WAIVED")
DETAIL_ROLES = ("LEAD_AGENT", "AGENT", "DRIVER", "ADVANCE")
VENDOR_TYPES = ("MEDICAL_EVAC", "GROUND_SECURITY", "LOCAL_LIAISON", "INTEL")
CHECK_IN_KINDS = ("SCHEDULED", "AD_HOC", "DURESS")
INCIDENT_TYPES = ("MEDICAL", "UNREST", "NATURAL_DISASTER")
RESPONSE_TRACKS = ("MEDEVAC", "SHELTER_IN_PLACE", "EXTRACTION")
TRIP_DECISIONS = ("APPROVE", "DENY")

# PRD 3.4 / 3.6 / 3.7: LOW below MODERATE below HIGH below EXTREME.
BAND_ORDER = ("LOW", "MODERATE", "HIGH", "EXTREME")
# PRD 3.6: MANAGER below DIRECTOR below DIRECTOR_AND_COMPLIANCE.
LEVEL_ORDER = ("MANAGER", "DIRECTOR", "DIRECTOR_AND_COMPLIANCE")
THREAT_LEVELS = ("LOW", "ELEVATED", "HIGH", "SEVERE")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# PRD 3.2 -- exposure scoring.
EXPOSURE_WINDOW_DAYS = 90
EXPOSURE_HALF_LIFE_DAYS = Decimal("30")
EXPOSURE_SCALE = Decimal("5")
SIGNAL_MULTIPLIER = {
    "MEDIA_MENTION": Decimal("1.0"),
    "SOCIAL_GEOTAG": Decimal("1.5"),
    "PUBLIC_FILING": Decimal("0.5"),
    "PROTEST_MENTION": Decimal("2.0"),
}

# PRD 3.2 -- composite risk score.
WEIGHT_THREAT = Decimal("0.45")
WEIGHT_EXPOSURE = Decimal("0.35")
WEIGHT_RESIDENTIAL = Decimal("0.20")
TIER_UPLIFT = {
    "TIER_1": Decimal("1.20"),
    "TIER_2": Decimal("1.10"),
    "TIER_3": Decimal("1.00"),
}
PROTEST_FLOOR = Decimal("60.00")
PROTEST_FLOOR_MIN_SEVERITY = 4

# PRD 3.3 -- destination composite and coverage floors.
WEIGHT_CRIME = Decimal("0.30")
WEIGHT_POLITICAL = Decimal("0.30")
WEIGHT_MEDICAL = Decimal("0.20")
WEIGHT_HAZARD = Decimal("0.20")
MEDICAL_INVERSION_BASE = Decimal("100")
REQUIRED_COVERAGE_CENTS = {
    "LOW": 25000000,
    "MODERATE": 50000000,
    "HIGH": 150000000,
    "EXTREME": 500000000,
}

# PRD 3.4 -- leg banding.
THREAT_UPLIFT = {
    "LOW": Decimal("0"),
    "ELEVATED": Decimal("5"),
    "HIGH": Decimal("10"),
    "SEVERE": Decimal("20"),
}
ADVANCE_BY_BAND = {
    "LOW": ("ROUTE_SURVEY",),
    "MODERATE": ("ROUTE_SURVEY", "HOTEL_SURVEY"),
    "HIGH": ("ROUTE_SURVEY", "HOTEL_SURVEY", "HOSPITAL_SURVEY", "COMMS_TEST"),
    "EXTREME": (
        "ROUTE_SURVEY",
        "HOTEL_SURVEY",
        "HOSPITAL_SURVEY",
        "COMMS_TEST",
        "LOCAL_LIAISON",
    ),
}
NON_WAIVABLE_ITEMS = ("ROUTE_SURVEY", "CROWD_PLAN")

# PRD 3.5 -- detail costing and the rest buffer.
DETAIL_ROLE_MULTIPLIER = {
    "LEAD_AGENT": Decimal("1.25"),
    "AGENT": Decimal("1.00"),
    "DRIVER": Decimal("0.85"),
    "ADVANCE": Decimal("1.10"),
}
MIN_BILLABLE_HOURS = 4
REST_BUFFER_HOURS = 12

# PRD 3.7 -- check-in cadence.
BAND_CHECK_IN_HOURS = {"LOW": 24, "MODERATE": 12, "HIGH": 8, "EXTREME": 4}
NULL_BAND_CHECK_IN_HOURS = 24
DEGRADED_CHECK_IN_HOURS = 2
DURESS_CHECK_IN_HOURS = 1
MISSED_CHECK_IN_THRESHOLD = 2

# PRD 3.8 -- incident response.
ACTIVATION_WINDOW_HOURS = 24
MEDEVAC_SURCHARGE_CENTS = 2500000
TRACK_CAPABILITY = {
    "MEDEVAC": "MEDICAL_EVAC",
    "SHELTER_IN_PLACE": "GROUND_SECURITY",
    "EXTRACTION": "GROUND_SECURITY",
}
TRACK_ACTIVE_STATUS = {
    "MEDEVAC": "MEDEVAC_ACTIVE",
    "SHELTER_IN_PLACE": "SHELTER_ACTIVE",
    "EXTRACTION": "EXTRACTION_ACTIVE",
}
INCIDENT_ACTIVE_STATUSES = ("MEDEVAC_ACTIVE", "SHELTER_ACTIVE", "EXTRACTION_ACTIVE")

# PRD 3.9 -- perquisite tiers.
PERQUISITE_TIER_MID_CENTS = 5000000
PERQUISITE_TIER_TOP_CENTS = 20000000
PERQUISITE_RATE_LOW = Decimal("0.10")
PERQUISITE_RATE_MID = Decimal("0.25")
PERQUISITE_RATE_TOP = Decimal("0.40")
PERQUISITE_RATE_BUSINESS_ONLY = Decimal("0.00")
PERQUISITE_RATE_EXEC_PERQUISITE = Decimal("1.00")

# PRD 3.2 -- revision allowance.
MAX_REVISION_ROUNDS = 3


def band_rank(band):
    if band is None:
        return -1
    return BAND_ORDER.index(band)


def level_rank(level):
    return LEVEL_ORDER.index(level)


# ---------------------------------------------------------------------------
# Calculation 1 / 2 -- public exposure score
# ---------------------------------------------------------------------------


def in_window_signals(signals, now):
    """PRD 3.2: age at least 0 and strictly less than 90 days, half-open."""
    selected = []
    for signal in signals:
        age = age_in_days(signal["observed_at"], now)
        if 0 <= age < EXPOSURE_WINDOW_DAYS:
            selected.append((signal, age))
    # Accumulated in ascending observed_at order, ties by ascending created_at.
    selected.sort(key=lambda pair: (pair[0]["observed_at"], pair[0]["created_at"],
                                    pair[0]["_seq"]))
    return selected


def exposure_score(signals, now, decay_weighted):
    """PRD 3.2: the decay-weighted and rolling-window readings of one formula."""
    total = Decimal("0")
    for signal, age in in_window_signals(signals, now):
        if decay_weighted:
            exponent = Decimal(age) / EXPOSURE_HALF_LIFE_DAYS
            weight = Decimal("0.5") ** exponent
        else:
            weight = Decimal("1")
        total += Decimal(signal["severity"]) * SIGNAL_MULTIPLIER[signal["signal_type"]] * weight
    scaled = round2(total * EXPOSURE_SCALE)
    return scaled if scaled < SCORE_CAP else SCORE_CAP


def has_protest_floor_signal(signals, now):
    """PRD 3.2: a PROTEST_MENTION of severity 4 or greater inside the window."""
    for signal, _age in in_window_signals(signals, now):
        if (signal["signal_type"] == "PROTEST_MENTION"
                and signal["severity"] >= PROTEST_FLOOR_MIN_SEVERITY):
            return True
    return False


# ---------------------------------------------------------------------------
# Calculation 3 -- composite risk score
# ---------------------------------------------------------------------------


def composite_risk_score(threat_monitoring_score, public_exposure_component,
                         residential_component_snapshot, tier, protest_floor):
    """PRD 3.2: weighting, then tier uplift, then protest floor, then cap+round."""
    base = (WEIGHT_THREAT * to_decimal(threat_monitoring_score)
            + WEIGHT_EXPOSURE * to_decimal(public_exposure_component)
            + WEIGHT_RESIDENTIAL * to_decimal(residential_component_snapshot))
    uplifted = base * TIER_UPLIFT[tier]
    if protest_floor and uplifted < PROTEST_FLOOR:
        uplifted = PROTEST_FLOOR
    rounded = round2(uplifted)
    return rounded if rounded < SCORE_CAP else SCORE_CAP


# ---------------------------------------------------------------------------
# Calculation 4 -- executive threat level
# ---------------------------------------------------------------------------


def threat_level_for(composite):
    """PRD 3.2: lower bounds inclusive, upper bounds exclusive."""
    value = to_decimal(composite)
    if value < Decimal("30.00"):
        return "LOW"
    if value < Decimal("55.00"):
        return "ELEVATED"
    if value < Decimal("80.00"):
        return "HIGH"
    return "SEVERE"


# ---------------------------------------------------------------------------
# Calculation 5 -- destination composite score and band
# ---------------------------------------------------------------------------


def destination_composite(crime, political, medical, hazard):
    """PRD 3.3: the medical index enters inverted as 100 minus its value."""
    total = (WEIGHT_CRIME * to_decimal(crime)
             + WEIGHT_POLITICAL * to_decimal(political)
             + WEIGHT_MEDICAL * (MEDICAL_INVERSION_BASE - to_decimal(medical))
             + WEIGHT_HAZARD * to_decimal(hazard))
    return round2(total)


def band_for_composite(composite):
    """PRD 3.3 / 3.4: the shared cut-points 25.00 / 50.00 / 75.00."""
    value = to_decimal(composite)
    if value < Decimal("25.00"):
        return "LOW"
    if value < Decimal("50.00"):
        return "MODERATE"
    if value < Decimal("75.00"):
        return "HIGH"
    return "EXTREME"


# ---------------------------------------------------------------------------
# Calculation 6 -- leg risk band
# ---------------------------------------------------------------------------


def leg_adjusted_score(destination_composite_score, threat_level):
    """PRD 3.4: destination composite plus threat uplift, rounded then capped."""
    total = to_decimal(destination_composite_score) + THREAT_UPLIFT[threat_level]
    rounded = round2(total)
    return rounded if rounded < SCORE_CAP else SCORE_CAP


# ---------------------------------------------------------------------------
# Calculation 7 -- advance requirement set
# ---------------------------------------------------------------------------


def required_advance_items(leg_band, trip_purpose):
    """PRD 3.4: band-derived set plus CROWD_PLAN for a public appearance,
    always emitted in the canonical order."""
    required = set(ADVANCE_BY_BAND[leg_band])
    if trip_purpose == "PUBLIC_APPEARANCE":
        required.add("CROWD_PLAN")
    return [item for item in ADVANCE_ITEMS if item in required]


# ---------------------------------------------------------------------------
# Calculation 8 -- required approval level
# ---------------------------------------------------------------------------


def required_approval_level(max_leg_risk_band, trip_purpose, tier):
    """PRD 3.6: band base, then purpose step-up, then independent tier override."""
    if max_leg_risk_band is None or max_leg_risk_band == "LOW":
        base = "MANAGER"
    elif max_leg_risk_band in ("MODERATE", "HIGH"):
        base = "DIRECTOR"
    else:
        base = "DIRECTOR_AND_COMPLIANCE"
    if trip_purpose == "PUBLIC_APPEARANCE":
        stepped = LEVEL_ORDER[min(level_rank(base) + 1, len(LEVEL_ORDER) - 1)]
    else:
        stepped = base
    if tier == "TIER_1" and max_leg_risk_band in ("HIGH", "EXTREME"):
        override = "DIRECTOR_AND_COMPLIANCE"
    else:
        override = "MANAGER"
    return stepped if level_rank(stepped) >= level_rank(override) else override


# ---------------------------------------------------------------------------
# Calculation 9 -- detail assignment cost
# ---------------------------------------------------------------------------


def planned_billable_hours(starts_at, ends_at):
    """PRD 3.5: whole minutes / 60, rounded up."""
    return hours_between(starts_at, ends_at)


def final_billable_hours(starts_at, actual_ends_at):
    """PRD 3.5: the larger of the four-hour minimum and the elapsed hours."""
    return max(MIN_BILLABLE_HOURS, hours_between(starts_at, actual_ends_at))


def detail_cost_cents(hours, hourly_rate_cents, role_on_detail):
    """PRD 3.5: hours * rate * position multiplier, rounded half-up per line."""
    product = (Decimal(hours) * Decimal(hourly_rate_cents)
               * DETAIL_ROLE_MULTIPLIER[role_on_detail])
    return round_cents(product)


# ---------------------------------------------------------------------------
# Calculation 10 -- vendor engagement cost
# ---------------------------------------------------------------------------


def engagement_hours(starts_at, ends_at):
    return hours_between(starts_at, ends_at)


def engagement_cost_cents(retainer_cents, hours, hourly_rate_cents):
    """PRD 3.5: retainer plus hours multiplied by the vendor's hourly rate."""
    return int(retainer_cents) + int(hours) * int(hourly_rate_cents)


# ---------------------------------------------------------------------------
# Calculation 11 -- check-in interval
# ---------------------------------------------------------------------------


def check_in_interval_hours(duress_active, readiness_state, max_leg_risk_band):
    """PRD 3.7: duress first, degradation second, band third."""
    if duress_active:
        return DURESS_CHECK_IN_HOURS
    if readiness_state == "DEGRADED":
        return DEGRADED_CHECK_IN_HOURS
    if max_leg_risk_band is None:
        return NULL_BAND_CHECK_IN_HOURS
    return BAND_CHECK_IN_HOURS[max_leg_risk_band]


def band_check_in_interval_hours(max_leg_risk_band):
    """PRD 3.7: the plain band-derived value with no degradation floor."""
    if max_leg_risk_band is None:
        return NULL_BAND_CHECK_IN_HOURS
    return BAND_CHECK_IN_HOURS[max_leg_risk_band]


# ---------------------------------------------------------------------------
# Calculation 12 -- track compatibility
# ---------------------------------------------------------------------------


def track_permitted(incident_type, severity, response_track):
    """PRD 3.8: the triage fork's permission matrix."""
    if incident_type == "MEDICAL":
        return response_track == "MEDEVAC"
    if incident_type == "UNREST":
        if response_track == "SHELTER_IN_PLACE":
            return True
        if response_track == "EXTRACTION":
            return severity >= 4
        return False
    if incident_type == "NATURAL_DISASTER":
        return response_track in ("MEDEVAC", "SHELTER_IN_PLACE")
    return False


# ---------------------------------------------------------------------------
# Calculation 14 -- perquisite allocation
# ---------------------------------------------------------------------------


def perquisite_tier_rate(prior_disclosure_cents):
    """PRD 3.9 step two: the tier rate read off the prior disclosure alone."""
    if prior_disclosure_cents < PERQUISITE_TIER_MID_CENTS:
        return PERQUISITE_RATE_LOW
    if prior_disclosure_cents < PERQUISITE_TIER_TOP_CENTS:
        return PERQUISITE_RATE_MID
    return PERQUISITE_RATE_TOP


def perquisite_rate(prior_disclosure_cents, cost_allocation_method):
    """PRD 3.9 step three: the allocation method overrides the tier."""
    if cost_allocation_method == "BUSINESS_ONLY":
        return PERQUISITE_RATE_BUSINESS_ONLY
    if cost_allocation_method == "EXEC_PERQUISITE":
        return PERQUISITE_RATE_EXEC_PERQUISITE
    return perquisite_tier_rate(prior_disclosure_cents)


def perquisite_split(total_security_cost_cents, rate):
    """PRD 3.9 step four: rounded half-up to a whole cent at this line item."""
    taxable = round_cents(Decimal(total_security_cost_cents) * rate)
    business = int(total_security_cost_cents) - taxable
    return taxable, business
