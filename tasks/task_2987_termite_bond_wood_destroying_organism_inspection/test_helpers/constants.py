"""Business constants for the Termite Bond & WDO Inspection API.

Every value here is transcribed from the PRD.  Tests import these rather than
hard-coding magic numbers, so that a single reading of the contract governs
every assertion.
"""

import math
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------

ROLE_COMPLIANCE_OFFICER = "ComplianceOfficer"
ROLE_BRANCH_MANAGER = "BranchManager"
ROLE_FIELD_INSPECTOR = "FieldInspector"
ROLE_APPLICATOR = "Applicator"
ROLE_CLAIMS_ADJUDICATOR = "ClaimsAdjudicator"
ROLE_PROPERTY_OWNER = "PropertyOwner"

ALL_ROLES = (
    ROLE_COMPLIANCE_OFFICER,
    ROLE_BRANCH_MANAGER,
    ROLE_FIELD_INSPECTOR,
    ROLE_APPLICATOR,
    ROLE_CLAIMS_ADJUDICATOR,
    ROLE_PROPERTY_OWNER,
)

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"
CLOCK_STARTUP_INSTANT_RENDERED = "2026-08-01T00:00:00.000Z"

# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

STATE_CODES = ("AL", "FL", "GA", "TX", "CA")

CONSTRUCTION_SLAB = "SLAB"
CONSTRUCTION_CRAWLSPACE = "CRAWLSPACE"
CONSTRUCTION_BASEMENT = "BASEMENT"
CONSTRUCTION_PIER_AND_BEAM = "PIER_AND_BEAM"
CONSTRUCTION_TYPES = (
    CONSTRUCTION_SLAB,
    CONSTRUCTION_CRAWLSPACE,
    CONSTRUCTION_BASEMENT,
    CONSTRUCTION_PIER_AND_BEAM,
)

LICENSE_STATUS_ACTIVE = "ACTIVE"
LICENSE_STATUS_SUSPENDED = "SUSPENDED"
LICENSE_STATUS_EXPIRED = "EXPIRED"

CATEGORY_WDO_INSPECTOR = "WDO_INSPECTOR"
CATEGORY_TERMITE_APPLICATOR = "TERMITE_APPLICATOR"
CATEGORY_FUMIGATION_CERTIFIED = "FUMIGATION_CERTIFIED"
LICENSE_CATEGORIES = (
    CATEGORY_WDO_INSPECTOR,
    CATEGORY_TERMITE_APPLICATOR,
    CATEGORY_FUMIGATION_CERTIFIED,
)

PURPOSE_INITIAL = "INITIAL"
PURPOSE_RENEWAL = "RENEWAL"
PURPOSE_REAL_ESTATE = "REAL_ESTATE"
PURPOSE_REINSTATEMENT = "REINSTATEMENT"
INSPECTION_PURPOSES = (
    PURPOSE_INITIAL,
    PURPOSE_RENEWAL,
    PURPOSE_REAL_ESTATE,
    PURPOSE_REINSTATEMENT,
)

INSPECTION_DRAFT = "DRAFT"
INSPECTION_GRAPHED = "GRAPHED"
INSPECTION_SUPERSEDED = "SUPERSEDED"

FINDING_ACTIVE_INFESTATION = "ACTIVE_INFESTATION"
FINDING_PREVIOUS_TREATMENT_EVIDENCE = "PREVIOUS_TREATMENT_EVIDENCE"
FINDING_DAMAGE = "DAMAGE"
FINDING_CONDUCIVE_CONDITION = "CONDUCIVE_CONDITION"
FINDING_TYPES = (
    FINDING_ACTIVE_INFESTATION,
    FINDING_PREVIOUS_TREATMENT_EVIDENCE,
    FINDING_DAMAGE,
    FINDING_CONDUCIVE_CONDITION,
)

ORGANISM_SUBTERRANEAN_TERMITE = "SUBTERRANEAN_TERMITE"
ORGANISM_DRYWOOD_TERMITE = "DRYWOOD_TERMITE"
ORGANISM_WOOD_BORING_BEETLE = "WOOD_BORING_BEETLE"
ORGANISM_FUNGUS = "FUNGUS"
ORGANISM_CARPENTER_ANT = "CARPENTER_ANT"
ORGANISM_NONE = "NONE"

CONDUCIVE_WOOD_TO_GROUND = "WOOD_TO_GROUND"
CONDUCIVE_EXCESS_MOISTURE = "EXCESS_MOISTURE"
CONDUCIVE_DEBRIS_UNDER_STRUCTURE = "DEBRIS_UNDER_STRUCTURE"
CONDUCIVE_INSUFFICIENT_CLEARANCE = "INSUFFICIENT_CLEARANCE"
CONDUCIVE_FAULTY_GRADE = "FAULTY_GRADE"
CONDUCIVE_NONE = "NONE"
CONDUCIVE_CODES = (
    CONDUCIVE_WOOD_TO_GROUND,
    CONDUCIVE_EXCESS_MOISTURE,
    CONDUCIVE_DEBRIS_UNDER_STRUCTURE,
    CONDUCIVE_INSUFFICIENT_CLEARANCE,
    CONDUCIVE_FAULTY_GRADE,
)

METHOD_LIQUID_BARRIER = "LIQUID_BARRIER"
METHOD_BAIT_STATION = "BAIT_STATION"
METHOD_FUMIGATION = "FUMIGATION"
TREATMENT_METHODS = (METHOD_LIQUID_BARRIER, METHOD_BAIT_STATION, METHOD_FUMIGATION)

PRODUCT_FIPRO_9 = "FIPRO_9"
PRODUCT_IMID_4 = "IMID_4"
PRODUCT_HEXA_BAIT_2 = "HEXA_BAIT_2"
PRODUCT_SULFURYL_F = "SULFURYL_F"

PLAN_PROPOSED = "PROPOSED"
PLAN_APPROVED = "APPROVED"
PLAN_COMPLETED = "COMPLETED"
PLAN_ABANDONED = "ABANDONED"

STATION_INSTALLED = "INSTALLED"
STATION_ACTIVE_HIT = "ACTIVE_HIT"
STATION_ESCALATED = "ESCALATED"
STATION_REMOVED = "REMOVED"

ACTIVITY_NONE = "NONE"
ACTIVITY_LIGHT = "LIGHT"
ACTIVITY_MODERATE = "MODERATE"
ACTIVITY_HEAVY = "HEAVY"

COMPLIANCE_ON_TIME = "ON_TIME"
COMPLIANCE_LATE = "LATE"
COMPLIANCE_MISSED = "MISSED"

TIER_RETREAT_ONLY = "RETREAT_ONLY"
TIER_REPAIR_AND_RETREAT = "REPAIR_AND_RETREAT"

BOND_ACTIVE = "ACTIVE"
BOND_LAPSED = "LAPSED"
BOND_TERMINATED = "TERMINATED"

RENEWAL_PENDING = "PENDING"
RENEWAL_PAID = "PAID"
RENEWAL_VOID = "VOID"

REPORT_DRAFT = "DRAFT"
REPORT_ISSUED = "ISSUED"
REPORT_AMENDED = "AMENDED"
REPORT_VOID = "VOID"

FORM_NPMA_33 = "NPMA_33"
FORM_FL_DACS_13645 = "FL_DACS_13645"
FORM_GA_100 = "GA_100"
FORM_TX_SPCS_TWDIR = "TX_SPCS_TWDIR"
FORM_CA_NPCA_1 = "CA_NPCA_1"

AMENDMENT_SECONDARY_EVIDENCE_ADDED = "SECONDARY_EVIDENCE_ADDED"
AMENDMENT_INACCESSIBLE_AREA_CLARIFIED = "INACCESSIBLE_AREA_CLARIFIED"
AMENDMENT_DAMAGE_SCOPE_REVISED = "DAMAGE_SCOPE_REVISED"
AMENDMENT_CLERICAL_CORRECTION = "CLERICAL_CORRECTION"

CLAIM_TYPE_REPAIR = "REPAIR"
CLAIM_TYPE_RETREAT = "RETREAT"

CLAIM_SUBMITTED = "SUBMITTED"
CLAIM_UNDER_ADJUDICATION = "UNDER_ADJUDICATION"
CLAIM_APPROVED_REPAIR = "APPROVED_REPAIR"
CLAIM_APPROVED_RETREAT_ONLY = "APPROVED_RETREAT_ONLY"
CLAIM_DENIED = "DENIED"
CLAIM_WITHDRAWN = "WITHDRAWN"

DECISION_APPROVE_REPAIR = "APPROVE_REPAIR"
DECISION_APPROVE_RETREAT_ONLY = "APPROVE_RETREAT_ONLY"
DECISION_DENY = "DENY"

DENIAL_PRE_EXISTING_DAMAGE = "PRE_EXISTING_DAMAGE"
DENIAL_NO_ELIGIBLE_DAMAGE = "NO_ELIGIBLE_DAMAGE"
DENIAL_BOND_LAPSED = "BOND_LAPSED"
DENIAL_OUTSIDE_COVERAGE = "OUTSIDE_COVERAGE"

EXCLUSION_FINDING_LEVEL = "FINDING_LEVEL"
EXCLUSION_AGGREGATE_PRORATION = "AGGREGATE_PRORATION"

# ---------------------------------------------------------------------------
# State jurisdiction tables (PRD 2.10)
# ---------------------------------------------------------------------------

STATE_FORM_MAP = {
    "AL": FORM_NPMA_33,
    "FL": FORM_FL_DACS_13645,
    "GA": FORM_GA_100,
    "TX": FORM_TX_SPCS_TWDIR,
    "CA": FORM_CA_NPCA_1,
}

STATE_TURNAROUND_HOURS = {"AL": 120, "FL": 72, "GA": 96, "TX": 96, "CA": 168}

STATE_RETENTION_YEARS = {"AL": 2, "FL": 4, "GA": 2, "TX": 2, "CA": 3}

RETENTION_DAYS_PER_YEAR = 365

# ---------------------------------------------------------------------------
# Pricing tables (PRD 3.5)
# ---------------------------------------------------------------------------

AREA_BRACKET_1_LIMIT = 1500
AREA_BRACKET_2_LIMIT = 3000
AREA_RATE_1 = 0.42
AREA_RATE_2 = 0.35
AREA_RATE_3 = 0.28

METHOD_BASE_FEE = {
    METHOD_LIQUID_BARRIER: 275.00,
    METHOD_BAIT_STATION: 390.00,
    METHOD_FUMIGATION: 640.00,
}

CONSTRUCTION_MULTIPLIER = {
    CONSTRUCTION_SLAB: 1.00,
    CONSTRUCTION_CRAWLSPACE: 1.15,
    CONSTRUCTION_BASEMENT: 1.25,
    CONSTRUCTION_PIER_AND_BEAM: 1.10,
}

INFESTATION_SURCHARGE_MULTIPLIER = 1.12

METHOD_PRICE_CAP = {
    METHOD_LIQUID_BARRIER: 4200.00,
    METHOD_BAIT_STATION: 3600.00,
    METHOD_FUMIGATION: 9800.00,
}

TRENCH_RATE_PER_LINEAR_FOOT = {
    CONSTRUCTION_SLAB: 1.0,
    CONSTRUCTION_CRAWLSPACE: 1.5,
    CONSTRUCTION_BASEMENT: 2.0,
    CONSTRUCTION_PIER_AND_BEAM: 1.25,
}

SLAB_DRILL_GALLONS_PER_BLOCK = 0.5
SLAB_DRILL_BLOCK_SQFT = 100
STATION_SPACING_FEET = 10
ATTACHED_STRUCTURE_EXTRA_STATIONS = 2

PERMITTED_METHODS = {
    CONSTRUCTION_SLAB: (METHOD_LIQUID_BARRIER, METHOD_BAIT_STATION, METHOD_FUMIGATION),
    CONSTRUCTION_CRAWLSPACE: (METHOD_LIQUID_BARRIER, METHOD_BAIT_STATION),
    CONSTRUCTION_BASEMENT: (METHOD_BAIT_STATION, METHOD_FUMIGATION),
    CONSTRUCTION_PIER_AND_BEAM: (
        METHOD_LIQUID_BARRIER,
        METHOD_BAIT_STATION,
        METHOD_FUMIGATION,
    ),
}

PERMITTED_PRODUCTS = {
    METHOD_LIQUID_BARRIER: (PRODUCT_FIPRO_9, PRODUCT_IMID_4),
    METHOD_BAIT_STATION: (PRODUCT_HEXA_BAIT_2,),
    METHOD_FUMIGATION: (PRODUCT_SULFURYL_F,),
}

# ---------------------------------------------------------------------------
# Bond money and calendar (PRD 3.7)
# ---------------------------------------------------------------------------

BASE_PREMIUM_RATE = 0.18
TIER_CAP_MULTIPLIER = {TIER_RETREAT_ONLY: 0, TIER_REPAIR_AND_RETREAT: 60}
CAP_LOADING_RATE = 0.004

TERM_LENGTH_DAYS = 365
RENEWAL_WINDOW_LEAD_DAYS = 60
GRACE_PERIOD_DAYS = 30
REINSTATEMENT_WINDOW_DAYS = 90

# ---------------------------------------------------------------------------
# Renewal pricing (PRD 3.8)
# ---------------------------------------------------------------------------

BASE_RENEWAL_RATE = 0.345
INSPECTION_FEE_FLAT = 85.00
INSPECTION_FEE_PER_100_SQFT = 2.155
CONDUCIVE_SURCHARGE_PER_ROW = 7.335
LATE_FEE_PER_DAY = 0.415

REINSTATEMENT_FLAT_FEE = 95.00
REINSTATEMENT_FEE_PER_LAPSE_DAY = 1.75
PRORATED_REMAINDER_MAX_LAPSE_DAYS = 30
REINSTATEMENT_GRAPH_MAX_AGE_DAYS = 30

# ---------------------------------------------------------------------------
# Bait station intervals (PRD 3.9)
# ---------------------------------------------------------------------------

STATION_INTERVAL_DAYS = {
    STATION_INSTALLED: 90,
    STATION_ACTIVE_HIT: 30,
    STATION_ESCALATED: 14,
}
SERVICE_GRACE_DAYS = 7
ESCALATION_RUN_LENGTH = 3
ESCALATION_THRESHOLD_RATE = 0.05

# ---------------------------------------------------------------------------
# Claim waterfall (PRD 3.10)
# ---------------------------------------------------------------------------

DEDUCTIBLE_TIER_1_LIMIT = 2000.00
DEDUCTIBLE_TIER_2_LIMIT = 10000.00
DEDUCTIBLE_RATE_1 = 0.10
DEDUCTIBLE_RATE_2 = 0.07
DEDUCTIBLE_RATE_3 = 0.05

# ---------------------------------------------------------------------------
# WDO report gates (PRD 3.4)
# ---------------------------------------------------------------------------

CLOSING_LEAD_HOURS = 24
AMENDMENT_WINDOW_DAYS = 30

# ---------------------------------------------------------------------------
# Field ranges
# ---------------------------------------------------------------------------

SQUARE_FOOTAGE_MIN = 200
SQUARE_FOOTAGE_MAX = 12000
LINEAR_FOOTAGE_MIN = 20
LINEAR_FOOTAGE_MAX = 2000
YEAR_BUILT_MIN = 1850
YEAR_BUILT_MAX = 2026
CRAWL_CLEARANCE_MIN = 0
CRAWL_CLEARANCE_MAX = 60
GALLONS_APPLIED_MIN = 0.10
GALLONS_APPLIED_MAX = 2000.00
CONCENTRATION_PCT_MIN = 0.01
CONCENTRATION_PCT_MAX = 5.00
CE_CREDITS_MIN = 0
CE_CREDITS_MAX = 99
CE_CREDITS_REINSTATEMENT_MIN = 8
DAMAGE_ESTIMATE_MAX = 250000.00
CLAIMED_DAMAGE_MIN = 0.01
CLAIMED_DAMAGE_MAX = 250000.00
SEVERITY_MIN = 1
SEVERITY_MAX = 5

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

GRID_COLUMNS = tuple("ABCDEFGHIJ")
GRID_ROWS = tuple(range(1, 11))


# ---------------------------------------------------------------------------
# Derivation helpers -- pure transcriptions of PRD arithmetic
# ---------------------------------------------------------------------------


def parse_instant(value):
    """Parse an ISO-8601 UTC instant (with or without fractional digits)."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def render_instant(moment):
    """Render a datetime as an ISO-8601 UTC instant with three fractional digits."""
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03d" % (moment.microsecond // 1000)
    ) + "Z"


def instant_plus_days(value, days):
    """Return the instant ``days`` whole days after the supplied instant."""
    return render_instant(parse_instant(value) + timedelta(days=days))


def date_plus_days(value, days):
    """Return the calendar date ``days`` days after the supplied ``YYYY-MM-DD``."""
    base = datetime.strptime(value[:10], "%Y-%m-%d")
    return (base + timedelta(days=days)).strftime("%Y-%m-%d")


def whole_days_between(earlier, later):
    """Whole UTC days from ``earlier`` to ``later``, discarding any partial day."""
    delta = parse_instant(later) - parse_instant(earlier)
    return int(delta.total_seconds() // 86400)


def round_half_up(value, places=2):
    """Round half up to ``places`` decimals, as PRD 2.8 mandates."""
    factor = 10 ** places
    scaled = value * factor
    # Nudge away from binary representation noise before the half-up decision.
    floored = math.floor(scaled)
    remainder = scaled - floored
    if remainder >= 0.5 - 1e-9:
        floored += 1
    return floored / factor


def retention_until(applied_at, state_code):
    """Retention deadline: applied_at date plus retention years times 365 days."""
    years = STATE_RETENTION_YEARS[state_code]
    return date_plus_days(applied_at[:10], years * RETENTION_DAYS_PER_YEAR)


def expected_target_gallons(construction_type, method, square_footage, linear_footage):
    """Liquid-barrier volume target from PRD 3.5."""
    if method != METHOD_LIQUID_BARRIER:
        return 0.00
    trench = linear_footage * TRENCH_RATE_PER_LINEAR_FOOT[construction_type]
    if construction_type == CONSTRUCTION_SLAB:
        blocks = math.ceil(square_footage / SLAB_DRILL_BLOCK_SQFT)
        drill = blocks * SLAB_DRILL_GALLONS_PER_BLOCK
    else:
        drill = 0.0
    return float(math.ceil(trench + drill))


def expected_target_station_count(method, linear_footage, has_attached_structures):
    """Bait-station count target from PRD 3.5."""
    if method != METHOD_BAIT_STATION:
        return 0
    count = math.ceil(linear_footage / STATION_SPACING_FEET)
    if has_attached_structures:
        count += ATTACHED_STRUCTURE_EXTRA_STATIONS
    return count


def expected_quoted_price(
    square_footage, method, construction_type, active_infestation_found
):
    """Six-step quote from PRD 3.5, rounding only at step 5 and capping at step 6."""
    remaining = square_footage
    subtotal = 0.0
    first = min(remaining, AREA_BRACKET_1_LIMIT)
    subtotal += first * AREA_RATE_1
    remaining -= first
    second = min(remaining, AREA_BRACKET_2_LIMIT - AREA_BRACKET_1_LIMIT)
    subtotal += second * AREA_RATE_2
    remaining -= second
    subtotal += remaining * AREA_RATE_3

    running = subtotal + METHOD_BASE_FEE[method]
    running *= CONSTRUCTION_MULTIPLIER[construction_type]
    if active_infestation_found:
        running *= INFESTATION_SURCHARGE_MULTIPLIER
    rounded = round_half_up(running, 2)
    return min(rounded, METHOD_PRICE_CAP[method])


def expected_bond_money(quoted_price_usd, coverage_tier):
    """Return (base_premium, repair_cap, annual_premium) per PRD 3.7."""
    base = round_half_up(quoted_price_usd * BASE_PREMIUM_RATE, 2)
    cap = round_half_up(base * TIER_CAP_MULTIPLIER[coverage_tier], 2)
    annual = round_half_up(base + CAP_LOADING_RATE * cap, 2)
    return base, cap, annual


def expected_deductible_rate(eligible_damage_usd):
    """Deductible rate keyed on the pre-deductible eligible amount, PRD 3.10."""
    if eligible_damage_usd < DEDUCTIBLE_TIER_1_LIMIT:
        return DEDUCTIBLE_RATE_1
    if eligible_damage_usd < DEDUCTIBLE_TIER_2_LIMIT:
        return DEDUCTIBLE_RATE_2
    return DEDUCTIBLE_RATE_3


def expected_station_grid_ref(station_index):
    """Derive a station's grid_ref from its 1-based ordinal, PRD 3.6."""
    block = (station_index - 1) // 10
    row = (station_index - 1) % 10 + 1
    return "%s%d" % (GRID_COLUMNS[block], row)


def expected_escalation_threshold(target_station_count):
    """5 percent of the station count, raised to the next whole number."""
    return math.ceil(target_station_count * ESCALATION_THRESHOLD_RATE)


def expected_interval_compliance(days_since_last_service, status_before):
    """Grade a service gap against the pre-visit status interval, PRD 3.9."""
    interval = STATION_INTERVAL_DAYS[status_before]
    if days_since_last_service <= interval:
        return COMPLIANCE_ON_TIME
    if days_since_last_service <= interval + SERVICE_GRACE_DAYS:
        return COMPLIANCE_LATE
    return COMPLIANCE_MISSED
